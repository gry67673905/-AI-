#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command sha256sum
backup_dir=""
confirm=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --backup) backup_dir="${2:-}"; shift 2 ;;
        --confirm-restore) confirm=true; shift ;;
        *) die "Unknown legacy restore option: $1" ;;
    esac
done
[ "$confirm" = true ] || die "Refusing legacy restoration without --confirm-restore."
case "$backup_dir" in
    /var/backups/ai-companion-legacy/*) ;;
    *) die "Legacy backup path is outside the approved backup root." ;;
esac
[ -d "$backup_dir" ] && [ ! -L "$backup_dir" ] || die "Legacy backup directory is missing or unsafe."
(cd "$backup_dir" && sha256sum -c --quiet SHA256SUMS) || die "Legacy backup checksum verification failed."
state_file="${backup_dir}/config/unit-states.tsv"
[ -s "$state_file" ] || die "Legacy unit state manifest is missing."

while IFS=$'\t' read -r unit active_state enabled_state fragment; do
    [ -n "$unit" ] || continue
    [ -f "$fragment" ] || {
        saved_fragment="${backup_dir}/config/$(basename "$fragment")"
        [ -f "$saved_fragment" ] || die "Saved unit fragment is missing: ${unit}"
        install -m 644 "$saved_fragment" "$fragment"
    }
done <"$state_file"

systemctl daemon-reload
while IFS=$'\t' read -r unit active_state enabled_state fragment; do
    [ -n "$unit" ] || continue
    case "$enabled_state" in
        enabled|enabled-runtime|linked|linked-runtime) systemctl enable "$unit" >/dev/null ;;
    esac
    case "$active_state" in
        active|activating|reloading) systemctl start "$unit" ;;
    esac
done <"$state_file"
if [ -s "${STATE_DIR}/ip-nginx-cutover" ]; then
    "${SCRIPT_DIR}/rollback-ip-nginx.sh" --confirm-rollback
fi
rm -f "${STATE_DIR}/legacy-retired"
log "Legacy unit states and prior Nginx route were restored; SQLite, .env and code were never deleted."
