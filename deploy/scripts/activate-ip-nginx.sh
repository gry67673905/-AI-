#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command curl
require_command flock
require_command nginx
require_command openssl
require_command sha256sum
require_command systemctl
require_command timeout
require_cloud_files

public_ipv4="${PUBLIC_IPV4:-}"
confirm_cutover=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --confirm-cutover) confirm_cutover=true; shift ;;
        *) die "Unknown IP Nginx activation option: $1" ;;
    esac
done
validate_ipv4 "$public_ipv4" || die "A valid public IPv4 must be supplied."
[ "$confirm_cutover" = true ] || die "Refusing to switch traffic without --confirm-cutover."

install -d -o root -g root -m 755 /run/lock
exec 8>/run/lock/smart-gov-cutover.lock
flock -n 8 || die "Another cutover or legacy-retirement operation is already running."
export SMART_GOV_CUTOVER_LOCK_HELD=1
require_rag_cutover_ready
require_cutover_smoke_ready
require_current_release_images
current_release="$(<"${STATE_DIR}/current-release")"
validate_release_tag "$current_release"

live_dir="/etc/letsencrypt/live/${public_ipv4}"
live_cert="${live_dir}/fullchain.pem"
live_key="${live_dir}/privkey.pem"
[ -s "$live_cert" ] && [ ! -L "$live_cert" ] || die "Trusted IP certificate is missing or unsafe."
[ -s "$live_key" ] && [ ! -L "$live_key" ] || die "Trusted IP private key is missing or unsafe."
openssl x509 -in "$live_cert" -noout -checkip "$public_ipv4" >/dev/null || die "Certificate lacks the approved IP subjectAltName."
openssl x509 -in "$live_cert" -noout -checkend 259200 >/dev/null || die "IP certificate expires too soon for cutover."
cert_public_key="$(openssl x509 -in "$live_cert" -pubkey -noout |
    openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
private_public_key="$(openssl pkey -in "$live_key" -pubout -outform DER 2>/dev/null |
    sha256sum | awk '{print $1}')"
[ "$cert_public_key" = "$private_public_key" ] || die "IP certificate and private key do not match."
systemctl is-enabled --quiet smart-gov-ip-cert-renew.timer || die "IP certificate renewal timer is not enabled."
systemctl is-active --quiet smart-gov-ip-cert-renew.timer || die "IP certificate renewal timer is not active."

"${SCRIPT_DIR}/health-check.sh" --timeout 60 --expect-rag enabled
require_current_release_images

target=/etc/nginx/sites-available/smart-gov-assistant.conf
enabled=/etc/nginx/sites-enabled/smart-gov-assistant.conf
ip_bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-ip-bootstrap.conf
domain_bootstrap_enabled=/etc/nginx/sites-enabled/smart-gov-bootstrap.conf
default_target=/etc/nginx/sites-available/default
default_enabled=/etc/nginx/sites-enabled/default
legacy_default_enabled=/etc/nginx/sites-enabled/ai-companion-api.conf
for candidate in "$enabled" "$ip_bootstrap_enabled" "$domain_bootstrap_enabled" "$default_enabled" "$legacy_default_enabled"; do
    [ ! -e "$candidate" ] || [ -L "$candidate" ] || die "Refusing to replace a non-symlink sites-enabled entry: ${candidate}"
done
for candidate in "$target" "$default_target"; do
    [ ! -e "$candidate" ] || { [ -f "$candidate" ] && [ ! -L "$candidate" ]; } ||
        die "Refusing to replace an unsafe sites-available entry: ${candidate}"
done
backup_dir="/var/backups/smart-gov-nginx/$(utc_stamp)-ip-cutover"
install -d -o root -g root -m 700 "$backup_dir"

backup_file() {
    local source="$1" name="$2"
    if [ -f "$source" ]; then
        cp -a "$source" "${backup_dir}/${name}"
    fi
}
backup_link() {
    local source="$1" name="$2"
    if [ -L "$source" ]; then
        readlink "$source" >"${backup_dir}/${name}"
    fi
}
backup_file "$target" target.conf
backup_link "$enabled" enabled-link.txt
backup_link "$ip_bootstrap_enabled" ip-bootstrap-link.txt
backup_link "$domain_bootstrap_enabled" domain-bootstrap-link.txt
backup_file "$default_target" default.conf
backup_link "$default_enabled" default-link.txt
backup_link "$legacy_default_enabled" legacy-default-link.txt

restore_previous_nginx() {
    rm -f "$enabled" "$target" "$ip_bootstrap_enabled" "$domain_bootstrap_enabled" "$default_enabled" "$legacy_default_enabled" "$default_target"
    [ ! -f "${backup_dir}/target.conf" ] || cp -a "${backup_dir}/target.conf" "$target"
    [ ! -f "${backup_dir}/enabled-link.txt" ] || ln -sfn "$(<"${backup_dir}/enabled-link.txt")" "$enabled"
    [ ! -f "${backup_dir}/ip-bootstrap-link.txt" ] || ln -sfn "$(<"${backup_dir}/ip-bootstrap-link.txt")" "$ip_bootstrap_enabled"
    [ ! -f "${backup_dir}/domain-bootstrap-link.txt" ] || ln -sfn "$(<"${backup_dir}/domain-bootstrap-link.txt")" "$domain_bootstrap_enabled"
    [ ! -f "${backup_dir}/default.conf" ] || cp -a "${backup_dir}/default.conf" "$default_target"
    [ ! -f "${backup_dir}/default-link.txt" ] || ln -sfn "$(<"${backup_dir}/default-link.txt")" "$default_enabled"
    [ ! -f "${backup_dir}/legacy-default-link.txt" ] || ln -sfn "$(<"${backup_dir}/legacy-default-link.txt")" "$legacy_default_enabled"
}

cutover_changed=false
cutover_complete=false
temporary_target=""
temporary_marker=""
rollback_incomplete_cutover() {
    local status=$?
    trap - EXIT INT TERM
    rm -f "${temporary_target:-}" "${temporary_marker:-}"
    if [ "$status" -ne 0 ] && [ "$cutover_changed" = true ] && [ "$cutover_complete" = false ]; then
        restore_previous_nginx
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
        rm -f "${STATE_DIR}/public-cutover-passed"
        printf '[smart-gov] ERROR: IP HTTPS cutover was interrupted; prior Nginx state restoration was attempted.\n' >&2
    fi
    exit "$status"
}

verify_served_ip_certificate() {
    local expected_fingerprint served_fingerprint temporary_served
    temporary_served="$(mktemp)"
    expected_fingerprint="$(openssl x509 -in "$live_cert" -noout -sha256 -fingerprint)"
    if ! timeout 10 openssl s_client -connect 127.0.0.1:443 -noservername -showcerts </dev/null 2>/dev/null |
        openssl x509 -outform PEM >"$temporary_served"; then
        rm -f "$temporary_served"
        return 1
    fi
    served_fingerprint="$(openssl x509 -in "$temporary_served" -noout -sha256 -fingerprint)"
    rm -f "$temporary_served"
    [ "$expected_fingerprint" = "$served_fingerprint" ]
}

temporary_target="$(mktemp /etc/nginx/sites-available/.smart-gov-assistant.conf.XXXXXX)"
sed "s/__PUBLIC_IPV4__/${public_ipv4}/g" \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-ip-https.conf.template" >"$temporary_target"
chmod 644 "$temporary_target"
trap rollback_incomplete_cutover EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cutover_changed=true
mv -fT "$temporary_target" "$target"
temporary_target=""
ln -sfn "$target" "$enabled"
rm -f "$ip_bootstrap_enabled" "$domain_bootstrap_enabled" "$default_enabled" "$legacy_default_enabled"

if ! nginx -t || ! systemctl reload nginx || ! verify_served_ip_certificate; then
    restore_previous_nginx
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    die "IP HTTPS Nginx activation failed; complete prior Nginx state was restored."
fi

rm -f "${STATE_DIR}/public-cutover-passed"
if ! "${SCRIPT_DIR}/verify-public-cutover.sh" \
    --public-ipv4 "$public_ipv4" --public-base "https://${public_ipv4}"; then
    restore_previous_nginx
    nginx -t
    systemctl reload nginx
    rm -f "${STATE_DIR}/public-cutover-passed"
    die "Public HTTPS verification failed; complete prior Nginx state was restored."
fi

umask 077
temporary_marker="$(mktemp "${STATE_DIR}/.ip-nginx-cutover.XXXXXX")"
{
    printf 'release_tag=%s\n' "$current_release"
    printf 'public_ipv4=%s\n' "$public_ipv4"
    printf 'backup_dir=%s\n' "$backup_dir"
    printf 'cutover_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" "${STATE_DIR}/ip-nginx-cutover"
temporary_marker=""
cutover_complete=true
trap - EXIT INT TERM
log "Verified IP HTTPS traffic now targets release ${current_release} on 127.0.0.1:18000; legacy services remain online."
