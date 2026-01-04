import os
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Response
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
        self.element_cache: Dict[int, Any] = {}
        self.network_logs = []
    
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
                description="Action to perform: navigate, click, type, submit, extract, screenshot, execute_js, auth_state",
                required=True
            ),
            ToolParameter(
                name="url",
                type="string",
                description="URL to navigate to (required for 'navigate' action)",
                required=False
            ),
            ToolParameter(
                name="element_id",
                type="integer",
                description="SoM Element ID for interaction (required for click, type actions)",
                required=False
            ),
            ToolParameter(
                name="selector",
                type="string",
                description="CSS selector for element (fallback for click, type actions)",
                required=False
            ),
            ToolParameter(
                name="text",
                type="string",
                description="Text to fill in form field (for 'type' action)",
                required=False
            ),
            ToolParameter(
                name="script",
                type="string",
                description="JavaScript code to execute (for 'execute_js' action)",
                required=False
            )
        ]
    
    async def _capture_network_traffic(self, response: Response):
        """Capture Fetch/XHR/Document traffic"""
        try:
            request = response.request
            if request.resource_type not in ["fetch", "xhr", "document"]:
                return

            log_entry = {
                "url": response.url,
                "method": request.method,
                "status": response.status,
                "timestamp": time.time(),
                "request_headers": request.headers,
                "response_headers": response.headers,
                "body": None
            }

            # Capture bodies for JSON and text content
            try:
                content_type = response.headers.get("content-type", "").lower()
                if "application/json" in content_type:
                    body = await response.json()
                    log_entry["body"] = str(body)
                elif "text/" in content_type:
                    body = await response.text()
                    log_entry["body"] = body
            except:
                pass

            self.network_logs.append(log_entry)
            if len(self.network_logs) > 50:
                self.network_logs.pop(0)
        except:
            pass

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
            
            self.context = await self.browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            
            self.page = await self.context.new_page()
            self.page.on("response", self._capture_network_traffic)
    
    async def _save_context(self):
        """Save browser context state for session persistence"""
        if self.context:
            context_state_file = self.state_dir / "browser_state.json"
            storage_state = await self.context.storage_state()
            with open(context_state_file, 'w') as f:
                json.dump(storage_state, f)

    def _get_recent_network_activity(self) -> str:
        """Summarize recent network activity"""
        if not self.network_logs: return "No recent XHR/Fetch."
        sorted_logs = sorted(self.network_logs, key=lambda x: x['timestamp'], reverse=True)
        summary = []
        for log in sorted_logs[:50]:
            req_headers = str(log.get('request_headers', {}))
            resp_headers = str(log.get('response_headers', {}))
            body_val = log.get('body')
            
            if body_val is None:
                body_str = "{not captured}"
            elif str(body_val).strip() == "":
                body_str = "{empty}"
            else:
                body_str = str(body_val)
                if len(body_str) > 500:
                    body_str = body_str[:500] + "... [Truncated]"
            
            summary.append(f"[{log['method']}] {log['status']} {log['url']} \n   Request Headers: {req_headers}\n   Response Headers: {resp_headers}\n   Body: {body_str}")
        return "\n".join(summary)

    async def _clean_marks(self):
        """Remove SoM markers from page"""
        if self.page:
            await self.page.evaluate("() => { document.querySelectorAll('.som-marker').forEach(e => e.remove()); }")

    async def _inject_marks(self) -> List[Dict[str, Any]]:
        """Inject SoM markers and return element metadata"""
        await self._clean_marks()
        self.element_cache = {}

        js_script = """
        () => {
            const elements = Array.from(document.querySelectorAll('a, button, input, textarea, select, [role="button"], [onclick]'));
            const items = [];
            let counter = 0;

            elements.forEach(el => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);

                // Visibility Checks
                if (rect.width < 5 || rect.height < 5) return;
                if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return;
                
                // Simplified occlusion check
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                if (centerX < 0 || centerY < 0 || centerX > window.innerWidth || centerY > window.innerHeight) return;

                counter++;
                
                // Draw Marker
                const marker = document.createElement('div');
                marker.className = 'som-marker';
                marker.textContent = counter;
                marker.style.cssText = 'position:absolute;left:' + (rect.left+window.scrollX) + 'px;top:' + (rect.top+window.scrollY) + 'px;background:#FF0000;color:white;font-size:12px;font-weight:900;padding:1px 3px;z-index:2147483647;pointer-events:none;border:1px solid white;border-radius:2px;box-shadow:0 0 2px black;';
                document.body.appendChild(marker);
                
                items.push({
                    id: counter,
                    tagName: el.tagName.toLowerCase(),
                    text: el.innerText ? el.innerText.replace(/\\n/g, ' ') : '',
                    type: el.type || ''
                });
                
                el.setAttribute('data-som-id', counter.toString());
            });
            return items;
        }
        """
        
        try:
            elements_metadata = await self.page.evaluate(js_script)
            # Find and cache handles
            for meta in elements_metadata:
                eid = meta['id']
                handle = await self.page.query_selector(f'[data-som-id="{eid}"]')
                if handle:
                    self.element_cache[eid] = handle
            return elements_metadata
        except Exception as e:
            logger.error(f"[SoM] JS Injection failed: {e}")
            return []

    async def _get_auth_state(self) -> Dict[str, Any]:
        """Export current auth state (Cookies, LocalStorage, Headers)"""
        cookies = {c['name']: c['value'] for c in await self.context.cookies()}
        
        headers = {
            "User-Agent": await self.page.evaluate("() => navigator.userAgent"),
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # LocalStorage
        origins = "{}"
        try:
            ls = await self.page.evaluate("() => JSON.stringify(window.localStorage)")
            storage_dict = json.loads(ls)
            origins = ls
            # JWT Heuristic
            for k, v in storage_dict.items():
                if "token" in k.lower() or "auth" in k.lower():
                    if isinstance(v, str) and v.startswith("eyJ"):
                        headers["Authorization"] = f"Bearer {v}"
        except:
            pass

        return {
            "cookies": cookies,
            "headers": headers,
            "local_storage": origins
        }
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute browser action"""
        await self._ensure_browser()
        
        action = kwargs.get("action")
        result = {"action": action, "success": False}
        
        try:
            url = kwargs.get("url")
            if url:
                # Handle localhost translation for Docker container
                if "localhost" in url:
                    url = url.replace("localhost", "host.docker.internal")
                
                # Navigate if provided URL is different (and not for navigate action which is handled below)
                if action != "navigate":
                    current_url = self.page.url
                    if url != current_url:
                        await self.page.goto(url, wait_until="networkidle", timeout=30000)

            if action == "navigate":
                if not url:
                    result["error"] = "URL is required for navigate action"
                    return result
                
                await self.page.goto(url, wait_until="networkidle", timeout=30000)
                # Save session after navigation
                await self._save_context()
                # Auto-extract after navigation
                return await self.execute(action="extract")
                
            elif action == "click":
                element_id = kwargs.get("element_id")
                selector = kwargs.get("selector")
                
                if element_id and element_id in self.element_cache:
                    await self.element_cache[element_id].click(timeout=10000)
                elif selector:
                    await self.page.click(selector, timeout=10000)
                else:
                    result["error"] = "element_id or selector is required for click action"
                    return result
                
                # Auto-extract to see result
                return await self.execute(action="extract")
                
            elif action == "type":
                element_id = kwargs.get("element_id")
                selector = kwargs.get("selector")
                text = kwargs.get("text", "")
                
                if element_id and element_id in self.element_cache:
                    await self.element_cache[element_id].fill(text, timeout=10000)
                elif selector:
                    await self.page.fill(selector, text, timeout=10000)
                else:
                    result["error"] = "element_id or selector is required for type action"
                    return result
                
                result["success"] = True
                
            elif action == "submit":
                element_id = kwargs.get("element_id")
                selector = kwargs.get("selector", "form")
                
                if element_id and element_id in self.element_cache:
                    await self.element_cache[element_id].press("Enter")
                else:
                    await self.page.locator(selector).press("Enter")
                
                await self.page.wait_for_load_state("networkidle", timeout=10000)
                # Save session after form submit (e.g., after login)
                await self._save_context()
                return await self.execute(action="extract")
                
            elif action == "extract":
                # THE SNAPSHOT TRIAD
                
                # 1. VISUAL (Set of Marks)
                elements_metadata = await self._inject_marks()
                screenshot_path = self.state_dir / "screenshot.png"
                await self.page.screenshot(path=str(screenshot_path))
                
                # 2. CODE (Dynamic DOM + Raw Source)
                content = await self.page.content()
                raw_source = "N/A"
                try:
                    # Attempt to get raw source via separate request
                    import httpx
                    async with httpx.AsyncClient(verify=False) as client:
                        resp = await client.get(self.page.url, timeout=5.0)
                        raw_source = resp.text
                except:
                    pass
                
                # 3. NETWORK (Summarized Logs)
                network_summary = self._get_recent_network_activity()
                
                from bs4 import BeautifulSoup, Comment
                soup = BeautifulSoup(content, 'lxml')
                
                # Intelligence Summary
                summary = {
                    "title": await self.page.title(),
                    "url": self.page.url,
                    "elements_with_marks": len(elements_metadata),
                    "forms": len(soup.find_all('form')),
                    "scripts": len(soup.find_all('script')),
                    "comments": len(soup.find_all(string=lambda text: isinstance(text, Comment)))
                }
                
                # Extract snippets for LLM reasoning
                snippets = []
                # Raw comments from dynamic DOM
                for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                    snippets.append(f"Comment: {str(comment).strip()}")
                
                # Check raw source for differences (hidden comments)
                if raw_source != "N/A":
                    raw_soup = BeautifulSoup(raw_source, 'lxml')
                    raw_comments = raw_soup.find_all(string=lambda text: isinstance(text, Comment))
                    for rc in raw_comments:
                        if str(rc).strip() not in [s.replace("Comment: ", "") for s in snippets]:
                            snippets.append(f"Raw Source Comment: {str(rc).strip()}")

                result.update({
                    "success": True,
                    "url": self.page.url,
                    "summary": summary,
                    "elements": elements_metadata,
                    "snippets": snippets,
                    "network": network_summary,
                    "screenshot_path": str(screenshot_path),
                    "html": content, # Still provide for backend flag detection
                    "raw_source": raw_source
                })
                
            elif action == "auth_state":
                auth = await self._get_auth_state()
                result.update({
                    "success": True,
                    "auth": auth
                })
                
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
