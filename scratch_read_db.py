import sqlite3
import json

conn = sqlite3.connect("C:/bot_data/signals.db")
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", tables)

for t in tables:
    t_name = t[0]
    cursor.execute(f"PRAGMA table_info({t_name})")
    cols = [c[1] for c in cursor.fetchall()]
    print(f"\nTable {t_name} columns:", cols)
    cursor.execute(f"SELECT * FROM {t_name} ORDER BY rowid DESC LIMIT 5")
    rows = cursor.fetchall()
    print(f"Latest 5 rows in {t_name}:")
    for r in rows:
        print(r)
