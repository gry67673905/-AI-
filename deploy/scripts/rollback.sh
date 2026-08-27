#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command docker

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

active_compose_file="$COMPOSE_FILE"
active_metastudio_compose_file="$METASTUDIO_COMPOSE_FILE"
active_cloud_env_file="$CLOUD_ENV_FILE"
[ -f "$active_compose_file" ] || die "Active compose.cloud.yaml is missing."
[ -f "$active_cloud_env_file" ] || die "Active deploy/cloud.env is missing."

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
original_active_env="$(mktemp "${STATE_DIR}/.rollback-active-env.XXXXXX")"
install -m 600 "$active_cloud_env_file" "$original_active_env"
original_active_compose="$(mktemp "${STATE_DIR}/.rollback-active-compose.XXXXXX")"
install -m 600 "$active_compose_file" "$original_active_compose"
original_active_metastudio_compose=""
active_metastudio_compose_existed=false
if [ -f "$active_metastudio_compose_file" ]; then
    original_active_metastudio_compose="$(mktemp "${STATE_DIR}/.rollback-active-metastudio.XXXXXX")"
    install -m 600 "$active_metastudio_compose_file" "$original_active_metastudio_compose"
    active_metastudio_compose_existed=true
fi
sanitized_backup_env=""
cleanup_rollback_temporaries() {
    rm -f "$original_active_env" "$original_active_compose" \
        "$original_active_metastudio_compose" "$sanitized_backup_env" 2>/dev/null || true
}
trap cleanup_rollback_temporaries EXIT

prepare_release_application_aliases() {
    local release_tag="$1" snapshot="$2" mapping repository image_id
    local source_id tagged_id count=0
    validate_release_tag "$release_tag" || return 1
    [ -s "$snapshot" ] && [ ! -L "$snapshot" ] || return 1
    mapping="$(mktemp "${STATE_DIR}/.rollback-images.XXXXXX")" || return 1
    if ! python3 - "$snapshot" >"$mapping" <<'PY'
import json
import re
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


required = {
    "smart-gov/api",
    "smart-gov/mcp-server",
    "smart-gov/mock-gov-api",
}
optional = {"smart-gov/material-worker"}
found: dict[str, str] = {}
for item in load(sys.argv[1]):
    repository = str(item.get("Repository", ""))
    if repository not in required | optional:
        continue
    image_id = str(item.get("ID", ""))
    if repository in found or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{12,64}", image_id):
        raise RuntimeError("invalid application image inventory")
    found[repository] = image_id
if not required.issubset(found) or set(found) - required - optional:
    raise RuntimeError("application image inventory is incomplete")
for repository in sorted(found):
    print(f"{repository}\t{found[repository]}")
PY
    then
        rm -f "$mapping"
        return 1
    fi
    while IFS=$'\t' read -r repository image_id; do
        case "$repository" in
            smart-gov/api|smart-gov/mcp-server|smart-gov/mock-gov-api|smart-gov/material-worker) ;;
            *) rm -f "$mapping"; return 1 ;;
        esac
        source_id="$(docker image inspect --format '{{.Id}}' "$image_id" 2>/dev/null)" || {
            rm -f "$mapping"
            return 1
        }
        docker image tag "$image_id" "${repository}:${release_tag}" || {
            rm -f "$mapping"
            return 1
        }
        tagged_id="$(docker image inspect --format '{{.Id}}' "${repository}:${release_tag}" 2>/dev/null)" || {
            rm -f "$mapping"
            return 1
        }
        [ "$source_id" = "$tagged_id" ] || {
            rm -f "$mapping"
            return 1
        }
        count=$((count + 1))
    done <"$mapping"
    rm -f "$mapping"
    [ "$count" -eq 3 ] || [ "$count" -eq 4 ]
}

prepare_release_application_aliases "$target_release" "${release_dir}/images.json" ||
    die "Rollback application images do not match the immutable target snapshot: ${target_release}"

canonical_services_for_active_compose() {
    printf '%s\n' postgres redis etcd minio milvus mock-gov-api mcp-server api
    if cloud_compose config --services | grep -Fxq material-worker; then
        printf '%s\n' material-worker
    fi
}

remove_unmanaged_material_worker() {
    local -a worker_ids=()
    if cloud_compose config --services | grep -Fxq material-worker; then
        return 0
    fi
    mapfile -t worker_ids < <(docker ps -aq \
        --filter label=com.docker.compose.project=smart-gov-cloud-demo \
        --filter label=com.docker.compose.service=material-worker)
    if [ "${#worker_ids[@]}" -gt 0 ]; then
        docker stop --time 15 "${worker_ids[@]}" >/dev/null 2>&1 || true
        docker rm "${worker_ids[@]}" >/dev/null 2>&1 || true
    fi
}

current_release=""
if [ -s "${STATE_DIR}/current-release" ]; then
    current_release="$(<"${STATE_DIR}/current-release")"
    validate_release_tag "$current_release"
fi

restore_compose_file="$active_compose_file"
restore_metastudio_compose_file="$active_metastudio_compose_file"
if [ -n "$current_release" ] && [ -f "${RELEASES_DIR}/${current_release}/compose.cloud.yaml" ]; then
    restore_compose_file="${RELEASES_DIR}/${current_release}/compose.cloud.yaml"
    if [ -f "${RELEASES_DIR}/${current_release}/compose.metastudio.yaml" ]; then
        restore_metastudio_compose_file="${RELEASES_DIR}/${current_release}/compose.metastudio.yaml"
    fi
fi

# A pre-rollback data backup only needs the base stack. Use a temporary copy
# with MetaStudio disabled so an unavailable *current* vendor secret cannot
# prevent an emergency rollback to a target that has MetaStudio disabled.
# The archived configuration is then replaced with the unmodified active
# environment (and optional override), preserving an honest rollback record.
if [ "$skip_backup" = false ]; then
    running_services="$(
        docker compose --project-directory "$PROJECT_ROOT" \
            --env-file "$active_cloud_env_file" -f "$active_compose_file" \
            ps --status running --services 2>/dev/null || true
    )"
    if grep -Fxq api <<<"$running_services"; then
        sanitized_backup_env="$(mktemp "${STATE_DIR}/.rollback-backup-env.XXXXXX")"
        awk '
            BEGIN { found = 0 }
            /^METASTUDIO_ENABLED=/ {
                print "METASTUDIO_ENABLED=false"
                found = 1
                next
            }
            { print }
            END { if (!found) print "METASTUDIO_ENABLED=false" }
        ' "$original_active_env" >"$sanitized_backup_env"
        chmod 600 "$sanitized_backup_env"
        backup_destination="${SMART_GOV_BACKUP_ROOT:-/var/backups/smart-gov-assistant}/$(utc_stamp)-pre-rollback-${target_release}"
        COMPOSE_FILE="$active_compose_file" \
        CLOUD_ENV_FILE="$sanitized_backup_env" \
        METASTUDIO_COMPOSE_FILE="$active_metastudio_compose_file" \
            "${SCRIPT_DIR}/backup.sh" --destination "$backup_destination"
        install -m 600 "$original_active_env" "${backup_destination}/config/cloud.env"
        if [ -f "$active_metastudio_compose_file" ]; then
            install -m 600 "$active_metastudio_compose_file" \
                "${backup_destination}/config/compose.metastudio.yaml"
        fi
        find "$backup_destination" -type f ! -name SHA256SUMS -print0 |
            sort -z |
            xargs -0 sha256sum >"${backup_destination}/SHA256SUMS"
        chmod 600 "${backup_destination}/SHA256SUMS"
        log "Pre-rollback backup preserved the original active configuration at ${backup_destination}."
    fi
fi

# shellcheck disable=SC2034  # Read dynamically by cloud_compose from lib.sh.
COMPOSE_FILE="${release_dir}/compose.cloud.yaml"
# shellcheck disable=SC2034  # Read dynamically by cloud_compose from lib.sh.
CLOUD_ENV_FILE="${release_dir}/cloud.env"
METASTUDIO_COMPOSE_FILE="${release_dir}/compose.metastudio.yaml"
export COMPOSE_FILE CLOUD_ENV_FILE METASTUDIO_COMPOSE_FILE
if metastudio_enabled; then
    [ -f "$METASTUDIO_COMPOSE_FILE" ] ||
        die "MetaStudio-enabled release metadata is incomplete: ${target_release}"
fi
require_cloud_files
require_secrets
require_metastudio_config
export RELEASE_TAG="$target_release"

case "$(cloud_env_value RAG_GROUP_ENABLED)" in
    true|TRUE|1) target_rag_mode=enabled ;;
    *) target_rag_mode=disabled ;;
esac

rollback_started=false
restore_previous_runtime() {
    local status="$?" restore_rag_mode restore_status=0
    local -a restore_services=() restore_worker_args=()
    trap - EXIT
    rm -f "$sanitized_backup_env" 2>/dev/null || true
    if [ "$status" -ne 0 ] && [ "$rollback_started" = true ]; then
        set +e
        log "Target rollback failed; attempting to restore the previously running release."
        install -m 600 "$original_active_env" "$active_cloud_env_file" || restore_status=1
        install -m 600 "$original_active_compose" "$active_compose_file" || restore_status=1
        if [ "$active_metastudio_compose_existed" = true ]; then
            install -m 600 "$original_active_metastudio_compose" \
                "$active_metastudio_compose_file" || restore_status=1
        else
            rm -f "$active_metastudio_compose_file" || restore_status=1
        fi
        COMPOSE_FILE="$restore_compose_file"
        CLOUD_ENV_FILE="$original_active_env"
        METASTUDIO_COMPOSE_FILE="$restore_metastudio_compose_file"
        export COMPOSE_FILE CLOUD_ENV_FILE METASTUDIO_COMPOSE_FILE
        if [ -n "$current_release" ]; then
            if ! prepare_release_application_aliases \
                "$current_release" "${RELEASES_DIR}/${current_release}/images.json"; then
                restore_status=1
            fi
            RELEASE_TAG="$current_release"
            export RELEASE_TAG
        else
            restore_status=1
            unset RELEASE_TAG
        fi
        case "$(cloud_env_value RAG_GROUP_ENABLED)" in
            true|TRUE|1) restore_rag_mode=enabled ;;
            *) restore_rag_mode=disabled ;;
        esac
        if [ "$restore_status" -eq 0 ]; then
            # This compose view omits api-candidate, which may still carry
            # public traffic on 18001 during canonical recovery.
            remove_unmanaged_material_worker || restore_status=1
            mapfile -t restore_services < <(canonical_services_for_active_compose)
            if printf '%s\n' "${restore_services[@]}" | grep -Fxq material-worker; then
                restore_worker_args=(--worker-service material-worker)
            fi
            cloud_compose up -d --no-build "${restore_services[@]}" || restore_status=1
            COMPOSE_FILE="$COMPOSE_FILE" CLOUD_ENV_FILE="$CLOUD_ENV_FILE" \
            METASTUDIO_COMPOSE_FILE="$METASTUDIO_COMPOSE_FILE" RELEASE_TAG="${RELEASE_TAG:-}" \
                "${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" \
                    --expect-rag "$restore_rag_mode" \
                    "${restore_worker_args[@]}" || restore_status=1
            if [ "$restore_status" -eq 0 ]; then
                # Run the fail-fast verifier in a subshell so a mismatch marks
                # restoration unsuccessful without bypassing this trap's
                # final diagnostic path.
                (require_release_images \
                    "$current_release" \
                    "${RELEASES_DIR}/${current_release}/images.json") || restore_status=1
            fi
        fi
        if [ "$restore_status" -eq 0 ]; then
            log "Previously running release was restored after the failed rollback attempt."
        else
            log "ERROR: automatic restoration of the previous runtime also failed; inspect Docker state immediately."
        fi
        set -e
    fi
    rm -f "$original_active_env" 2>/dev/null || true
    exit "$status"
}
trap restore_previous_runtime EXIT

rollback_started=true
# Preserve a parallel candidate until traffic has explicitly returned to the
# canonical API and stop-candidate.sh performs its guarded cleanup.
remove_unmanaged_material_worker
mapfile -t target_services < <(canonical_services_for_active_compose)
target_worker_args=()
if printf '%s\n' "${target_services[@]}" | grep -Fxq material-worker; then
    target_worker_args=(--worker-service material-worker)
fi
cloud_compose up -d --no-build "${target_services[@]}"
COMPOSE_FILE="$COMPOSE_FILE" CLOUD_ENV_FILE="$CLOUD_ENV_FILE" \
METASTUDIO_COMPOSE_FILE="$METASTUDIO_COMPOSE_FILE" RELEASE_TAG="$RELEASE_TAG" \
    "${SCRIPT_DIR}/health-check.sh" --timeout "$health_timeout" \
        --expect-rag "$target_rag_mode" "${target_worker_args[@]}"
require_release_images "$target_release" "${release_dir}/images.json"

active_cloud_env_temporary="$(mktemp "${active_cloud_env_file}.rollback.XXXXXX")"
install -m 600 "$CLOUD_ENV_FILE" "$active_cloud_env_temporary"
mv -f "$active_cloud_env_temporary" "$active_cloud_env_file"
active_compose_temporary="$(mktemp "${active_compose_file}.rollback.XXXXXX")"
install -m 600 "$COMPOSE_FILE" "$active_compose_temporary"
mv -f "$active_compose_temporary" "$active_compose_file"
if [ -f "$METASTUDIO_COMPOSE_FILE" ]; then
    active_metastudio_temporary="$(mktemp "${active_metastudio_compose_file}.rollback.XXXXXX")"
    install -m 600 "$METASTUDIO_COMPOSE_FILE" "$active_metastudio_temporary"
    mv -f "$active_metastudio_temporary" "$active_metastudio_compose_file"
else
    rm -f "$active_metastudio_compose_file"
fi

if [ -n "$current_release" ]; then
    printf '%s\n' "$current_release" >"${STATE_DIR}/previous-release"
fi
printf '%s\n' "$target_release" >"${STATE_DIR}/current-release"
chmod 600 "${STATE_DIR}/current-release" "${STATE_DIR}/previous-release" 2>/dev/null || true

rollback_started=false

log "Application images rolled back to ${target_release}; persistent data was not restored or deleted."
log "If migrations are not backward-compatible, stop and use the separately reviewed data-restore procedure."
