import os
import base64
import json
import time
from openai import OpenAI
from dotenv import load_dotenv
from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT, OPTION_CHAIN_SYSTEM_PROMPT

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=45.0,
    max_retries=0
)

def encode_img(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

of_path = "screenshots/footprint/20261013_115523_order_flow.png"
oc_path = "screenshots/option_chain/20261013_115531_option_chain_main.png"

models_to_test = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/muse-glimmer-30b",
    "google/diffusiongemma-26b-a4b-it",
    "nvidia/nemotron-parse-2.0",
    "meta/llama-3.2-11b-vision-instruct"
]

print("--- Testing models on single order flow screenshot ---", flush=True)
b64_of = encode_img(of_path)

for m in models_to_test:
    t0 = time.time()
    try:
        res = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": ORDER_FLOW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all Order Flow metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_of}"}},
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        dur = time.time() - t0
        text = res.choices[0].message.content or ""
        print(f"[{m}] SUCCESS ({dur:.2f}s): {text[:200]}...", flush=True)
    except Exception as e:
        dur = time.time() - t0
        print(f"[{m}] ERROR ({dur:.2f}s): {e}", flush=True)
