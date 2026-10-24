import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=60.0
)

DUMMY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAEASTN7b4AAAAASUVORK5CYII="

models_to_test = [
    "meta/llama-3.2-90b-vision-instruct",
    "google/gemma-4-31b-it",
    "meta/llama-3.2-11b-vision-instruct"
]

for m in models_to_test:
    print(f"Testing {m} (60s timeout)...", flush=True)
    t0 = time.time()
    try:
        res = client.chat.completions.create(
            model=m,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in three words."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{DUMMY_PNG_B64}"}}
                    ]
                }
            ],
            max_tokens=25,
            temperature=0.1
        )
        elapsed = time.time() - t0
        content = res.choices[0].message.content.strip().replace("\n", " ")
        print(f"-> SUCCESS in {elapsed:.2f}s: {content}", flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"-> FAILED in {elapsed:.2f}s: {e}", flush=True)
