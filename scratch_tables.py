import sqlite3
conn = sqlite3.connect("C:/bot_data/signals.db")
print("Tables:", [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
