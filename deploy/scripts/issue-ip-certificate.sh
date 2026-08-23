#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command curl
require_command flock
require_command grep
require_command nginx
require_command openssl
require_command sed
require_command sleep
require_command systemctl

lego_bin=/usr/local/bin/lego-v5
[ -x "$lego_bin" ] && [ ! -L "$lego_bin" ] || die "Pinned lego v5 binary is unavailable or unsafe."
"$lego_bin" --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "Pinned lego binary is not version 5.4.0."

public_ipv4="${PUBLIC_IPV4:-}"
staging=false
http_ingress_confirmed=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --http-security-group-confirmed) http_ingress_confirmed=true; shift ;;
        --staging) staging=true; shift ;;
        *) die "Unknown IP certificate option: $1" ;;
    esac
done
validate_ipv4 "$public_ipv4" || die "A valid public IPv4 must be supplied."
[ "$http_ingress_confirmed" = true ] || die "Confirm public TCP 80 ingress with --http-security-group-confirmed."

install -d -o root -g root -m 755 /run/lock
exec 9>/run/lock/smart-gov-ip-cert.lock
flock -n 9 || die "Another IP certificate issue or renewal operation is already running."
export SMART_GOV_IP_CERT_LOCK_HELD=1

install -d -o root -g root -m 755 /var/www/smart-gov-acme
challenge_dir=/var/www/smart-gov-acme/.well-known/acme-challenge
install -d -o root -g root -m 755 "$challenge_dir"

bootstrap_target=/etc/nginx/sites-available/smart-gov-ip-bootstrap.conf
bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-ip-bootstrap.conf
bootstrap_backup="/var/backups/smart-gov-nginx/$(utc_stamp)-ip-bootstrap"
install -d -o root -g root -m 700 "$bootstrap_backup"
had_target=false
had_enabled=false
legacy_default_links=(
    /etc/nginx/sites-enabled/ai-companion-api.conf
    /etc/nginx/sites-enabled/default
)
if [ -f "$bootstrap_target" ]; then
    cp -a "$bootstrap_target" "${bootstrap_backup}/bootstrap.conf"
    had_target=true
fi
if [ -L "$bootstrap_enabled" ]; then
    readlink "$bootstrap_enabled" >"${bootstrap_backup}/enabled-link.txt"
    had_enabled=true
fi
: >"${bootstrap_backup}/legacy-default-links.tsv"
for legacy_link in "${legacy_default_links[@]}"; do
    [ ! -e "$legacy_link" ] || [ -L "$legacy_link" ] ||
        die "Refusing to replace a non-symlink legacy default vhost entry: ${legacy_link}"
    if [ -L "$legacy_link" ]; then
        printf '%s\t%s\n' "$legacy_link" "$(readlink "$legacy_link")" \
            >>"${bootstrap_backup}/legacy-default-links.tsv"
    fi
done
restore_bootstrap() {
    local legacy_link legacy_target
    rm -f "$bootstrap_enabled" "$bootstrap_target"
    if [ "$had_target" = true ]; then
        cp -a "${bootstrap_backup}/bootstrap.conf" "$bootstrap_target"
    fi
    if [ "$had_enabled" = true ]; then
        ln -sfn "$(<"${bootstrap_backup}/enabled-link.txt")" "$bootstrap_enabled"
    fi
    while IFS=$'\t' read -r legacy_link legacy_target; do
        [ -n "$legacy_link" ] || continue
        ln -sfn "$legacy_target" "$legacy_link"
    done <"${bootstrap_backup}/legacy-default-links.tsv"
}

bootstrap_changed=false
issue_complete=false
restore_bootstrap_on_failure() {
    local status=$?
    trap - EXIT INT TERM
    if [ "$status" -ne 0 ] && [ "$bootstrap_changed" = true ] && [ "$issue_complete" = false ]; then
        restore_bootstrap
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
        printf '[smart-gov] ERROR: IP certificate issuance failed; prior Nginx state restoration was attempted.\n' >&2
    fi
    exit "$status"
}

[ ! -e "$bootstrap_enabled" ] || [ -L "$bootstrap_enabled" ] ||
    die "Refusing to replace a non-symlink IP bootstrap sites-enabled entry."
[ ! -e "$bootstrap_target" ] || { [ -f "$bootstrap_target" ] && [ ! -L "$bootstrap_target" ]; } ||
    die "Refusing to replace an unsafe IP bootstrap target."
temporary_bootstrap="$(mktemp /etc/nginx/sites-available/.smart-gov-ip-bootstrap.conf.XXXXXX)"
sed "s/__PUBLIC_IPV4__/${public_ipv4}/g" \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-ip-bootstrap.conf.template" >"$temporary_bootstrap"
chmod 644 "$temporary_bootstrap"
trap restore_bootstrap_on_failure EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bootstrap_changed=true
for legacy_link in "${legacy_default_links[@]}"; do
    rm -f "$legacy_link"
done
mv -fT "$temporary_bootstrap" "$bootstrap_target"
ln -sfn "$bootstrap_target" "$bootstrap_enabled"
if ! nginx -t || ! systemctl reload nginx; then
    restore_bootstrap
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    die "Unable to enable the IP HTTP-01 webroot; prior Nginx state was restored."
fi

probe_file="$(mktemp "${challenge_dir}/preflight.XXXXXX")"
probe_name="$(basename "$probe_file")"
printf '%s\n' "$probe_name" >"$probe_file"
chmod 644 "$probe_file"
probe_ok=false
for _ in {1..10}; do
    probe_body="$(curl --noproxy '*' --fail --silent --show-error --max-time 5 \
        -H "Host: ${public_ipv4}" "http://127.0.0.1/.well-known/acme-challenge/${probe_name}" || true)"
    if [ "$probe_body" = "$probe_name" ]; then
        probe_ok=true
        break
    fi
    # systemctl reload may return just before the old Nginx worker stops
    # accepting connections. Retry only this local, non-billable probe.
    sleep 1
done
rm -f "$probe_file"
[ "$probe_ok" = true ] || die "Local Nginx HTTP-01 webroot returned unexpected content."

if [ "$staging" = true ]; then
    acme_server=https://acme-staging-v02.api.letsencrypt.org/directory
    lego_path=/etc/lego-smart-gov/staging-ip
else
    acme_server=https://acme-v02.api.letsencrypt.org/directory
    lego_path=/etc/lego-smart-gov/production-ip
fi
install -d -o root -g root -m 700 /etc/lego-smart-gov "$lego_path"
temporary_ip="$(mktemp /etc/lego-smart-gov/.ip-address.XXXXXX)"
printf '%s\n' "$public_ipv4" >"$temporary_ip"
install -m 600 "$temporary_ip" /etc/lego-smart-gov/ip-address
rm -f "$temporary_ip"
install -m 755 "${SCRIPT_DIR}/deploy-ip-certificate-hook.sh" /usr/local/sbin/smart-gov-deploy-ip-cert

config_path="${lego_path}/.lego.yml"
temporary_config="$(mktemp "${lego_path}/.lego.yml.XXXXXX")"
{
    printf 'storage: %s\n' "$lego_path"
    printf 'networkStack: ipv4only\n'
    printf 'accounts:\n'
    printf '  smart-gov-ip:\n'
    printf '    server: %s\n' "$acme_server"
    printf '    acceptsTermsOfService: true\n'
    printf 'challenges:\n'
    printf '  http-webroot:\n'
    printf '    http:\n'
    printf '      webroot: /var/www/smart-gov-acme\n'
    printf 'certificates:\n'
    printf '  smart-gov-ip:\n'
    printf '    account: smart-gov-ip\n'
    printf '    challenge: http-webroot\n'
    printf '    domains:\n'
    printf '      - "%s"\n' "$public_ipv4"
    printf '    profile: shortlived\n'
    printf '    renew:\n'
    printf '      days: 3\n'
    printf '      disableRandomSleep: true\n'
    printf '      ari:\n'
    printf '        disable: true\n'
    if [ "$staging" = false ]; then
        printf 'hooks:\n'
        printf '  deploy:\n'
        printf '    command: /usr/local/sbin/smart-gov-deploy-ip-cert\n'
        printf '    timeout: 1m\n'
    fi
} >"$temporary_config"
install -m 600 "$temporary_config" "$config_path"
rm -f "$temporary_config"

log "Requesting a short-lived IP certificate through the persistent HTTP-01 webroot."
"$lego_bin" --config "$config_path"
source_cert="${lego_path}/certificates/smart-gov-ip.crt"
source_key="${lego_path}/certificates/smart-gov-ip.key"
[ -s "$source_cert" ] && [ -s "$source_key" ] || die "lego did not create the expected IP certificate pair."
openssl x509 -in "$source_cert" -noout -checkip "$public_ipv4" >/dev/null ||
    die "Issued certificate does not contain the requested IP subjectAltName."
not_before="$(openssl x509 -in "$source_cert" -noout -startdate | sed 's/^notBefore=//')"
not_after="$(openssl x509 -in "$source_cert" -noout -enddate | sed 's/^notAfter=//')"
lifetime_seconds=$(( $(date -u -d "$not_after" +%s) - $(date -u -d "$not_before" +%s) ))
[ "$lifetime_seconds" -ge 345600 ] || die "Issued certificate lifetime is unexpectedly shorter than four days."
[ "$lifetime_seconds" -le 691200 ] || die "Issued certificate is not from the short-lived profile."

if [ "$staging" = true ]; then
    restore_bootstrap
    nginx -t
    systemctl reload nginx
    bootstrap_changed=false
    issue_complete=true
    trap - EXIT INT TERM
    log "IP HTTP-01 staging validation succeeded; no trusted certificate or traffic route was changed."
    exit 0
fi

live_cert="/etc/letsencrypt/live/${public_ipv4}/fullchain.pem"
live_key="/etc/letsencrypt/live/${public_ipv4}/privkey.pem"
[ -s "$live_cert" ] && [ -s "$live_key" ] || die "Production deploy hook did not install the live IP certificate pair."
openssl x509 -in "$live_cert" -noout -checkip "$public_ipv4" >/dev/null ||
    die "Live certificate does not contain the requested IP subjectAltName."

install -m 755 "${SCRIPT_DIR}/renew-ip-certificate.sh" /usr/local/sbin/smart-gov-renew-ip-cert
install -m 644 "${PROJECT_ROOT}/deploy/systemd/smart-gov-ip-cert-renew.service" \
    /etc/systemd/system/smart-gov-ip-cert-renew.service
install -m 644 "${PROJECT_ROOT}/deploy/systemd/smart-gov-ip-cert-renew.timer" \
    /etc/systemd/system/smart-gov-ip-cert-renew.timer
systemctl daemon-reload
systemctl enable --now smart-gov-ip-cert-renew.timer
systemctl is-enabled --quiet smart-gov-ip-cert-renew.timer || die "IP certificate renewal timer is not enabled."
systemctl is-active --quiet smart-gov-ip-cert-renew.timer || die "IP certificate renewal timer is not active."

umask 077
temporary_marker="$(mktemp "${STATE_DIR}/.ip-certificate-active.XXXXXX")"
{
    printf 'public_ipv4=%s\n' "$public_ipv4"
    printf 'profile=shortlived\n'
    printf 'activated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" "${STATE_DIR}/ip-certificate-active"
restore_bootstrap
nginx -t
systemctl reload nginx
bootstrap_changed=false
issue_complete=true
trap - EXIT INT TERM
log "Trusted short-lived IP certificate installed; twice-daily renewal is enabled without stopping Nginx."
