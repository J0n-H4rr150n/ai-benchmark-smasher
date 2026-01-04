import base64
from pathlib import Path
from typing import Dict, Any, List
from .base import BaseTool, ToolParameter

class ViewScreenshotTool(BaseTool):
    """Allow LLM to retrieve and analyze screenshots"""
    
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
    
    @property
    def name(self) -> str:
        return "view_screenshot"
    
    @property
    def description(self) -> str:
        return "Retrieve and analyze a screenshot by its filename. Use this when you need visual confirmation of the page state."
    
    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="filename",
                type="string",
                description="Screenshot filename (e.g., 'screenshot_20260104_164500.png'). You can use 'latest' to get the most recent screenshot.",
                required=True
            )
        ]
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        filename = kwargs.get("filename")
        
        if filename == "latest":
            # Find the most recent screenshot
            screenshots = sorted(self.state_dir.glob("screenshot_*.png"), reverse=True)
            if not screenshots:
                return {"error": "No screenshots found"}
            screenshot_path = screenshots[0]
        else:
            screenshot_path = self.state_dir / filename
        
        if not screenshot_path.exists():
            return {"error": f"Screenshot not found: {filename}"}
        
        # Read and encode the image as base64
        with open(screenshot_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        return {
            "success": True,
            "filename": screenshot_path.name,
            "path": str(screenshot_path),
            "image_data": image_data,
            "mime_type": "image/png",
            "note": "Screenshot retrieved. You can now visually analyze this image."
        }
