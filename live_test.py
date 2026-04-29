
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"
TOKEN = "laravibe-repair-2026-safe-token"

code = """<?php
namespace App\Http\Controllers;

class UserController extends Controller
{
    public function show($id)
    {
        // Bug: calling undefined method
        return User::find($id)->getDetails();
    }
}
"""

def test_repair():
    print(f"Submitting repair request to {BASE_URL}...")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/repair",
            json={"code": code, "prompt": "Fix the undefined method call and ensure User model is imported."},
            headers={"Authorization": f"Bearer {TOKEN}"}
        )
    except Exception as e:
        print(f"ERROR connecting to server: {e}")
        return
    
    if resp.status_code != 202:
        print(f"FAILED: {resp.status_code} - {resp.text}")
        return
    
    sub_id = resp.json()["submission_id"]
    print(f"Repair accepted! Submission ID: {sub_id}")
    
    print("Streaming events (polling)...")
    for _ in range(60):
        time.sleep(5)
        try:
            status_resp = requests.get(f"{BASE_URL}/api/repair/{sub_id}")
            sub = status_resp.json()
            print(f"Current Status: {sub['status']}")
            if sub["status"] in ["completed", "failed"]:
                print(f"Final Outcome: {sub['status']}")
                if sub["status"] == "completed":
                    print("--- FIXED CODE ---")
                    print(sub.get("final_code", "N/A"))
                else:
                    print(f"Error: {sub.get('error_summary')}")
                break
        except Exception as e:
            print(f"Error polling: {e}")

if __name__ == "__main__":
    test_repair()
