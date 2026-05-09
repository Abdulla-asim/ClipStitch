"""
LLM provider abstraction for clipstitch.
Supports OpenAI, Google Gemini, and local Ollama.
"""

import os
import logging
from abc import ABC, abstractmethod

from clipstitch.config import get

log = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a system+user prompt; return the response text."""
        ...

    def describe_image(self, image_path: str) -> str | None:
        """
        Return a one-paragraph description of the image at image_path.
        Default implementation returns None (provider doesn't support vision).
        """
        return None


# ─── OpenAI ──────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import OpenAI
        # Try environment variable first, then config
        api_key = os.getenv("OPENAI_API_KEY") or get("llm.openai_api_key")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. Please set it in .env or in Settings > LLM Provider"
            )
        self._client = OpenAI(api_key=api_key)
        self._model = get("llm.model", "gpt-4o-mini")

    def complete(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()

    def describe_image(self, image_path: str) -> str | None:
        """Use GPT-4o vision to describe a screenshot/image."""
        from clipstitch.monitor.image import image_to_base64
        b64 = image_to_base64(image_path)
        # Use a vision-capable model; fall back to gpt-4o if configured model lacks vision
        vision_model = self._model if "gpt-4" in self._model else "gpt-4o"
        try:
            resp = self._client.chat.completions.create(
                model=vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "Describe what is shown in this screenshot in 1-3 concise sentences. "
                            "Focus on the main content: text visible, UI elements, subject matter, "
                            "charts or diagrams if present."
                        )},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "low",
                        }},
                    ],
                }],
                max_tokens=200,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning("OpenAI vision failed: %s", e)
            return None


# ─── Gemini ───────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    def __init__(self):
        import google.generativeai as genai
        # Try environment variable first, then config
        api_key = os.getenv("GEMINI_API_KEY") or get("llm.gemini_api_key")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Please set it in .env or in Settings > LLM Provider"
            )
        genai.configure(api_key=api_key)
        model_name = get("llm.model", "gemini-1.5-flash")
        self._model = genai.GenerativeModel(
            model_name,
            system_instruction="You are a helpful assistant."
        )

    def complete(self, system: str, user: str) -> str:
        combined = f"{system}\n\n{user}"
        resp = self._model.generate_content(combined)
        return resp.text.strip()

    def describe_image(self, image_path: str) -> str | None:
        """Use Gemini vision to describe a screenshot/image."""
        try:
            import google.generativeai as genai
            from PIL import Image as PILImage
            img = PILImage.open(image_path)
            # Use the configured model (already initialised); fall back to gemini-2.0-flash
            model_name = get("llm.model", "gemini-2.0-flash")
            vision_model = genai.GenerativeModel(model_name)
            resp = vision_model.generate_content([
                "Describe what is shown in this screenshot in 1-3 concise sentences. "
                "Focus on the main content: text visible, UI elements, subject matter, "
                "charts or diagrams if present.",
                img,
            ])
            return resp.text.strip()
        except Exception as e:
            log.warning("Gemini vision failed: %s", e)
            return None


# ─── Ollama ───────────────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    def __init__(self):
        import ollama
        self._ollama = ollama
        self._model = get("llm.ollama_model", "llama3")
        self._host  = get("llm.ollama_host", "http://localhost:11434")

    def complete(self, system: str, user: str) -> str:
        resp = self._ollama.chat(
            model=self._model,
            messages=[
                {"role": "system",  "content": system},
                {"role": "user",    "content": user},
            ],
            options={"temperature": 0.7},
        )
        return resp["message"]["content"].strip()


# ─── Factory ──────────────────────────────────────────────────────────────────

_PROVIDERS = {
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

_instance: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Return (and cache) the configured LLM provider."""
    global _instance
    if _instance is None:
        name = get("llm.provider", "openai").lower()
        cls = _PROVIDERS.get(name)
        if cls is None:
            raise ValueError(f"Unknown LLM provider: {name!r}. Choose from {list(_PROVIDERS)}")
        _instance = cls()
        log.info("LLM provider: %s", name)
    return _instance


def reset_provider() -> None:
    """Force re-initialisation on next call (useful after config change)."""
    global _instance
    _instance = None
