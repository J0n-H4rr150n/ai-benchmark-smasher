import requests
import json
import os
import time
import sys
import threading
from datetime import datetime
import tester_framework as fw

# Global state for interrupt handling
IS_AI_RUNNING = False

def run_interaction_loop(session_id, last_message, run_data, log_file, max_turns=5):
    """Runs a batch of autonomous turns and updates run_data"""
    global IS_AI_RUNNING
    local_turn = 1
    
    while local_turn <= max_turns:
        IS_AI_RUNNING = True
        print(f"\n--- Batch Turn {local_turn} ---")
        turn_start = time.time()
        
        # Thinking indicator thread
        stop_thinking = threading.Event()
        def thinking_timer():
            while not stop_thinking.is_set():
                elapsed = time.time() - turn_start
                # Clear line and print
                sys.stdout.write(f"\r   (Gemini is thinking... {elapsed:.1f}s)")
                sys.stdout.flush()
                time.sleep(0.1)
        
        t = threading.Thread(target=thinking_timer, daemon=True)
        t.start()
        
        try:
            data = fw.execute_turn(session_id, last_message)
        finally:
            stop_thinking.set()
            t.join()
            sys.stdout.write("\r" + " " * 50 + "\r") # Clear the thinking line
            sys.stdout.flush()
            
        duration = time.time() - turn_start
        print(f"   ✓ Thought for {duration:.1f}s")
        
        if "error" in data:
            print(f"   ✗ Stopping batch due to error.")
            break
            
        global_step = data.get('step_number', 'unknown')
        print(f"--- Global STEP {global_step} ---")
        
        if data.get('content'):
            print(f"\n[Gemini]: {data['content']}\n")

        # Print Structured Analysis
        if data.get('llm_findings') and data['llm_findings'] != "None": 
            print(f"  - Findings: {data['llm_findings']}")
        if data.get('llm_decision'): 
            print(f"  - Decision: {data['llm_decision']}")

        # Get tool results for display
        assistant_msg = fw.get_recent_history(session_id)
        
        if data.get('tool_calls'):
            print(f"\n[Tool Calls]: {[tc['tool'] for tc in data['tool_calls']]}")
            last_message = "Continue"
            if assistant_msg and assistant_msg.get('tool_results'):
                for res in assistant_msg['tool_results']:
                    if 'network' in res:
                        print(f"    Network: {res['network'].strip()}")
        else:
            print(f"\n[AI finished its thought]")
        
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

        if not data.get('tool_calls'):
            IS_AI_RUNNING = False
            break

        local_turn += 1
        time.sleep(2) # Breath between turns
        
    IS_AI_RUNNING = False
    return last_message

def main():
    global IS_AI_RUNNING
    print("========================================")
    print("   AI MISSION CONTROL - CTF TESTER")
    print("========================================\n")

    # 1. SETUP WIZARD
    latest_log_path = fw.find_latest_log()
    resume_data = None
    target_url = "http://localhost:47658/"
    goal = "Find the FLAG{}. Check source code and network traffic."

    try:
        if latest_log_path:
            with open(latest_log_path, 'r') as f:
                resume_data = json.load(f)
            
            print(f"  Target: {resume_data['target_url']}")
            print(f"  Goal: {resume_data['goal']}")
            
            choice = input("\nDo you want to RESUME this session? (y/n): ").lower()
            if choice == 'y':
                session_id = resume_data["session_id"]
                target_url = resume_data["target_url"]
                goal = resume_data["goal"] or goal
                
                print("\n[!] IMPORTANT: Authentication state (cookies/session) is NOT maintained across script restarts.")
                print("    If the mission requires being logged in, the AI will need to re-authenticate.\n")

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
                print(f"✓ Resuming Session {session_id}...")
            else:
                resume_data = None

        if not resume_data:
            target_url = input(f"Target URL [{target_url}]: ") or target_url
            goal_input = input(f"Mission Goal [{goal}]: ")
            if goal_input: goal = goal_input
            
            print(f"\n[!] Creating New Mission Session...")
            resp = requests.post(f"{fw.BASE_URL}/sessions", json={
                "target_url": target_url,
                "goal": goal
            }, timeout=30)
            resp.raise_for_status()
            session_id = resp.json()["id"]
            last_message = goal
            print(f"✓ Started New Session {session_id}...")

    except KeyboardInterrupt:
        print("\n[Exiting Setup...]")
        return
    except Exception as e:
        print(f"   ✗ Connection/Setup Failed: {e}")
        return

    # 2. MAIN INTERACTIVE LOOP
    print("\nEntering Mission Loop. Type 'exit' to quit, or hit Enter to start/continue autonomous run.")
    print("[!] During a run, press Ctrl+C to PAUSE and return to Mission Control.")
    print("[!] Press Ctrl+C at the prompt to EXIT Mission Control.\n")
    
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
            user_input = input("\n[Mission Control] > ").strip()
            
            if user_input.lower() == 'exit':
                break
                
            if user_input:
                # User gave specific feedback or hint
                last_message = user_input
                print(f"✓ Injecting guidance and resuming run...")
            else:
                print(f"✓ Resuming autonomous run...")
            
            # 2. Handle AI Execution
            # Inside run_interaction_loop, IS_AI_RUNNING will be set to True
            last_message = run_interaction_loop(session_id, last_message, current_run_data, log_file, max_turns=20)
            print("\n[Return to Mission Control]")
            
        except KeyboardInterrupt:
            if IS_AI_RUNNING:
                print("\n\n[!] MISSION PAUSED. Standing by for instructions...")
                last_message = "Continue" # Default for next Enter
                IS_AI_RUNNING = False
                continue
            else:
                print("\n[Exiting Mission Control...]")
                break
        except Exception as e:
            print(f"\n[!] Unexpected Error in Main Loop: {e}")
            break

    # 3. CLEANUP & SUMMARY
    try:
        print("\n[Ending Session]")
        summary_file, summary_md = fw.generate_markdown_summary(current_run_data, log_file)
        if summary_file:
            print(f"✓ Summary generated: {summary_file}")
        print(f"Session data saved to {log_file}")
    except KeyboardInterrupt:
        print("\n[Cleanup Interrupted. Data saved to log.]")
    except Exception as e:
        print(f"   ✗ Summary generation failed: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass # Already handled inside main for specific messages
    finally:
        print("\n[Mission Closed]")
        sys.exit(0)
