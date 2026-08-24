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

backup_root="${SMART_GOV_BACKUP_ROOT:-/var/backups/smart-gov-assistant}"
backup_dir=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --destination) backup_dir="${2:-}"; shift 2 ;;
        *) die "Unknown backup option: $1" ;;
    esac
done
if [ -z "$backup_dir" ]; then
    backup_dir="${backup_root}/$(utc_stamp)"
fi
[[ "$backup_dir" == /* ]] || die "Backup destination must be an absolute path."
[ ! -e "$backup_dir" ] || die "Backup destination already exists: ${backup_dir}"

umask 077
mkdir -p "$backup_dir/config"
chmod 700 "$backup_dir"

running_services="$(cloud_compose ps --status running --services)"
grep -Fxq postgres <<<"$running_services" || die "PostgreSQL is not running."
grep -Fxq minio <<<"$running_services" || die "MinIO is not running."

log "Creating a consistent PostgreSQL custom-format dump."
cloud_compose exec -T postgres sh -ec \
    'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    >"${backup_dir}/postgres.dump"
chmod 600 "${backup_dir}/postgres.dump"

log "Mirroring private MinIO buckets into the backup directory."
export BACKUP_DIR="$backup_dir"
cloud_compose --profile ops run --rm minio-backup
unset BACKUP_DIR

install -m 600 "$COMPOSE_FILE" "${backup_dir}/config/compose.cloud.yaml"
if metastudio_enabled; then
    install -m 600 "$METASTUDIO_COMPOSE_FILE" \
        "${backup_dir}/config/compose.metastudio.yaml"
fi
install -m 600 "$CLOUD_ENV_FILE" "${backup_dir}/config/cloud.env"
tar -C "${PROJECT_ROOT}/deploy" -czf "${backup_dir}/config/docker-secrets.tar.gz" secrets
chmod 600 "${backup_dir}/config/docker-secrets.tar.gz"

cloud_compose images --format json >"${backup_dir}/images.json"
chmod 600 "${backup_dir}/images.json"
{
    printf 'created_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'compose_project=smart-gov-cloud-demo\n'
    printf 'milvus_rebuild_source=postgres_active_knowledge_chunks\n'
    printf 'redis_backup=omitted_disposable_cache\n'
} >"${backup_dir}/manifest.txt"

find "$backup_dir" -type f ! -name SHA256SUMS -print0 |
    sort -z |
    xargs -0 sha256sum >"${backup_dir}/SHA256SUMS"
chmod -R go-rwx "$backup_dir"
log "Backup completed at ${backup_dir}. Secret values were not displayed."
