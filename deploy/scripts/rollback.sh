#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command docker
require_cloud_files
require_secrets

target_release=""
skip_backup=false
health_timeout=900
while [ "$#" -gt 0 ]; do
    case "$1" in
        --release) target_release="${2:-}"; shift 2 ;;
        --skip-backup) skip_backup=true; shift ;;
        --health-timeout) health_timeout="${2:-}"; shift 2 ;;
        *) die "Unknown rollback option: $1" ;;
    esac
done

if [ -z "$target_release" ] && [ -s "${STATE_DIR}/previous-release" ]; then
    target_release="$(<"${STATE_DIR}/previous-release")"
fi
[ -n "$target_release" ] || die "No previous release is recorded; pass --release explicitly."
validate_release_tag "$target_release"

release_dir="${RELEASES_DIR}/${target_release}"
[ -f "${release_dir}/compose.cloud.yaml" ] || die "Release metadata was not found: ${target_release}"
[ -f "${release_dir}/cloud.env" ] || die "Release environment snapshot was not found: ${target_release}"

for image in \
    "smart-gov/api:${target_release}" \
    "smart-gov/mcp-server:${target_release}" \
    "smart-gov/mock-gov-api:${target_release}"; do
    docker image inspect "$image" >/dev/null 2>&1 || die "Rollback image is unavailable: ${image}"
done

if [ "$skip_backup" = false ] && cloud_compose ps --status running --services | grep -Fxq api; then
    "${SCRIPT_DIR}/backup.sh"
fi

current_release=""
if [ -s "${STATE_DIR}/current-release" ]; then
    current_release="$(<"${STATE_DIR}/current-release")"
fi

active_cloud_env_file="$CLOUD_ENV_FILE"

# shellcheck disable=SC2034  # Read dynamically by cloud_compose from lib.sh.
COMPOSE_FILE="${release_dir}/compose.cloud.yaml"
# shellcheck disable=SC2034  # Read dynamically by cloud_compose from lib.sh.
CLOUD_ENV_FILE="${release_dir}/cloud.env"
export RELEASE_TAG="$target_release"
cloud_compose up -d --no-build --remove-orphans \
    postgres redis etcd minio milvus mock-gov-api mcp-server api
"${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout"

active_cloud_env_temporary="$(mktemp "${active_cloud_env_file}.rollback.XXXXXX")"
install -m 600 "$CLOUD_ENV_FILE" "$active_cloud_env_temporary"
mv -f "$active_cloud_env_temporary" "$active_cloud_env_file"

if [ -n "$current_release" ]; then
    printf '%s\n' "$current_release" >"${STATE_DIR}/previous-release"
fi
printf '%s\n' "$target_release" >"${STATE_DIR}/current-release"
chmod 600 "${STATE_DIR}/current-release" "${STATE_DIR}/previous-release" 2>/dev/null || true

log "Application images rolled back to ${target_release}; persistent data was not restored or deleted."
log "If migrations are not backward-compatible, stop and use the separately reviewed data-restore procedure."
