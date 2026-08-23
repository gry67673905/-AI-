#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command nginx
require_command python3
require_command sha256sum

legacy_root="${LEGACY_APP_ROOT:-/opt/ai-companion-server}"
backup_root="${LEGACY_BACKUP_ROOT:-/var/backups/ai-companion-legacy}"
backup_dir="${backup_root}/$(utc_stamp)"
[ -d "$legacy_root" ] || die "Legacy application directory was not found."
[ -f "${legacy_root}/data/app.sqlite3" ] || die "Legacy SQLite database was not found."

umask 077
mkdir -p "${backup_dir}/config"
chmod 700 "$backup_dir"

python3 - "${legacy_root}/data/app.sqlite3" "${backup_dir}/app.sqlite3" <<'PY'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
destination = sqlite3.connect(destination_path)
try:
    source.backup(destination)
    result = destination.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError("SQLite quick_check failed")
finally:
    destination.close()
    source.close()
PY

for source in \
    "${legacy_root}/.env" \
    /etc/nginx/nginx.conf \
    /etc/nginx/sites-available/default \
    /etc/nginx/sites-available/ai-companion-api.conf; do
    if [ -f "$source" ]; then
        install -m 600 "$source" "${backup_dir}/config/$(basename "$source")"
    fi
done

nginx -T >"${backup_dir}/config/nginx-effective.conf" 2>&1
chmod 600 "${backup_dir}/config/nginx-effective.conf"
find /etc/nginx/sites-enabled -maxdepth 1 -type l -printf '%f\t%l\n' \
    >"${backup_dir}/config/nginx-enabled-links.tsv"
chmod 600 "${backup_dir}/config/nginx-enabled-links.tsv"

legacy_units=(
    ai-companion-api.service
    ai-companion-guides.service
    ai-companion-guides.timer
    image-enrich.service
    image-enrich.timer
    ai-companion-image-enrich.service
    ai-companion-image-enrich.timer
    poi-enrichment.service
    poi-enrichment.timer
    travel-image-enrichment.service
    travel-image-enrichment.timer
)
: >"${backup_dir}/config/unit-states.tsv"
for unit in "${legacy_units[@]}"; do
    fragment="$(systemctl show "$unit" -p FragmentPath --value 2>/dev/null || true)"
    if [ -n "$fragment" ] && [ -f "$fragment" ]; then
        install -m 600 "$fragment" "${backup_dir}/config/$(basename "$fragment")"
        active_state="$(systemctl is-active "$unit" 2>/dev/null || true)"
        enabled_state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
        printf '%s\t%s\t%s\t%s\n' "$unit" "$active_state" "$enabled_state" "$fragment" \
            >>"${backup_dir}/config/unit-states.tsv"
    fi
done
chmod 600 "${backup_dir}/config/unit-states.tsv"

tar -C "$legacy_root" -czf "${backup_dir}/legacy-code-and-scripts.tar.gz" \
    app deploy scripts requirements.txt README.md 2>/dev/null ||
    die "Unable to archive the legacy code and operational scripts."
chmod 600 "${backup_dir}/legacy-code-and-scripts.tar.gz"
find "$backup_dir" -type f ! -name SHA256SUMS -print0 |
    sort -z |
    xargs -0 sha256sum >"${backup_dir}/SHA256SUMS"
chmod -R go-rwx "$backup_dir"

log "Legacy control-plane backup completed at ${backup_dir}."
log "The 3.7 GiB legacy media tree remains in place and was not duplicated or deleted."
printf 'LEGACY_BACKUP_DIR=%s\n' "$backup_dir"
