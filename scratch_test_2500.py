import os
import base64
import time
from openai import OpenAI
from dotenv import load_dotenv
from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT, OPTION_CHAIN_SYSTEM_PROMPT
from src.vision.extractor import safe_json_loads

load_dotenv()
client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=os.getenv("NVIDIA_API_KEY"), timeout=60.0, max_retries=0)

def encode_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

of_b64 = encode_b64("screenshots/footprint/20261013_111021_order_flow.png")
oc_b64 = encode_b64("screenshots/option_chain/20261013_111029_option_chain_main.png")

for model in ["google/diffusiongemma-26b-a4b-it", "meta/llama-3.2-11b-vision-instruct"]:
    print(f"\n==================== {model} (max_tokens=2500) ====================")
    for name, p_sys, img_b64 in [("Order Flow", ORDER_FLOW_SYSTEM_PROMPT, of_b64), ("Option Chain", OPTION_CHAIN_SYSTEM_PROMPT, oc_b64)]:
        t0 = time.perf_counter()
        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": p_sys},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract all metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                    ]}
                ],
                "temperature": 0.1,
                "max_tokens": 2500
            }
            if "llama-3.2" in model:
                kwargs["response_format"] = {"type": "json_object"}
            
            res = client.chat.completions.create(**kwargs)
            dur = time.perf_counter() - t0
            raw = res.choices[0].message.content or ""
            print(f"[{name}] {dur:.2f}s | chars={len(raw)}")
            # Try parsing
            try:
                parsed = safe_json_loads(raw)
                print(f"   -> Successfully parsed! Keys: {list(parsed.keys())}")
                if "current_price" in parsed:
                    print(f"   -> current_price: {parsed.get('current_price')}, cum_delta: {parsed.get('cumulative_delta')}")
                if "underlying_price" in parsed:
                    print(f"   -> underlying_price: {parsed.get('underlying_price')}, strikes count: {len(parsed.get('strikes', []))}")
            except Exception as pe:
                print(f"   -> Parse error: {pe}")
                print(f"   -> Raw snippet: {raw[:200]} ... {raw[-150:]}")
        except Exception as e:
            dur = time.perf_counter() - t0
            print(f"[{name}] FAIL ({dur:.2f}s): {e}")
