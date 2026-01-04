from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from .. import schemas, crud, models
from ..database import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", response_model=schemas.SessionResponse)
async def create_session(
    session_data: schemas.SessionCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new CTF solving session"""
    session = await crud.create_session(db, session_data)
    return session


@router.get("/{session_id}", response_model=schemas.SessionResponse)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get session details"""
    session = await crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/findings", response_model=List[schemas.FindingResponse])
async def get_findings(
    session_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get all findings for a session"""
    findings = await crud.get_session_findings(db, session_id)
    return findings


@router.get("/{session_id}/flags", response_model=List[schemas.FlagResponse])
async def get_flags(
    session_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get all flags discovered in a session"""
    flags = await crud.get_session_flags(db, session_id)
    return flags
