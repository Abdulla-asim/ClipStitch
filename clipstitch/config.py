"""Configuration loader for clipstitch."""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"

load_dotenv(ENV_PATH)


def load_config() -> dict:
    """Load and return the config.json as a dict."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.json not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    """Persist a config dict back to config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# Singleton config instance loaded at import time
config = load_config()


def get(path: str, default=None):
    """
    Dot-separated key access into the config.
    e.g. get("llm.model") -> "gpt-4o-mini"
    """
    keys = path.split(".")
    val = config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val
