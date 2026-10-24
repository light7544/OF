import sqlite3

conn = sqlite3.connect("C:/bot_data/signals.db")
c = conn.cursor()
c.execute("SELECT id, timestamp, spot, bias FROM angel_chain_snapshots WHERE timestamp LIKE '2026-10-13%' ORDER BY id ASC")
for row in c.fetchall():
    print(row)
