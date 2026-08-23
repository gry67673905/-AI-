#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

timeout_seconds=900
public_base=""
expect_rag="auto"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --timeout) timeout_seconds="${2:-}"; shift 2 ;;
        --public-base) public_base="${2:-}"; shift 2 ;;
        --expect-rag) expect_rag="${2:-}"; shift 2 ;;
        *) die "Unknown health-check option: $1" ;;
    esac
done

[[ "$timeout_seconds" =~ ^[0-9]+$ ]] || die "Timeout must be a positive integer."
case "$expect_rag" in
    auto)
        case "$(cloud_env_value RAG_GROUP_ENABLED)" in
            true|TRUE|1) expect_rag=enabled ;;
            *) expect_rag=disabled ;;
        esac
        ;;
    enabled|disabled) ;;
    *) die "--expect-rag must be auto, enabled or disabled." ;;
esac
require_command curl
require_command docker
require_command python3
require_cloud_files

validate_readiness_shape() {
    local expected_mode="$1"
    python3 -c '
import json, sys
mode = sys.argv[1]
payload = json.load(sys.stdin)
expected = {"postgres", "redis", "milvus", "mcp", "mock_gov_api", "minio", "business_seed"}
if mode == "enabled":
    expected.add("rag_corpus")
checks = payload.get("checks")
if payload.get("status") != "ready" or not isinstance(checks, dict) or set(checks) != expected:
    raise SystemExit(1)
if any(not isinstance(item, dict) or item.get("status") != "ok" for item in checks.values()):
    raise SystemExit(1)
' "$expected_mode"
}

deadline=$((SECONDS + timeout_seconds))
while [ "$SECONDS" -lt "$deadline" ]; do
    if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18000/health/live >/dev/null 2>&1 &&
        ready_response="$(curl --fail --silent --show-error --max-time 15 http://127.0.0.1:18000/health/ready 2>/dev/null)" &&
        grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$ready_response"; then
        if printf '%s' "$ready_response" | validate_readiness_shape "$expect_rag"; then
            break
        fi
    fi
    sleep 5
done

if [ "$SECONDS" -ge "$deadline" ]; then
    cloud_compose ps
    die "Cloud demo stack did not become ready within ${timeout_seconds} seconds."
fi

expected_services=(postgres redis etcd minio milvus mock-gov-api mcp-server api)
running_services="$(cloud_compose ps --status running --services)"
for service in "${expected_services[@]}"; do
    grep -Fxq "$service" <<<"$running_services" || die "Required service is not running: ${service}"
done

if [ -n "$public_base" ]; then
    [[ "$public_base" == https://* ]] || die "Public health verification requires an HTTPS base URL."
    public_ready="$(curl --fail --silent --show-error --max-time 20 "${public_base%/}/health/ready")"
    grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$public_ready" ||
        die "Public readiness response was not ready."
    printf '%s' "$public_ready" | validate_readiness_shape "$expect_rag" ||
        die "Public readiness dependency set did not match RAG mode ${expect_rag}."
fi

log "Cloud demo health checks passed with RAG ${expect_rag}; response bodies were not printed."
