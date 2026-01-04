import json
from pathlib import Path
from typing import Dict, Any, List
from .base import BaseTool, ToolParameter

class GetFuzzerResultTool(BaseTool):
    """Retrieve detailed fuzzer results by ID and request number"""
    
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.results_dir = state_dir / "fuzzer_results"
    
    @property
    def name(self) -> str:
        return "get_fuzzer_result"
    
    @property
    def description(self) -> str:
        return "Retrieve detailed request/response data from a previous fuzzer run. Use this to inspect full bodies and headers for specific requests."
    
    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="results_id",
                type="string",
                description="The results_id returned from a web_fuzzer run",
                required=True
            ),
            ToolParameter(
                name="req_num",
                type="integer",
                description="The specific request number to retrieve (from results_summary). Omit to get all results.",
                required=False
            )
        ]
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        results_id = kwargs.get("results_id")
        req_num = kwargs.get("req_num")
        
        results_file = self.results_dir / f"fuzz_{results_id}.json"
        
        if not results_file.exists():
            return {"error": f"Results file not found for ID: {results_id}"}
        
        with open(results_file, 'r') as f:
            full_results = json.load(f)
        
        if req_num is not None:
            # Return specific request
            for result in full_results:
                if result.get("req_num") == req_num:
                    return result
            return {"error": f"Request number {req_num} not found in results"}
        else:
            # Return all results (might be large!)
            return {
                "results_id": results_id,
                "total_results": len(full_results),
                "results": full_results
            }
