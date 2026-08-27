#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command curl
require_command docker
require_command flock
require_command sha256sum
require_cloud_files
require_secrets
require_metastudio_config
require_material_documents_config

release_tag="${CLOUD_RELEASE_TAG:-$(utc_stamp)-candidate}"
health_timeout=900
public_ipv4="${PUBLIC_IPV4:-}"
security_group_confirmed="${HTTPS_SECURITY_GROUP_CONFIRMED:-false}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --release) release_tag="${2:-}"; shift 2 ;;
        --health-timeout) health_timeout="${2:-}"; shift 2 ;;
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --https-security-group-confirmed) security_group_confirmed=true; shift ;;
        *) die "Unknown candidate deployment option: $1" ;;
    esac
done
validate_release_tag "$release_tag"
validate_ipv4 "$public_ipv4" || die "A valid public IPv4 must be supplied."
[[ "$health_timeout" =~ ^[0-9]+$ ]] || die "Health timeout must be a positive integer."

preflight_args=(
    --public-ipv4 "$public_ipv4"
    --candidate-port-required
)
if [ "$security_group_confirmed" = true ]; then
    preflight_args+=(--https-security-group-confirmed)
fi
"${SCRIPT_DIR}/preflight.sh" "${preflight_args[@]}"
bash "${SCRIPT_DIR}/verify-metastudio-smoke.sh" --skip-http

install -d -o root -g root -m 755 /run/lock
exec 8>/run/lock/smart-gov-candidate.lock
flock -n 8 || die "Another candidate deployment operation is already running."

if docker ps -aq \
    --filter label=com.docker.compose.project=smart-gov-cloud-demo \
    --filter label=com.docker.compose.service=api-candidate | grep -q . ||
    docker ps -aq \
        --filter label=com.docker.compose.project=smart-gov-cloud-demo \
        --filter label=com.docker.compose.service=material-worker-candidate | grep -q .; then
    die "A candidate API or material worker already exists; run stop-candidate.sh before replacing it."
fi

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
export RELEASE_TAG="$release_tag"
candidate_compose config --quiet

running_services="$(cloud_compose ps --status running --services)"
for service in postgres redis etcd minio milvus mock-gov-api mcp-server api; do
    grep -Fxq "$service" <<<"$running_services" ||
        die "Canonical service is not running before candidate deployment: ${service}"
done

candidate_started=false
cleanup_failed_candidate() {
    local status=$?
    trap - EXIT INT TERM
    if [ "$status" -ne 0 ] && [ "$candidate_started" = true ]; then
        candidate_compose rm --stop --force api-candidate material-worker-candidate >/dev/null 2>&1 || true
        rm -f "${STATE_DIR}/candidate-release"
        printf '[smart-gov] ERROR: Candidate failed; candidate container was removed and canonical API was untouched.\n' >&2
    fi
    exit "$status"
}
trap cleanup_failed_candidate EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

log "Building parallel API candidate ${release_tag}."
if ! candidate_compose build --pull api-candidate; then
    log "Registry-backed build failed; checking the canonical image for a safe network-isolated fallback."
    canonical_container="$(cloud_compose ps -q api)"
    [ -n "$canonical_container" ] || die "Canonical API container was not found for the fallback build."
    canonical_image="$(docker inspect --format '{{.Config.Image}}' "$canonical_container")"
    docker image inspect "$canonical_image" >/dev/null 2>&1 ||
        die "Canonical API image is unavailable for the fallback build."
    [ -f "${PROJECT_ROOT}/backend/Dockerfile.candidate-overlay" ] ||
        die "Candidate overlay Dockerfile is missing."

    local_requirements="$(sha256sum "${PROJECT_ROOT}/backend/requirements.txt" | awk '{print $1}')"
    image_requirements="$(docker run --rm --entrypoint sha256sum "$canonical_image" /app/requirements.txt | awk '{print $1}')"
    [ -n "$image_requirements" ] && [ "$local_requirements" = "$image_requirements" ] ||
        die "Candidate dependencies differ from the canonical image; refusing the offline fallback."

    docker build --pull=false \
        --file "${PROJECT_ROOT}/backend/Dockerfile.candidate-overlay" \
        --build-arg "BASE_IMAGE=${canonical_image}" \
        --tag "smart-gov/api:${release_tag}" \
        "${PROJECT_ROOT}/backend"
    log "Network-isolated candidate image built from the dependency-identical canonical image."
fi
if ! candidate_compose build --pull material-worker-candidate; then
    log "Registry-backed material-worker build failed; checking the canonical worker for a safe network-isolated fallback."
    canonical_worker_container="$(cloud_compose ps -q material-worker)"
    [ -n "$canonical_worker_container" ] ||
        die "Canonical material worker was not found for the fallback build."
    canonical_worker_image="$(docker inspect --format '{{.Config.Image}}' "$canonical_worker_container")"
    docker image inspect "$canonical_worker_image" >/dev/null 2>&1 ||
        die "Canonical material-worker image is unavailable for the fallback build."
    [ -f "${PROJECT_ROOT}/backend/Dockerfile.material-worker-candidate-overlay" ] ||
        die "Material-worker candidate overlay Dockerfile is missing."

    local_worker_requirements="$(sha256sum "${PROJECT_ROOT}/backend/requirements.material-worker.txt" | awk '{print $1}')"
    image_worker_requirements="$(docker run --rm --entrypoint sha256sum "$canonical_worker_image" /app/requirements.material-worker.txt | awk '{print $1}')"
    [ -n "$image_worker_requirements" ] &&
        [ "$local_worker_requirements" = "$image_worker_requirements" ] ||
        die "Candidate material-worker dependencies differ from the canonical image; refusing the offline fallback."

    docker build --pull=false \
        --file "${PROJECT_ROOT}/backend/Dockerfile.material-worker-candidate-overlay" \
        --build-arg "BASE_IMAGE=${canonical_worker_image}" \
        --tag "smart-gov/material-worker:${release_tag}" \
        "${PROJECT_ROOT}/backend"
    log "Network-isolated material-worker candidate built from the dependency-identical canonical image."
fi
candidate_compose up -d --no-deps api-candidate
candidate_compose up -d --no-deps material-worker-candidate
candidate_started=true

RELEASE_TAG="$release_tag" "${SCRIPT_DIR}/health-check.sh" \
    --timeout "$health_timeout" \
    --expect-rag enabled \
    --loopback-port 18001 \
    --api-service api-candidate \
    --worker-service material-worker-candidate
RELEASE_TAG="$release_tag" bash "${SCRIPT_DIR}/verify-metastudio-smoke.sh" \
    --base-url http://127.0.0.1:18001

image_id="$(docker image inspect --format '{{.Id}}' "smart-gov/api:${release_tag}")"
worker_image_id="$(docker image inspect --format '{{.Id}}' "smart-gov/material-worker:${release_tag}")"
deployment_bundle_sha256="$(deployment_bundle_sha256)"
[[ "$deployment_bundle_sha256" =~ ^[0-9a-f]{64}$ ]] ||
    die "Candidate deployment bundle digest is invalid."
temporary_marker="$(mktemp "${STATE_DIR}/.candidate-release.XXXXXX")"
{
    printf 'release_tag=%s\n' "$release_tag"
    printf 'image_id=%s\n' "$image_id"
    printf 'worker_image_id=%s\n' "$worker_image_id"
    printf 'deployment_bundle_sha256=%s\n' "$deployment_bundle_sha256"
    printf 'loopback_port=18001\n'
    printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" "${STATE_DIR}/candidate-release"

candidate_started=false
trap - EXIT INT TERM
log "Candidate ${release_tag} is healthy on 127.0.0.1:18001; canonical API 18000 was not changed."
