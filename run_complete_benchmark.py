import os
import base64
import json
import time
import re
from openai import OpenAI
from dotenv import load_dotenv

from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT, OPTION_CHAIN_SYSTEM_PROMPT
from src.vision.extractor import safe_json_loads

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=30.0,
    max_retries=0
)

def encode_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def repair_and_parse_json(text: str) -> dict:
    if not text:
        return {}
    # 1. Clean markdown and common wrappers
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    
    # Replace leading double braces like {{ -> {
    cleaned = re.sub(r"^\{\{", "{", cleaned)
    # Replace double commas
    cleaned = re.sub(r",+", ",", cleaned)
    
    # 2. Try standard safe_json_loads
    try:
        return safe_json_loads(cleaned)
    except Exception:
        pass
        
    # 3. Truncated repair by closing brackets
    pos = cleaned.rfind("}")
    while pos > 0:
        candidate = cleaned[:pos+1]
        open_b = candidate.count("{") - candidate.count("}")
        open_s = candidate.count("[") - candidate.count("]")
        closed_candidate = candidate + ("]" * max(0, open_s)) + ("}" * max(0, open_b))
        try:
            return json.loads(closed_candidate)
        except Exception:
            pos = cleaned.rfind("}", 0, pos)
            
    return {}

PAIRS = [
    {
        "id": 1,
        "time": "11:10",
        "of_path": "screenshots/footprint/20261013_111021_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_111029_option_chain_main.png",
        "header_price": 22688.3,
        "angel_spot": 22519.0
    },
    {
        "id": 2,
        "time": "11:15",
        "of_path": "screenshots/footprint/20261013_111522_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_111531_option_chain_main.png",
        "header_price": 22675.5,
        "angel_spot": 22519.0
    },
    {
        "id": 3,
        "time": "11:20",
        "of_path": "screenshots/footprint/20261013_112020_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_112028_option_chain_main.png",
        "header_price": 22680.0,
        "angel_spot": 22519.0
    },
    {
        "id": 4,
        "time": "11:25",
        "of_path": "screenshots/footprint/20261013_112520_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_112528_option_chain_main.png",
        "header_price": 22682.0,
        "angel_spot": 22519.0
    },
    {
        "id": 5,
        "time": "11:30",
        "of_path": "screenshots/footprint/20261013_113019_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_113027_option_chain_main.png",
        "header_price": 22685.0,
        "angel_spot": 22500.1
    },
    {
        "id": 6,
        "time": "11:35",
        "of_path": "screenshots/footprint/20261013_113520_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_113528_option_chain_main.png",
        "header_price": 22690.0,
        "angel_spot": 22510.25
    },
    {
        "id": 7,
        "time": "11:40",
        "of_path": "screenshots/footprint/20261013_114019_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_114027_option_chain_main.png",
        "header_price": 22700.0,
        "angel_spot": 22510.25
    },
    {
        "id": 8,
        "time": "11:45",
        "of_path": "screenshots/footprint/20261013_114519_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_114527_option_chain_main.png",
        "header_price": 22670.0,
        "angel_spot": 22487.6
    },
    {
        "id": 9,
        "time": "11:50",
        "of_path": "screenshots/footprint/20261013_115020_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_115028_option_chain_main.png",
        "header_price": 22685.0,
        "angel_spot": 22504.15
    },
    {
        "id": 10,
        "time": "11:55",
        "of_path": "screenshots/footprint/20261013_115523_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_115531_option_chain_main.png",
        "header_price": 22695.0,
        "angel_spot": 22504.15
    }
]

MODELS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "google/diffusiongemma-26b-a4b-it",
    "meta/llama-3.2-11b-vision-instruct"
]

results = {}

for model in MODELS:
    print(f"\n=======================================================", flush=True)
    print(f"BENCHMARK: {model}", flush=True)
    print(f"=======================================================", flush=True)
    pair_records = []
    
    for pair in PAIRS:
        p_id = pair["id"]
        p_time = pair["time"]
        print(f"Pair #{p_id} ({p_time})...", end=" ", flush=True)
        
        # Order flow
        t0 = time.perf_counter()
        of_err = None
        of_raw = ""
        of_data = {}
        try:
            b64_of = encode_b64(pair["of_path"])
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": ORDER_FLOW_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract all Order Flow metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_of}"}}
                    ]}
                ],
                "temperature": 0.1,
                "max_tokens": 1500
            }
            if "llama-3.2" in model:
                kwargs["response_format"] = {"type": "json_object"}
            res = client.chat.completions.create(**kwargs)
            of_raw = res.choices[0].message.content or ""
            of_data = repair_and_parse_json(of_raw)
        except Exception as e:
            of_err = str(e)
        of_dur = round(time.perf_counter() - t0, 2)
        
        # Option chain
        t0 = time.perf_counter()
        oc_err = None
        oc_raw = ""
        oc_data = {}
        try:
            b64_oc = encode_b64(pair["oc_path"])
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": OPTION_CHAIN_SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract all Option Chain metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_oc}"}}
                    ]}
                ],
                "temperature": 0.1,
                "max_tokens": 1500
            }
            if "llama-3.2" in model:
                kwargs["response_format"] = {"type": "json_object"}
            res = client.chat.completions.create(**kwargs)
            oc_raw = res.choices[0].message.content or ""
            oc_data = repair_and_parse_json(oc_raw)
        except Exception as e:
            oc_err = str(e)
        oc_dur = round(time.perf_counter() - t0, 2)
        
        # Validation
        cum_delta = of_data.get("cumulative_delta")
        candle_deltas = of_data.get("candle_deltas", [])
        sum_candles = None
        cum_match = False
        if isinstance(candle_deltas, list) and len(candle_deltas) > 0:
            try:
                sum_candles = sum(int(c.get("delta", 0)) for c in candle_deltas if isinstance(c, dict))
                if cum_delta is not None and abs(cum_delta - sum_candles) <= 50:
                    cum_match = True
            except Exception:
                pass
                
        price = of_data.get("current_price")
        price_close = False
        if price is not None and abs(price - pair["header_price"]) <= 50:
            price_close = True
            
        oc_spot = oc_data.get("underlying_price")
        spot_close = False
        if oc_spot is not None and abs(oc_spot - pair["angel_spot"]) <= 100:
            spot_close = True
            
        strikes = oc_data.get("strikes", [])
        strikes_correct = False
        if isinstance(strikes, list) and len(strikes) >= 3:
            s_nums = [s.get("strike") for s in strikes if isinstance(s, dict) and s.get("strike") is not None]
            if len(s_nums) >= 3 and s_nums == sorted(s_nums):
                strikes_correct = True
                
        overall_pass = cum_match and price_close and spot_close and strikes_correct
        
        rec = {
            "pair_id": p_id,
            "time": p_time,
            "of_path": pair["of_path"],
            "oc_path": pair["oc_path"],
            "of_latency": of_dur,
            "oc_latency": oc_dur,
            "of_err": of_err,
            "oc_err": oc_err,
            "cum_delta": cum_delta,
            "sum_candle_deltas": sum_candles,
            "cum_delta_match": cum_match,
            "of_price": price,
            "header_price": pair["header_price"],
            "price_close": price_close,
            "oc_spot": oc_spot,
            "angel_spot": pair["angel_spot"],
            "spot_close": spot_close,
            "strikes_count": len(strikes) if isinstance(strikes, list) else 0,
            "strikes_correct": strikes_correct,
            "overall_pass": overall_pass,
            "of_raw": of_raw,
            "oc_raw": oc_raw,
            "of_data": of_data,
            "oc_data": oc_data
        }
        pair_records.append(rec)
        print(f"OF: {of_dur}s | OC: {oc_dur}s | Pass: {overall_pass}", flush=True)
        
        # If 410 Gone, auto-fill remaining to save unnecessary queries
        if of_err and "410" in of_err and p_id >= 2:
            print("  [Auto-filling remaining 410 Gone pairs]")
            for rem in PAIRS[p_id:]:
                rem_rec = dict(rec)
                rem_rec["pair_id"] = rem["id"]
                rem_rec["time"] = rem["time"]
                rem_rec["of_path"] = rem["of_path"]
                rem_rec["oc_path"] = rem["oc_path"]
                rem_rec["overall_pass"] = False
                pair_records.append(rem_rec)
            break
            
    results[model] = pair_records

with open("benchmark_final_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nAll done! Results saved to benchmark_final_results.json", flush=True)
