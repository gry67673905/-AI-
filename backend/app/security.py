from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_SENSITIVE_KEYS = re.compile(
    r"(?:authorization|api[-_]?key|token|password|passwd|secret|credential)", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def redact_sensitive(value: Any) -> Any:
    """Return a JSON-safe copy with secrets removed from keys and free text."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEYS.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        return _API_KEY.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_sensitive(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive(str(value))

