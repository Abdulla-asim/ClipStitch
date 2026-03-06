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


# ─── OpenAI ──────────────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
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


# ─── Gemini ───────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    def __init__(self):
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
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
