#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command openssl
umask 077

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

if [ ! -f "$CLOUD_ENV_FILE" ]; then
    cp "${PROJECT_ROOT}/deploy/cloud.env.example" "$CLOUD_ENV_FILE"
    chmod 600 "$CLOUD_ENV_FILE"
    log "Created deploy/cloud.env from the non-secret example."
fi

ensure_value() {
    local name="$1"
    local value="$2"
    local destination="${SECRETS_DIR}/${name}"
    if [ ! -s "$destination" ]; then
        printf '%s' "$value" >"$destination"
    fi
    chmod 600 "$destination"
}

random_hex() {
    openssl rand -hex "$1"
}

ensure_value postgres_password "$(random_hex 32)"
ensure_value redis_password "$(random_hex 32)"
ensure_value minio_root_user "smartgov$(random_hex 8)"
ensure_value minio_root_password "$(random_hex 32)"
ensure_value jwt_signing_key "$(random_hex 48)"
ensure_value pii_hmac_key "$(random_hex 32)"
ensure_value pii_encryption_key "$(random_hex 32)"
ensure_value mcp_internal_token "$(random_hex 32)"
ensure_value gov_api_token "$(random_hex 32)"
ensure_value demo_sms_code "$(printf '%06d' "$((16#$(random_hex 3) % 1000000))")"
ensure_value demo_provider_ack "I_ACKNOWLEDGE_DEMO_PROVIDERS"
ensure_value demo_admin_password "DemoA!$(random_hex 32)"
ensure_value demo_staff_password "DemoS!$(random_hex 32)"

deepseek_destination="${SECRETS_DIR}/deepseek_api_key"
if [ ! -s "$deepseek_destination" ]; then
    if [ -n "${DEEPSEEK_API_KEY_FILE:-}" ]; then
        [ -s "$DEEPSEEK_API_KEY_FILE" ] || die "DEEPSEEK_API_KEY_FILE is missing or empty."
        install -m 600 "$DEEPSEEK_API_KEY_FILE" "$deepseek_destination"
    elif [ -t 0 ]; then
        read -r -s -p "DeepSeek API key (input hidden): " deepseek_value
        printf '\n'
        [ -n "$deepseek_value" ] || die "DeepSeek API key must not be empty."
        printf '%s' "$deepseek_value" >"$deepseek_destination"
        unset deepseek_value
    else
        die "Provide DeepSeek through DEEPSEEK_API_KEY_FILE or an interactive hidden prompt."
    fi
fi
chmod 600 "$deepseek_destination"

dashscope_destination="${SECRETS_DIR}/dashscope_api_key"
if [ ! -s "$dashscope_destination" ]; then
    if [ -n "${DASHSCOPE_API_KEY_FILE:-}" ]; then
        [ -s "$DASHSCOPE_API_KEY_FILE" ] || die "DASHSCOPE_API_KEY_FILE is missing or empty."
        install -m 600 "$DASHSCOPE_API_KEY_FILE" "$dashscope_destination"
    elif [ -t 0 ]; then
        read -r -s -p "DashScope API key (input hidden): " dashscope_value
        printf '\n'
        [ -n "$dashscope_value" ] || die "DashScope API key must not be empty."
        printf '%s' "$dashscope_value" >"$dashscope_destination"
        unset dashscope_value
    else
        die "Provide DashScope through DASHSCOPE_API_KEY_FILE or an interactive hidden prompt."
    fi
fi
chmod 400 "$dashscope_destination"

require_secrets
log "Cloud Docker secrets are ready; no secret value was displayed."
