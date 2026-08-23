#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/compose.cloud.yaml"
CLOUD_ENV_FILE="${PROJECT_ROOT}/deploy/cloud.env"
SECRETS_DIR="${PROJECT_ROOT}/deploy/secrets"
STATE_DIR="${PROJECT_ROOT}/deploy/state"
# shellcheck disable=SC2034  # Used by scripts that source this library.
RELEASES_DIR="${PROJECT_ROOT}/deploy/releases"

log() {
    printf '[smart-gov] %s\n' "$*"
}

die() {
    printf '[smart-gov] ERROR: %s\n' "$*" >&2
    exit 1
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "Run this server operation as root."
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command is unavailable: $1"
}

require_cloud_files() {
    [ -f "$COMPOSE_FILE" ] || die "Missing compose.cloud.yaml."
    [ -f "$CLOUD_ENV_FILE" ] || die "Missing deploy/cloud.env; copy cloud.env.example first."
}

cloud_compose() {
    local resolved_release="${RELEASE_TAG:-}"
    if [ -z "$resolved_release" ] && [ -s "${STATE_DIR}/current-release" ]; then
        resolved_release="$(<"${STATE_DIR}/current-release")"
        validate_release_tag "$resolved_release"
    fi
    if [ -n "$resolved_release" ]; then
        RELEASE_TAG="$resolved_release" docker compose --project-directory "$PROJECT_ROOT" --env-file "$CLOUD_ENV_FILE" -f "$COMPOSE_FILE" "$@"
    else
        docker compose --project-directory "$PROJECT_ROOT" --env-file "$CLOUD_ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
}

cloud_env_value() {
    local key="$1"
    awk -F= -v key="$key" '
        $0 !~ /^[[:space:]]*#/ && $1 == key {
            sub(/^[^=]*=/, "")
            value = $0
        }
        END { print value }
    ' "$CLOUD_ENV_FILE"
}

set_cloud_env_value() {
    local key="$1" value="$2" temporary
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "Invalid cloud environment key."
    temporary="$(mktemp "${CLOUD_ENV_FILE}.tmp.XXXXXX")"
    awk -v key="$key" -v value="$value" '
        BEGIN { found = 0 }
        $0 ~ ("^" key "=") {
            print key "=" value
            found = 1
            next
        }
        { print }
        END {
            if (!found) print key "=" value
        }
    ' "$CLOUD_ENV_FILE" >"$temporary"
    install -m 600 "$temporary" "$CLOUD_ENV_FILE"
    rm -f "$temporary"
}

utc_stamp() {
    date -u +%Y%m%dT%H%M%SZ
}

validate_release_tag() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]] ||
        die "Release tag must contain only letters, digits, dot, underscore and dash."
}

require_rag_cutover_ready() {
    local current_release
    [ "$(cloud_env_value RAG_GROUP_ENABLED)" = true ] ||
        die "Cutover requires RAG_GROUP_ENABLED=true."
    [ "$(cloud_env_value RAG_DATASET_VERSION)" = team-2026-08-22-v1 ] ||
        die "Cutover requires the approved fixed RAG dataset version."
    [ "$(cloud_env_value RAG_ARCHIVE_SHA256)" = b5221f51465a230192148cb8e3db81a81e21348809a2738ca8ce89d8f6543f93 ] ||
        die "Cutover requires the approved sanitized RAG archive hash."
    [ -s "${STATE_DIR}/rag-active" ] ||
        die "Cutover requires a successful import-rag.sh activation marker."
    grep -Fxq 'dataset_version=team-2026-08-22-v1' "${STATE_DIR}/rag-active" ||
        die "RAG activation marker has an unexpected dataset version."
    grep -Fxq 'archive_sha256=b5221f51465a230192148cb8e3db81a81e21348809a2738ca8ce89d8f6543f93' "${STATE_DIR}/rag-active" ||
        die "RAG activation marker has an unexpected archive hash."
    [ "$(cloud_env_value RAG_EXPECTED_CHUNK_COUNT)" = 15858 ] ||
        die "Cutover requires exactly 15,858 approved RAG chunks."
    [ "$(cloud_env_value RAG_EXPECTED_ROUTE_COUNT)" = 1012 ] ||
        die "Cutover requires exactly 1,012 approved RAG routes."
    [ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
    current_release="$(<"${STATE_DIR}/current-release")"
    grep -Fxq "release_tag=${current_release}" "${STATE_DIR}/rag-active" ||
        die "RAG activation marker belongs to another release."
}

require_cutover_smoke_ready() {
    local release_tag
    [ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
    release_tag="$(<"${STATE_DIR}/current-release")"
    validate_release_tag "$release_tag"
    [ -s "${STATE_DIR}/cutover-smoke-passed" ] ||
        die "Run verify-cloud-smoke.sh before cutover."
    grep -Fxq "release_tag=${release_tag}" "${STATE_DIR}/cutover-smoke-passed" ||
        die "Cutover smoke marker belongs to a different release."
    grep -Fxq 'dataset_version=team-2026-08-22-v1' "${STATE_DIR}/cutover-smoke-passed" ||
        die "Cutover smoke marker belongs to a different RAG dataset."
    grep -Fxq 'paid_deepseek_calls=1' "${STATE_DIR}/cutover-smoke-passed" ||
        die "Cutover requires the explicitly approved paid DeepSeek smoke."
    grep -Fxq 'required_sources=local_catalog,mcp,rag' "${STATE_DIR}/cutover-smoke-passed" ||
        die "Cutover smoke did not verify all grounded source groups."
}

validate_ipv4() {
    local value="$1" part
    local -a parts
    [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    IFS=. read -r -a parts <<<"$value"
    [ "${#parts[@]}" -eq 4 ] || return 1
    for part in "${parts[@]}"; do
        [ "$((10#$part))" -le 255 ] || return 1
    done
}

require_public_cutover_ready() {
    local public_ipv4="$1" release_tag paid_marker_sha
    validate_ipv4 "$public_ipv4" || die "A valid public IPv4 is required for the public cutover marker."
    [ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
    release_tag="$(<"${STATE_DIR}/current-release")"
    [ -s "${STATE_DIR}/public-cutover-passed" ] ||
        die "Run the public HTTPS cutover verification before retiring legacy services."
    grep -Fxq "release_tag=${release_tag}" "${STATE_DIR}/public-cutover-passed" ||
        die "Public cutover verification belongs to another release."
    grep -Fxq "public_ipv4=${public_ipv4}" "${STATE_DIR}/public-cutover-passed" ||
        die "Public cutover verification belongs to another IPv4 endpoint."
    grep -Fxq 'checks=live,ready,catalog,admin_login,staff_login,sse,rate_limit' \
        "${STATE_DIR}/public-cutover-passed" ||
        die "Public cutover verification is incomplete."
    paid_marker_sha="$(sha256sum "${STATE_DIR}/cutover-smoke-passed" | awk '{print $1}')"
    grep -Fxq "paid_smoke_sha256=${paid_marker_sha}" "${STATE_DIR}/public-cutover-passed" ||
        die "Public cutover verification does not reference the active paid-smoke marker."
    grep -Fxq 'deterministic_sse=clarification_no_llm' "${STATE_DIR}/public-cutover-passed" ||
        die "Public SSE verification was not the approved deterministic no-LLM path."
    grep -Fxq 'additional_paid_calls=0' "${STATE_DIR}/public-cutover-passed" ||
        die "Public cutover verification did not preserve the single paid-call budget."
    [ -s "${STATE_DIR}/ip-nginx-cutover" ] && [ ! -L "${STATE_DIR}/ip-nginx-cutover" ] ||
        die "IP Nginx cutover marker is missing or unsafe."
    grep -Fxq "release_tag=${release_tag}" "${STATE_DIR}/ip-nginx-cutover" ||
        die "IP Nginx cutover marker belongs to another release."
    grep -Fxq "public_ipv4=${public_ipv4}" "${STATE_DIR}/ip-nginx-cutover" ||
        die "IP Nginx cutover marker belongs to another IPv4 endpoint."
}

require_current_release_images() {
    local release_tag snapshot current temporary
    require_command docker
    require_command python3
    [ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
    release_tag="$(<"${STATE_DIR}/current-release")"
    validate_release_tag "$release_tag"
    snapshot="${RELEASES_DIR}/${release_tag}/images.json"
    [ -s "$snapshot" ] && [ ! -L "$snapshot" ] || die "Current release image snapshot is missing or unsafe."
    temporary="$(mktemp "${STATE_DIR}/.running-images.XXXXXX")"
    cloud_compose images --format json >"$temporary"
    if ! python3 - "$snapshot" "$temporary" "$release_tag" <<'PY'
import json
import sys
from pathlib import Path


def load(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("empty image inventory")
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def normalized(path: str) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for item in load(path):
        name = str(item.get("ContainerName", ""))
        if not name:
            raise RuntimeError("image inventory lacks container identity")
        result[name] = (
            str(item.get("ID", "")), str(item.get("Repository", "")),
            str(item.get("Tag", "")),
        )
    return result


expected = normalized(sys.argv[1])
running = normalized(sys.argv[2])
if expected != running:
    raise SystemExit(1)
api = [value for value in running.values() if value[1] == "smart-gov/api"]
if len(api) != 1 or api[0][2] != sys.argv[3]:
    raise SystemExit(1)
PY
    then
        rm -f "$temporary"
        die "Running container image IDs/tags differ from the immutable current-release snapshot."
    fi
    rm -f "$temporary"
}

required_secret_names() {
    printf '%s\n' \
        postgres_password \
        redis_password \
        minio_root_user \
        minio_root_password \
        jwt_signing_key \
        pii_hmac_key \
        pii_encryption_key \
        mcp_internal_token \
        gov_api_token \
        demo_sms_code \
        demo_provider_ack \
        demo_admin_password \
        demo_staff_password \
        deepseek_api_key \
        dashscope_api_key
}

require_secrets() {
    local name mode owner_uid
    while IFS= read -r name; do
        [ -s "${SECRETS_DIR}/${name}" ] || die "Missing or empty Docker secret: ${name}"
        [ ! -L "${SECRETS_DIR}/${name}" ] || die "Docker secret ${name} must not be a symbolic link."
        owner_uid="$(stat -c '%u' "${SECRETS_DIR}/${name}")"
        [ "$owner_uid" = 0 ] || die "Docker secret ${name} must be owned by root."
        mode="$(stat -c '%a' "${SECRETS_DIR}/${name}")"
        case "$mode" in
            600|400) ;;
            *) die "Docker secret ${name} must have mode 600 or 400, found ${mode}." ;;
        esac
    done < <(required_secret_names)
}
