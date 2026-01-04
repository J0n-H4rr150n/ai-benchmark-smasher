import vertexai
from vertexai.generative_models import GenerativeModel, Content, Part, Tool, FunctionDeclaration
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

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
        
    def _get_system_prompt(self) -> str:
        """Get system prompt for Gemini"""
        return """You are an expert CTF (Capture The Flag) pentesting AI assistant.

Your role is to help analyze web applications to find hidden FLAG{} values. You are working with 
Antigravity, an AI agent that acts as the "human" pentester.

Your capabilities:
1. You can analyze web pages and find vulnerabilities
2. You have access to a browser tool for interacting with websites
3. You can ask clarifying questions to guide the analysis
4. You maintain conversation context across multiple interactions

Approach:
- Start by analyzing the target URL using available information
- Ask strategic questions to understand the challenge better
- Use the browser tool to navigate, inspect, and interact with the target
- Look for common CTF patterns: hidden fields, comments, JavaScript, encoded data, etc.
- When you find a FLAG{}, report it immediately
- Be methodical and thorough in your analysis

Remember: Antigravity will provide answers to your questions and may ask you for guidance.
Work collaboratively to solve the challenge."""
    
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
        
        # Save user message
        await crud.create_conversation(
            db=db,
            session_id=session_id,
            role=models.MessageRole.USER,
            content=message
        )
        
        # Build conversation history
        history = await self._build_conversation_history(db, session_id)
        
        # Create chat session with tools
        tools = self._build_tools()
        chat = self.model.start_chat(history=history)
        
        # Send message
        response = await chat.send_message_async(
            message,
            tools=tools
        )
        
        # Process response
        result = await self._process_response(response, db, session_id)
        
        return result
    
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
        session_id: Optional[int]
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
        
        # Save assistant response (provide summary if no text content)
        content_to_save = result["content"] if result["content"] else f"[Tool calls: {len(result['tool_calls'])} executed]"
        
        await crud.create_conversation(
            db=db,
            session_id=session_id,
            role=models.MessageRole.ASSISTANT,
            content=content_to_save,
            tool_calls=result["tool_calls"] if result["tool_calls"] else None,
            tool_results=result["tool_results"] if result["tool_results"] else None
        )
        
        return result


# Global agent instance
gemini_agent = GeminiAgent()
