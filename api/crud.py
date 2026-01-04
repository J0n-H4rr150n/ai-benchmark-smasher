from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional, Dict, Any
from datetime import datetime

from . import models, schemas


# Session CRUD
async def create_session(db: AsyncSession, session_data: schemas.SessionCreate) -> models.CTFSession:
    """Create a new CTF session"""
    db_session = models.CTFSession(
        target_url=session_data.target_url,
        goal=session_data.goal,
        status=models.SessionStatus.ACTIVE
    )
    db.add(db_session)
    await db.flush()
    await db.refresh(db_session)
    return db_session


async def get_session(db: AsyncSession, session_id: int) -> Optional[models.CTFSession]:
    """Get session by ID"""
    result = await db.execute(
        select(models.CTFSession).where(models.CTFSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def update_session_status(db: AsyncSession, session_id: int, status: models.SessionStatus):
    """Update session status"""
    session = await get_session(db, session_id)
    if session:
        session.status = status
        session.updated_at = datetime.utcnow()
        await db.flush()


# Conversation CRUD
async def create_conversation(
    db: AsyncSession,
    session_id: Optional[int],
    role: models.MessageRole,
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    step_number: Optional[int] = None,
    llm_analysis: Optional[str] = None,
    llm_findings: Optional[str] = None,
    llm_ideas: Optional[str] = None,
    llm_next_steps: Optional[str] = None,
    llm_need_block: Optional[str] = None,
    llm_decision: Optional[str] = None,
    llm_critique: Optional[str] = None,
    llm_confidence_score: Optional[str] = None,
    llm_grading_score: Optional[str] = None
) -> models.Conversation:
    """Create a conversation message"""
    conversation = models.Conversation(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
        step_number=step_number,
        llm_analysis=llm_analysis,
        llm_findings=llm_findings,
        llm_ideas=llm_ideas,
        llm_next_steps=llm_next_steps,
        llm_need_block=llm_need_block,
        llm_decision=llm_decision,
        llm_critique=llm_critique,
        llm_confidence_score=llm_confidence_score,
        llm_grading_score=llm_grading_score
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_conversation_history(
    db: AsyncSession,
    session_id: Optional[int] = None,
    limit: int = 50
) -> List[models.Conversation]:
    """Get conversation history"""
    query = select(models.Conversation).order_by(desc(models.Conversation.created_at)).limit(limit)
    
    if session_id is not None:
        query = query.where(models.Conversation.session_id == session_id)
    
    result = await db.execute(query)
    conversations = result.scalars().all()
    return list(reversed(conversations))  # Return in chronological order


# Finding CRUD
async def create_finding(
    db: AsyncSession,
    session_id: int,
    finding_type: str,
    description: str,
    location: Optional[str] = None,
    evidence: Optional[dict] = None
) -> models.Finding:
    """Create a new finding"""
    finding = models.Finding(
        session_id=session_id,
        finding_type=finding_type,
        description=description,
        location=location,
        evidence=evidence
    )
    db.add(finding)
    await db.flush()
    await db.refresh(finding)
    return finding


async def get_session_findings(db: AsyncSession, session_id: int) -> List[models.Finding]:
    """Get all findings for a session"""
    result = await db.execute(
        select(models.Finding)
        .where(models.Finding.session_id == session_id)
        .order_by(models.Finding.created_at)
    )
    return list(result.scalars().all())


# Flag CRUD
async def create_flag(
    db: AsyncSession,
    session_id: int,
    flag_value: str,
    context: Optional[str] = None
) -> Optional[models.Flag]:
    """Create a new flag (if not already exists)"""
    # Check if flag already exists
    result = await db.execute(
        select(models.Flag).where(models.Flag.flag_value == flag_value)
    )
    existing_flag = result.scalar_one_or_none()
    
    if existing_flag:
        return None  # Flag already discovered
    
    flag = models.Flag(
        session_id=session_id,
        flag_value=flag_value,
        context=context
    )
    db.add(flag)
    await db.flush()
    await db.refresh(flag)
    return flag


async def get_session_flags(db: AsyncSession, session_id: int) -> List[models.Flag]:
    """Get all flags for a session"""
    result = await db.execute(
        select(models.Flag)
        .where(models.Flag.session_id == session_id)
        .order_by(models.Flag.discovered_at)
    )
    return list(result.scalars().all())


async def get_all_flags(db: AsyncSession) -> List[models.Flag]:
    """Get all discovered flags across all sessions"""
    result = await db.execute(
        select(models.Flag).order_by(desc(models.Flag.discovered_at))
    )
    return list(result.scalars().all())
