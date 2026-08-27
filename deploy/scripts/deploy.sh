#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command docker
require_command sha256sum
require_cloud_files
require_secrets
require_metastudio_config
require_material_documents_config
bash "${SCRIPT_DIR}/verify-metastudio-smoke.sh" --skip-http

domain="${SMART_GOV_DOMAIN:-}"
public_ipv4="${PUBLIC_IPV4:-}"
security_group_confirmed="${HTTPS_SECURITY_GROUP_CONFIRMED:-false}"
release_tag="${CLOUD_RELEASE_TAG:-$(utc_stamp)}"
health_timeout=900

while [ "$#" -gt 0 ]; do
    case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --https-security-group-confirmed) security_group_confirmed=true; shift ;;
        --release) release_tag="${2:-}"; shift 2 ;;
        --health-timeout) health_timeout="${2:-}"; shift 2 ;;
        *) die "Unknown deploy option: $1" ;;
    esac
done
validate_release_tag "$release_tag"

preflight_args=(--domain "$domain" --public-ipv4 "$public_ipv4")
if [ "$security_group_confirmed" = true ]; then
    preflight_args+=(--https-security-group-confirmed)
fi
"${SCRIPT_DIR}/preflight.sh" "${preflight_args[@]}"

if grep -Fq 'settings.environment != "local" and settings.enable_demo_providers' \
    "${PROJECT_ROOT}/backend/app/infrastructure/runtime.py"; then
    die "Backend still rejects Demo Providers in ENVIRONMENT=demo; apply the reviewed demo-environment guard before deployment."
fi

docker info >/dev/null
docker compose version >/dev/null
cloud_compose config --quiet

case "$(cloud_env_value RAG_GROUP_ENABLED)" in
    true|TRUE|1) expected_rag=enabled ;;
    *) expected_rag=disabled ;;
esac
if [ ! -s "${STATE_DIR}/current-release" ] && [ "$expected_rag" != disabled ]; then
    die "Initial deployment must use RAG_GROUP_ENABLED=false; run import-rag.sh after the seven-check bootstrap is healthy."
fi

mkdir -p "$STATE_DIR" "$RELEASES_DIR"
chmod 700 "$STATE_DIR" "$RELEASES_DIR"

if cloud_compose ps --status running --services 2>/dev/null | grep -Fxq api; then
    log "An existing cloud demo stack is running; creating a pre-deploy backup."
    "${SCRIPT_DIR}/backup.sh"
fi

export RELEASE_TAG="$release_tag"
promoting_candidate=false
candidate_marker="${STATE_DIR}/candidate-release"
if [ -e "$candidate_marker" ]; then
    candidate_tag="$(candidate_release_tag)" ||
        die "Candidate release marker is invalid; stop the candidate before deploying."
    [ "$candidate_tag" = "$release_tag" ] ||
        die "Active candidate ${candidate_tag} cannot be promoted as ${release_tag}."

    marker_api_id="$(awk -F= '$1 == "image_id" {print $2}' "$candidate_marker")"
    marker_worker_id="$(awk -F= '$1 == "worker_image_id" {print $2}' "$candidate_marker")"
    marker_bundle_sha256="$(awk -F= '$1 == "deployment_bundle_sha256" {print $2}' "$candidate_marker")"
    [[ "$marker_api_id" =~ ^sha256:[0-9a-f]{64}$ ]] ||
        die "Candidate API image ID is missing or invalid."
    [[ "$marker_worker_id" =~ ^sha256:[0-9a-f]{64}$ ]] ||
        die "Candidate worker image ID is missing or invalid."
    [[ "$marker_bundle_sha256" =~ ^[0-9a-f]{64}$ ]] ||
        die "Candidate deployment bundle digest is missing or invalid."
    current_api_id="$(docker image inspect --format '{{.Id}}' "smart-gov/api:${release_tag}" 2>/dev/null)" ||
        die "Validated candidate API image is unavailable."
    current_worker_id="$(docker image inspect --format '{{.Id}}' "smart-gov/material-worker:${release_tag}" 2>/dev/null)" ||
        die "Validated candidate worker image is unavailable."
    [ "$current_api_id" = "$marker_api_id" ] ||
        die "Candidate API tag no longer points to the validated image."
    [ "$current_worker_id" = "$marker_worker_id" ] ||
        die "Candidate worker tag no longer points to the validated image."
    current_bundle_sha256="$(deployment_bundle_sha256)"
    [ "$current_bundle_sha256" = "$marker_bundle_sha256" ] ||
        die "Deployment configuration, bind-mounted entrypoint or secrets changed after candidate validation."
    promoting_candidate=true
    log "Promoting the already validated candidate API and worker images for ${release_tag}."
fi

if [ "$promoting_candidate" = true ]; then
    # API and worker must remain byte-for-byte identical to the candidate that
    # passed health and smoke checks. Rebuilding their mutable tags here would
    # let unvalidated code share the candidate's queue lane.
    cloud_compose build --pull mcp-server mock-gov-api
else
    log "Building immutable application images for release ${release_tag}."
    cloud_compose build --pull api material-worker mcp-server mock-gov-api
fi
# A validated api-candidate may be carrying public traffic while the canonical
# 18000 service is promoted. Never use --remove-orphans here: this compose
# view intentionally omits the candidate profile and would otherwise delete
# the live candidate before the final Nginx switch.
cloud_compose up -d \
    postgres redis etcd minio milvus mock-gov-api mcp-server api material-worker

"${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" --expect-rag "$expected_rag" \
    --worker-service material-worker

release_dir="${RELEASES_DIR}/${release_tag}"
mkdir -p "$release_dir"
install -m 600 "$COMPOSE_FILE" "${release_dir}/compose.cloud.yaml"
if metastudio_enabled; then
    install -m 600 "$METASTUDIO_COMPOSE_FILE" "${release_dir}/compose.metastudio.yaml"
fi
install -m 600 "$CLOUD_ENV_FILE" "${release_dir}/cloud.env"
cloud_compose images --format json >"${release_dir}/images.json"
chmod 600 "${release_dir}/images.json"

if [ -s "${STATE_DIR}/current-release" ]; then
    install -m 600 "${STATE_DIR}/current-release" "${STATE_DIR}/previous-release"
fi
printf '%s\n' "$release_tag" >"${STATE_DIR}/current-release"
chmod 600 "${STATE_DIR}/current-release"

log "Release ${release_tag} is healthy on 127.0.0.1:18000."
log "Legacy systemd services and Nginx routing were not changed."
