import asyncio
import httpx
import re
import time
from typing import Dict, Any, List, Optional
from .base import BaseTool, ToolParameter

class WebFuzzerTool(BaseTool):
    """Safe, rate-limited endpoint fuzzer for IDOR and discovery"""
    
    @property
    def name(self) -> str:
        return "web_fuzzer"
    
    @property
    def description(self) -> str:
        return "Safe, rate-limited endpoint fuzzer. Use it to test ranges of IDs or wordlists against an endpoint (e.g. for IDOR)."
    
    @property
    def parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="mode",
                type="string",
                description="Fuzzing mode: 'integer' (sequential numbers) or 'list' (provided strings/wordlist)",
                required=True
            ),
            ToolParameter(
                name="url_template",
                type="string",
                description="URL with {{VAL}} placeholder (e.g. 'http://example.com/api/user/{{VAL}}')",
                required=True
            ),
            ToolParameter(
                name="start_value",
                type="integer",
                description="Starting number for 'integer' mode",
                required=False
            ),
            ToolParameter(
                name="end_value",
                type="integer",
                description="Ending number for 'integer' mode",
                required=False
            ),
            ToolParameter(
                name="values",
                type="array",
                description="List of strings for 'list' mode",
                required=False
            ),
            ToolParameter(
                name="wordlist_path",
                type="string",
                description="Absolute path to a wordlist file for 'list' mode",
                required=False
            ),
            ToolParameter(
                name="method",
                type="string",
                description="HTTP method (default: GET)",
                required=False
            ),
            ToolParameter(
                name="batch_size",
                type="integer",
                description="Max requests per call (default: 20, max: 50)",
                required=False
            ),
            ToolParameter(
                name="rate_limit_ms",
                type="integer",
                description="Delay between requests in ms (default: 500, min: 100)",
                required=False
            ),
            ToolParameter(
                name="success_criteria",
                type="string",
                description="Regex/keyword to flag interesting responses",
                required=False
            )
        ]

    async def execute(self, **kwargs) -> Dict[str, Any]:
        mode = kwargs.get("mode")
        url_template = kwargs.get("url_template")
        method = kwargs.get("method", "GET").upper()
        batch_size = min(int(kwargs.get("batch_size", 20)), 50)
        rate_limit_ms = max(int(kwargs.get("rate_limit_ms", 500)), 100)
        success_criteria = kwargs.get("success_criteria")
        
        # Prepare values
        fuzz_values = []
        if mode == "integer":
            start = int(kwargs.get("start_value", 0))
            end = int(kwargs.get("end_value", start))
            for i in range(start, min(end + 1, start + batch_size)):
                fuzz_values.append(str(i))
        elif mode == "list":
            if kwargs.get("values"):
                fuzz_values = kwargs.get("values")[:batch_size]
            elif kwargs.get("wordlist_path"):
                try:
                    with open(kwargs["wordlist_path"], 'r') as f:
                        fuzz_values = [line.strip() for line in f if line.strip()][:batch_size]
                except Exception as e:
                    return {"error": f"Failed to read wordlist: {e}"}
        else:
            return {"error": f"Invalid mode: {mode}"}

        if not fuzz_values:
            return {"error": "No values provided for fuzzing"}

        results = []
        baseline_stats = {} # (status, length) -> count

        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            for val in fuzz_values:
                url = url_template.replace("{{VAL}}", val)
                # Handle localhost translation for Docker container
                if "localhost" in url:
                    url = url.replace("localhost", "host.docker.internal")
                
                try:
                    resp = await client.request(method, url)
                    data = {
                        "value": val,
                        "status": resp.status_code,
                        "length": len(resp.text),
                        "interesting": False
                    }
                    
                    if success_criteria and re.search(success_criteria, resp.text, re.IGNORECASE):
                        data["interesting"] = True
                        data["snippet"] = resp.text
                    
                    # Track baseline
                    key = (data["status"], data["length"])
                    baseline_stats[key] = baseline_stats.get(key, 0) + 1
                    
                    results.append(data)
                except Exception as e:
                    results.append({"value": val, "error": str(e)})

                await asyncio.sleep(rate_limit_ms / 1000.0)

        # Detect Anomaly
        # Baseline is the most common (status, length) pair
        baseline_key = max(baseline_stats, key=baseline_stats.get) if baseline_stats else (None, None)
        
        anomalies = []
        for r in results:
            if "error" in r: continue
            if (r["status"], r["length"]) != baseline_key or r.get("interesting"):
                anomalies.append(r)

        return {
            "mode": mode,
            "url_template": url_template,
            "total_requests": len(results),
            "baseline": {"status": baseline_key[0], "length": baseline_key[1], "count": baseline_stats.get(baseline_key, 0)},
            "anomalies": anomalies,
            "summary": f"Performed {len(results)} requests. Found {len(anomalies)} anomalies relative to baseline ({baseline_key})."
        }
