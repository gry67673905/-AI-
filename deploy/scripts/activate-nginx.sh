#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command nginx
require_command curl
require_cloud_files
bash "${SCRIPT_DIR}/verify-metastudio-smoke.sh" --skip-http
require_rag_cutover_ready
require_cutover_smoke_ready

domain="${SMART_GOV_DOMAIN:-}"
confirm=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --confirm-cutover) confirm=true; shift ;;
        *) die "Unknown Nginx activation option: $1" ;;
    esac
done

[ "$confirm" = true ] || die "Refusing to switch traffic without --confirm-cutover."
[[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || die "Invalid domain."
[ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ] || die "TLS certificate is missing for ${domain}."

"${SCRIPT_DIR}/health-check.sh" --timeout 60 --expect-rag enabled

target=/etc/nginx/sites-available/smart-gov-assistant.conf
enabled=/etc/nginx/sites-enabled/smart-gov-assistant.conf
bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-bootstrap.conf
backup_dir="/var/backups/smart-gov-nginx/$(utc_stamp)"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
had_target=false
had_enabled=false
had_bootstrap=false
if [ -f "$target" ]; then
    cp -a "$target" "${backup_dir}/smart-gov-assistant.conf"
    had_target=true
fi
if [ -L "$enabled" ]; then
    readlink "$enabled" >"${backup_dir}/enabled-link.txt"
    had_enabled=true
fi
if [ -L "$bootstrap_enabled" ]; then
    readlink "$bootstrap_enabled" >"${backup_dir}/bootstrap-link.txt"
    had_bootstrap=true
fi

restore_previous_nginx() {
    rm -f "$enabled" "$target" "$bootstrap_enabled"
    if [ "$had_target" = true ]; then
        cp -a "${backup_dir}/smart-gov-assistant.conf" "$target"
    fi
    if [ "$had_enabled" = true ]; then
        ln -sfn "$(<"${backup_dir}/enabled-link.txt")" "$enabled"
    fi
    if [ "$had_bootstrap" = true ]; then
        ln -sfn "$(<"${backup_dir}/bootstrap-link.txt")" "$bootstrap_enabled"
    fi
}

sed "s/__DOMAIN__/${domain}/g" \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-https.conf.template" >"$target"
chmod 644 "$target"
ln -sfn "$target" "$enabled"
rm -f "$bootstrap_enabled"

if ! nginx -t; then
    restore_previous_nginx
    nginx -t || true
    die "Nginx validation failed; the complete previous Nginx state was restored."
fi
if ! systemctl reload nginx; then
    restore_previous_nginx
    nginx -t || true
    systemctl reload nginx || true
    die "Nginx reload failed; the complete previous Nginx state was restored."
fi

if ! "${SCRIPT_DIR}/health-check.sh" --timeout 60 --public-base "https://${domain}"; then
    restore_previous_nginx
    nginx -t
    systemctl reload nginx
    die "Public HTTPS health failed; the complete previous Nginx state was restored."
fi

log "HTTPS traffic for ${domain} now targets 127.0.0.1:18000."
log "Legacy systemd services are still running; retire them only with retire-legacy.sh."
