from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database import get_db
from .. import schemas, crud
from .. import models
from ..crud_knowledge import store_successful_run
from ..core.ai_agent import gemini_agent

router = APIRouter(prefix="/chat", tags=["chat"])


from datetime import datetime
import time
from ..config import settings

@router.post("/", response_model=schemas.ChatResponse)
async def send_chat_message(
    chat_msg: schemas.ChatMessage,
    db: AsyncSession = Depends(get_db)
):
    """Send a message to Gemini AI agent"""
    start_time = time.time()
    
    # Get session context if available
    message_with_context = chat_msg.message
    if chat_msg.session_id:
        session = await crud.get_session(db, chat_msg.session_id)
        if session:
            # Inject session context
            context = f"\n[Session Context: Target URL={session.target_url}"
            if session.goal:
                context += f", Goal={session.goal}"
            context += "]\n"
            message_with_context = context + chat_msg.message
    
    # Process message through Gemini
    result = await gemini_agent.chat(
        message=message_with_context,
        db=db,
        session_id=chat_msg.session_id
    )

    # If mission is complete, store run in knowledge base (idempotent).
    # This ensures the web UI also saves to pgvector without needing extra client logic.
    try:
        if chat_msg.session_id and result.get("content") and "GOAL-COMPLETE" in result["content"]:
            existing = await db.execute(
                select(models.SuccessfulRun.id).where(models.SuccessfulRun.session_id == chat_msg.session_id).limit(1)
            )
            already_saved = existing.scalar_one_or_none() is not None

            if not already_saved:
                # Build methodology from the most recent assistant analyses
                history = await crud.get_conversation_history(db, chat_msg.session_id, limit=250)
                assistant_turns = [h for h in history if h.role == models.MessageRole.ASSISTANT]

                methodology_parts = []
                for turn in assistant_turns:
                    if turn.llm_analysis:
                        label = f"Step {turn.step_number}" if turn.step_number is not None else "Step"
                        methodology_parts.append(f"{label}: {turn.llm_analysis}")

                methodology = "\n\n".join(methodology_parts[-5:]) or (result.get("llm_analysis") or result.get("content") or "")

                # Heuristic vulnerability type detection
                vuln_type = None
                content_lower = (result.get("content") or "").lower()
                if "idor" in content_lower:
                    vuln_type = "IDOR"
                elif "sql" in content_lower or "injection" in content_lower:
                    vuln_type = "SQLi"
                elif "xss" in content_lower:
                    vuln_type = "XSS"
                elif "auth" in content_lower or "bypass" in content_lower:
                    vuln_type = "Auth Bypass"

                # Tools used across the run
                tools_used = sorted({
                    tc.get("tool")
                    for turn in assistant_turns
                    for tc in (turn.tool_calls or [])
                    if isinstance(tc, dict) and tc.get("tool")
                })

                # Total turns (assistant steps)
                total_turns = 0
                step_numbers = [t.step_number for t in assistant_turns if t.step_number is not None]
                if step_numbers:
                    total_turns = max(step_numbers)
                else:
                    total_turns = len(assistant_turns)

                # Use session metadata if available
                session_goal = session.goal if session and session.goal else None
                session_target = session.target_url if session else None

                await store_successful_run(
                    db=db,
                    session_id=chat_msg.session_id,
                    goal=session_goal or "(unspecified goal)",
                    methodology=methodology,
                    vulnerability_type=vuln_type,
                    target_url=session_target,
                    total_turns=total_turns,
                    key_findings=result.get("llm_findings"),
                    breakthrough_insight=result.get("llm_decision"),
                    tools_used=tools_used,
                    summary_file_path=None
                )
    except Exception as e:
        # Never fail the chat response due to knowledge base persistence
        import logging
        logging.getLogger(__name__).warning(f"[KNOWLEDGE] Failed to store successful run: {e}")
    
    elapsed = time.time() - start_time
    
    # Get the conversation ID of the assistant's response
    conversations = await crud.get_conversation_history(db, chat_msg.session_id, limit=1)
    conversation_id = conversations[0].id if conversations else 0
    
    # Convert findings to response models
    findings_response = []
    if chat_msg.session_id:
        findings = await crud.get_session_findings(db, chat_msg.session_id)
        findings_response = [schemas.FindingResponse.model_validate(f) for f in findings]
    
    # Convert flags to response models
    flags_response = []
    if result.get("flags"):
        if chat_msg.session_id:
            flags = await crud.get_session_flags(db, chat_msg.session_id)
            flags_response = [schemas.FlagResponse.model_validate(f) for f in flags]
    
    return schemas.ChatResponse(
        conversation_id=conversation_id,
        role=schemas.MessageRole.ASSISTANT,
        content=result["content"],
        tool_calls=result.get("tool_calls"),
        tool_results=result.get("tool_results"),
        findings=findings_response if findings_response else None,
        flags=flags_response if flags_response else None,
        
        # Metadata
        model_used=settings.gemini_model,
        elapsed_time=round(elapsed, 2),
        timestamp=datetime.now(),
        
        # Analysis (if available in result)
        llm_analysis=result.get("llm_analysis"),
        llm_critique=result.get("llm_critique"),
        llm_next_steps=result.get("llm_next_steps"),
        llm_confidence_score=result.get("llm_confidence_score")
    )


@router.get("/sessions", response_model=list[schemas.SessionResponse])
async def get_sessions(
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Get listing of past sessions"""
    sessions = await crud.get_all_sessions(db, limit)
    return [schemas.SessionResponse.model_validate(s) for s in sessions]


@router.get("/history", response_model=list[schemas.ConversationResponse])
async def get_chat_history(
    session_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get conversation history"""
    conversations = await crud.get_conversation_history(db, session_id, limit)
    return [schemas.ConversationResponse.model_validate(c) for c in conversations]
