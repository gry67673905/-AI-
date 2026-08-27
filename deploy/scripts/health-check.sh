#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

timeout_seconds=900
public_base=""
expect_rag="auto"
loopback_port=18000
api_service=api
worker_service=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --timeout) timeout_seconds="${2:-}"; shift 2 ;;
        --public-base) public_base="${2:-}"; shift 2 ;;
        --expect-rag) expect_rag="${2:-}"; shift 2 ;;
        --loopback-port) loopback_port="${2:-}"; shift 2 ;;
        --api-service) api_service="${2:-}"; shift 2 ;;
        --worker-service) worker_service="${2:-}"; shift 2 ;;
        *) die "Unknown health-check option: $1" ;;
    esac
done

validate_upstream_port "$loopback_port"
case "$api_service" in
    api|api-candidate) ;;
    *) die "--api-service must be api or api-candidate." ;;
esac
case "$worker_service" in
    ""|material-worker|material-worker-candidate) ;;
    *) die "--worker-service must be material-worker or material-worker-candidate." ;;
esac

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
    if curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:${loopback_port}/health/live" >/dev/null 2>&1 &&
        ready_response="$(curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:${loopback_port}/health/ready" 2>/dev/null)" &&
        grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$ready_response"; then
        if printf '%s' "$ready_response" | validate_readiness_shape "$expect_rag"; then
            break
        fi
    fi
    sleep 5
done

if [ "$SECONDS" -ge "$deadline" ]; then
    if [ "$api_service" = api-candidate ]; then
        candidate_compose ps
    else
        cloud_compose ps
    fi
    die "Cloud demo stack did not become ready within ${timeout_seconds} seconds."
fi

expected_services=(postgres redis etcd minio milvus mock-gov-api mcp-server "$api_service")
if [ -n "$worker_service" ]; then
    expected_services+=("$worker_service")
fi
if [ "$api_service" = api-candidate ]; then
    running_services="$(candidate_compose ps --status running --services)"
else
    running_services="$(cloud_compose ps --status running --services)"
fi
for service in "${expected_services[@]}"; do
    grep -Fxq "$service" <<<"$running_services" || die "Required service is not running: ${service}"
done

if [ -n "$worker_service" ]; then
    # This is a local, non-paid validation. It parses every reviewed manifest
    # item, verifies each packaged DOCX and checksum, and requires at least one
    # generatable source without contacting any model provider. Keep it tied
    # to the worker gate so rolling back a pre-feature release remains possible.
    if [ "$api_service" = api-candidate ]; then
        candidate_compose exec -T "$api_service" \
            python -m app.ops.material_template_check >/dev/null ||
            die "Candidate material-template pack is missing, empty or invalid."
    else
        cloud_compose exec -T "$api_service" \
            python -m app.ops.material_template_check >/dev/null ||
            die "Material-template pack is missing, empty or invalid."
    fi

    if [ "$api_service" = api-candidate ]; then
        worker_container="$(candidate_compose ps -q "$worker_service")"
    else
        worker_container="$(cloud_compose ps -q "$worker_service")"
    fi
    [ -n "$worker_container" ] || die "Material document worker container was not found."
    worker_deadline=$((SECONDS + timeout_seconds))
    while [ "$SECONDS" -lt "$worker_deadline" ]; do
        worker_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$worker_container" 2>/dev/null || true)"
        [ "$worker_health" = healthy ] && break
        sleep 3
    done
    [ "${worker_health:-}" = healthy ] || die "Material document worker did not become healthy."
fi

if [ -n "$public_base" ]; then
    [[ "$public_base" == https://* ]] || die "Public health verification requires an HTTPS base URL."
    public_ready="$(curl --fail --silent --show-error --max-time 20 "${public_base%/}/health/ready")"
    grep -Eq '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$public_ready" ||
        die "Public readiness response was not ready."
    printf '%s' "$public_ready" | validate_readiness_shape "$expect_rag" ||
        die "Public readiness dependency set did not match RAG mode ${expect_rag}."
fi

log "Cloud demo health checks passed with RAG ${expect_rag}; response bodies were not printed."
