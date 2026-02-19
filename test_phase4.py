import requests
import json
import os
import time

BASE_URL = "http://localhost:7860/api/v1"

def test_admin_config():
    print("Testing Admin Config...")
    try:
        res = requests.get(f"{BASE_URL}/admin/config")
        if res.status_code == 200:
            print(f"PASS: {res.json()}")
            return res.json()['snapshot_read_token']
        else:
            print(f"FAIL: {res.status_code} {res.text}")
    except Exception as e:
        print(f"FAIL: {e}")
    return None

def test_memories(token):
    print("\nTesting Memories...")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create
    mem = {
        "content": "Phase 4 Test Memory",
        "category": "semantic",
        "level": "semantic",
        "source_llm": "test_script",
        "confidence_score": 0.95
    }
    res = requests.post(f"{BASE_URL}/memories/", json=mem, headers=headers)
    if res.status_code == 200:
        mem_id = res.json()['id']
        print(f"PASS: Created memory {mem_id}")
    else:
        print(f"FAIL: Create {res.status_code} {res.text}")
        return

    # List
    res = requests.get(f"{BASE_URL}/memories/", headers=headers)
    if res.status_code == 200:
        data = res.json()
        if isinstance(data, dict) and 'items' in data:
            print(f"PASS: Listed {len(data['items'])} memories")
        elif isinstance(data, list):
            print(f"PASS: Listed {len(data)} memories")
        else:
            print(f"FAIL: Unexpected format {type(data)}")
    else:
        print(f"FAIL: List {res.status_code} {res.text}")

def test_conversations():
    print("\nTesting Conversations...")
    res = requests.get(f"{BASE_URL}/conversations/")
    if res.status_code == 200:
        print(f"PASS: Listed {len(res.json())} conversations")
    else:
        print(f"FAIL: List {res.status_code} {res.text}")

def test_import():
    print("\nTesting Import (Simulated)...")
    # This is hard to test without a file, but we can check the endpoint exists
    # by sending a bad request
    res = requests.post(f"{BASE_URL}/import/upload")
    if res.status_code == 422: # Missing file
        print("PASS: Import endpoint active (422 as expected for missing file)")
    else:
        print(f"FAIL: Import {res.status_code} {res.text}")

if __name__ == "__main__":
    token = test_admin_config()
    if token:
        test_memories(token)
        test_conversations()
        test_import()
