from __future__ import annotations

import hashlib
import unicodedata


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
