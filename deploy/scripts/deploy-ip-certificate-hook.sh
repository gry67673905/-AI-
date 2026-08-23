#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '[smart-gov-ip-cert] %s\n' "$*"
}

die() {
    printf '[smart-gov-ip-cert] ERROR: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "The IP certificate deploy hook must run as root."
for command_name in awk date flock install mktemp nginx openssl readlink sed sha256sum systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || die "Required deploy-hook command is unavailable: ${command_name}"
done

if [ "${SMART_GOV_IP_CERT_LOCK_HELD:-}" != 1 ]; then
    install -d -o root -g root -m 755 /run/lock
    exec 9>/run/lock/smart-gov-ip-cert.lock
    flock -n 9 || die "Another IP certificate deployment operation is already running."
fi

ip_file=/etc/lego-smart-gov/ip-address
[ -s "$ip_file" ] && [ ! -L "$ip_file" ] || die "Stored IP certificate identity is missing or unsafe."
public_ipv4="$(<"$ip_file")"
[[ "$public_ipv4" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "Stored IP certificate identity is invalid."

expected_cert=/etc/lego-smart-gov/production-ip/certificates/smart-gov-ip.crt
expected_key=/etc/lego-smart-gov/production-ip/certificates/smart-gov-ip.key
source_cert="${LEGO_HOOK_CERT_PATH:-$expected_cert}"
source_key="${LEGO_HOOK_CERT_KEY_PATH:-$expected_key}"
[ "$source_cert" = "$expected_cert" ] || die "Deploy hook received an unexpected certificate path."
[ "$source_key" = "$expected_key" ] || die "Deploy hook received an unexpected private-key path."
[ -s "$source_cert" ] && [ ! -L "$source_cert" ] || die "Renewed certificate source is missing or unsafe."
[ -s "$source_key" ] && [ ! -L "$source_key" ] || die "Renewed private-key source is missing or unsafe."

openssl x509 -in "$source_cert" -noout -checkip "$public_ipv4" >/dev/null ||
    die "Certificate does not contain the required IP subjectAltName."
openssl x509 -in "$source_cert" -noout -checkend 259200 >/dev/null ||
    die "Certificate has fewer than three days remaining."
not_before="$(openssl x509 -in "$source_cert" -noout -startdate | sed 's/^notBefore=//')"
not_after="$(openssl x509 -in "$source_cert" -noout -enddate | sed 's/^notAfter=//')"
lifetime_seconds=$(( $(date -u -d "$not_after" +%s) - $(date -u -d "$not_before" +%s) ))
[ "$lifetime_seconds" -ge 345600 ] || die "Certificate lifetime is unexpectedly shorter than four days."
[ "$lifetime_seconds" -le 691200 ] || die "Certificate is not a short-lived profile certificate."
cert_public_key="$(openssl x509 -in "$source_cert" -pubkey -noout |
    openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
private_public_key="$(openssl pkey -in "$source_key" -pubout -outform DER 2>/dev/null |
    sha256sum | awk '{print $1}')"
[ "$cert_public_key" = "$private_public_key" ] || die "Certificate and private key do not match."

live_dir="/etc/letsencrypt/live/${public_ipv4}"
[ ! -L "$live_dir" ] || die "Live IP certificate directory must not be a symbolic link."
install -d -o root -g root -m 700 "$live_dir" /var/backups/smart-gov-cert
had_live_pair=false
if [ -e "${live_dir}/fullchain.pem" ] && [ -e "${live_dir}/privkey.pem" ]; then
    had_live_pair=true
    backup_dir="/var/backups/smart-gov-cert/$(date -u +%Y%m%dT%H%M%SZ)-ip-deploy"
    install -d -o root -g root -m 700 "$backup_dir"
    install -m 644 "${live_dir}/fullchain.pem" "${backup_dir}/fullchain.pem"
    install -m 600 "${live_dir}/privkey.pem" "${backup_dir}/privkey.pem"
elif [ -e "${live_dir}/fullchain.pem" ] || [ -e "${live_dir}/privkey.pem" ]; then
    die "Refusing to replace an incomplete live certificate pair."
fi

temporary_cert="$(mktemp "${live_dir}/.fullchain.pem.XXXXXX")"
temporary_key="$(mktemp "${live_dir}/.privkey.pem.XXXXXX")"
pair_dirty=false
restore_pair() {
    local status=$?
    trap - EXIT INT TERM
    rm -f "$temporary_cert" "$temporary_key"
    if [ "$status" -ne 0 ] && [ "$pair_dirty" = true ]; then
        rm -f "${live_dir}/fullchain.pem" "${live_dir}/privkey.pem"
        if [ "$had_live_pair" = true ]; then
            install -m 644 "${backup_dir}/fullchain.pem" "${live_dir}/fullchain.pem"
            install -m 600 "${backup_dir}/privkey.pem" "${live_dir}/privkey.pem"
        fi
        nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap restore_pair EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

install -m 644 "$source_cert" "$temporary_cert"
install -m 600 "$source_key" "$temporary_key"
pair_dirty=true
mv -fT "$temporary_cert" "${live_dir}/fullchain.pem"
mv -fT "$temporary_key" "${live_dir}/privkey.pem"
nginx -t
systemctl reload nginx
pair_dirty=false
trap - EXIT INT TERM

temporary_marker="$(mktemp /etc/lego-smart-gov/.ip-deployed.XXXXXX)"
{
    printf 'public_ipv4=%s\n' "$public_ipv4"
    printf 'profile=shortlived\n'
    printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"$temporary_marker"
chmod 600 "$temporary_marker"
mv -fT "$temporary_marker" /etc/lego-smart-gov/ip-deployed
log "Short-lived IP certificate deployed and Nginx safely reloaded."
