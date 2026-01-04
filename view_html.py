import requests
import json

BASE_URL = "http://localhost:8000"
session_id = 23

resp = requests.get(f"{BASE_URL}/chat/history", params={"session_id": session_id})
history = resp.json()

for msg in history:
    if msg.get('tool_results'):
        for result in msg['tool_results']:
            if isinstance(result, dict) and 'html' in result:
                print("="*80)
                print("EXTRACTED HTML:")
                print("="*80)
                print(result['html'])
                print("="*80)
