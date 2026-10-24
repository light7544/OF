import re
import json

def repair_truncated_json(text: str) -> dict:
    # Find last valid strike end `}`
    # If cut off inside strikes array
    pos = text.rfind("}")
    while pos > 0:
        candidate = text[:pos+1]
        # Count unclosed { and [
        open_b = candidate.count("{") - candidate.count("}")
        open_s = candidate.count("[") - candidate.count("]")
        closed_candidate = candidate + ("]" * open_s) + ("}" * open_b)
        try:
            return json.loads(closed_candidate)
        except Exception:
            pos = text.rfind("}", 0, pos)
    raise ValueError("Could not repair JSON")

test_raw = '''{
  "symbol": "NIFTY",
  "underlying_price": 25503.20,
  "expiry": "13-OCT-2026",
  "days_to_expiry": 0,
  "pcr": 0.0,
  "atm_iv": 0.0,
  "max_pain": 25503.2,
  "strikes": [
    {
      "strike": 22250,
      "call": {"ltp": 257.95, "change": 134.90, "volume": 14929915, "oi": 60008750, "oi_change": 0, "buildup": "Short Covering"},
      "put": {"ltp": 4.95, "change": -37.40, "volume": 184753730, "oi": 0, "oi_change": 0, "buildup": "Short Buildup"}
    },
    {
      "strike": 22300,
      "call": {"ltp": 209.75, "change": 117.80, "volume": 82926935, "oi": 0, "oi_change": 0, "buildup": "Short Covering"},
      "put": {"ltp": 7.70, "change": -53.80, "volume": 33288665, "oi": 0, "oi_change": 0, "buildup": "Short Buildup"}
    }
'''

repaired = repair_truncated_json(test_raw)
print("Repaired successfully! Strikes:", len(repaired["strikes"]))
print(repaired["strikes"])
