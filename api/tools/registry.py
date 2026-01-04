from typing import Dict, Type, List
from pathlib import Path
from .base import BaseTool, ToolDefinition
from .browser import BrowserTool
from .web_fuzzer import WebFuzzerTool
from .get_fuzzer_result import GetFuzzerResultTool


class ToolRegistry:
    """Registry for managing all available tools"""
    
    def __init__(self, state_dir: Path = None):
        self._tools: Dict[str, BaseTool] = {}
        self.state_dir = state_dir or Path("/app/.playwright")
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default tools"""
        self.register(BrowserTool(self.state_dir))
        self.register(WebFuzzerTool(self.state_dir))
        self.register(GetFuzzerResultTool(self.state_dir))
    
    def register(self, tool: BaseTool):
        """Register a new tool"""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> BaseTool:
        """Get tool by name"""
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        """Get all registered tools"""
        return list(self._tools.values())
    
    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Get all tool definitions for Gemini function calling"""
        return [tool.get_definition() for tool in self._tools.values()]
    
    async def execute_tool(self, tool_name: str, **kwargs) -> Dict:
        """Execute a tool by name"""
        tool = self.get_tool(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not found"}
        
        return await tool.execute(**kwargs)
    
    async def cleanup_all(self):
        """Cleanup all tools"""
        for tool in self._tools.values():
            await tool.cleanup()


# Global tool registry instance
tool_registry = ToolRegistry()
