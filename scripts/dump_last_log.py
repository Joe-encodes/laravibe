import sqlite3
import json
import sys

def dump_latest_iteration():
    print("Fetching latest repair iteration from data/repair.db...\n")
    try:
        conn = sqlite3.connect("data/repair.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT submission_id, iteration, error_logs, boost_context, ai_prompt, ai_response, patch_applied
            FROM repair_iterations
            ORDER BY created_at DESC
            LIMIT 1
        ''')
        row = cursor.fetchone()
        
        if not row:
            print("No iterations found in the database.")
            return

        sub_id, iteration, error_logs, boost_context, ai_prompt, ai_response, patch_applied = row
        
        print(f"=== SUBMISSION ID: {sub_id} | ITERATION: {iteration} ===\n")
        
        print("--- 1. BOOST CONTEXT (Injected) ---")
        if boost_context:
            try:
                print(json.dumps(json.loads(boost_context), indent=2))
            except:
                print(boost_context)
        else:
            print("None/Empty")
            
        print("\n--- 2. CURRENT ERROR / STATE ---")
        print(error_logs or "None")
        
        print("\n--- 3. FULL PROMPT SENT TO MODEL (If Saved) ---")
        print(ai_prompt or "Prompt not saved in DB for this iteration.")
        
        print("\n--- 4. RAW AI RESPONSE ---")
        print(ai_response or "None")
        
        print("\n--- 5. EXTRACTED PATCH ---")
        print(patch_applied or "None")
        print("\n==================================")
        
    except Exception as e:
        print(f"Error accessing database: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    dump_latest_iteration()
