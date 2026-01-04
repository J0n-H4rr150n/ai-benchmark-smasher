import os
import json
from typing import Dict, Any, List, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from pathlib import Path

from .base import BaseTool, ToolParameter
from ..config import settings


class BrowserTool(BaseTool):
    """Playwright-based browser automation tool with persistent sessions"""
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.state_dir = Path(settings.playwright_state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
    
    @property
    def name(self) -> str:
        return "browser"
    
    @property
    def description(self) -> str:
        return "Navigate web pages, interact with forms, click buttons, and extract content using a real browser with persistent session"
    
    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="action",
                type="string",
                description="Action to perform: navigate, click, fill, submit, extract, screenshot, execute_js",
                required=True
            ),
            ToolParameter(
                name="url",
                type="string",
                description="URL to navigate to (required for 'navigate' action)",
                required=False
            ),
            ToolParameter(
                name="selector",
                type="string",
                description="CSS selector for element (required for click, fill actions)",
                required=False
            ),
            ToolParameter(
                name="text",
                type="string",
                description="Text to fill in form field (for 'fill' action)",
                required=False
            ),
            ToolParameter(
                name="script",
                type="string",
                description="JavaScript code to execute (for 'execute_js' action)",
                required=False
            )
        ]
    
    async def _ensure_browser(self):
        """Ensure browser and context are initialized"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            
            # Load persistent context
            context_state_file = self.state_dir / "browser_state.json"
            storage_state = None
            
            if context_state_file.exists():
                with open(context_state_file, 'r') as f:
                    storage_state = json.load(f)
            
            self.context = await self.browser.new_context(storage_state=storage_state)
            self.page = await self.context.new_page()
    
    async def _save_context(self):
        """Save browser context state for session persistence"""
        if self.context:
            context_state_file = self.state_dir / "browser_state.json"
            storage_state = await self.context.storage_state()
            with open(context_state_file, 'w') as f:
                json.dump(storage_state, f)
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute browser action"""
        await self._ensure_browser()
        
        action = kwargs.get("action")
        result = {"action": action, "success": False}
        
        try:
            if action == "navigate":
                url = kwargs.get("url")
                if not url:
                    result["error"] = "URL is required for navigate action"
                    return result
                
                await self.page.goto(url, wait_until="networkidle", timeout=30000)
                result["success"] = True
                result["url"] = self.page.url
                result["title"] = await self.page.title()
                
            elif action == "click":
                selector = kwargs.get("selector")
                if not selector:
                    result["error"] = "Selector is required for click action"
                    return result
                
                await self.page.click(selector, timeout=10000)
                result["success"] = True
                result["url"] = self.page.url
                
            elif action == "fill":
                selector = kwargs.get("selector")
                text = kwargs.get("text", "")
                if not selector:
                    result["error"] = "Selector is required for fill action"
                    return result
                
                await self.page.fill(selector, text, timeout=10000)
                result["success"] = True
                
            elif action == "submit":
                selector = kwargs.get("selector", "form")
                await self.page.locator(selector).press("Enter")
                await self.page.wait_for_load_state("networkidle", timeout=10000)
                result["success"] = True
                result["url"] = self.page.url
                
            elif action == "extract":
                from bs4 import BeautifulSoup
                content = await self.page.content()
                
                # Parse for intelligent summary
                soup = BeautifulSoup(content, 'lxml')
                
                # Extract key elements for LLM
                summary = {
                    "title": await self.page.title(),
                    "forms": len(soup.find_all('form')),
                    "inputs": len(soup.find_all('input')),
                    "links": len(soup.find_all('a')),
                    "scripts": len(soup.find_all('script')),
                    "comments": len([c for c in soup.find_all(string=lambda text: isinstance(text, __import__('bs4').Comment))])
                }
                
                # Extract important snippets
                snippets = []
                
                # HTML comments (often hide flags)
                from bs4 import Comment
                comments = soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments[:10]:
                    snippets.append(f"<!-- {str(comment).strip()[:200]} -->")
                
                # Script content
                for script in soup.find_all('script')[:5]:
                    if script.string:
                        snippets.append(f"<script>{script.string[:300]}</script>")
                
                # Hidden fields
                for hidden in soup.find_all('input', type='hidden')[:10]:
                    snippets.append(f"Hidden: {hidden.get('name')}={hidden.get('value')}")
                
                result["success"] = True
                result["html"] = content  # Full HTML for backend flag detection
                result["url"] = self.page.url
                result["title"] = summary["title"]
                result["summary"] = summary
                result["key_snippets"] = snippets
                
            elif action == "screenshot":
                screenshot_path = self.state_dir / "screenshot.png"
                await self.page.screenshot(path=str(screenshot_path))
                result["success"] = True
                result["screenshot_path"] = str(screenshot_path)
                
            elif action == "execute_js":
                script = kwargs.get("script")
                if not script:
                    result["error"] = "Script is required for execute_js action"
                    return result
                
                js_result = await self.page.evaluate(script)
                result["success"] = True
                result["result"] = js_result
            
            else:
                result["error"] = f"Unknown action: {action}"
            
            # Save context after each action
            await self._save_context()
            
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    async def cleanup(self):
        """Clean up browser resources"""
        if self.context:
            await self._save_context()
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
