from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
from ..database import get_db
from ..crud_knowledge import store_successful_run, search_knowledge_base

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class StoreRunRequest(BaseModel):
    session_id: int
    goal: str
    methodology: str
    vulnerability_type: Optional[str] = None
    target_url: Optional[str] = None
    total_turns: Optional[int] = None
    key_findings: Optional[str] = None
    breakthrough_insight: Optional[str] = None
    tools_used: Optional[List[str]] = None
    summary_file_path: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 3


@router.post("/store")
async def store_successful_run_endpoint(
    request: StoreRunRequest,
    db: AsyncSession = Depends(get_db)
):
    """Store a successful CTF run in the knowledge base"""
    try:
        result = await store_successful_run(
            db=db,
            session_id=request.session_id,
            goal=request.goal,
            methodology=request.methodology,
            vulnerability_type=request.vulnerability_type,
            target_url=request.target_url,
            total_turns=request.total_turns,
            key_findings=request.key_findings,
            breakthrough_insight=request.breakthrough_insight,
            tools_used=request.tools_used,
            summary_file_path=request.summary_file_path
        )
        return {"success": True, "id": result.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_knowledge_endpoint(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Search knowledge base for similar strategies"""
    try:
        results = await search_knowledge_base(
            db=db,
            query=request.query,
            limit=request.limit
        )
        return {"success": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
