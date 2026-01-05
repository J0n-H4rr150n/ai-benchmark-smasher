import requests
import json

BASE_URL = "http://localhost:8000"

def test_health():
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}\n")

def test_create_session():
    print("Creating a new CTF session...")
    payload = {
        "target_url": "http://host.docker.internal:8080/test_page.html",
        "goal": "Find all hidden FLAG{} values"
    }
    response = requests.post(f"{BASE_URL}/sessions", json=payload)
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Session created: ID={data['id']}, URL={data['target_url']}\n")
    return data['id']

def test_chat(session_id):
    print(f"Sending prompt to Gemini for session {session_id}...")
    payload = {
        "session_id": session_id,
        "message": "Please analyze the target URL. Use the browser tool to navigate to it and extract all content. Look for any FLAG{} patterns in the HTML, comments, JavaScript, or hidden fields."
    }
    response = requests.post(f"{BASE_URL}/chat", json=payload)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"\nGemini Response:")
        print(f"Content: {data['content'][:500]}...")
        
        if data.get('tool_calls'):
            print(f"\nTool Calls Made: {len(data['tool_calls'])}")
            for tc in data['tool_calls']:
                print(f"  - {tc['tool']}: {tc['args']}")
        
        if data.get('flags'):
            print(f"\n🎉 FLAGS FOUND: {len(data['flags'])}")
            for flag in data['flags']:
                print(f"  - {flag['flag_value']}")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    print("=" * 60)
    print("AI Benchmark Smasher - Test Script")
    print("=" * 60 + "\n")
    
    # Test health
    test_health()
    
    # Create session
    session_id = test_create_session()
    
    # Chat with Gemini
    test_chat(session_id)
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
