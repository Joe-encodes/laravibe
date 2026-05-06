"""
Migration script to add failure tracking columns to iterations table.
Run this if your database schema is out of sync with the models.

Usage:
    python3 scripts/migrate_failure_tracking.py
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "repair.db"

COLUMNS_TO_ADD = [
    ("failure_reason", "VARCHAR(100)"),
    ("failure_details", "TEXT"),
    ("pm_category", "VARCHAR(100)"),
    ("pm_strategy", "TEXT"),
]

def migrate():
    """Add new failure tracking columns if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(iterations)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        print(f"✅ Existing columns: {existing_cols}")
        
        # Add missing columns
        for col_name, col_type in COLUMNS_TO_ADD:
            if col_name not in existing_cols:
                print(f"  Adding column: {col_name} ({col_type})")
                cursor.execute(f"ALTER TABLE iterations ADD COLUMN {col_name} {col_type}")
            else:
                print(f"  ✓ Column {col_name} already exists")
        
        conn.commit()
        print("\n✅ Migration complete!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    print(f"Migrating database: {DB_PATH}")
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        sys.exit(1)
    migrate()
