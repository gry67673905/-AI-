#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command flock
require_command sha256sum
require_cloud_files
public_ipv4="${PUBLIC_IPV4:-}"
confirm=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --confirm-stop-legacy) confirm=true; shift ;;
        *) die "Unknown legacy retirement option: $1" ;;
    esac
done

[ "$confirm" = true ] || die "Refusing to stop legacy services without --confirm-stop-legacy."
validate_ipv4 "$public_ipv4" || die "A valid public IPv4 must be supplied."

install -d -o root -g root -m 755 /run/lock
exec 8>/run/lock/smart-gov-cutover.lock
flock -n 8 || die "Another cutover or legacy-retirement operation is already running."
export SMART_GOV_CUTOVER_LOCK_HELD=1
require_rag_cutover_ready
require_cutover_smoke_ready
require_current_release_images
require_public_cutover_ready "$public_ipv4"

"${SCRIPT_DIR}/health-check.sh" --timeout 60 --expect-rag enabled --public-base "https://${public_ipv4}"
require_current_release_images
backup_output="$("${SCRIPT_DIR}/backup-legacy.sh")"
printf '%s\n' "$backup_output"
backup_dir="$(sed -n 's/^LEGACY_BACKUP_DIR=//p' <<<"$backup_output" | tail -1)"
[ -d "$backup_dir" ] || die "Unable to locate the verified legacy backup."
(cd "$backup_dir" && sha256sum -c --quiet SHA256SUMS) ||
    die "Legacy backup checksum verification failed; no unit was stopped."
[ -s "${backup_dir}/config/unit-states.tsv" ] || die "Legacy unit state manifest is missing."

legacy_units=(
    ai-companion-guides.timer
    image-enrich.timer
    ai-companion-image-enrich.timer
    poi-enrichment.timer
    travel-image-enrichment.timer
    ai-companion-guides.service
    image-enrich.service
    ai-companion-image-enrich.service
    poi-enrichment.service
    travel-image-enrichment.service
    ai-companion-api.service
)
loaded_units=()
declare -A was_active=()
declare -A was_enabled=()
for unit in "${legacy_units[@]}"; do
    fragment="$(systemctl show "$unit" -p FragmentPath --value 2>/dev/null || true)"
    if [ -n "$fragment" ] && [ -f "$fragment" ]; then
        [ -f "${backup_dir}/config/$(basename "$fragment")" ] ||
            die "Refusing to stop an unbacked unit: ${unit}"
        loaded_units+=("$unit")
        was_active["$unit"]="$(systemctl is-active "$unit" 2>/dev/null || true)"
        was_enabled["$unit"]="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
    fi
done

modified_units=()
retirement_complete=false
restore_on_failure() {
    local status=$? unit index
    trap - EXIT INT TERM
    if [ "$status" -ne 0 ] && [ "$retirement_complete" = false ]; then
        for ((index=${#modified_units[@]}-1; index>=0; index--)); do
            unit="${modified_units[$index]}"
            case "${was_enabled[$unit]}" in
                enabled|enabled-runtime|linked|linked-runtime) systemctl enable "$unit" >/dev/null 2>&1 || true ;;
            esac
            case "${was_active[$unit]}" in
                active|activating|reloading) systemctl start "$unit" >/dev/null 2>&1 || true ;;
            esac
        done
        if [ -s "${STATE_DIR}/ip-nginx-cutover" ]; then
            "${SCRIPT_DIR}/rollback-ip-nginx.sh" --confirm-rollback >/dev/null 2>&1 || true
        fi
        printf '[smart-gov] ERROR: Legacy retirement failed; prior unit and Nginx state restoration was attempted.\n' >&2
    fi
    exit "$status"
}
trap restore_on_failure EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for unit in "${loaded_units[@]}"; do
    modified_units+=("$unit")
    systemctl stop "$unit"
    case "${was_enabled[$unit]}" in
        enabled|enabled-runtime|linked|linked-runtime) systemctl disable "$unit" >/dev/null ;;
    esac
done

for unit in "${loaded_units[@]}"; do
    state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    if [ "$state" = failed ]; then
        # A oneshot that was activating when deliberately stopped can retain
        # a failed latch even though it has no process. Clear only that latch;
        # never start or enable the retired unit.
        systemctl reset-failed "$unit"
        state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    fi
    case "$state" in
        inactive|unknown) ;;
        *) die "Legacy unit did not become inactive: ${unit} (${state})" ;;
    esac
    enabled_state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
    case "$enabled_state" in
        enabled|enabled-runtime|linked|linked-runtime)
            die "Legacy unit remained enabled: ${unit} (${enabled_state})"
            ;;
    esac
done
"${SCRIPT_DIR}/health-check.sh" --timeout 60 --expect-rag enabled --public-base "https://${public_ipv4}"
require_current_release_images
temporary_marker="$(mktemp "${STATE_DIR}/.legacy-retired.XXXXXX")"
{
    printf 'public_ipv4=%s\n' "$public_ipv4"
    printf 'backup_dir=%s\n' "$backup_dir"
    printf 'retired_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" "${STATE_DIR}/legacy-retired"
retirement_complete=true
trap - EXIT INT TERM
log "Legacy API and background timers are stopped and disabled; files and data were retained."
