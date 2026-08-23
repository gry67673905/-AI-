#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command flock
require_command nginx
require_command sed
confirm=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-rollback) confirm=true; shift ;;
        *) die "Unknown IP Nginx rollback option: $1" ;;
    esac
done
[ "$confirm" = true ] || die "Refusing to restore prior Nginx state without --confirm-rollback."
if [ "${SMART_GOV_CUTOVER_LOCK_HELD:-}" != 1 ]; then
    install -d -o root -g root -m 755 /run/lock
    exec 8>/run/lock/smart-gov-cutover.lock
    flock -n 8 || die "Another cutover or legacy-retirement operation is already running."
    export SMART_GOV_CUTOVER_LOCK_HELD=1
fi
marker="${STATE_DIR}/ip-nginx-cutover"
[ -s "$marker" ] && [ ! -L "$marker" ] || die "IP Nginx cutover marker is missing or unsafe."
backup_dir="$(sed -n 's/^backup_dir=//p' "$marker")"
case "$backup_dir" in
    /var/backups/smart-gov-nginx/*-ip-cutover) ;;
    *) die "Cutover backup directory is outside the approved backup root." ;;
esac
[ -d "$backup_dir" ] && [ ! -L "$backup_dir" ] || die "Cutover backup directory is missing or unsafe."

target=/etc/nginx/sites-available/smart-gov-assistant.conf
enabled=/etc/nginx/sites-enabled/smart-gov-assistant.conf
ip_bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-ip-bootstrap.conf
domain_bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-bootstrap.conf
default_target=/etc/nginx/sites-available/default
default_enabled=/etc/nginx/sites-enabled/default
legacy_default_enabled=/etc/nginx/sites-enabled/ai-companion-api.conf
rm -f "$enabled" "$target" "$ip_bootstrap_enabled" "$domain_bootstrap_enabled" "$default_enabled" "$legacy_default_enabled" "$default_target"
[ ! -f "${backup_dir}/target.conf" ] || cp -a "${backup_dir}/target.conf" "$target"
[ ! -f "${backup_dir}/enabled-link.txt" ] || ln -sfn "$(<"${backup_dir}/enabled-link.txt")" "$enabled"
[ ! -f "${backup_dir}/ip-bootstrap-link.txt" ] || ln -sfn "$(<"${backup_dir}/ip-bootstrap-link.txt")" "$ip_bootstrap_enabled"
[ ! -f "${backup_dir}/domain-bootstrap-link.txt" ] || ln -sfn "$(<"${backup_dir}/domain-bootstrap-link.txt")" "$domain_bootstrap_enabled"
[ ! -f "${backup_dir}/default.conf" ] || cp -a "${backup_dir}/default.conf" "$default_target"
[ ! -f "${backup_dir}/default-link.txt" ] || ln -sfn "$(<"${backup_dir}/default-link.txt")" "$default_enabled"
[ ! -f "${backup_dir}/legacy-default-link.txt" ] || ln -sfn "$(<"${backup_dir}/legacy-default-link.txt")" "$legacy_default_enabled"
nginx -t
systemctl reload nginx
rm -f "${STATE_DIR}/public-cutover-passed" "${STATE_DIR}/ip-nginx-cutover"
log "Prior Nginx state restored; application data and the r5 containers were not removed."
