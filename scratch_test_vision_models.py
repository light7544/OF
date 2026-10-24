import os
import base64
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY")

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    timeout=15.0
)

# 1x1 transparent png
DUMMY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAEASTN7b4AAAAASUVORK5CYII="

candidate_models = [
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.2-11b-vision-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "nvidia/neva-22b",
    "nvidia/vila",
    "microsoft/phi-3-vision-128k-instruct",
    "google/gemma-3-12b-it",
    "google/gemma-4-31b-it",
    "adept/fuyu-8b",
    "google/deplot",
    "microsoft/kosmos-2",
]

print("Testing which models accept images via /v1/chat/completions:", flush=True)
for model_name in candidate_models:
    print(f"Testing {model_name}...", end=" ", flush=True)
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in 3 words."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{DUMMY_PNG_B64}"}}
                    ]
                }
            ],
            max_tokens=20,
            temperature=0.1
        )
        ans = response.choices[0].message.content.strip().replace("\n", " ")
        print(f"-> [OK] {ans[:60]}", flush=True)
    except Exception as e:
        err_msg = str(e).split("\n")[0]
        print(f"-> [FAIL] {err_msg[:80]}", flush=True)
