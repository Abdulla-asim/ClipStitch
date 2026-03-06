"""
Privacy filter for ClipStory.
Scans clipboard content for sensitive data and redacts it before storage.
"""

import re
from clipstory.config import get

# ─── Patterns ─────────────────────────────────────────────────────────────────

_PASSWORD_RE = re.compile(
    r'(?i)(password|passwd|pwd|secret|token|pass)\s*[=:]\s*\S+',
    re.IGNORECASE,
)

_API_KEY_RE = re.compile(
    r'(?:'
    r'sk-[A-Za-z0-9]{20,}'          # OpenAI
    r'|AIza[A-Za-z0-9_\-]{30,}'     # Google
    r'|gh[pousr]_[A-Za-z0-9]{30,}'  # GitHub tokens
    r'|[A-Za-z0-9]{40,}'            # Generic long keys
    r')',
)

_EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)


def apply_privacy_filter(content: str) -> tuple[str, bool]:
    """
    Scan and redact sensitive data in content.
    Returns (filtered_content, was_redacted).
    """
    redacted = False
    result = content

    if get("privacy.redact_passwords", True):
        new = _PASSWORD_RE.sub(_redact_match, result)
        if new != result:
            redacted = True
        result = new

    if get("privacy.redact_api_keys", True):
        new = _API_KEY_RE.sub("[REDACTED_KEY]", result)
        if new != result:
            redacted = True
        result = new

    if get("privacy.redact_emails", False):
        new = _EMAIL_RE.sub("[REDACTED_EMAIL]", result)
        if new != result:
            redacted = True
        result = new

    return result, redacted


def _redact_match(m: re.Match) -> str:
    """Keep the key name but redact the value."""
    full = m.group(0)
    # Find the separator position and redact everything after it
    for sep in ("=", ":"):
        if sep in full:
            key_part = full[: full.index(sep) + 1]
            return key_part + "[REDACTED]"
    return "[REDACTED]"
