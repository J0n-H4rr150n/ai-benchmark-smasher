import vertexai
from vertexai.generative_models import GenerativeModel, Content, Part, Tool, FunctionDeclaration
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import time

from ..config import settings
from ..tools.registry import tool_registry
from .. import crud, models

import logging
logger = logging.getLogger(__name__)


class GeminiAgent:
    """Gemini 2.5 AI agent for CTF analysis and conversation"""
    
    def __init__(self):
        # Initialize Vertex AI
        vertexai.init(
            project=settings.gcp_project_id,
            location=settings.gemini_location
        )
        
        self.model = GenerativeModel(
            settings.gemini_model,
            system_instruction=self._get_system_prompt()
        )
        
        # Rate limiting state
        self._last_call_time = 0
        self._rate_limit_lock = asyncio.Lock()
        self._min_interval = 12.0  # 12 seconds = 5 calls per 60 seconds
        
    def _get_system_prompt(self) -> str:
        """Get system prompt for Gemini"""
        return """You are an expert CTF (Capture The Flag) pentesting AI assistant.

Your role is to help analyze web applications to find hidden FLAG{} values. You are working with 
Antigravity, an AI agent that acts as the "human" pentester.

### STRUCTURED OUTPUT REQUIREMENT
To ensure maximum clarity and systematically track progress, YOU MUST provide your reasoning in the following structured format using the exact tags shown below:

[LLM ANALYSIS]
Analyze the current state of the application, the results of the last tool execution, and what you've learned so far. Be detailed.

[LLM FINDINGS]
List any specific interesting elements found: hidden fields, interesting comments, new URLs, script behaviors, etc. If nothing new, state "None".

[LLM IDEAS]
Brainstorm potential attack vectors, areas to explore next, or hypotheses about where the flag might be hidden.

[LLM CRITIQUE]
Critique your previous actions or findings. What might you have missed? What could be improved?

[LLM DECISION]
State your final decision for this turn. What is the most critical action or conclusion?

[LLM NEXT STEPS]
Clearly state what you intend to do in the immediate next step and why.

[CONFIDENCE SCORE]
Provide a score from 0.0 to 1.0 representing your confidence in your current approach/path.

[GRADING SCORE]
Provide a score from 0.0 to 1.0 representing how close you think you are to finding the flag (1.0 = flag found).

[RESPONSE]
Your normal conversational response to Antigravity, explaining your thought process clearly and concisely.

### Capabilities:
1. You can analyze web pages and find vulnerabilities using the "Snapshot Triad" (Visual SoM, Raw Source, and Network Traffic).
2. You have access to a browser tool for methodology-driven interaction.
3. You can ask clarifying questions to guide the analysis.

### Approach:
- Start by analyzing the target URL.
- Always review BOTH the raw HTML source and the dynamic rendered DOM (SoM) to find discrepancies.
- Use the network traffic summary to identify hidden APIs or XHR requests.
- When you find a FLAG{}, report it immediately.
- Be methodical and thorough."""
    
    def _build_tools(self) -> List[Tool]:
        """Build Gemini function calling tools from registry"""
        tool_defs = tool_registry.get_tool_definitions()
        function_declarations = []
        
        for tool_def in tool_defs:
            # Convert our ToolDefinition to Gemini FunctionDeclaration
            parameters = {
                "type": "object",
                "properties": {},
                "required": []
            }
            
            for param in tool_def.parameters:
                parameters["properties"][param.name] = {
                    "type": param.type,
                    "description": param.description
                }
                if param.required:
                    parameters["required"].append(param.name)
            
            func_decl = FunctionDeclaration(
                name=tool_def.name,
                description=tool_def.description,
                parameters=parameters
            )
            function_declarations.append(func_decl)
        
        return [Tool(function_declarations=function_declarations)] if function_declarations else []
    
    async def chat(
        self,
        message: str,
        db: AsyncSession,
        session_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Send message to Gemini and get response"""
        
        # Determine next step number
        current_history = await crud.get_conversation_history(db, session_id, limit=1)
        next_step = 1
        if current_history:
            last_conv = current_history[-1]
            if last_conv.step_number is not None:
                next_step = last_conv.step_number + 1
        
        # Save user message
        await crud.create_conversation(
            db=db,
            session_id=session_id,
            role=models.MessageRole.USER,
            content=message,
            step_number=next_step
        )
        
        # Build conversation history
        history = await self._build_conversation_history(db, session_id)
        
        # Repetition Detection
        repetition_detected = await self._detect_repetition(db, session_id)
        if repetition_detected:
            warning = "System Note: Tool call repetition detected. Please explore a different path (e.g., check other files, headers, or try different inputs) to avoid getting stuck."
            logger.warning(f"[REPETITION] Injecting warning for session {session_id}")
            history.append(Content(role="user", parts=[Part.from_text(warning)]))
        
        # Create chat session with tools
        tools = self._build_tools()
        chat = self.model.start_chat(history=history)
        
        # Rate limiting: wait if necessary
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                logger.info(f"[RATE LIMIT] Waiting {wait_time:.2f}s before next request (Strict Limit: 5 RPM)")
                await asyncio.sleep(wait_time)
            
            # Send message
            response = await chat.send_message_async(
                message,
                tools=tools
            )
            self._last_call_time = time.time()
        
        # Process response
        result = await self._process_response(response, db, session_id, step_number=next_step)
        
        return result

    async def _detect_repetition(self, db: AsyncSession, session_id: Optional[int]) -> bool:
        """Detect if the last few tool calls are identical"""
        if not session_id:
            return False
            
        history = await crud.get_conversation_history(db, session_id, limit=6)
        tool_call_hashes = []
        
        import hashlib
        import json
        
        for conv in history:
            if conv.tool_calls:
                # Create a stable hash of the tool calls
                call_str = json.dumps(conv.tool_calls, sort_keys=True)
                call_hash = hashlib.md5(call_str.encode()).hexdigest()
                tool_call_hashes.append(call_hash)
        
        # If we have at least 3 identical consecutive tool call sets, it's a loop
        if len(tool_call_hashes) >= 3:
            last_three = tool_call_hashes[-3:]
            if len(set(last_three)) == 1:
                return True
                
        return False
    
    async def _build_conversation_history(
        self,
        db: AsyncSession,
        session_id: Optional[int]
    ) -> List[Content]:
        """Build conversation history for Gemini"""
        history = []
        
        conversations = await crud.get_conversation_history(db, session_id, limit=20)
        
        for conv in conversations:
            if conv.role == models.MessageRole.USER:
                history.append(Content(role="user", parts=[Part.from_text(conv.content)]))
            elif conv.role == models.MessageRole.ASSISTANT:
                history.append(Content(role="model", parts=[Part.from_text(conv.content)]))
        
        return history
    
    async def _process_response(
        self,
        response,
        db: AsyncSession,
        session_id: Optional[int],
        step_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """Process Gemini response and execute tool calls"""
        
        result = {
            "content": "",
            "tool_calls": [],
            "tool_results": [],
            "flags": [],
            "findings": []
        }
        
        # Check for function calls
        for part in response.candidates[0].content.parts:
            # Check if part has text (not all parts will have text, e.g., function calls)
            if hasattr(part, 'text') and part.text:
                result["content"] += part.text
            
            if hasattr(part, 'function_call') and part.function_call:
                func_call = part.function_call
                tool_name = func_call.name
                tool_args = dict(func_call.args)
                
                result["tool_calls"].append({
                    "tool": tool_name,
                    "args": tool_args
                })
                
                try:
                    # Execute tool  
                    logger.info(f"[TOOL] Executing {tool_name} with args: {tool_args}")
                    tool_result = await tool_registry.execute_tool(tool_name, **tool_args)
                    result["tool_results"].append(tool_result)
                    
                    # Debug: log tool result keys
                    logger.info(f"[DEBUG] Tool result type: {type(tool_result)}, keys: {tool_result.keys() if isinstance(tool_result, dict) else 'N/A'}")
                    
                    # Check tool result for flags (scan full HTML content)
                    if isinstance(tool_result, dict):
                        html_content = tool_result.get("html", "")
                        logger.info(f"[DEBUG] HTML content length: {len(html_content)}")
                        
                        if html_content and session_id:
                            try:
                                # Search for FLAG{} patterns in full content
                                import re
                                flags = re.findall(r'FLAG\{[^}]+\}', html_content, re.IGNORECASE)
                                
                                if flags:
                                    logger.info(f"[FLAG DETECTION] Found {len(flags)} flags: {flags}")
                                else:
                                    logger.info(f"[FLAG DETECTION] No flags found in {len(html_content)} chars of HTML")
                                
                                for flag in flags:
                                    try:
                                        db_flag = await crud.create_flag(db, session_id, flag, "Found via browser tool")
                                        if db_flag:
                                            result["flags"].append(flag)
                                            logger.info(f"[FLAG SAVED] {flag} saved to session {session_id}")
                                        else:
                                            logger.warning(f"[FLAG EXISTS] {flag} already exists")
                                    except Exception as e:
                                        logger.error(f"[FLAG ERROR] Failed to save flag {flag}: {e}", exc_info=True)
                                        
                            except Exception as e:
                                logger.error(f"[FLAG DETECTION ERROR] {e}", exc_info=True)
                                
                except Exception as e:
                    logger.error(f"[TOOL ERROR] Failed to execute {tool_name}: {e}", exc_info=True)
                    result["tool_results"].append({"error": str(e)})
        
        # Save assistant response
        # Parse structured output if present
        import re
        
        parsed = {
            "analysis": None,
            "findings": None,
            "ideas": None,
            "critique": None,
            "decision": None,
            "next_steps": None,
            "confidence_score": None,
            "grading_score": None,
            "response": result["content"]
        }
        
        # Regex patterns for the tags
        patterns = {
            "analysis": r"\[LLM ANALYSIS\](.*?)\[LLM",
            "findings": r"\[LLM FINDINGS\](.*?)\[LLM",
            "ideas": r"\[LLM IDEAS\](.*?)\[LLM",
            "critique": r"\[LLM CRITIQUE\](.*?)\[LLM",
            "decision": r"\[LLM DECISION\](.*?)\[LLM",
            "next_steps": r"\[LLM NEXT STEPS\](.*?)\[CONFIDENCE",
            "confidence_score": r"\[CONFIDENCE SCORE\](.*?)\[GRADING",
            "grading_score": r"\[GRADING SCORE\](.*?)\[RESPONSE\]",
            "response": r"\[RESPONSE\](.*)"
        }
        
        # Fallback patterns
        fallbacks = {
            "analysis": r"\[LLM ANALYSIS\](.*)",
            "findings": r"\[LLM FINDINGS\](.*)",
            "ideas": r"\[LLM IDEAS\](.*)",
            "critique": r"\[LLM CRITIQUE\](.*)",
            "decision": r"\[LLM DECISION\](.*)",
            "next_steps": r"\[LLM NEXT STEPS\](.*)",
            "confidence_score": r"\[CONFIDENCE SCORE\](.*)",
            "grading_score": r"\[GRADING SCORE\](.*)"
        }
        
        full_content = result["content"]
        
        for key, pattern in patterns.items():
            match = re.search(pattern, full_content, re.DOTALL | re.IGNORECASE)
            if match:
                parsed[key] = match.group(1).strip()
            elif key in fallbacks:
                # Try fallback (anything until end of string)
                f_match = re.search(fallbacks[key], full_content, re.DOTALL | re.IGNORECASE)
                if f_match:
                    parsed[key] = f_match.group(1).strip()

        # Update result content to be the [RESPONSE] section if parsed, otherwise keep original
        if parsed["response"]:
            result["content"] = parsed["response"]
            
        content_to_save = result["content"] if result["content"] else f"[Tool calls: {len(result['tool_calls'])} executed]"
        
        await crud.create_conversation(
            db=db,
            session_id=session_id,
            role=models.MessageRole.ASSISTANT,
            content=content_to_save,
            tool_calls=result["tool_calls"] if result["tool_calls"] else None,
            tool_results=result["tool_results"] if result["tool_results"] else None,
            step_number=step_number,
            llm_analysis=parsed["analysis"],
            llm_findings=parsed["findings"],
            llm_ideas=parsed["ideas"],
            llm_next_steps=parsed["next_steps"],
            llm_decision=parsed["decision"],
            llm_critique=parsed["critique"],
            llm_confidence_score=parsed["confidence_score"],
            llm_grading_score=parsed["grading_score"]
        )
        
        # Merge parsed fields into result for return
        result.update({
            f"llm_{k}": v for k, v in parsed.items() if k != "response"
        })
        
        return result


# Global agent instance
gemini_agent = GeminiAgent()
