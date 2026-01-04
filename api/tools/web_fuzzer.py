import asyncio
import httpx
import re
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from .base import BaseTool, ToolParameter

class WebFuzzerTool(BaseTool):
    """Safe, rate-limited endpoint fuzzer for IDOR and discovery"""
    
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.results_dir = state_dir / "fuzzer_results"
        self.results_dir.mkdir(exist_ok=True)
    
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
        full_results = []  # Store complete data separately
        baseline_stats = {} # (status, length) -> count

        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            for idx, val in enumerate(fuzz_values, start=1):
                url = url_template.replace("{{VAL}}", val)
                # Handle localhost translation for Docker container
                if "localhost" in url:
                    url = url.replace("localhost", "host.docker.internal")
                
                try:
                    resp = await client.request(method, url)
                    
                    # Extract useful headers (Burp Intruder style)
                    content_type = resp.headers.get("content-type", "unknown")
                    location = resp.headers.get("location", "")
                    set_cookie = resp.headers.get("set-cookie", "")
                    
                    # Summary data for quick viewing
                    data = {
                        "req_num": idx,
                        "value": val,
                        "status": resp.status_code,
                        "resp_length": len(resp.text),
                        "content_type": content_type,
                        "location": location,
                        "set_cookie": bool(set_cookie),
                        "interesting": False
                    }
                    
                    # Full data for detailed inspection
                    full_data = {
                        **data,
                        "url": url,
                        "method": method,
                        "request_headers": dict(resp.request.headers),
                        "response_headers": dict(resp.headers),
                        "response_body": resp.text,
                    }
                    
                    # Check for success criteria match
                    if success_criteria and re.search(success_criteria, resp.text, re.IGNORECASE):
                        data["interesting"] = True
                        full_data["interesting"] = True
                        # Only include snippet in summary for interesting responses
                        data["snippet"] = resp.text[:500] + ("..." if len(resp.text) > 500 else "")
                    
                    # Track baseline
                    key = (data["status"], data["resp_length"])
                    baseline_stats[key] = baseline_stats.get(key, 0) + 1
                    
                    results.append(data)
                    full_results.append(full_data)
                except Exception as e:
                    err_data = {"req_num": idx, "value": val, "error": str(e)}
                    results.append(err_data)
                    full_results.append(err_data)

                await asyncio.sleep(rate_limit_ms / 1000.0)

        # Detect Anomaly
        # Baseline is the most common (status, length) pair
        baseline_key = max(baseline_stats, key=baseline_stats.get) if baseline_stats else (None, None)
        
        anomalies = []
        for r in results:
            if "error" in r:
                anomalies.append(r)  # Errors are always anomalies
                continue
            if (r.get("status"), r.get("resp_length")) != baseline_key or r.get("interesting"):
                anomalies.append(r)

        # Save full results to disk
        results_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.results_dir / f"fuzz_{results_id}.json"
        with open(results_file, 'w') as f:
            json.dump(full_results, f, indent=2)

        return {
            "results_id": results_id,
            "mode": mode,
            "url_template": url_template,
            "total_requests": len(results),
            "baseline": {"status": baseline_key[0], "length": baseline_key[1], "count": baseline_stats.get(baseline_key, 0)},
            "results_summary": results,  # Full table for analysis
            "anomalies": anomalies,
            "summary": f"Performed {len(results)} requests. Baseline: {baseline_key[0]} with {baseline_key[1]} bytes ({baseline_stats.get(baseline_key, 0)} occurrences). Found {len(anomalies)} anomalies. Use results_id '{results_id}' to retrieve full details."
        }
