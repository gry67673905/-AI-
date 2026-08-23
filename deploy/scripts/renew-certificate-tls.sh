#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '[smart-gov-cert] %s\n' "$*"
}

die() {
    printf '[smart-gov-cert] ERROR: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Run certificate renewal as root."
for command_name in nginx openssl sha256sum ss systemctl; do
    command -v "$command_name" >/dev/null 2>&1 ||
        die "Required renewal command is unavailable: ${command_name}"
done

lego_bin=/usr/local/bin/lego-v5
[ -x "$lego_bin" ] || die "Pinned lego v5 binary is unavailable."
[ ! -L "$lego_bin" ] || die "Pinned lego v5 binary must not be a symbolic link."
"$lego_bin" --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "Pinned lego binary is not version 5.4.0."

domain_file=/etc/lego-smart-gov/domain
[ -s "$domain_file" ] || die "Certificate domain state is missing."
[ ! -L "$domain_file" ] || die "Certificate domain state must not be a symbolic link."
domain="$(<"$domain_file")"
[[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] ||
    die "Stored certificate domain is invalid."

lego_path=/etc/lego-smart-gov/production
config_path="${lego_path}/.lego.yml"
source_cert="${lego_path}/certificates/smart-gov-api.crt"
source_key="${lego_path}/certificates/smart-gov-api.key"
live_dir="/etc/letsencrypt/live/${domain}"
[ -s "$config_path" ] || die "lego v5 configuration is missing."
[ ! -L "$config_path" ] || die "lego v5 configuration must not be a symbolic link."
[ -s "$source_cert" ] || die "lego certificate state is missing."
[ -s "$source_key" ] || die "lego private-key state is missing."
[ -s "${live_dir}/fullchain.pem" ] || die "Live certificate is missing."
[ -s "${live_dir}/privkey.pem" ] || die "Live private key is missing."
[ ! -L "$live_dir" ] || die "Live certificate directory must not be a symbolic link."

if openssl x509 -in "${live_dir}/fullchain.pem" -noout -checkend 2592000 >/dev/null; then
    log "Certificate has more than 30 days remaining; no listener was stopped."
    exit 0
fi

backup_dir="/var/backups/smart-gov-cert/$(date -u +%Y%m%dT%H%M%SZ)-renew"
install -d -m 700 "$backup_dir"
install -m 600 "${live_dir}/fullchain.pem" "${backup_dir}/fullchain.pem"
install -m 600 "${live_dir}/privkey.pem" "${backup_dir}/privkey.pem"

nginx_was_active=false
certificate_replaced=false
restore_and_restart() {
    local status=$?
    trap - EXIT INT TERM
    if [ "$status" -ne 0 ] && [ "$certificate_replaced" = true ]; then
        install -m 644 "${backup_dir}/fullchain.pem" "${live_dir}/fullchain.pem"
        install -m 600 "${backup_dir}/privkey.pem" "${live_dir}/privkey.pem"
    fi
    rm -f "${temporary_cert:-}" "${temporary_key:-}"
    if [ "$nginx_was_active" = true ]; then
        if ! nginx -t; then
            install -m 644 "${backup_dir}/fullchain.pem" "${live_dir}/fullchain.pem"
            install -m 600 "${backup_dir}/privkey.pem" "${live_dir}/privkey.pem"
            nginx -t || true
        fi
        if ! systemctl start nginx; then
            printf '[smart-gov-cert] ERROR: Nginx could not be restored after renewal.\n' >&2
            status=1
        fi
    fi
    exit "$status"
}
trap restore_and_restart EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if systemctl is-active --quiet nginx; then
    nginx -t
    nginx_was_active=true
    systemctl stop nginx
fi
if ss -H -ltn '( sport = :443 )' | grep -q .; then
    die "TCP 443 is still occupied after Nginx stopped."
fi

log "Running a timer-randomized TLS-ALPN renewal check."
"$lego_bin" --config "$config_path"

openssl x509 -in "$source_cert" -noout -checkhost "$domain" >/dev/null ||
    die "Renewed certificate does not cover the configured domain."
openssl x509 -in "$source_cert" -noout -checkend 259200 >/dev/null ||
    die "Renewed certificate expires too soon."
cert_public_key="$(openssl x509 -in "$source_cert" -pubkey -noout |
    openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
private_public_key="$(openssl pkey -in "$source_key" -pubout -outform DER 2>/dev/null |
    sha256sum | awk '{print $1}')"
[ "$cert_public_key" = "$private_public_key" ] ||
    die "Renewed certificate and private key do not match."

temporary_cert="$(mktemp "${live_dir}/.fullchain.pem.XXXXXX")"
temporary_key="$(mktemp "${live_dir}/.privkey.pem.XXXXXX")"
install -m 644 "$source_cert" "$temporary_cert"
install -m 600 "$source_key" "$temporary_key"
certificate_replaced=true
mv -fT "$temporary_cert" "${live_dir}/fullchain.pem"
mv -fT "$temporary_key" "${live_dir}/privkey.pem"

if [ "$nginx_was_active" = true ]; then
    nginx -t
    systemctl start nginx
    nginx_was_active=false
fi
trap - EXIT INT TERM
log "Certificate renewal check completed and Nginx state was restored."
