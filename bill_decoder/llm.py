"""Thin wrapper around the Gemini API: image + prompt in, text or parsed JSON out."""
import json
import mimetypes
import os
import time

from dotenv import load_dotenv

load_dotenv()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")

_client = None
_PERMANENT_ERRORS = ("API key not valid", "PERMISSION_DENIED", "UNAUTHENTICATED", "INVALID_ARGUMENT", "NOT_FOUND")


class LLMError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        from google import genai  # imported lazily so tests and offline tools don't need the SDK configured
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
        _client = genai.Client(api_key=key)
    return _client


def call_gemini(prompt, image_path=None, json_mode=False, retries=4):
    """Send a prompt (and optional image) to Gemini.

    Retries rate limits / server errors / malformed JSON with exponential backoff; fails fast on
    errors that retrying cannot fix (bad key, bad request, unknown model).
    """
    from google.genai import types

    contents = []
    if image_path:
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as f:
            contents.append(types.Part.from_bytes(data=f.read(), mime_type=mime))
    contents.append(prompt)
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json" if json_mode else "text/plain",
    )

    last_error = None
    for attempt in range(retries):
        try:
            resp = _get_client().models.generate_content(model=MODEL_NAME, contents=contents, config=config)
            return json.loads(resp.text) if json_mode else resp.text
        except LLMError:
            raise
        except Exception as e:
            if any(marker in str(e) for marker in _PERMANENT_ERRORS):
                raise LLMError(f"Gemini request failed: {e}") from e
            last_error = e
            if attempt < retries - 1:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                print(f"  Gemini error (attempt {attempt + 1}/{retries}): {e}. Retrying in {wait}s")
                time.sleep(wait)
    raise LLMError(f"Gemini call failed after {retries} attempts: {last_error}")


if __name__ == "__main__":
    print(call_gemini("Reply with exactly: Gemini is working"))
