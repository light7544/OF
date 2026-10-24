import sqlite3

c = sqlite3.connect("file:C:/bot_data/signals.db?mode=ro", uri=True)
print("signals rows:", c.execute("select count(*) from signals").fetchone()[0])
print("angel snapshots:", c.execute("select count(*), sum(is_mock) from angel_chain_snapshots").fetchone())
for r in c.execute("""select id, signal, is_mock, created_at,
    instr(factors_json,'angel_option_chain')>0
    from signals order by id desc limit 3"""):
    print(r)
