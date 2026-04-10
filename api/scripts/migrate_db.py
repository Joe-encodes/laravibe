import sqlite3
import hashlib
import pathlib
from datetime import datetime

DB_PATH = pathlib.Path("data/repair.db")

# Hashes mapped to Case ID and Category from the manifest
BACKFILL_MAP = {
    "8f67a542e966445836a3e7236f32ffad": ("case-001", "missing_model"),
    "5d2340f445c01e4bb6783d7e9e64cb38": ("case-002", "wrong_namespace"),
    "4c5a22c42382d76d01b79bfd8fc977e1": ("case-003", "missing_import"),
}

def migrate():
    if not DB_PATH.exists():
        print("No database found to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("--- Adding new research columns ---")
    cols_to_add = [
        ("case_id", "TEXT"),
        ("category", "TEXT"),
        ("experiment_id", "TEXT"),
    ]

    for col_name, col_type in cols_to_add:
        try:
            c.execute(f"ALTER TABLE submissions ADD COLUMN {col_name} {col_type}")
            print(f"Added column: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"Column {col_name} already exists.")
            else:
                raise e

    print("\n--- Backfilling historical categories ---")
    c.execute("SELECT id, original_code FROM submissions WHERE case_id IS NULL")
    rows = c.fetchall()
    
    updated_count = 0
    for sub_id, code in rows:
        # Fallback keyword matching for older records
        detected_case = None
        if "Product" in code and "missing_model" not in code: # basic heuristic
            detected_case = ("case-001", "missing_model")
        elif "namespace" in code and "App\\Http\\Controllers" in code: # heuristic for 002
            detected_case = ("case-002", "wrong_namespace")
        elif "Str::" in code:
            detected_case = ("case-003", "missing_import")
            
        if detected_case:
            case_id, category = detected_case
            c.execute(
                "UPDATE submissions SET case_id = ?, category = ?, experiment_id = ? WHERE id = ?",
                (case_id, category, f"backfill-{datetime.now().strftime('%Y-%m-%d')}", sub_id)
            )
            updated_count += 1
            print(f"Tagged submission {sub_id[:8]} as {case_id} ({category})")

    conn.commit()
    print(f"\nMigration complete. Backfilled {updated_count} records.")
    conn.close()

if __name__ == "__main__":
    migrate()
