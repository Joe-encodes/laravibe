import sqlite3
import pandas as pd

conn = sqlite3.connect('data/repair.db')

# Tables
tables = ['users', 'submissions', 'iterations', 'repair_summaries']

for t in tables:
    print(f"\n--- Table: {t} ---")
    try:
        df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
        print(f"Total rows: {len(df)}")
        # Check for nulls
        null_counts = df.isnull().sum()
        print("Null counts:")
        print(null_counts[null_counts > 0])
        
        # Check for empty strings or just whitespace
        empty_counts = (df.map(lambda x: str(x).strip() == '' if pd.notnull(x) else False)).sum()
        print("Empty string counts:")
        print(empty_counts[empty_counts > 0])
    except Exception as e:
        print(f"Error: {e}")

conn.close()
