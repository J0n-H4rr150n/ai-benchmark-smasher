import requests
import json
import os
import time
import sys
import threading
from datetime import datetime
import tester_framework as fw

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.theme import Theme
from rich.live import Live
from rich.table import Table

# Custom theme for CTF
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "success": "bold green",
    "gemini": "bold purple",
    "tool": "bold blue",
    "finding": "green",
    "decision": "cyan",
    "step": "bold yellow"
})

console = Console(theme=custom_theme)

# Global state for interrupt handling
IS_AI_RUNNING = False

def run_interaction_loop(session_id, last_message, run_data, log_file, max_turns=5):
    """Runs a batch of autonomous turns and updates run_data"""
    global IS_AI_RUNNING
    local_turn = 1
    
    while local_turn <= max_turns:
        IS_AI_RUNNING = True
        console.print(Rule(f"[bold yellow]Turn {local_turn}[/bold yellow]", style="yellow"))
        
        turn_start = time.time()
        
        # Thinking indicator
        with console.status("[bold purple]Gemini is thinking...", spinner="dots"):
            try:
                data = fw.execute_turn(session_id, last_message)
            except KeyboardInterrupt:
                # Pass it up
                raise
            
        duration = time.time() - turn_start
        console.print(f"[dim]✓ Thought for {duration:.1f}s[/dim]")
        
        if "error" in data:
            console.print(Panel(f"[danger]Backend Error:[/danger] {data['error']}", border_style="red"))
            break
            
        global_step = data.get('step_number', 'unknown')
        
        # Compact Summary Line
        console.print(Rule(style="dim"))
        assistant_msg_text = data.get('content', '').strip()
        if assistant_msg_text:
            console.print(f"[bold white]Assistant:[/bold white] {assistant_msg_text}")
        
        # Tool Call Summary
        if data.get('tool_calls'):
            for tc in data['tool_calls']:
                tool_name = tc['tool']
                params = tc.get('args', {})
                
                # Format tool call compactly
                if tool_name == 'browser':
                    action = params.get('action', 'unknown')
                    url = params.get('url', '')
                    selector = params.get('selector', '')
                    text = params.get('text', '')
                    element_id = params.get('element_id', '')
                    
                    if action == 'navigate':
                        console.print(f"[tool]tool call → {tool_name}[{action}]:[/tool] {url}")
                    elif action == 'click':
                        target = f"element #{element_id}" if element_id else f"selector '{selector}'"
                        console.print(f"[tool]tool call → {tool_name}[{action}]:[/tool] {target}")
                    elif action == 'type':
                        target = f"element #{element_id}" if element_id else f"selector '{selector}'"
                        console.print(f"[tool]tool call → {tool_name}[{action}]:[/tool] {target} = '{text}'")
                    else:
                        console.print(f"[tool]tool call → {tool_name}[{action}]:[/tool] {params}")
                elif tool_name == 'web_fuzzer':
                    mode = params.get('mode', '')
                    url_template = params.get('url_template', '')
                    console.print(f"[tool]tool call → {tool_name}[{mode}]:[/tool] {url_template}")
                else:
                    # Generic tool display
                    param_str = ", ".join([f"{k}={v}" for k, v in params.items()])
                    console.print(f"[tool]tool call → {tool_name}:[/tool] {param_str}")
            
            last_message = "Continue"

        # Detailed LLM Reasoning Section (collapsible panel)
        reasoning_lines = []
        
        if data.get('llm_analysis') and data['llm_analysis'] != "None":
            reasoning_lines.append(f"[bold cyan]Analysis:[/bold cyan]\n{data['llm_analysis']}")
        
        if data.get('llm_findings') and data['llm_findings'] != "None":
            reasoning_lines.append(f"[bold green]Findings:[/bold green]\n{data['llm_findings']}")
        
        if data.get('llm_ideas') and data['llm_ideas'] != "None":
            reasoning_lines.append(f"[bold yellow]Ideas:[/bold yellow]\n{data['llm_ideas']}")
        
        if data.get('llm_next_steps') and data['llm_next_steps'] != "None":
            reasoning_lines.append(f"[bold magenta]Next Steps:[/bold magenta]\n{data['llm_next_steps']}")
        
        if data.get('llm_critique') and data['llm_critique'] != "None":
            reasoning_lines.append(f"[bold red]Critique:[/bold red]\n{data['llm_critique']}")
        
        if data.get('llm_decision') and data['llm_decision'] != "None":
            reasoning_lines.append(f"[bold white]Decision:[/bold white]\n{data['llm_decision']}")
        
        # Scores on one line
        scores = []
        if data.get('llm_confidence_score'):
            scores.append(f"Confidence: {data['llm_confidence_score']}/1.0")
        if data.get('llm_grading_score'):
            scores.append(f"Progress: {data['llm_grading_score']}/1.0")
        if scores:
            reasoning_lines.append(f"[dim]" + " | ".join(scores) + "[/dim]")
        
        if data.get('llm_need_block') and data['llm_need_block'] != "None":
            reasoning_lines.append(f"[warning]⚠️  Need from User:[/warning]\n{data['llm_need_block']}")
        
        if reasoning_lines:
            console.print(Panel(
                "\n\n".join(reasoning_lines),
                title="[bold cyan]🧠 Reasoning[/bold cyan]",
                border_style="dim cyan",
                padding=(1, 2)
            ))
        
        # Get tool results for turn recording
        assistant_msg = fw.get_recent_history(session_id)
        
        # Record turn
        turn_info = {
            "turn_number": local_turn,
            "global_step": global_step,
            "input_message": last_message,
            "raw_response": data,
            "assistant_message": assistant_msg,
            "duration": duration
        }
        run_data["turns"].append(turn_info)
        
        # Intermediate save
        with open(log_file, 'w') as f:
            json.dump(run_data, f, indent=2)

        # Check for goal completion
        if data.get('content') and 'GOAL-COMPLETE' in data['content']:
            console.print("\n[bold green]🎯 PRIMARY GOAL ACHIEVED! Auto-saving mission...[/bold green]")
            with console.status("[bold cyan]Generating summary...", spinner="dots"):
                summary_file, _ = fw.generate_markdown_summary(run_data, log_file)
            if summary_file:
                console.print(f"[success]✓ Summary saved:[/success] [link=file://{summary_file}]{os.path.basename(summary_file)}[/link]")
            
            # Store in knowledge base
            console.print("[info]💾 Storing strategy in knowledge base...[/info]")
            try:
                # Extract methodology from run
                methodology_parts = []
                for turn in run_data.get("turns", []):
                    if turn.get("raw_response", {}).get("llm_analysis"):
                        methodology_parts.append(f"Turn {turn['turn_number']}: {turn['raw_response']['llm_analysis']}")
                
                methodology = "\n\n".join(methodology_parts[-5:])  # Last 5 turns of analysis
                
                # Detect vulnerability type from content
                vuln_type = None
                content_lower = data.get('content', '').lower()
                if 'idor' in content_lower:
                    vuln_type = "IDOR"
                elif 'sql' in content_lower or 'injection' in content_lower:
                    vuln_type = "SQLi"
                elif 'xss' in content_lower:
                    vuln_type = "XSS"
                elif 'auth' in content_lower or 'bypass' in content_lower:
                    vuln_type = "Auth Bypass"
                
                # Get tools used
                tools_used = list(set([
                    tc['tool'] 
                    for turn in run_data.get("turns", []) 
                    for tc in turn.get("raw_response", {}).get("tool_calls", [])
                ]))
                
                # Store in knowledge base via API
                resp = requests.post(f"{fw.BASE_URL}/knowledge/store", json={
                    "session_id": session_id,
                    "goal": goal,
                    "methodology": methodology,
                    "vulnerability_type": vuln_type,
                    "target_url": target_url,
                    "total_turns": len(run_data.get("turns", [])),
                    "key_findings": data.get('llm_findings', ''),
                    "breakthrough_insight": data.get('llm_decision', ''),
                    "tools_used": tools_used,
                    "summary_file_path": summary_file
                }, timeout=30)
                
                if resp.status_code == 200:
                    console.print("[success]✓ Strategy stored in knowledge base[/success]")
                else:
                    console.print(f"[warning]⚠ Failed to store in knowledge base: {resp.text}[/warning]")
            except Exception as e:
                console.print(f"[warning]⚠ Knowledge base storage error: {e}[/warning]")
            
            console.print("[dim]You can continue exploring or type 'exit'/'new' to finish.[/dim]\n")

        if not data.get('tool_calls'):
            IS_AI_RUNNING = False
            break

        local_turn += 1
        time.sleep(1) # Small breath
        
    IS_AI_RUNNING = False
    return last_message

def main():
    global IS_AI_RUNNING
    
    console.print(Panel.fit(
        "[bold yellow]MISSION CONTROL[/bold yellow]\n[dim]AI-Powered Vulnerability Research[/dim]",
        border_style="yellow",
        padding=(1, 4)
    ))

    # 1. SETUP WIZARD
    latest_log_path = fw.find_latest_log()
    resume_data = None
    target_url = "http://localhost:47658/"
    goal = "Find the FLAG{}. Check source code and network traffic."

    try:
        if latest_log_path:
            with open(latest_log_path, 'r') as f:
                resume_data = json.load(f)
            
            console.print(Panel(
                f"[bold cyan]Target:[/bold cyan] {resume_data['target_url']}\n"
                f"[bold cyan]Goal:[/bold cyan] {resume_data['goal']}",
                title="Latest Session Detected",
                border_style="cyan"
            ))
            
            choice = console.input("\n[bold yellow]Do you want to RESUME this session? (y/n): [/bold yellow]").lower()
            if choice == 'y':
                session_id = resume_data["session_id"]
                target_url = resume_data["target_url"]
                goal = resume_data["goal"] or goal
                
                console.print("\n[warning][!] IMPORTANT:[/warning] Authentication state (cookies/session) is NOT maintained across script restarts.\n")

                # Load summary
                summary_path = f"log/summaries/summary_{os.path.basename(latest_log_path).replace('.json', '.md')}"
                initial_context = f"Mission Resumed. The browser session has been RESET; you may need to log in again if you were previously authenticated.\n\nLast run summary:\n"
                if os.path.exists(summary_path):
                    with open(summary_path, 'r') as f:
                        initial_context += f.read()
                else:
                    last_turn = resume_data["turns"][-1] if resume_data.get("turns") else None
                    initial_context += f"Last findings: {last_turn['raw_response'].get('llm_findings', 'None') if last_turn else 'None'}"
                
                last_message = f"{initial_context}\n\nPlease continue the investigation."
                console.print(f"[success]✓ Resuming Session {session_id}...[/success]")
            else:
                resume_data = None

        if not resume_data:
            target_url = console.input(f"[bold white]Target URL[/bold white] [dim]({target_url})[/dim]: ") or target_url
            goal_input = console.input(f"[bold white]Mission Goal[/bold white] [dim]({goal})[/dim]: ")
            if goal_input: goal = goal_input
            
            console.print(f"\n[bold info]Creating New Mission Session...[/bold info]")
            resp = requests.post(f"{fw.BASE_URL}/sessions", json={
                "target_url": target_url,
                "goal": goal
            }, timeout=30)
            resp.raise_for_status()
            session_id = resp.json()["id"]
            last_message = goal
            console.print(f"[success]✓ Started New Session {session_id}...[/success]")

    except KeyboardInterrupt:
        console.print("\n[warning]Exiting Setup...[/warning]")
        return
    except Exception as e:
        console.print(f"\n[danger]✗ Connection/Setup Failed:[/danger] {e}")
        return

    # 2. MAIN INTERACTIVE LOOP
    console.print(Rule(style="dim"))
    console.print("[dim]During a run, press Ctrl+C to PAUSE. At prompt, press Ctrl+C to EXIT.[/dim]\n")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"log/runs/tester_{timestamp}.json"
    os.makedirs("log/runs", exist_ok=True)
    
    current_run_data = {
        "timestamp": timestamp,
        "session_id": session_id,
        "target_url": target_url,
        "goal": goal,
        "turns": []
    }

    while True:
        try:
            IS_AI_RUNNING = False
            # Show options before each prompt
            console.print("[dim]Commands: [bold]exit[/bold] | [bold]new[/bold] | [bold]Enter[/bold] to continue[/dim]")
            user_input = console.input("[bold yellow]Mission Control[/bold yellow] > ").strip()
            
            if user_input.lower() == 'exit':
                break
            
            if user_input.lower() == 'new':
                # Save current session summary
                console.print("\n[info]Saving current mission...[/info]")
                with console.status("[bold cyan]Generating summary...", spinner="dots"):
                    fw.generate_markdown_summary(current_run_data, log_file)
                
                # Prompt for new mission
                console.print("\n[bold yellow]Starting New Mission[/bold yellow]")
                target_url = console.input(f"[bold white]Target URL[/bold white]: ") or "http://localhost:47658/"
                goal_input = console.input(f"[bold white]Mission Goal[/bold white]: ")
                if goal_input: goal = goal_input
                
                console.print(f"\n[bold info]Creating New Mission Session...[/bold info]")
                resp = requests.post(f"{fw.BASE_URL}/sessions", json={
                    "target_url": target_url,
                    "goal": goal
                }, timeout=30)
                resp.raise_for_status()
                session_id = resp.json()["id"]
                last_message = goal
                
                # Reset for new mission
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = f"log/runs/tester_{timestamp}.json"
                current_run_data = {
                    "timestamp": timestamp,
                    "session_id": session_id,
                    "target_url": target_url,
                    "goal": goal,
                    "turns": []
                }
                console.print(f"[success]✓ New Session {session_id} Started[/success]\n")
                continue
                
            if user_input:
                last_message = user_input
                console.print(f"[success]✓ Injecting guidance and resuming run...[/success]")
            else:
                console.print(f"[success]✓ Resuming autonomous run...[/success]")
            
            # Run execution batch
            last_message = run_interaction_loop(session_id, last_message, current_run_data, log_file, max_turns=20)
            console.print("\n[dim]-- Return to Mission Control --[/dim]")
            
        except KeyboardInterrupt:
            if IS_AI_RUNNING:
                console.print("\n\n[warning][!] MISSION PAUSED.[/warning] Standing by for instructions...")
                last_message = "Continue"
                IS_AI_RUNNING = False
                continue
            else:
                console.print("\n[warning][!] Exiting Mission Control...[/warning]")
                break
        except Exception as e:
            console.print(f"\n[danger]✗ Unexpected Error in Main Loop:[/danger] {e}")
            break

    # 3. CLEANUP & SUMMARY
    try:
        console.print(Rule(style="dim"))
        console.print("[bold yellow]Ending Session[/bold yellow]")
        with console.status("[bold cyan]Generating mission summary...", spinner="dots"):
            summary_file, _ = fw.generate_markdown_summary(current_run_data, log_file)
        
        if summary_file:
            console.print(f"[success]✓ Summary generated:[/success] [link=file://{summary_file}]{os.path.basename(summary_file)}[/link]")
        console.print(f"[success]✓ Session data saved to:[/success] {log_file}")
    except KeyboardInterrupt:
        console.print("\n[warning]Cleanup Interrupted. Data saved to log.[/warning]")
    except Exception as e:
        console.print(f"\n[danger]✗ Summary generation failed:[/danger] {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        console.print(Rule(style="yellow"))
        console.print("[bold yellow]MISSION CLOSED[/bold yellow]", justify="center")
        sys.exit(0)
