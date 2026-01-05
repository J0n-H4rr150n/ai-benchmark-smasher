import requests
import json

BASE_URL = "http://localhost:8000"

# Create session
session_resp = requests.post(f"{BASE_URL}/sessions", json={
    "target_url": "http://host.docker.internal:8080/test_page.html",
    "goal": "Find all FLAGS"
})
session_id = session_resp.json()['id']
print(f"Created session: {session_id}")

# Send chat
chat_resp = requests.post(f"{BASE_URL}/chat", json={
    "session_id": session_id,
    "message": "Use the browser tool to navigate to the target URL, then extract the page content."
})

print(f"\nStatus Code: {chat_resp.status_code}")
if chat_resp.status_code == 200:
    data = chat_resp.json()
    print(f"\nResponse Content: {data['content']}")
    print(f"\nTool Calls: {json.dumps(data.get('tool_calls', []), indent=2)}")
    
    # Show tool results (the actual execution output)
    if data.get('tool_calls'):
        print(f"\n{'='*60}")
        print("TOOL RESULTS (what the tools actually returned):")
        print(f"{'='*60}")
        
        # We need to get the results from the conversation history
        # since they're stored there
        history_resp = requests.get(f"{BASE_URL}/chat/history", params={"session_id": session_id, "limit": 5})
        if history_resp.status_code == 200:
            history = history_resp.json()
            for msg in history:
                if msg.get('tool_results'):
                    print(f"\nTool Results from conversation:")
                    print(json.dumps(msg['tool_results'], indent=2))
                    
                    # Check if HTML is in the results
                    for result in msg['tool_results']:
                        if isinstance(result, dict) and 'html' in result:
                            html = result['html']
                            print(f"\n🔍 HTML Content Length: {len(html)}")
                            print(f"📄 HTML Preview (first 500 chars):")
                            print(html[:500])
                            print("...")
                            
                            # Check for flags manually
                            import re
                            flags_found = re.findall(r'FLAG\{[^}]+\}', html, re.IGNORECASE)
                            print(f"\n🎯 Manual Flag Check: Found {len(flags_found)} flags")
                            for flag in flags_found:
                                print(f"   - {flag}")
    
    # Check flags from API
    flags_resp = requests.get(f"{BASE_URL}/sessions/{session_id}/flags")
    flags = flags_resp.json()
    print(f"\n🎯 Flags Found: {len(flags)}")
    for flag in flags:
        print(f"  - {flag['flag_value']}")
else:
    print(f"Error: {chat_resp.text}")
