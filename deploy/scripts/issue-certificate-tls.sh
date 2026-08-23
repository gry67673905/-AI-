#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command openssl
require_command ss
require_command systemctl

lego_bin=/usr/local/bin/lego-v5
[ -x "$lego_bin" ] || die "Pinned lego v5 binary is unavailable."
[ ! -L "$lego_bin" ] || die "Pinned lego v5 binary must not be a symbolic link."
"$lego_bin" --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "Pinned lego binary is not version 5.4.0."

domain="${SMART_GOV_DOMAIN:-}"
email="${LEGO_EMAIL:-}"
public_ipv4="${PUBLIC_IPV4:-}"
security_group_confirmed="${HTTPS_SECURITY_GROUP_CONFIRMED:-false}"
staging=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --email) email="${2:-}"; shift 2 ;;
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --https-security-group-confirmed) security_group_confirmed=true; shift ;;
        --staging) staging=true; shift ;;
        *) die "Unknown TLS-ALPN certificate option: $1" ;;
    esac
done

[[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] ||
    die "Invalid domain."
if [ -n "$email" ] && [[ ! "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    die "The supplied ACME email is invalid."
fi

preflight_args=(--domain "$domain" --public-ipv4 "$public_ipv4")
if [ "$security_group_confirmed" = true ]; then
    preflight_args+=(--https-security-group-confirmed)
fi
"${SCRIPT_DIR}/preflight.sh" "${preflight_args[@]}"

if ss -H -ltn '( sport = :443 )' | grep -q .; then
    die "Initial TLS-ALPN issuance requires local TCP 443 to be free; no service was stopped."
fi

if [ "$staging" = true ]; then
    acme_server=https://acme-staging-v02.api.letsencrypt.org/directory
    lego_path=/etc/lego-smart-gov/staging
else
    acme_server=https://acme-v02.api.letsencrypt.org/directory
    lego_path=/etc/lego-smart-gov/production
fi
install -d -m 700 /etc/lego-smart-gov "$lego_path"

config_path="${lego_path}/.lego.yml"
temporary_config="$(mktemp "${lego_path}/.lego.yml.XXXXXX")"
{
    printf 'storage: %s\n' "$lego_path"
    printf 'networkStack: ipv4only\n'
    printf 'accounts:\n'
    printf '  smart-gov:\n'
    printf '    server: %s\n' "$acme_server"
    if [ -n "$email" ]; then
        printf '    email: %s\n' "$email"
    fi
    printf '    acceptsTermsOfService: true\n'
    printf 'challenges:\n'
    printf '  tls-443:\n'
    printf '    tls:\n'
    printf '      address: ":443"\n'
    printf 'certificates:\n'
    printf '  smart-gov-api:\n'
    printf '    account: smart-gov\n'
    printf '    challenge: tls-443\n'
    printf '    domains:\n'
    printf '      - %s\n' "$domain"
    printf '    renew:\n'
    printf '      days: 30\n'
    printf '      disableRandomSleep: true\n'
    printf '      ari:\n'
    printf '        disable: true\n'
} >"$temporary_config"
install -m 600 "$temporary_config" "$config_path"
rm -f "$temporary_config"

log "Starting a standalone TLS-ALPN-01 challenge on TCP 443."
"$lego_bin" --config "$config_path"

source_cert="${lego_path}/certificates/smart-gov-api.crt"
source_key="${lego_path}/certificates/smart-gov-api.key"
[ -s "$source_cert" ] || die "lego did not create the expected certificate."
[ -s "$source_key" ] || die "lego did not create the expected private key."
openssl x509 -in "$source_cert" -noout -checkhost "$domain" >/dev/null ||
    die "Issued certificate does not cover the requested domain."
openssl x509 -in "$source_cert" -noout -checkend 259200 >/dev/null ||
    die "Issued certificate expires too soon."
cert_public_key="$(openssl x509 -in "$source_cert" -pubkey -noout |
    openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk '{print $1}')"
private_public_key="$(openssl pkey -in "$source_key" -pubout -outform DER 2>/dev/null |
    sha256sum | awk '{print $1}')"
[ "$cert_public_key" = "$private_public_key" ] ||
    die "Issued certificate and private key do not match."

if [ "$staging" = true ]; then
    log "TLS-ALPN staging validation succeeded; no trusted certificate or routing was changed."
    exit 0
fi

live_dir="/etc/letsencrypt/live/${domain}"
[ ! -L "$live_dir" ] || die "Refusing to replace a symbolic-link certificate directory."
install -d -m 700 "$live_dir"
install -d -m 700 /var/backups/smart-gov-cert
had_live_pair=false
if [ -e "${live_dir}/fullchain.pem" ] && [ -e "${live_dir}/privkey.pem" ]; then
    had_live_pair=true
    backup_dir="/var/backups/smart-gov-cert/$(utc_stamp)-pre-lego"
    install -d -m 700 "$backup_dir"
    install -m 600 "${live_dir}/fullchain.pem" "${backup_dir}/fullchain.pem"
    install -m 600 "${live_dir}/privkey.pem" "${backup_dir}/privkey.pem"
elif [ -e "${live_dir}/fullchain.pem" ] || [ -e "${live_dir}/privkey.pem" ]; then
    die "Refusing to replace an incomplete existing certificate pair."
fi

temporary_cert="$(mktemp "${live_dir}/.fullchain.pem.XXXXXX")"
temporary_key="$(mktemp "${live_dir}/.privkey.pem.XXXXXX")"
live_pair_dirty=false
restore_initial_pair() {
    local status=$?
    trap - EXIT INT TERM
    rm -f "$temporary_cert" "$temporary_key"
    if [ "$status" -ne 0 ] && [ "$live_pair_dirty" = true ]; then
        rm -f "${live_dir}/fullchain.pem" "${live_dir}/privkey.pem"
        if [ "$had_live_pair" = true ]; then
            install -m 644 "${backup_dir}/fullchain.pem" "${live_dir}/fullchain.pem"
            install -m 600 "${backup_dir}/privkey.pem" "${live_dir}/privkey.pem"
        fi
    fi
    exit "$status"
}
trap restore_initial_pair EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
install -m 644 "$source_cert" "$temporary_cert"
install -m 600 "$source_key" "$temporary_key"
live_pair_dirty=true
mv -fT "$temporary_cert" "${live_dir}/fullchain.pem"
mv -fT "$temporary_key" "${live_dir}/privkey.pem"
live_pair_dirty=false
trap - EXIT INT TERM

temporary_domain="$(mktemp /etc/lego-smart-gov/.domain.XXXXXX)"
printf '%s\n' "$domain" >"$temporary_domain"
install -m 600 "$temporary_domain" /etc/lego-smart-gov/domain
rm -f "$temporary_domain"
install -m 755 "${SCRIPT_DIR}/renew-certificate-tls.sh" \
    /usr/local/sbin/smart-gov-renew-tls
install -m 644 "${PROJECT_ROOT}/deploy/systemd/smart-gov-cert-renew.service" \
    /etc/systemd/system/smart-gov-cert-renew.service
install -m 644 "${PROJECT_ROOT}/deploy/systemd/smart-gov-cert-renew.timer" \
    /etc/systemd/system/smart-gov-cert-renew.timer
systemctl daemon-reload
systemctl enable --now smart-gov-cert-renew.timer

log "Trusted TLS certificate installed for ${domain}; automated renewal is enabled."
log "Nginx routing was not changed and the legacy HTTP service remained online."
