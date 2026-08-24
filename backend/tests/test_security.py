from __future__ import annotations

from app.security import redact_pii_text, redact_sensitive


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


def test_pii_is_removed_before_llm_context() -> None:
    text = redact_pii_text("手机号13800138000，身份证110101199001011234，邮箱demo@example.com")
    assert "13800138000" not in text
    assert "110101199001011234" not in text
    assert "demo@example.com" not in text


def test_pii_redaction_handles_asr_separators_and_chinese_digits() -> None:
    text = redact_pii_text(
        "电话138-0013-8000或一三八零零一三八零零零，"
        "另一个念法幺三八 零零幺三 八零零零，"
        "逐位念1 3 8 0 0 1 3 8 0 0 0，"
        "点号138.0013.8000，证件110101/19900101/1234"
    )
    assert "138-0013-8000" not in text
    assert "一三八零零一三八零零零" not in text
    assert "幺三八 零零幺三 八零零零" not in text
    assert "1 3 8 0 0 1 3 8 0 0 0" not in text
    assert "138.0013.8000" not in text
    assert "110101/19900101/1234" not in text
    assert text.count("[REDACTED_PHONE]") == 5
    assert "[REDACTED_ID]" in text
