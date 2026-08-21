from __future__ import annotations

from app.security import redact_sensitive


def test_redaction_covers_sensitive_keys_and_free_text() -> None:
    value = {
        "Authorization": "Bearer actual-token",
        "nested": {
            "api_key": "sk-abcdefgh12345678",
            "message": "failed with Bearer another-secret and sk-123456789",
        },
    }

    redacted = redact_sensitive(value)

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "another-secret" not in redacted["nested"]["message"]
    assert "sk-123456789" not in redacted["nested"]["message"]

