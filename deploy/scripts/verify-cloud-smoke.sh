#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command docker
require_cloud_files
require_secrets
require_rag_cutover_ready

confirm=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-paid-chat) confirm=true; shift ;;
        *) die "Unknown cloud smoke option: $1" ;;
    esac
done
[ "$confirm" = true ] || die "The final smoke makes one paid DeepSeek call; pass --confirm-paid-chat after cost approval."

"${SCRIPT_DIR}/health-check.sh" --timeout 120 --expect-rag enabled

log "Running one paid, non-PII grounded chat plus catalogue and role-login checks."
if ! cloud_compose exec -T api python - <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def call(stage: str, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            return json.loads(response.read())
    except Exception:
        raise RuntimeError(f"{stage} failed") from None


def secret(name: str) -> str:
    value = Path("/run/secrets", name).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("required smoke credential is unavailable")
    return value


try:
    ready = call("readiness", "/health/ready")
    checks = ready.get("checks", {})
    if ready.get("status") != "ready" or set(checks) != {
        "postgres", "redis", "milvus", "mcp", "mock_gov_api", "minio",
        "business_seed", "rag_corpus",
    }:
        raise RuntimeError("readiness shape failed")

    query = urllib.parse.quote("社会保障卡")
    catalog = call("catalog", f"/api/v1/services?q={query}")
    service = next(
        (item for item in catalog.get("items", []) if item.get("code") == "DEMO-SS-CARD-001"),
        None,
    )
    if not service or not service.get("id") or not service.get("external_item_id"):
        raise RuntimeError("catalog seed failed")

    for role in ("ADMIN", "STAFF"):
        prefix = "DEMO_ADMIN" if role == "ADMIN" else "DEMO_STAFF"
        auth = call(
            f"{role.lower()} login",
            "/api/v1/auth/login",
            method="POST",
            body={
                "username": os.environ[f"{prefix}_USERNAME"],
                "password": secret(f"demo_{role.lower()}_password"),
            },
        )
        if not auth.get("access_token"):
            raise RuntimeError(f"{role.lower()} login assertion failed")

    chat = call(
        "paid grounded chat",
        "/api/v1/chat",
        method="POST",
        body={
            "message": "办理社会保障卡需要准备哪些材料？",
            "service_id": service["id"],
        },
    )
    source_kinds = {item.get("kind") for item in chat.get("sources", [])}
    if not isinstance(chat.get("answer"), str) or not chat["answer"].strip():
        raise RuntimeError("paid chat answer assertion failed")
    if not {"local_catalog", "mcp", "rag"}.issubset(source_kinds):
        raise RuntimeError("grounded source assertion failed")
    if not any(
        item.get("kind") == "rag"
        and str(item.get("reference", "")).startswith("ragdb://team-2026-08-22-v1/")
        for item in chat.get("sources", [])
    ):
        raise RuntimeError("versioned RAG source assertion failed")
except Exception as exc:
    print(f"Cloud smoke failed at a redacted stage ({type(exc).__name__}).", file=sys.stderr)
    raise SystemExit(1) from None

print("Cloud smoke passed; response bodies, answers, credentials and tokens were not printed.")
PY
then
    die "Cloud smoke failed; no cutover marker was written."
fi

release_tag="$(<"${STATE_DIR}/current-release")"
validate_release_tag "$release_tag"
umask 077
{
    printf 'release_tag=%s\n' "$release_tag"
    printf 'dataset_version=team-2026-08-22-v1\n'
    printf 'verified_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'paid_deepseek_calls=1\n'
    printf 'required_sources=local_catalog,mcp,rag\n'
} >"${STATE_DIR}/cutover-smoke-passed"
chmod 600 "${STATE_DIR}/cutover-smoke-passed"
log "Cutover smoke marker recorded for release ${release_tag}."
