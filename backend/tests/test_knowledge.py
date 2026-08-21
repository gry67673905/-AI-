from __future__ import annotations

import math

import pytest

from app.knowledge import EMBEDDING_DIMENSION, hash_embedding


def test_hash_embedding_is_stable_and_normalized() -> None:
    first = hash_embedding("  社保卡  如何办理？")
    second = hash_embedding("社保卡 如何办理?")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSION
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_hash_embedding_distinguishes_questions() -> None:
    assert hash_embedding("身份证补办") != hash_embedding("营业执照申请")


def test_hash_embedding_handles_empty_text() -> None:
    assert hash_embedding("") == [0.0] * EMBEDDING_DIMENSION

