import os
import sys
import json
import base64
import requests

# Clean URLs from the log (remove spaces)
SEED_URL = "https://courses.monoprix.fr/images-v3/0c44253f-c4a3-4340-9d37-d41e42b9d14a/79883652-540c-4467-9304-44583163359d/300x300.jpg"
CAND_URL = "https://courses.monoprix.fr/images-v3/0c44253f-c4a3-4340-9d37-d41e42b9d14a/7c3a86eb-7e9f-47dd-95e0-4ab36a582eab/300x300.jpg"

API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
MODEL = "gemini-1.5-flash"  # Fast, cheap, good vision

def get_base64_image(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": "https://courses.monoprix.fr/",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return base64.b64encode(resp.content).decode('utf-8')


def test_openai_vision():
    if not API_KEY:
        print("No API Key found")
        return

    print(f"Testing {MODEL} (OpenAI Compatible) with Vision (Base64)...")
    
    img1_b64 = "data:image/jpeg;base64," + get_base64_image(SEED_URL)
    img2_b64 = "data:image/jpeg;base64," + get_base64_image(CAND_URL)

    # OpenAI expects URLs directly for GPT-4o
    url = "https://api.openai.com/v1/chat/completions"
    
    payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Compare these two product images. Are they the exact same product variant (ignoring minor packaging updates)? Reply with JSON: {\"match\": boolean, \"confidence\": float_0_to_1, \"reason\": string}."},
                    {"type": "image_url", "image_url": {"url": img1_b64}},
                    {"type": "image_url", "image_url": {"url": img2_b64}}
                ]
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    resp = requests.post(url, json=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    })
    
    if resp.status_code != 200:
        print("Error:", resp.status_code, resp.text)
        return
        
    print("Response:", json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    test_openai_vision()
