import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("NVIDIA_API_KEY")
if not api_key:
    print("NVIDIA_API_KEY not found")
    exit(1)

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key
)

try:
    models = client.models.list()
    model_ids = sorted([m.id for m in models.data])
    print(f"Total models available: {len(model_ids)}")
    
    # Filter candidate vision models or models containing vision, vl, multimodal, maverick, llama, etc.
    vision_candidates = [m for m in model_ids if any(k in m.lower() for k in ["vision", "vl", "multimodal", "maverick", "pixtral", "clip", "neva", "florence", "omni", "paligemma", "llama-4"])]
    print("\nCandidate Vision / Multimodal Models:")
    for m in vision_candidates:
        print(f" - {m}")
        
    print("\nCheck specific 'maverick' or 'llama-4' matches:")
    llama4_matches = [m for m in model_ids if "llama-4" in m.lower() or "maverick" in m.lower()]
    print(llama4_matches)
    
    # Save full list to a scratch json file for reference
    with open("nvidia_models.json", "w") as f:
        json.dump(model_ids, f, indent=2)
except Exception as e:
    print("Error querying models:", e)
