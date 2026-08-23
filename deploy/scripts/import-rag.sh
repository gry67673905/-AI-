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

confirm=false
health_timeout=1200
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-paid-import) confirm=true; shift ;;
        --health-timeout) health_timeout="${2:-}"; shift 2 ;;
        *) die "Unknown RAG import option: $1" ;;
    esac
done
[ "$confirm" = true ] || die "RAG embedding can incur DashScope charges; pass --confirm-paid-import after cost approval."
[[ "$health_timeout" =~ ^[0-9]+$ ]] || die "Health timeout must be a positive integer."

dataset_version=team-2026-08-22-v1
archive_sha256=b5221f51465a230192148cb8e3db81a81e21348809a2738ca8ce89d8f6543f93
expected_chunks=15858
expected_routes=1012
archive_setting="$(cloud_env_value RAG_IMPORT_ARCHIVE)"
[ -n "$archive_setting" ] || archive_setting=./artifacts/rag/group-rag-sanitized-v1.zip
case "$archive_setting" in
    /*) archive_path="$archive_setting" ;;
    *) archive_path="${PROJECT_ROOT}/${archive_setting#./}" ;;
esac
[ -f "$archive_path" ] || die "Sanitized RAG archive is missing."
[ "$(sha256sum "$archive_path" | awk '{print $1}')" = "$archive_sha256" ] ||
    die "Sanitized RAG archive SHA-256 does not match the approved artifact."
[ "$(cloud_env_value RAG_GROUP_ENABLED)" = false ] ||
    die "Set RAG_GROUP_ENABLED=false before a first import or dataset replacement."
[ -s "${STATE_DIR}/current-release" ] || die "Current release marker is missing."
current_release="$(<"${STATE_DIR}/current-release")"
validate_release_tag "$current_release"
release_environment="${RELEASES_DIR}/${current_release}/cloud.env"
[ -f "$release_environment" ] || die "Current release environment snapshot is missing."

docker info >/dev/null
cloud_compose config --quiet
"${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" --expect-rag disabled

import_command=(
    python -m app.ops.import_rag_corpus
    --zip /import/group-rag-sanitized-v1.zip
    --dataset-version "$dataset_version"
    --expected-sha256 "$archive_sha256"
    --expected-chunks "$expected_chunks"
    --source-owner project-team
    --license-status INTERNAL_APPROVED
    --allow-unverified-demo
)

log "Validating the sanitized archive without network calls or writes."
cloud_compose --profile ops run --rm rag-import "${import_command[@]}" --dry-run
log "Starting the explicitly approved paid embedding import."
cloud_compose --profile ops run --rm rag-import "${import_command[@]}"

umask 077
mkdir -p "$STATE_DIR"
environment_backup="${STATE_DIR}/cloud.env.before-rag-$(utc_stamp)"
release_environment_backup="${STATE_DIR}/release-cloud.env.before-rag-$(utc_stamp)"
install -m 600 "$CLOUD_ENV_FILE" "$environment_backup"
install -m 600 "$release_environment" "$release_environment_backup"

restore_disabled_api() {
    local failure_status=$?
    trap - ERR
    install -m 600 "$environment_backup" "$CLOUD_ENV_FILE" || true
    install -m 600 "$release_environment_backup" "$release_environment" || true
    cloud_compose up -d --no-deps --force-recreate api || true
    "${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" --expect-rag disabled || true
    printf '[smart-gov] ERROR: RAG activation failed; API configuration was restored with RAG disabled. Imported versioned data was retained for diagnosis.\n' >&2
    exit "$failure_status"
}
trap restore_disabled_api ERR

set_cloud_env_value RAG_DATASET_VERSION "$dataset_version"
set_cloud_env_value RAG_ARCHIVE_SHA256 "$archive_sha256"
set_cloud_env_value RAG_EXPECTED_CHUNK_COUNT "$expected_chunks"
set_cloud_env_value RAG_EXPECTED_ROUTE_COUNT "$expected_routes"
set_cloud_env_value RAG_GROUP_ENABLED true

log "Import succeeded; recreating API with the fixed RAG dataset enabled."
cloud_compose up -d --no-deps --force-recreate api
"${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" --expect-rag enabled
install -m 600 "$CLOUD_ENV_FILE" "$release_environment"
trap - ERR

{
    printf 'dataset_version=%s\n' "$dataset_version"
    printf 'archive_sha256=%s\n' "$archive_sha256"
    printf 'activated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'release_tag=%s\n' "$current_release"
} >"${STATE_DIR}/rag-active"
chmod 600 "${STATE_DIR}/rag-active"

log "Team RAG ${dataset_version} is active and all eight readiness checks passed."
