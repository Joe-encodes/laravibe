import sqlite3
import pathlib

DB_PATH = pathlib.Path("data/repair.db")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE submissions ADD COLUMN user_id VARCHAR(255)")
        print("Column 'user_id' added successfully.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column 'user_id' already exists.")
        else:
            raise e
    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
