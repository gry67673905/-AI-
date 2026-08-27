#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_ROOT}/compose.cloud.yaml}"
METASTUDIO_COMPOSE_FILE="${METASTUDIO_COMPOSE_FILE:-${PROJECT_ROOT}/compose.metastudio.yaml}"
CANDIDATE_COMPOSE_FILE="${CANDIDATE_COMPOSE_FILE:-${PROJECT_ROOT}/compose.candidate.yaml}"
CLOUD_ENV_FILE="${CLOUD_ENV_FILE:-${PROJECT_ROOT}/deploy/cloud.env}"
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
    if metastudio_enabled; then
        [ -f "$METASTUDIO_COMPOSE_FILE" ] || die "Missing compose.metastudio.yaml."
    fi
}

cloud_compose() {
    local resolved_release="${RELEASE_TAG:-}"
    local -a compose_files=(-f "$COMPOSE_FILE")
    if metastudio_enabled; then
        compose_files+=(-f "$METASTUDIO_COMPOSE_FILE")
    fi
    if [ -z "$resolved_release" ] && [ -s "${STATE_DIR}/current-release" ]; then
        resolved_release="$(<"${STATE_DIR}/current-release")"
        validate_release_tag "$resolved_release"
    fi
    if [ -n "$resolved_release" ]; then
        RELEASE_TAG="$resolved_release" docker compose --project-directory "$PROJECT_ROOT" --env-file "$CLOUD_ENV_FILE" "${compose_files[@]}" "$@"
    else
        docker compose --project-directory "$PROJECT_ROOT" --env-file "$CLOUD_ENV_FILE" "${compose_files[@]}" "$@"
    fi
}

candidate_release_tag() {
    local marker="${STATE_DIR}/candidate-release" value
    [ -s "$marker" ] && [ ! -L "$marker" ] || return 1
    value="$(awk -F= '$1 == "release_tag" {print $2}' "$marker")"
    [ -n "$value" ] || return 1
    validate_release_tag "$value"
    printf '%s\n' "$value"
}

deployment_bundle_sha256() {
    local digest file index label manifest="" secret_name
    local -a bundle_labels=(
        compose.cloud.yaml
        compose.candidate.yaml
        deploy/cloud.env
        deploy/container-secret-entrypoint.sh
    )
    local -a bundle_files=(
        "$COMPOSE_FILE"
        "$CANDIDATE_COMPOSE_FILE"
        "$CLOUD_ENV_FILE"
        "${PROJECT_ROOT}/deploy/container-secret-entrypoint.sh"
    )
    if metastudio_enabled; then
        bundle_labels+=(compose.metastudio.yaml)
        bundle_files+=("$METASTUDIO_COMPOSE_FILE")
    fi

    for index in "${!bundle_files[@]}"; do
        file="${bundle_files[$index]}"
        label="${bundle_labels[$index]}"
        [ -f "$file" ] && [ ! -L "$file" ] ||
            die "Deployment bundle file is missing or unsafe: ${label}"
        digest="$(sha256sum -- "$file" | awk '{print $1}')"
        [[ "$digest" =~ ^[0-9a-f]{64}$ ]] ||
            die "Could not hash deployment bundle file: ${label}"
        manifest+="${digest}  ${label}"$'\n'
    done
    while IFS= read -r secret_name; do
        [ -n "$secret_name" ] || continue
        file="${SECRETS_DIR}/${secret_name}"
        [ -f "$file" ] && [ ! -L "$file" ] ||
            die "Deployment secret is missing or unsafe: ${secret_name}"
        digest="$(sha256sum -- "$file" | awk '{print $1}')"
        [[ "$digest" =~ ^[0-9a-f]{64}$ ]] ||
            die "Could not hash deployment secret: ${secret_name}"
        manifest+="${digest}  deploy/secrets/${secret_name}"$'\n'
    done < <(find "$SECRETS_DIR" -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)
    printf '%s' "$manifest" | sha256sum | awk '{print $1}'
}

candidate_compose() {
    local resolved_release="${RELEASE_TAG:-}"
    local -a compose_files=(-f "$COMPOSE_FILE")
    [ -f "$CANDIDATE_COMPOSE_FILE" ] || die "Missing compose.candidate.yaml."
    if metastudio_enabled; then
        compose_files+=(-f "$METASTUDIO_COMPOSE_FILE")
    fi
    compose_files+=(-f "$CANDIDATE_COMPOSE_FILE")
    if [ -z "$resolved_release" ]; then
        resolved_release="$(candidate_release_tag 2>/dev/null || true)"
    fi
    if [ -n "$resolved_release" ]; then
        RELEASE_TAG="$resolved_release" docker compose \
            --project-directory "$PROJECT_ROOT" --env-file "$CLOUD_ENV_FILE" \
            "${compose_files[@]}" --profile candidate "$@"
    else
        docker compose --project-directory "$PROJECT_ROOT" \
            --env-file "$CLOUD_ENV_FILE" "${compose_files[@]}" \
            --profile candidate "$@"
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

metastudio_enabled() {
    [ -f "$CLOUD_ENV_FILE" ] || return 1
    case "$(cloud_env_value METASTUDIO_ENABLED)" in
        true|TRUE|1) return 0 ;;
        *) return 1 ;;
    esac
}

material_documents_enabled() {
    [ -f "$CLOUD_ENV_FILE" ] || return 1
    case "$(cloud_env_value MATERIAL_DOCUMENTS_ENABLED)" in
        true|TRUE|1) return 0 ;;
        *) return 1 ;;
    esac
}

require_material_documents_config() {
    local mode owner_uid value secret_path="${SECRETS_DIR}/vision_dashscope_api_key"
    local materials_bucket knowledge_bucket templates_bucket generated_bucket
    [ -f "$CLOUD_ENV_FILE" ] ||
        die "Missing deploy/cloud.env; material-document configuration cannot be checked."
    material_documents_enabled ||
        die "Cloud deployment must set MATERIAL_DOCUMENTS_ENABLED=true."
    [ "$(cloud_env_value MATERIAL_TEMPLATE_PROVIDER)" = dashscope ] ||
        die "Cloud material-template provider must be the pinned DashScope adapter."
    [ "$(cloud_env_value MATERIAL_TEMPLATE_MODEL)" = qwen3-vl-flash-2026-01-22 ] ||
        die "Cloud material-template model must be qwen3-vl-flash-2026-01-22."
    [ "$(cloud_env_value MATERIAL_TEMPLATE_DASHSCOPE_BASE_URL)" = \
        https://dashscope.aliyuncs.com/compatible-mode/v1 ] ||
        die "Cloud material-template base URL must be the pinned DashScope endpoint."
    materials_bucket="$(cloud_env_value MATERIALS_BUCKET)"
    knowledge_bucket="$(cloud_env_value KNOWLEDGE_BUCKET)"
    templates_bucket="$(cloud_env_value MATERIAL_TEMPLATES_BUCKET)"
    generated_bucket="$(cloud_env_value GENERATED_DOCUMENTS_BUCKET)"
    [ -n "$materials_bucket" ] && [ -n "$knowledge_bucket" ] &&
        [ -n "$templates_bucket" ] && [ -n "$generated_bucket" ] ||
        die "Cloud deployment must explicitly configure all four MinIO buckets."
    materials_bucket="${materials_bucket,,}"
    knowledge_bucket="${knowledge_bucket,,}"
    templates_bucket="${templates_bucket,,}"
    generated_bucket="${generated_bucket,,}"
    [ "$materials_bucket" != "$knowledge_bucket" ] &&
        [ "$materials_bucket" != "$templates_bucket" ] &&
        [ "$materials_bucket" != "$generated_bucket" ] &&
        [ "$knowledge_bucket" != "$templates_bucket" ] &&
        [ "$knowledge_bucket" != "$generated_bucket" ] &&
        [ "$templates_bucket" != "$generated_bucket" ] ||
        die "Materials, knowledge, template sources and generated documents must use four distinct MinIO buckets."
    value="$(cloud_env_value MATERIAL_DOCUMENT_GLOBAL_DAILY_LIMIT)"
    [[ "$value" =~ ^[0-9]+$ ]] && [ "$value" -ge 1 ] && [ "$value" -le 10000 ] ||
        die "MATERIAL_DOCUMENT_GLOBAL_DAILY_LIMIT must be an integer between 1 and 10000."
    [ -z "$(cloud_env_value MATERIAL_TEMPLATE_DASHSCOPE_API_KEY)" ] ||
        die "Do not place MATERIAL_TEMPLATE_DASHSCOPE_API_KEY in deploy/cloud.env; use its Docker secret file."
    [ -z "$(cloud_env_value MATERIAL_TEMPLATE_DASHSCOPE_API_KEY_FILE)" ] ||
        die "Do not override MATERIAL_TEMPLATE_DASHSCOPE_API_KEY_FILE in deploy/cloud.env."
    [ -f "$secret_path" ] && [ -s "$secret_path" ] ||
        die "Missing or empty Docker secret: vision_dashscope_api_key"
    [ ! -L "$secret_path" ] ||
        die "Docker secret vision_dashscope_api_key must not be a symbolic link."
    owner_uid="$(stat -c '%u' "$secret_path")"
    [ "$owner_uid" = 0 ] ||
        die "Docker secret vision_dashscope_api_key must be owned by root."
    mode="$(stat -c '%a' "$secret_path")"
    case "$mode" in
        600|400) ;;
        *) die "Docker secret vision_dashscope_api_key must have mode 600 or 400, found ${mode}." ;;
    esac
}

require_metastudio_config() {
    local key value
    # Cloud deployment must never fall back to direct plaintext credential
    # variables. Only the Docker secret file paths in the Compose override are
    # permitted. Enforce this even while the optional feature is disabled so a
    # dormant credential cannot leak into release snapshots or backups.
    for key in \
        METASTUDIO_APP_KEY \
        METASTUDIO_HUAWEI_ACCESS_KEY \
        METASTUDIO_HUAWEI_SECRET_KEY \
        VISION_DASHSCOPE_API_KEY; do
        [ -z "$(cloud_env_value "$key")" ] ||
            die "Do not place ${key} in deploy/cloud.env; use its Docker secret file."
    done

    metastudio_enabled || return 0
    require_command python3

    for key in METASTUDIO_APP_ID METASTUDIO_PROJECT_ID METASTUDIO_ROBOT_ID; do
        value="$(cloud_env_value "$key")"
        [ -n "$value" ] || die "MetaStudio configuration is missing ${key}."
        case "$value" in
            CONFIGURE_BEFORE_ENABLE|CHANGE_ME|SET_ME|UNSET)
                die "MetaStudio configuration still contains a placeholder: ${key}."
                ;;
        esac
        if [ "$key" = METASTUDIO_APP_ID ]; then
            [[ "$value" =~ ^[0-9a-f]{32}$ ]] ||
                die "MetaStudio APPID must be exactly 32 lowercase hexadecimal characters."
        else
            [[ "$value" =~ ^[A-Za-z0-9._-]{1,128}$ ]] ||
                die "MetaStudio identifier has an unsafe format: ${key}."
        fi
    done

    [ "$(cloud_env_value METASTUDIO_SDK_VERSION)" = 5.0.6 ] ||
        die "MetaStudio client SDK version must be exactly 5.0.6."
    [ "$(cloud_env_value METASTUDIO_REGION)" = cn-north-4 ] ||
        die "MetaStudio region must be Huawei Cloud Beijing-4 (cn-north-4)."
    [ "$(cloud_env_value METASTUDIO_ONCE_CODE_ENDPOINT)" = \
        https://metastudio.cn-north-4.myhuaweicloud.com ] ||
        die "MetaStudio once-code endpoint is not the pinned Beijing-4 endpoint."
    [ "$(cloud_env_value METASTUDIO_SERVER_ADDRESS)" = \
        metastudio-api.cn-north-4.myhuaweicloud.com ] ||
        die "MetaStudio client endpoint is not the pinned Beijing-4 endpoint."
    [ "$(cloud_env_value VISION_ENABLED)" = true ] ||
        die "Cloud MetaStudio deployment must enable the bounded vision adapter."
    [ "$(cloud_env_value VISION_PROVIDER)" = dashscope ] ||
        die "Cloud vision provider must be the pinned DashScope adapter."
    [ "$(cloud_env_value VISION_TURN_CLOSE_WAIT_MS)" = 2000 ] ||
        die "Cloud vision turn-close wait must be exactly 2000 milliseconds."
    vision_daily_limit="$(cloud_env_value VISION_ANALYSIS_GLOBAL_DAILY)"
    [[ "$vision_daily_limit" =~ ^[0-9]+$ ]] ||
        die "Cloud vision global daily analysis limit must be an integer."
    [ "$vision_daily_limit" -ge 20 ] && [ "$vision_daily_limit" -le 200 ] ||
        die "Cloud vision global daily analysis limit must be between 20 and 200."
    [ "$(cloud_env_value VISION_FAST_MAX_CONCURRENCY)" = 2 ] ||
        die "Cloud fast-vision concurrency must be exactly 2."
    python3 - \
        "$(cloud_env_value METASTUDIO_CALLBACK_URL)" \
        "${PROJECT_ROOT}/android/app/src/main/assets/metastudio/sdk" \
        "$(cloud_env_value METASTUDIO_SDK_VERSION)" \
        "${SECRETS_DIR}/metastudio_app_key" \
        "${SECRETS_DIR}/metastudio_huawei_access_key" \
        "${SECRETS_DIR}/metastudio_huawei_secret_key" \
        "${SECRETS_DIR}/vision_dashscope_api_key" \
        "$(cloud_env_value VISION_DASHSCOPE_BASE_URL)" <<'PY'
import json
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

callback = urlsplit(sys.argv[1])
if (
    sys.argv[1] != "https://123.249.68.176/api/v1/integrations/metastudio/llm"
    or
    callback.scheme != "https"
    or not callback.hostname
    or callback.username is not None
    or callback.password is not None
    or callback.query
    or callback.fragment
    or callback.path != "/api/v1/integrations/metastudio/llm"
):
    raise SystemExit("MetaStudio callback must be the pinned argument-free public HTTPS IP integration URL.")

vision_base = urlsplit(sys.argv[-1])
if (
    vision_base.scheme != "https"
    or not vision_base.hostname
    or vision_base.username is not None
    or vision_base.password is not None
    or vision_base.query
    or vision_base.fragment
    or vision_base.path.rstrip("/") != "/compatible-mode/v1"
):
    raise SystemExit("DashScope vision base URL must be a credential-free HTTPS compatible-mode/v1 endpoint.")

sdk_dir = Path(sys.argv[2])
marker_path = sdk_dir / "sdk-integrity.json"
expected_archive_sha256 = "d8d028588b35580856d8cc1fc35b67b50fbc8f99525c45ea5d990feec86c7641"
expected_cms_sha256 = "2bae230d3585e753adec0f001b81eb080f66c1a9cd2b99dea59c1f2827bbf0ea"
expected_signer_thumbprint = "ad39bc7c7a3d6bc0df3e91d53c023aabecc62b64"
expected_files = {
    "HwICSUiSdk.css": "da0cf9bd498ae2ab929a498f61c7a2c5aa025c73eb9a4bee7205e2a2f6752411",
    "HwICSUiSdk.d.ts": "ac217d3b81707a0afe912c9dfd8e0324b5518252d9cb1c0a4c007949a4fe82ec",
    "HwICSUiSdk.esm.js": "cc76cfe04fad8cbfd5d8136a397ed5d524e753e803ee459ea99e85a6c7d7d9e2",
    "HwICSUiSdk.js": "3e481679f7a556c90c83e7646315c09c74a16164c92a33404ba269b17aa0b17f",
    "images/aiChatImg.png": "d0103b231e6eddb728e850df06243eb49efdb62bc95a90f0cbbe28a90650b1b7",
    "images/bg_mobile.png": "c93137284a011cee4c271a9344b9ea3866b7abe71d5337308d557afde490c48e",
    "images/bg.png": "e2ae567b7f4935e1eebe2f7dbede67f45820f8a5a3118c402bf568f32ecf5477",
    "modelData.js": "775cf9362fc3c98fcbc6fda571f8341c636347a9287b85cadd6b92589fd70970",
    "package.json": "2eb945ddeec3be3a9726da64cf774b65e96f1630a78c429fac0b921f6cf4ebf3",
    "provenance/HwICSUiSdk-5.0.6.zip.cms": expected_cms_sha256,
    "wasmData.js": "18620018c309eb0f601f4137e2a39a136ce3fedd6259232f457b2d704e4203d9",
}
if sdk_dir.is_symlink() or not sdk_dir.is_dir():
    raise SystemExit("MetaStudio 5.0.6 SDK directory is missing/unsafe.")
if not marker_path.is_file() or marker_path.is_symlink() or marker_path.stat().st_size == 0:
    raise SystemExit("MetaStudio 5.0.6 SDK integrity proof is missing/unsafe.")
try:
    manifest = json.loads(marker_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit("MetaStudio SDK integrity proof is invalid.") from exc
if (
    manifest.get("version") != sys.argv[3]
    or manifest.get("cms_verified") is not True
    or str(manifest.get("archive_sha256", "")).lower() != expected_archive_sha256
    or str(manifest.get("cms_sha256", "")).lower() != expected_cms_sha256
    or str(manifest.get("signer_thumbprint", "")).lower() != expected_signer_thumbprint
):
    raise SystemExit("MetaStudio SDK version, archive, CMS or signer proof is not the pinned 5.0.6 release.")
declared_files = manifest.get("files")
if not isinstance(declared_files, dict) or declared_files != expected_files:
    raise SystemExit("MetaStudio SDK integrity manifest does not contain the exact pinned 11-file inventory.")
actual_paths = set()
for path in sdk_dir.rglob("*"):
    if path == marker_path:
        continue
    if path.is_symlink():
        raise SystemExit("MetaStudio SDK contains a symbolic-link asset or directory.")
    if path.is_dir():
        continue
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit("MetaStudio SDK contains an empty, non-regular or symbolic-link asset.")
    actual_paths.add(path.relative_to(sdk_dir).as_posix())
if actual_paths != set(expected_files):
    raise SystemExit("MetaStudio SDK directory does not match the exact pinned 11-file inventory.")
for relative_path, expected in expected_files.items():
    actual = hashlib.sha256((sdk_dir / relative_path).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"MetaStudio SDK asset is missing or modified: {relative_path}")

for index, raw_path in enumerate(sys.argv[4:-1]):
    path = Path(raw_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit("MetaStudio secret cannot be read.") from exc
    if len(raw) > 4096:
        raise SystemExit("MetaStudio secret exceeds the safe size limit.")
    value = raw.rstrip(b"\r\n")
    if not value or b"\r" in value or b"\n" in value or b"\x00" in value:
        raise SystemExit("MetaStudio secrets must be non-empty single-line files.")
    if index == 0 and not re.fullmatch(rb"[0-9a-f]{32}", value):
        raise SystemExit("MetaStudio App Key must be exactly 32 lowercase hexadecimal characters.")
PY
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

validate_upstream_port() {
    case "$1" in
        18000|18001) return 0 ;;
        *) die "Nginx upstream port must be exactly 18000 or 18001." ;;
    esac
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

require_release_images() {
    local release_tag="$1" snapshot="$2" temporary
    require_command docker
    require_command python3
    validate_release_tag "$release_tag"
    [ -s "$snapshot" ] && [ ! -L "$snapshot" ] || die "Release image snapshot is missing or unsafe: ${release_tag}"
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


def is_parallel_candidate(container_name: str) -> bool:
    """Candidate inventory is validated separately and may disappear post-cutover."""
    return (
        "-api-candidate-" in container_name
        or "-material-worker-candidate-" in container_name
    )


expected = {
    name: value
    for name, value in normalized(sys.argv[1]).items()
    if not is_parallel_candidate(name)
}
running = {
    name: value
    for name, value in normalized(sys.argv[2]).items()
    if not is_parallel_candidate(name)
}
if set(expected) != set(running):
    raise SystemExit(1)
application_repositories = {
    "smart-gov/api",
    "smart-gov/mcp-server",
    "smart-gov/mock-gov-api",
}
if any(value[1] == "smart-gov/material-worker" for value in expected.values()):
    application_repositories.add("smart-gov/material-worker")
for name, expected_value in expected.items():
    running_value = running[name]
    expected_id, expected_repository, expected_tag = expected_value
    running_id, running_repository, running_tag = running_value
    if expected_id != running_id or expected_repository != running_repository:
        raise SystemExit(1)
    if running_repository in application_repositories:
        # Historical releases may predate uniform release aliases.  The image
        # ID is immutable; accept either the recorded tag or the verified
        # release alias that rollback creates for that exact ID.
        if running_tag not in {expected_tag, sys.argv[3]}:
            raise SystemExit(1)
    elif expected_tag != running_tag:
        raise SystemExit(1)
for repository in application_repositories:
    if sum(
        1
        for name, value in running.items()
        if value[1] == repository and not is_parallel_candidate(name)
    ) != 1:
        raise SystemExit(1)
api = [
    value
    for name, value in running.items()
    if value[1] == "smart-gov/api" and not is_parallel_candidate(name)
]
if len(api) != 1 or api[0][2] != sys.argv[3]:
    raise SystemExit(1)
PY
    then
        rm -f "$temporary"
        die "Running container image IDs/tags differ from the immutable release snapshot: ${release_tag}"
    fi
    rm -f "$temporary"
}

require_current_release_images() {
    local release_tag snapshot
    [ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
    release_tag="$(<"${STATE_DIR}/current-release")"
    validate_release_tag "$release_tag"
    snapshot="${RELEASES_DIR}/${release_tag}/images.json"
    require_release_images "$release_tag" "$snapshot"
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
    if metastudio_enabled; then
        printf '%s\n' \
            metastudio_app_key \
            metastudio_huawei_access_key \
            metastudio_huawei_secret_key
    fi
    if metastudio_enabled || material_documents_enabled; then
        printf '%s\n' vision_dashscope_api_key
    fi
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
