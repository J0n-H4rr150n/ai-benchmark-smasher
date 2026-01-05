import vertexai
from vertexai.generative_models import GenerativeModel, Content, Part, Tool, FunctionDeclaration
from typing import List, Dict, Any, Optional
from sqlalchemy import select, desc
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

Your role is to help analyze web applications to find hidden FLAG{} values, vulnerabilities, and security issues. You are working autonomously to complete the mission goal provided by the user.

### GOAL COMPLETION
When you have successfully completed the PRIMARY GOAL of the mission (e.g., found the FLAG{}, identified the critical vulnerability, etc.), include the exact phrase "GOAL-COMPLETE" in your [RESPONSE] section. This signals that the primary objective is achieved, though you may continue exploring for additional findings if desired.

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

[LLM NEED BLOCK]
If you are missing a tool, need a modification to a tool, or need a specific script to proceed with your plan, explicitly describe it here. If not, state "None".

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
- When you find a FLAG{}, report it immediately and include "GOAL-COMPLETE" in your response.
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

        try:
            msg_preview = (message or "").replace("\n", " ").strip()
            if len(msg_preview) > 200:
                msg_preview = msg_preview[:200] + "…"
            logger.info(f"[STEP START] session={session_id} step={next_step} msg='{msg_preview}'")
        except Exception:
            logger.info(f"[STEP START] session={session_id} step={next_step}")
        
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

        try:
            tool_count = len(result.get("tool_calls") or [])
            tool_names = []
            for tc in (result.get("tool_calls") or []):
                if isinstance(tc, dict) and tc.get("tool"):
                    tool_names.append(str(tc.get("tool")))
            tool_names_str = ",".join(tool_names[:8])
            if len(tool_names) > 8:
                tool_names_str += f",…(+{len(tool_names) - 8})"
            flags_count = len(result.get("flags") or [])
            goal_complete = bool(result.get("content")) and ("GOAL-COMPLETE" in result.get("content", ""))
            logger.info(
                f"[STEP END] session={session_id} step={next_step} tools={tool_count} tool_names={tool_names_str} flags={flags_count} goal_complete={goal_complete}"
            )
        except Exception:
            logger.info(f"[STEP END] session={session_id} step={next_step}")
        
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
        """Build conversation history for Gemini, including tool calls and results"""
        if not session_id:
            return []
            
        history = []
        
        # Get history (sorted by created_at in the query if possible, or manually)
        # conversations = await crud.get_conversation_history(db, session_id, limit=30)
        # Using a slightly larger limit to ensure we have full context for complex traces
        query = select(models.Conversation).where(models.Conversation.session_id == session_id).order_by(models.Conversation.created_at.asc())
        result = await db.execute(query)
        conversations = result.scalars().all()
        
        for conv in conversations:
            if conv.role == models.MessageRole.USER:
                if conv.content:
                    history.append(Content(role="user", parts=[Part.from_text(conv.content)]))
            
            elif conv.role == models.MessageRole.ASSISTANT:
                parts = []
                # First, add the text content if any
                if conv.content:
                    parts.append(Part.from_text(conv.content))
                
                # Second, add any tool calls (native FunctionCall objects)
                if conv.tool_calls:
                    for tc in conv.tool_calls:
                        try:
                            parts.append(Part.from_dict({
                                'function_call': {
                                    'name': tc['tool'],
                                    'args': tc['args']
                                }
                            }))
                        except Exception as e:
                            logger.error(f"[HISTORY ERROR] Failed to reconstruct tool call {tc.get('tool')}: {e}")
                
                if parts:
                    history.append(Content(role="model", parts=parts))
                
                # Third, if there are results, they MUST follow as a separate Content with 'user' role
                if conv.tool_results and conv.tool_calls:
                    result_parts = []
                    # Robust matching: only zip up to the minimum length to avoid crashes, 
                    # though ideally they should always match.
                    results_to_process = conv.tool_results
                    calls_to_process = conv.tool_calls
                    
                    if len(results_to_process) != len(calls_to_process):
                        logger.warning(f"[HISTORY] Mismatch in tool calls ({len(calls_to_process)}) and results ({len(results_to_process)}) for conv {conv.id}")
                    
                    for i in range(min(len(calls_to_process), len(results_to_process))):
                        tc = calls_to_process[i]
                        tr = results_to_process[i]
                        try:
                            # Vertex requires the name to match the function call
                            if tc and 'tool' in tc:
                                result_parts.append(Part.from_function_response(
                                    name=tc['tool'],
                                    response=tr or {}
                                ))
                        except Exception as e:
                            logger.error(f"[HISTORY ERROR] Failed to reconstruct tool result {i} for {tc.get('tool') if tc else 'unknown'}: {e}")
                    
                    if result_parts:
                        history.append(Content(role="user", parts=result_parts))
        
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
            "need_block": None,
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
            "need_block": r"\[LLM NEED BLOCK\](.*?)\[LLM",
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
            "need_block": r"\[LLM NEED BLOCK\](.*)",
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
            llm_need_block=parsed["need_block"],
            llm_decision=parsed["decision"],
            llm_critique=parsed["critique"],
            llm_confidence_score=parsed["confidence_score"],
            llm_grading_score=parsed["grading_score"]
        )
        
        # Merge parsed fields into result for return
        result.update({
            f"llm_{k}": v for k, v in parsed.items() if k != "response"
        })
        
        # Log to JSON file
        await self._log_to_json(session_id, step_number, result)
        
        return result

    async def _log_to_json(self, session_id: int, step_number: int, result: Dict[str, Any]):
        """Log execution step to JSON file"""
        import json
        import os
        from datetime import datetime
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "step": step_number,
            "content": result.get("content"),
            "tool_calls": result.get("tool_calls"),
            "tool_results": result.get("tool_results"),
            "flags": result.get("flags"),
            "findings": result.get("findings"),
            "analysis": result.get("llm_analysis"),
            "decision": result.get("llm_decision"),
            "next_steps": result.get("llm_next_steps")
        }
        
        try:
            os.makedirs("logs", exist_ok=True)

            # 1) Append-only JSONL stream (quick + safe)
            stream_log_file = "logs/runs.json"
            with open(stream_log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, default=str) + "\n")

            # 2) Pretty per-session file for easy review in VS Code
            if session_id is not None:
                os.makedirs(os.path.join("logs", "runs"), exist_ok=True)
                session_log_file = os.path.join("logs", "runs", f"{session_id}.json")
                tmp_file = session_log_file + ".tmp"

                session_doc = {
                    "session_id": session_id,
                    "entries": []
                }

                if os.path.exists(session_log_file):
                    try:
                        with open(session_log_file, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                        if isinstance(existing, dict):
                            session_doc["session_id"] = existing.get("session_id", session_id)
                            if isinstance(existing.get("entries"), list):
                                session_doc["entries"] = existing["entries"]
                    except Exception:
                        # If the file is corrupted/partial, fall back to a fresh document.
                        session_doc = {"session_id": session_id, "entries": []}

                session_doc["entries"].append(log_entry)

                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(session_doc, f, indent=4, ensure_ascii=False, default=str)
                os.replace(tmp_file, session_log_file)
                
        except Exception as e:
            logger.error(f"[LOGGING ERROR] Failed to write logs: {e}")

# Global agent instance
gemini_agent = GeminiAgent()
