from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .. import schemas, crud
from ..core.ai_agent import gemini_agent

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=schemas.ChatResponse)
async def send_chat_message(
    chat_msg: schemas.ChatMessage,
    db: AsyncSession = Depends(get_db)
):
    """Send a message to Gemini AI agent"""
    
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
        findings=findings_response if findings_response else None,
        flags=flags_response if flags_response else None
    )


@router.get("/history", response_model=list[schemas.ConversationResponse])
async def get_chat_history(
    session_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Get conversation history"""
    conversations = await crud.get_conversation_history(db, session_id, limit)
    return [schemas.ConversationResponse.model_validate(c) for c in conversations]
