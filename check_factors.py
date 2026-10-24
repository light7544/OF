import sqlite3, json
c = sqlite3.connect("file:C:/bot_data/signals.db?mode=ro", uri=True)
r = c.execute("select id, signal, is_mock, created_at, factors_json from signals order by id desc limit 1").fetchone()
print(r[:4])
print(json.dumps(json.loads(r[4]), indent=2))
