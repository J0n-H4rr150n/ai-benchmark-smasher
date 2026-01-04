from pathlib import Path
from typing import Dict, Any, List
from .base import BaseTool, ToolParameter

class SearchKnowledgeTool(BaseTool):
    """Search knowledge base of successful CTF strategies"""
    
    @property
    def name(self) -> str:
        return "search_knowledge_base"
    
    @property
    def description(self) -> str:
        return "Search past successful CTF runs for similar strategies and methodologies. Use this to learn from previous successes when tackling similar challenges."
    
    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="What to search for (e.g., 'IDOR vulnerability', 'SQL injection in login form', 'bypassing authentication')",
                required=True
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="Maximum number of results to return (default: 3)",
                required=False
            )
        ]
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query")
        limit = kwargs.get("limit", 3)
        
        # Import here to avoid circular dependency
        from ..database import AsyncSessionLocal
        from ..crud_knowledge import search_knowledge_base
        
        async with AsyncSessionLocal() as db:
            results = await search_knowledge_base(db, query, limit)
        
        if not results:
            return {
                "success": True,
                "results": [],
                "message": "No similar strategies found in knowledge base yet. This appears to be a new type of challenge!"
            }
        
        # Format results for Gemini
        formatted_results = []
        for r in results:
            formatted_results.append({
                "similarity": round(r["similarity"], 2),
                "vulnerability_type": r["vulnerability_type"],
                "goal": r["goal"],
                "methodology": r["methodology"],
                "breakthrough_insight": r["breakthrough_insight"],
                "tools_used": r["tools_used"],
                "target_characteristics": r["target_characteristics"]
            })
        
        return {
            "success": True,
            "query": query,
            "results": formatted_results,
            "count": len(formatted_results),
            "message": f"Found {len(formatted_results)} similar successful strategies"
        }
