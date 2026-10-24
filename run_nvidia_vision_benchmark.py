import os
import base64
import json
import time
import traceback
from typing import Dict, Any, List
from openai import OpenAI
from dotenv import load_dotenv

from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT, OPTION_CHAIN_SYSTEM_PROMPT
from src.vision.extractor import safe_json_loads

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=60.0,
    max_retries=0
)

def encode_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

# 10 pairs of order-flow and option-chain screenshots
PAIRS = [
    {
        "id": 1,
        "name": "11:10 IST",
        "of_path": "screenshots/footprint/20261013_111021_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_111029_option_chain_main.png",
        "angel_spot": 22519.0
    },
    {
        "id": 2,
        "name": "11:15 IST",
        "of_path": "screenshots/footprint/20261013_111522_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_111531_option_chain_main.png",
        "angel_spot": 22519.0
    },
    {
        "id": 3,
        "name": "11:20 IST",
        "of_path": "screenshots/footprint/20261013_112020_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_112028_option_chain_main.png",
        "angel_spot": 22519.0
    },
    {
        "id": 4,
        "name": "11:25 IST",
        "of_path": "screenshots/footprint/20261013_112520_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_112528_option_chain_main.png",
        "angel_spot": 22519.0
    },
    {
        "id": 5,
        "name": "11:30 IST",
        "of_path": "screenshots/footprint/20261013_113019_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_113027_option_chain_main.png",
        "angel_spot": 22500.1
    },
    {
        "id": 6,
        "name": "11:35 IST",
        "of_path": "screenshots/footprint/20261013_113520_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_113528_option_chain_main.png",
        "angel_spot": 22510.25
    },
    {
        "id": 7,
        "name": "11:40 IST",
        "of_path": "screenshots/footprint/20261013_114019_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_114027_option_chain_main.png",
        "angel_spot": 22510.25
    },
    {
        "id": 8,
        "name": "11:45 IST",
        "of_path": "screenshots/footprint/20261013_114519_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_114527_option_chain_main.png",
        "angel_spot": 22487.6
    },
    {
        "id": 9,
        "name": "11:50 IST",
        "of_path": "screenshots/footprint/20261013_115020_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_115028_option_chain_main.png",
        "angel_spot": 22504.15
    },
    {
        "id": 10,
        "name": "11:55 IST",
        "of_path": "screenshots/footprint/20261013_115523_order_flow.png",
        "oc_path": "screenshots/option_chain/20261013_115531_option_chain_main.png",
        "angel_spot": 22504.15
    }
]

MODELS = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "google/diffusiongemma-26b-a4b-it",
    "meta/llama-3.2-11b-vision-instruct"
]

def run_extraction(model: str, system_prompt: str, user_text: str, img_b64: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    res = {
        "model": model,
        "latency_sec": 0.0,
        "status": "FAIL",
        "error_code": None,
        "error_message": None,
        "raw_response": None,
        "parsed_json": None
    }
    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        if "llama-3.2" in model:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        dur = time.perf_counter() - t0
        res["latency_sec"] = round(dur, 2)
        raw_text = response.choices[0].message.content or ""
        res["raw_response"] = raw_text
        parsed = safe_json_loads(raw_text)
        res["parsed_json"] = parsed
        res["status"] = "SUCCESS"
    except Exception as e:
        dur = time.perf_counter() - t0
        res["latency_sec"] = round(dur, 2)
        res["error_message"] = str(e)
        if "410" in str(e):
            res["error_code"] = 410
        elif "429" in str(e):
            res["error_code"] = 429
        elif "timed out" in str(e).lower():
            res["error_code"] = "TIMEOUT"
        else:
            res["error_code"] = "ERROR"
    return res

results = {}

print("Starting benchmark across 10 screenshot pairs...", flush=True)

for model in MODELS:
    print(f"\n=======================================================", flush=True)
    print(f"BENCHMARKING MODEL: {model}", flush=True)
    print(f"=======================================================", flush=True)
    model_results = []
    
    for pair in PAIRS:
        p_id = pair["id"]
        p_name = pair["name"]
        print(f"\nProcessing Pair #{p_id} ({p_name}):", flush=True)
        
        # 1. Order Flow
        print(f"  -> Calling Order Flow...", end=" ", flush=True)
        of_b64 = encode_b64(pair["of_path"])
        of_res = run_extraction(
            model=model,
            system_prompt=ORDER_FLOW_SYSTEM_PROMPT,
            user_text="Extract all Order Flow metrics into valid JSON.",
            img_b64=of_b64
        )
        print(f"[{of_res['status']}] {of_res['latency_sec']}s", flush=True)
        if of_res['error_message']:
            print(f"     Err: {of_res['error_message'][:90]}", flush=True)

        # 2. Option Chain
        print(f"  -> Calling Option Chain...", end=" ", flush=True)
        oc_b64 = encode_b64(pair["oc_path"])
        oc_res = run_extraction(
            model=model,
            system_prompt=OPTION_CHAIN_SYSTEM_PROMPT,
            user_text="Extract all Option Chain metrics into valid JSON.",
            img_b64=oc_b64
        )
        print(f"[{oc_res['status']}] {oc_res['latency_sec']}s", flush=True)
        if oc_res['error_message']:
            print(f"     Err: {oc_res['error_message'][:90]}", flush=True)

        # 3. Validation checks
        checks = {
            "pair_id": p_id,
            "pair_name": p_name,
            "of_path": pair["of_path"],
            "oc_path": pair["oc_path"],
            "angel_spot": pair["angel_spot"],
            "of_status": of_res["status"],
            "oc_status": oc_res["status"],
            "of_latency": of_res["latency_sec"],
            "oc_latency": oc_res["latency_sec"],
            "of_raw": of_res["raw_response"],
            "oc_raw": oc_res["raw_response"],
            "of_data": of_res["parsed_json"],
            "oc_data": oc_res["parsed_json"],
            "cum_delta_match": False,
            "cum_delta_val": None,
            "sum_candle_deltas": None,
            "price_close_to_header": False,
            "extracted_of_price": None,
            "spot_within_100": False,
            "extracted_oc_spot": None,
            "strikes_read_correctly": False,
            "strikes_count": 0,
            "overall_pass": False
        }

        # Check Order Flow
        if of_res["parsed_json"] and isinstance(of_res["parsed_json"], dict):
            of_d = of_res["parsed_json"]
            c_delta = of_d.get("cumulative_delta")
            c_deltas_list = of_d.get("candle_deltas", [])
            price = of_d.get("current_price")
            checks["extracted_of_price"] = price
            checks["cum_delta_val"] = c_delta
            
            # Check cum delta math
            if isinstance(c_deltas_list, list) and len(c_deltas_list) > 0:
                s = sum(int(cd.get("delta", 0)) for cd in c_deltas_list if isinstance(cd, dict) and cd.get("delta") is not None)
                checks["sum_candle_deltas"] = s
                if c_delta is not None and abs(c_delta - s) < 50:
                    checks["cum_delta_match"] = True
            
            # Check price close to header (Nifty fut is ~22600-22750 today)
            if price is not None and 22400 <= price <= 22900:
                checks["price_close_to_header"] = True

        # Check Option Chain
        if oc_res["parsed_json"] and isinstance(oc_res["parsed_json"], dict):
            oc_d = oc_res["parsed_json"]
            oc_spot = oc_d.get("underlying_price")
            checks["extracted_oc_spot"] = oc_spot
            if oc_spot is not None and abs(oc_spot - pair["angel_spot"]) <= 100:
                checks["spot_within_100"] = True
            
            strikes = oc_d.get("strikes", [])
            if isinstance(strikes, list) and len(strikes) >= 3:
                checks["strikes_count"] = len(strikes)
                s_vals = [s.get("strike") for s in strikes if isinstance(s, dict) and s.get("strike") is not None]
                if len(s_vals) >= 3 and s_vals == sorted(s_vals):
                    checks["strikes_read_correctly"] = True

        checks["overall_pass"] = (
            checks["cum_delta_match"] and 
            checks["price_close_to_header"] and 
            checks["spot_within_100"] and 
            checks["strikes_read_correctly"]
        )
        model_results.append(checks)
        
        # If model is 410 Gone, no need to spam 20 failed requests
        if of_res.get("error_code") == 410 and oc_res.get("error_code") == 410 and p_id >= 2:
            print(f"  [Notice] Model {model} is 410 Gone. Filling remaining pairs as 410.")
            for rem_pair in PAIRS[p_id:]:
                rem_checks = dict(checks)
                rem_checks["pair_id"] = rem_pair["id"]
                rem_checks["pair_name"] = rem_pair["name"]
                rem_checks["of_path"] = rem_pair["of_path"]
                rem_checks["oc_path"] = rem_pair["oc_path"]
                rem_checks["angel_spot"] = rem_pair["angel_spot"]
                rem_checks["of_latency"] = of_res["latency_sec"]
                rem_checks["oc_latency"] = oc_res["latency_sec"]
                rem_checks["of_status"] = "FAIL (410 Gone)"
                rem_checks["oc_status"] = "FAIL (410 Gone)"
                rem_checks["overall_pass"] = False
                model_results.append(rem_checks)
            break

    results[model] = model_results

# Save all results to disk
with open("benchmark_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nBenchmark completed successfully! Results written to benchmark_results.json", flush=True)
