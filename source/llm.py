import os
import time
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def call_gemini(prompt, image_path=None, json_mode=False, retries=5):
    """Send a prompt (and optional image) to Gemini. Retries on rate limits/server errors."""
    contents = []
    if image_path:
        mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        with open(image_path, "rb") as f:
            contents.append(types.Part.from_bytes(data=f.read(), mime_type=mime))
    contents.append(prompt)

    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if json_mode else "text/plain",
    )

    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME, contents=contents, config=config
            )
            return json.loads(resp.text) if json_mode else resp.text
        except Exception as e:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s, 40s...
            print(f"  Gemini error (attempt {attempt + 1}/{retries}): {e}. Retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError("Gemini call failed after all retries")


if __name__ == "__main__":
    print(call_gemini("Reply with exactly: Gemini is working"))