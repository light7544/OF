import os
import base64
from openai import OpenAI
from dotenv import load_dotenv
from src.vision.prompts import ORDER_FLOW_SYSTEM_PROMPT

load_dotenv()
client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=os.getenv("NVIDIA_API_KEY"), timeout=30.0)

with open("screenshots/footprint/20261013_115523_order_flow.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

for m in ["google/diffusiongemma-26b-a4b-it", "nvidia/nemotron-parse-2.0"]:
    res = client.chat.completions.create(
        model=m,
        messages=[
            {"role": "system", "content": ORDER_FLOW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all Order Flow metrics into valid JSON."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ],
        temperature=0.1,
        max_tokens=500,
    )
    print(f"=== {m} ===")
    print(res.choices[0].message.content)
