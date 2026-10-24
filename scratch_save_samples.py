# Extract the raw JSON for 3 specific screenshot pairs:
# Pair 1 (11:10), Pair 3 (11:20), Pair 5 (11:30)

pair_1_raw = {
    "pair": "Pair 1 (11:10 IST)",
    "order_flow_file": "screenshots/footprint/20261013_111021_order_flow.png",
    "option_chain_file": "screenshots/option_chain/20261013_111029_option_chain_main.png",
    "order_flow_json": {
        "symbol": "NIFTY-FUT",
        "current_price": 22688.30,
        "candle_interval": "5m",
        "cumulative_delta": 11455,
        "poc_price": 22688.30,
        "vah_price": 22694.00,
        "val_price": 22683.00,
        "candle_deltas": [
            {"timestamp": "10:40", "open": 22683.00, "high": 22694.50, "low": 22683.00, "close": 22693.50, "delta": 975, "cumulative_delta": 975, "total_volume": 3710},
            {"timestamp": "10:45", "open": 22683.00, "high": 22694.50, "low": 22683.00, "close": 22693.00, "delta": 910, "cumulative_delta": 1885, "total_volume": 1400}
        ]
    },
    "option_chain_json": {
        "symbol": "NIFTY",
        "underlying_price": 25503.20,
        "expiry": "13-OCT-2026",
        "days_to_expiry": 0,
        "pcr": None,
        "atm_iv": None,
        "max_pain": 0.0,
        "strikes": [
            {"strike": 22250, "call": {"ltp": 257.95, "change": 134.90, "volume": 14929915, "buildup": "Short Covering"}, "put": {"ltp": 4.95, "change": -88.31, "volume": 184753370, "buildup": "Short Buildup"}},
            {"strike": 22300, "call": {"ltp": 209.75, "change": 117.80, "volume": 6000870, "buildup": "Short Covering"}, "put": {"ltp": 7.70, "change": -87.48, "volume": 33828665, "buildup": "Short Buildup"}},
            {"strike": 22400, "call": {"ltp": 163.45, "change": 97.65, "volume": 82963935, "buildup": "Short Covering"}, "put": {"ltp": 19.55, "change": -83.14, "volume": 42902560, "buildup": "Short Buildup"}},
            {"strike": 22450, "call": {"ltp": 121.50, "change": 74.45, "volume": 20473425, "buildup": "Short Covering"}, "put": {"ltp": 31.80, "change": -79.00, "volume": 37637935, "buildup": "Short Buildup"}},
            {"strike": 22500, "call": {"ltp": 83.40, "change": 50.50, "volume": 24294615, "buildup": "Long Buildup"}, "put": {"ltp": 51.45, "change": -73.36, "volume": 54843935, "buildup": "Short Buildup"}},
            {"strike": 22550, "call": {"ltp": 31.20, "change": 13.45, "volume": 45353930, "buildup": "Long Buildup"}, "put": {"ltp": 80.00, "change": -156.65, "volume": 303773130, "buildup": "Short Buildup"}}
        ]
    }
}

pair_3_raw = {
    "pair": "Pair 3 (11:20 IST)",
    "order_flow_file": "screenshots/footprint/20261013_112020_order_flow.png",
    "option_chain_file": "screenshots/option_chain/20261013_112028_option_chain_main.png",
    "order_flow_json": {
        "symbol": "NIFTY-FUT",
        "current_price": 22680.00,
        "candle_interval": "5m",
        "cumulative_delta": 325,
        "poc_price": 22680.00,
        "vah_price": 22690.00,
        "val_price": 22675.00,
        "candle_deltas": [
            {"timestamp": "11:15", "open": 22670.00, "high": 22685.00, "low": 22670.00, "close": 22680.00, "delta": 325, "cumulative_delta": 325, "total_volume": 1250}
        ]
    },
    "option_chain_json": {
        "symbol": "NIFTY",
        "underlying_price": 22504.60,
        "expiry": "13-OCT-2026",
        "days_to_expiry": 0,
        "pcr": 1.05,
        "atm_iv": 13.8,
        "max_pain": 22500.0,
        "strikes": [
            {"strike": 22250, "call": {"ltp": 262.25, "change": 139.20, "volume": 15122315, "buildup": "Short Covering"}, "put": {"ltp": 4.00, "change": -38.35, "volume": 19537975, "buildup": "Short Buildup"}},
            {"strike": 22300, "call": {"ltp": 214.15, "change": 122.20, "volume": 6135090, "buildup": "Short Buildup"}, "put": {"ltp": 6.25, "change": -55.25, "volume": 35810895, "buildup": "Short Buildup"}},
            {"strike": 22350, "call": {"ltp": 168.25, "change": 102.45, "volume": 9104470, "buildup": "Short Buildup"}, "put": {"ltp": 9.95, "change": -75.65, "volume": 28848645, "buildup": "Short Buildup"}},
            {"strike": 22400, "call": {"ltp": 125.15, "change": 78.10, "volume": 21172840, "buildup": "Long Buildup"}, "put": {"ltp": 18.00, "change": -98.00, "volume": 48192000, "buildup": "Short Buildup"}},
            {"strike": 22450, "call": {"ltp": 85.90, "change": 52.80, "volume": 254212440, "buildup": "Long Buildup"}, "put": {"ltp": 27.85, "change": -126.01, "volume": 4096533, "buildup": "Short Buildup"}},
            {"strike": 22500, "call": {"ltp": 46.30, "change": -146.85, "volume": 52972965, "buildup": "Neutral"}, "put": {"ltp": 43.15, "change": -50.00, "volume": 481798720, "buildup": "Long Buildup"}}
        ]
    }
}

pair_5_raw = {
    "pair": "Pair 5 (11:30 IST)",
    "order_flow_file": "screenshots/footprint/20261013_113019_order_flow.png",
    "option_chain_file": "screenshots/option_chain/20261013_113027_option_chain_main.png",
    "order_flow_json": {
        "symbol": "NIFTY-FUT",
        "current_price": 22685.00,
        "candle_interval": "5m",
        "cumulative_delta": 520,
        "poc_price": 22685.00,
        "vah_price": 22695.00,
        "val_price": 22680.00,
        "candle_deltas": [
            {"timestamp": "11:20", "open": 22675.00, "high": 22685.00, "low": 22670.00, "close": 22680.00, "delta": 1240, "cumulative_delta": 2280, "total_volume": 2400},
            {"timestamp": "11:25", "open": 22680.00, "high": 22690.00, "low": 22675.00, "close": 22685.00, "delta": 1040, "cumulative_delta": 3320, "total_volume": 1560}
        ]
    },
    "option_chain_json": {
        "symbol": "NIFTY",
        "underlying_price": 22486.50,
        "expiry": "13-OCT-2024",
        "days_to_expiry": 0,
        "pcr": 0.82,
        "atm_iv": 14.5,
        "max_pain": 22450.0,
        "strikes": [
            {"strike": 22250, "call": {"ltp": 239.55, "change": 116.50, "volume": 15321215, "buildup": "Short Covering"}, "put": {"ltp": 4.55, "change": -37.80, "volume": 20368350, "buildup": "Short Buildup"}},
            {"strike": 22300, "call": {"ltp": 192.05, "change": 100.10, "volume": 6280290, "buildup": "Short Covering"}, "put": {"ltp": 7.25, "change": -54.25, "volume": 37443950, "buildup": "Short Buildup"}},
            {"strike": 22350, "call": {"ltp": 146.05, "change": 80.70, "volume": 9275480, "buildup": "Short Covering"}, "put": {"ltp": 11.80, "change": -73.60, "volume": 30318560, "buildup": "Short Buildup"}},
            {"strike": 22400, "call": {"ltp": 104.85, "change": 57.80, "volume": 21901970, "buildup": "Long Buildup"}, "put": {"ltp": 20.15, "change": -95.80, "volume": 49171035, "buildup": "Short Buildup"}},
            {"strike": 22450, "call": {"ltp": 68.10, "change": 31.55, "volume": 58642615, "buildup": "Long Buildup"}, "put": {"ltp": 34.40, "change": -117.30, "volume": 44385730, "buildup": "Short Buildup"}}
        ]
    }
}

import json
with open("sample_3_pairs.json", "w") as f:
    json.dump([pair_1_raw, pair_3_raw, pair_5_raw], f, indent=2)
print("Saved 3 sample pairs successfully")
