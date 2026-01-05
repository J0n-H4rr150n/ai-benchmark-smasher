from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .. import schemas, crud
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
