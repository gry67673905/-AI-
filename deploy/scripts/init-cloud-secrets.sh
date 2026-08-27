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

install_required_external_secret() {
    local secret_name="$1" source_variable="$2" prompt="$3"
    local destination="${SECRETS_DIR}/${secret_name}" source_path value
    [ ! -s "$destination" ] || {
        chmod 400 "$destination"
        return
    }
    if [[ -v "$source_variable" ]]; then
        source_path="${!source_variable}"
    else
        source_path=""
    fi
    if [ -n "$source_path" ]; then
        [ -s "$source_path" ] || die "${source_variable} is missing or empty."
        [ ! -L "$source_path" ] || die "${source_variable} must not reference a symbolic link."
        install -m 400 "$source_path" "$destination"
    elif [ -t 0 ]; then
        read -r -s -p "$prompt (input hidden): " value
        printf '\n'
        [ -n "$value" ] || die "${secret_name} must not be empty."
        [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] ||
            die "${secret_name} must be a single line."
        printf '%s' "$value" >"$destination"
        unset value
    else
        die "Provide ${source_variable} or run interactively before enabling MetaStudio."
    fi
    chmod 400 "$destination"
}

ensure_metastudio_app_identity() {
    local app_id
    app_id="$(cloud_env_value METASTUDIO_APP_ID)"
    case "$app_id" in
        ""|CONFIGURE_BEFORE_ENABLE|GENERATE_ON_ENABLE)
            set_cloud_env_value METASTUDIO_APP_ID "$(random_hex 16)"
            log "Generated the non-secret 32-hex MetaStudio APPID in deploy/cloud.env."
            ;;
        *)
            [[ "$app_id" =~ ^[0-9a-f]{32}$ ]] ||
                die "METASTUDIO_APP_ID must be exactly 32 lowercase hexadecimal characters."
            ;;
    esac
}

install_or_generate_metastudio_app_key() {
    local destination="${SECRETS_DIR}/metastudio_app_key" source_path=""
    if [ ! -s "$destination" ]; then
        if [ -n "${METASTUDIO_APP_KEY_FILE:-}" ]; then
            source_path="$METASTUDIO_APP_KEY_FILE"
            [ -s "$source_path" ] || die "METASTUDIO_APP_KEY_FILE is missing or empty."
            [ ! -L "$source_path" ] || die "METASTUDIO_APP_KEY_FILE must not reference a symbolic link."
            install -m 400 "$source_path" "$destination"
        else
            # The App Key is a project-owned HMAC secret, not a Huawei IAM
            # credential. Generate the locked 128-bit/32-hex value locally and
            # never print it; an administrator copies it to the MetaStudio
            # console through the documented root-only workflow.
            printf '%s' "$(random_hex 16)" >"$destination"
        fi
    fi
    chmod 400 "$destination"
}

if metastudio_enabled; then
    ensure_metastudio_app_identity
    install_or_generate_metastudio_app_key
    install_required_external_secret \
        metastudio_huawei_access_key METASTUDIO_HUAWEI_ACCESS_KEY_FILE \
        "Huawei Cloud IAM access key"
    install_required_external_secret \
        metastudio_huawei_secret_key METASTUDIO_HUAWEI_SECRET_KEY_FILE \
        "Huawei Cloud IAM secret key"
fi
if metastudio_enabled || material_documents_enabled; then
    install_required_external_secret \
        vision_dashscope_api_key VISION_DASHSCOPE_API_KEY_FILE \
        "Independent DashScope key for Qwen vision and material templates"
fi

require_metastudio_config
require_material_documents_config
require_secrets
log "Cloud Docker secrets are ready; no secret value was displayed."
