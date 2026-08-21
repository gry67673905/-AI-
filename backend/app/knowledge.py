from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Final


EMBEDDING_DIMENSION: Final = 256

DEMO_DOCUMENTS: Final[list[dict[str, object]]] = [
    {
        "id": "demo-social-security-card",
        "title": "社会保障卡申领（演示）",
        "content": (
            "演示流程：申请人准备有效身份证件，可通过当地政务服务渠道提交社会保障卡申领。"
            "办理地点、时限和是否需要照片应以当地主管部门最新要求为准。"
        ),
        "source": "demo://knowledge/social-security-card",
        "metadata": {"demo": True, "category": "社会保障"},
    },
    {
        "id": "demo-id-card-replacement",
        "title": "居民身份证补领（演示）",
        "content": (
            "演示流程：身份证遗失后，可向公安机关居民身份证受理点咨询并申请补领。"
            "通常需要本人到场核验身份，具体材料、费用和领取方式以当地公安机关规定为准。"
        ),
        "source": "demo://knowledge/id-card-replacement",
        "metadata": {"demo": True, "category": "户籍身份"},
    },
    {
        "id": "demo-business-license",
        "title": "营业执照设立登记（演示）",
        "content": (
            "演示流程：经营主体设立登记通常包括名称申报、提交设立材料和领取营业执照。"
            "企业类型不同，所需章程、住所证明等材料也不同，请以登记机关清单为准。"
        ),
        "source": "demo://knowledge/business-license",
        "metadata": {"demo": True, "category": "市场监管"},
    },
]


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", normalized).strip()


def hash_embedding(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Create a deterministic signed-hashing vector from character 1-3 grams."""

    if dimension <= 0:
        raise ValueError("dimension must be positive")
    normalized = normalize_text(text)
    vector = [0.0] * dimension
    grams: list[str] = []
    for size in (1, 2, 3):
        grams.extend(normalized[index : index + size] for index in range(len(normalized) - size + 1))
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % dimension
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(component * component for component in vector))
    if norm:
        return [component / norm for component in vector]
    return vector


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_text(content).encode("utf-8")).hexdigest()

