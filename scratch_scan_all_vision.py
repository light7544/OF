import os
import json
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=httpx.Timeout(8.0, connect=5.0),
    max_retries=0
)

DUMMY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAEASTN7b4AAAAASUVORK5CYII="

with open("nvidia_models.json") as f:
    all_models = json.load(f)

print(f"Scanning {len(all_models)} models for image acceptance (timeout=8s, retries=0)...", flush=True)

successes = []
for m in all_models:
    try:
        res = client.chat.completions.create(
            model=m,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hi"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{DUMMY_PNG_B64}"}}
                    ]
                }
            ],
            max_tokens=10,
            temperature=0.1
        )
        print(f"[SUCCESS] {m}", flush=True)
        successes.append(m)
    except Exception as e:
        err = str(e).split("\n")[0]
        # Only print if not common text-only error
        if "404" not in err and "410" not in err and "timed out" not in err and "does not support image" in err.lower():
            # expected text-only
            pass
        else:
            print(f"[FAIL] {m}: {err[:70]}", flush=True)

print("\nAll working vision models found:", successes, flush=True)
