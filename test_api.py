import requests
import time
import json

BASE_URL = "http://localhost:7860/api/v1"
HEALTH_URL = "http://localhost:7860/health"

def test_api():
    print("--- 1. Testing Health ---")
    try:
        res = requests.get(HEALTH_URL)
        print(f"Health Status: {res.status_code}")
        print(f"Body: {res.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")
        return

    print("\n--- 2. Testing Stats ---")
    try:
        res = requests.get(f"{BASE_URL}/memories/stats")
        print(f"Stats Status: {res.status_code}")
        print(f"Body: {res.json()}")
    except Exception as e:
        print(f"Stats failed: {e}")

    print("\n--- 3. Testing Conflicts List ---")
    try:
        res = requests.get(f"{BASE_URL}/conflicts/")
        print(f"Conflicts Status: {res.status_code}")
        data = res.json()
        print(f"Conflicts Count: {len(data)}")
        if len(data) > 0:
            print(f"First Conflict: {data[0]['id']}")
    except Exception as e:
        print(f"Conflicts list failed: {e}")

    print("\n--- 4. Testing Default Memory List ---")
    try:
        res = requests.get(f"{BASE_URL}/memories/")
        print(f"Memories Status: {res.status_code}")
        data = res.json()
        print(f"Memories Count (Default): {len(data)}")
        if len(data) > 0:
            print(f"First Memory: {data[0]['content'][:50]}...")
    except Exception as e:
        print(f"Memories list failed: {e}")

if __name__ == "__main__":
    test_api()
