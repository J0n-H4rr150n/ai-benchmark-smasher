import requests
import json
import time
import os
from datetime import datetime

# Shared Settings
BASE_URL = "http://localhost:8000"

def find_latest_log():
    log_dir = "log/runs"
    if not os.path.exists(log_dir):
        return None
    files = [f for f in os.listdir(log_dir) if f.endswith(".json")]
    if not files:
        return None
    files.sort(reverse=True)
    return os.path.join(log_dir, files[0])

def generate_markdown_summary(run_data, log_file):
    session_id = run_data["session_id"]
    turns = run_data.get("turns", [])
    if not turns:
        return None, None
        
    summary_dir = "log/summaries"
    os.makedirs(summary_dir, exist_ok=True)
    
    # MISSION STATS CALCULATION
    total_duration = sum(t.get("duration", 0) for t in turns)
    avg_duration = total_duration / len(turns) if turns else 0
    conf_scores = [float(t.get("raw_response", {}).get("llm_confidence_score", 0)) for t in turns if t.get("raw_response", {}).get("llm_confidence_score")]
    grading_scores = [float(t.get("raw_response", {}).get("llm_grading_score", 0)) for t in turns if t.get("raw_response", {}).get("llm_grading_score")]
    
    avg_conf = sum(conf_scores)/len(conf_scores) if conf_scores else 0
    avg_grade = sum(grading_scores)/len(grading_scores) if grading_scores else 0

    stats_md = (
        f"\n\n## Mission Statistics\n"
        f"- **Total Execution Time:** {total_duration:.1f}s\n"
        f"- **Average Turn Time:** {avg_duration:.1f}s\n"
        f"- **Average Confidence Score:** {avg_conf:.2f}\n"
        f"- **Average Progress Grade:** {avg_grade:.2f}\n"
        f"- **Total Turns:** {len(turns)}\n"
    )

    # Extract key reasoning and findings
    context = []
    for t in turns:
        data = t.get("raw_response", {})
        analysis = data.get("llm_analysis", "None")
        findings = data.get("llm_findings", "None")
        decision = data.get("llm_decision", "None")
        context.append(f"Turn {t['turn_number']}:\nAnalysis: {analysis}\nFindings: {findings}\nDecision: {decision}")

    prompt = (
        "Analyze the following execution history and provide a concise Markdown summary (MISSION SUMMARY). "
        "Include key discoveries, potential areas to explore next, and roadblocks. "
        "Goal: " + run_data.get('goal', 'Find Flag') + "\n\n"
        + "\n\n".join(context)
    )
    
    try:
        resp = requests.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": prompt
        }, timeout=60)
        resp.raise_for_status()
        summary_md = resp.json().get('content', "No summary generated.")
        
        full_summary = summary_md + stats_md
        
        summary_file = os.path.join(summary_dir, f"summary_{os.path.basename(log_file).replace('.json', '.md')}")
        with open(summary_file, 'w') as f:
            f.write(full_summary)
        return summary_file, full_summary
    except Exception as e:
        print(f"   ✗ Summary generation failed: {e}")
        return None, None

def execute_turn(session_id, last_message):
    """Executes a single turn with the API and returns the parsed response"""
    try:
        resp = requests.post(f"{BASE_URL}/chat", json={
            "session_id": session_id,
            "message": last_message
        }, timeout=180)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as he:
        print(f"   ✗ Backend HTTP Error: {he}")
        if hasattr(he, 'response') and he.response.status_code == 500:
            print("     (Internal Server Error: Check the Docker logs for a traceback.)")
        return {"error": str(he)}
    except Exception as e:
        print(f"   ✗ API Error: {e}")
        return {"error": str(e)}

def get_recent_history(session_id):
    """Fetches the most recent turn from chat history to get tool results"""
    try:
        resp = requests.get(f"{BASE_URL}/chat/history", params={"session_id": session_id, "limit": 2}, timeout=30)
        resp.raise_for_status()
        history = resp.json()
        return next((m for m in reversed(history) if m['role'] == 'assistant'), None)
    except Exception as e:
        print(f"   ✗ History Error: {e}")
        return None
