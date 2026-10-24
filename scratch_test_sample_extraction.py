import os
import base64
import json
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=30.0,
    max_retries=0
)

# Load prompts from src.vision.prompts
from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT, ORDER_FLOW_USER_PROMPT

sample_img = "screenshots/footprint/20261013_115523_order_flow.png"
with open(sample_img, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

models_to_test = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "meta/muse-glimmer-30b",
    "google/diffusiongemma-26b-a4b-it",
    "nvidia/nemotron-parse-2.0",
    "meta/llama-3.2-11b-vision-instruct"
]

print("Testing prompt extraction capability on sample screenshot:", flush=True)

for m in models_to_test:
    print(f"\n--- Testing {m} ---", flush=True)
    t0 = time.time()
    try:
        res = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": ORDER_FLOW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ORDER_FLOW_USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }
            ],
            response_format={"type": "json_object"} if "llama-3.2" in m else None,
            max_tokens=1024,
            temperature=0.1
        )
        elapsed = time.time() - t0
        content = res.choices[0].message.content
        print(f"SUCCESS in {elapsed:.2f}s:")
        print(content[:300] + ("..." if len(content) > 300 else ""))
    except Exception as e:
        elapsed = time.time() - t0
        print(f"FAILED in {elapsed:.2f}s: {e}")
