from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr


def secret_value(value: SecretStr | None, file_path: str | None) -> str | None:
    """Resolve a single-line secret without importing service-specific clients."""

    if file_path:
        try:
            raw = Path(file_path).read_text(encoding="utf-8")
        except OSError:
            return None
        resolved = raw.strip()
        if "\n" in resolved or "\r" in resolved:
            return None
        return resolved or None
    if value is None:
        return None
    resolved = value.get_secret_value().strip()
    if "\n" in resolved or "\r" in resolved:
        return None
    return resolved or None
