from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from job_agent.agent_ops.contracts import ContentSummary, PrivacyLevel


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "password",
    "access_token",
    "refresh_token",
    "client_secret",
}
_PRIVATE_KEYS = {
    "prompt",
    "raw_prompt",
    "raw_response",
    "resume",
    "resume_text",
    "jd",
    "jd_text",
    "source_text",
    "private_research",
    "anonymous_research",
}
_AUTH = re.compile(r"(?i)^\s*(?:bearer|basic)\s+\S+")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def redact(value: Any, *, level: PrivacyLevel = PrivacyLevel.REDACTED) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            normalized = _key(str(raw_key))
            if normalized in _SECRET_KEYS:
                result[str(raw_key)] = "[REDACTED_CREDENTIAL]"
            elif normalized in _PRIVATE_KEYS and level != PrivacyLevel.FULL:
                result[str(raw_key)] = "[REDACTED_PRIVATE_CONTENT]"
            elif level == PrivacyLevel.METADATA_ONLY:
                result[str(raw_key)] = _metadata_value(item)
            else:
                result[str(raw_key)] = redact(item, level=level)
        return result
    if isinstance(value, (list, tuple)):
        if level == PrivacyLevel.METADATA_ONLY:
            return {"type": "list", "count": len(value)}
        return [redact(item, level=level) for item in value]
    if isinstance(value, str):
        if _AUTH.match(value):
            return "[REDACTED_CREDENTIAL]"
        if level == PrivacyLevel.METADATA_ONLY:
            return {"type": "string", "chars": len(value)}
    return value


def _metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value)}
    if isinstance(value, (list, tuple)):
        return {"type": "list", "count": len(value)}
    if isinstance(value, str):
        return {"type": "string", "chars": len(value)}
    return {"type": type(value).__name__}


def summarize(
    value: Any,
    *,
    level: PrivacyLevel = PrivacyLevel.REDACTED,
    sensitive: bool = False,
    preview_chars: int = 120,
) -> ContentSummary:
    safe = redact(value, level=level)
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    raw_text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    preview: str | None = None
    if level == PrivacyLevel.FULL and not sensitive:
        preview = encoded[:preview_chars]
    elif level == PrivacyLevel.REDACTED and not sensitive:
        preview = encoded[:preview_chars]
    return ContentSummary(
        sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        chars=len(raw_text),
        estimated_tokens=max((len(raw_text) + 3) // 4, 0),
        preview=preview,
        redacted=sensitive or level != PrivacyLevel.FULL,
    )


def contains_sensitive_text(value: Any, needles: list[str]) -> bool:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return any(needle and needle in encoded for needle in needles)
