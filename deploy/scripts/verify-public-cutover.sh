#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command curl
require_command flock
require_command python3
require_command sha256sum
require_cloud_files
require_secrets

public_ipv4="${PUBLIC_IPV4:-}"
public_base=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --public-base) public_base="${2:-}"; shift 2 ;;
        *) die "Unknown public cutover verification option: $1" ;;
    esac
done
validate_ipv4 "$public_ipv4" || die "A valid public IPv4 must be supplied."
[ "$public_base" = "https://${public_ipv4}" ] || die "Public base must be the exact approved HTTPS IP origin."

if [ "${SMART_GOV_CUTOVER_LOCK_HELD:-}" != 1 ]; then
    install -d -o root -g root -m 755 /run/lock
    exec 8>/run/lock/smart-gov-cutover.lock
    flock -n 8 || die "Another cutover or legacy-retirement operation is already running."
    export SMART_GOV_CUTOVER_LOCK_HELD=1
fi
require_rag_cutover_ready
require_cutover_smoke_ready
require_current_release_images

"${SCRIPT_DIR}/health-check.sh" --timeout 90 --expect-rag enabled --public-base "$public_base"

log "Verifying public HTTPS live/ready, catalogue, role login, SSE and structured Nginx rate limiting."
python3 - "$public_base" \
    "${SECRETS_DIR}/demo_admin_password" "${SECRETS_DIR}/demo_staff_password" <<'PY'
from __future__ import annotations

import concurrent.futures
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

base, admin_password_path, staff_password_path = sys.argv[1:]
ssl_context = ssl.create_default_context()
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl_context)
)


def secret(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("public smoke credential is unavailable")
    return value


def request(path: str, *, method: str = "GET", body: dict | None = None,
            token: str | None = None, timeout: int = 30):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    return opener.open(req, timeout=timeout)


try:
    with request("/health/live") as response:
        if response.status != 200:
            raise RuntimeError("public live failed")

    with request("/health/ready", timeout=20) as response:
        ready = json.loads(response.read())
    expected_checks = {
        "postgres", "redis", "milvus", "mcp", "mock_gov_api", "minio",
        "business_seed", "rag_corpus",
    }
    if ready.get("status") != "ready" or set(ready.get("checks", {})) != expected_checks:
        raise RuntimeError("public ready failed")

    query = urllib.parse.quote("社会保障卡")
    with request(f"/api/v1/services?q={query}") as response:
        catalog = json.loads(response.read())
    if not any(item.get("code") == "DEMO-SS-CARD-001" for item in catalog.get("items", [])):
        raise RuntimeError("public catalogue failed")

    tokens: dict[str, str] = {}
    for role, username, password in (
        ("admin", "admin.demo", secret(admin_password_path)),
        ("staff", "staff.demo", secret(staff_password_path)),
    ):
        with request(
            "/api/v1/auth/login", method="POST",
            body={"username": username, "password": password}, timeout=30,
        ) as response:
            auth = json.loads(response.read())
        if not auth.get("access_token"):
            raise RuntimeError(f"public {role} login failed")
        tokens[role] = auth["access_token"]

    # This deliberately ambiguous question enters ConsultationCoordinator's
    # deterministic clarification branch before any LLM invocation.
    sse_request = urllib.request.Request(
        base + "/api/v1/chat/stream",
        data=json.dumps({"message": "社保怎么办"}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {tokens['admin']}",
        },
        method="POST",
    )
    with opener.open(sse_request, timeout=180) as response:
        content_type = response.headers.get("Content-Type", "")
        sse_body = response.read().decode("utf-8")
    if not content_type.startswith("text/event-stream"):
        raise RuntimeError("public SSE content type failed")
    if not all(f"event: {name}" in sse_body for name in ("meta", "delta", "done")):
        raise RuntimeError("public SSE event sequence failed")
    if "event: error" in sse_body:
        raise RuntimeError("public SSE returned an error event")
    if '"clarification_required": true' not in sse_body:
        raise RuntimeError("public SSE did not use the deterministic clarification path")

    rate_path = "/api/v1/services?q=" + query

    def rate_probe(_: int) -> tuple[int, str]:
        req = urllib.request.Request(base + rate_path, headers={"Accept": "application/json"})
        rate_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ssl_context)
        )
        try:
            with rate_opener.open(req, timeout=20) as response:
                response.read()
                return response.status, ""
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, body

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
        rate_results = list(pool.map(rate_probe, range(100)))
    if not any(status == 200 for status, _ in rate_results):
        raise RuntimeError("public rate-limit baseline failed")
    limited = [body for status, body in rate_results if status == 429]
    if not limited:
        raise RuntimeError("public rate limit did not trigger")
    if not any(json.loads(body).get("error", {}).get("code") == "rate_limit_exceeded" for body in limited):
        raise RuntimeError("public rate-limit response was not structured")
except Exception as exc:
    print(f"Public cutover verification failed at a redacted stage ({type(exc).__name__}).", file=sys.stderr)
    raise SystemExit(1) from None

print("Public cutover verification passed; no response body, answer, token or credential was printed.")
PY

release_tag="$(<"${STATE_DIR}/current-release")"
validate_release_tag "$release_tag"
paid_smoke_sha256="$(sha256sum "${STATE_DIR}/cutover-smoke-passed" | awk '{print $1}')"
umask 077
temporary_marker="$(mktemp "${STATE_DIR}/.public-cutover-passed.XXXXXX")"
{
    printf 'release_tag=%s\n' "$release_tag"
    printf 'public_ipv4=%s\n' "$public_ipv4"
    printf 'verified_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'checks=live,ready,catalog,admin_login,staff_login,sse,rate_limit\n'
    printf 'paid_smoke_sha256=%s\n' "$paid_smoke_sha256"
    printf 'deterministic_sse=clarification_no_llm\n'
    printf 'additional_paid_calls=0\n'
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" "${STATE_DIR}/public-cutover-passed"
log "Public HTTPS cutover marker recorded for release ${release_tag}."
