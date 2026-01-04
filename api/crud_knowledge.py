from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import List, Dict, Any, Optional
from .models import SuccessfulRun
from .core.embedding_service import get_embedding_service


async def store_successful_run(
    db: AsyncSession,
    session_id: int,
    goal: str,
    methodology: str,
    vulnerability_type: Optional[str] = None,
    target_url: Optional[str] = None,
    total_turns: Optional[int] = None,
    key_findings: Optional[str] = None,
    breakthrough_insight: Optional[str] = None,
    tools_used: Optional[List[str]] = None,
    target_characteristics: Optional[str] = None,
    summary_file_path: Optional[str] = None
) -> SuccessfulRun:
    """
    Store a successful CTF run in the knowledge base with embedding
    
    Args:
        db: Database session
        session_id: ID of the successful session
        goal: Mission goal
        methodology: Detailed methodology text (will be embedded)
        ... other metadata fields
        
    Returns:
        Created SuccessfulRun object
    """
    # Generate embedding for methodology
    embedding_service = get_embedding_service()
    methodology_embedding = embedding_service.generate_embedding(methodology)
    
    # Create record
    successful_run = SuccessfulRun(
        session_id=session_id,
        goal=goal,
        vulnerability_type=vulnerability_type,
        target_url=target_url,
        total_turns=total_turns,
        methodology=methodology,
        key_findings=key_findings,
        breakthrough_insight=breakthrough_insight,
        tools_used=tools_used or [],
        target_characteristics=target_characteristics,
        methodology_embedding=methodology_embedding,
        summary_file_path=summary_file_path
    )
    
    db.add(successful_run)
    await db.commit()
    await db.refresh(successful_run)
    
    return successful_run


async def search_knowledge_base(
    db: AsyncSession,
    query: str,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Search for similar successful runs using cosine similarity
    
    Args:
        db: Database session
        query: Search query text
        limit: Max number of results to return
        
    Returns:
        List of matching runs with similarity scores
    """
    # Generate query embedding
    embedding_service = get_embedding_service()
    query_embedding = embedding_service.generate_embedding(query)
    
    # Convert to string for SQL query
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
    
    # Cosine similarity search using pgvector
    # Lower distance = more similar (cosine distance)
    query_sql = text("""
        SELECT 
            id,
            session_id,
            goal,
            vulnerability_type,
            target_url,
            total_turns,
            methodology,
            key_findings,
            breakthrough_insight,
            tools_used,
            target_characteristics,
            summary_file_path,
            1 - (methodology_embedding <=> :query_embedding::vector) as similarity
        FROM successful_runs
        ORDER BY methodology_embedding <=> :query_embedding::vector
        LIMIT :limit
    """)
    
    result = await db.execute(
        query_sql,
        {"query_embedding": embedding_str, "limit": limit}
    )
    rows = result.fetchall()
    
    # Format results
    results = []
    for row in rows:
        results.append({
            "id": row.id,
            "session_id": row.session_id,
            "goal": row.goal,
            "vulnerability_type": row.vulnerability_type,
            "target_url": row.target_url,
            "total_turns": row.total_turns,
            "methodology": row.methodology,
            "key_findings": row.key_findings,
            "breakthrough_insight": row.breakthrough_insight,
            "tools_used": row.tools_used,
            "target_characteristics": row.target_characteristics,
            "summary_file_path": row.summary_file_path,
            "similarity": float(row.similarity)
        })
    
    return results


async def get_all_successful_runs(db: AsyncSession) -> List[SuccessfulRun]:
    """Get all successful runs from knowledge base"""
    result = await db.execute(select(SuccessfulRun).order_by(SuccessfulRun.created_at.desc()))
    return result.scalars().all()


async def get_successful_run_by_id(db: AsyncSession, run_id: int) -> Optional[SuccessfulRun]:
    """Get a specific successful run by ID"""
    result = await db.execute(select(SuccessfulRun).where(SuccessfulRun.id == run_id))
    return result.scalar_one_or_none()
