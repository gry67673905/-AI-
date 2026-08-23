#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command nginx
require_command certbot
require_command curl

domain="${SMART_GOV_DOMAIN:-}"
email="${CERTBOT_EMAIL:-}"
public_ipv4="${PUBLIC_IPV4:-}"
security_group_confirmed="${HTTPS_SECURITY_GROUP_CONFIRMED:-false}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --email) email="${2:-}"; shift 2 ;;
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --https-security-group-confirmed) security_group_confirmed=true; shift ;;
        *) die "Unknown certificate option: $1" ;;
    esac
done

if [ -n "$email" ] && [[ ! "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
    die "The supplied Certbot email is invalid."
fi
preflight_args=(--domain "$domain" --public-ipv4 "$public_ipv4")
if [ "$security_group_confirmed" = true ]; then
    preflight_args+=(--https-security-group-confirmed)
fi
"${SCRIPT_DIR}/preflight.sh" "${preflight_args[@]}"

install -d -m 755 /var/www/certbot
bootstrap_target=/etc/nginx/sites-available/smart-gov-bootstrap.conf
sed "s/__DOMAIN__/${domain}/g" \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-bootstrap.conf.template" >"$bootstrap_target"
chmod 644 "$bootstrap_target"
ln -sfn "$bootstrap_target" /etc/nginx/sites-enabled/smart-gov-bootstrap.conf

certbot_config=/etc/letsencrypt/smart-gov-cli.ini
install -m 600 "${PROJECT_ROOT}/deploy/certbot/cli.ini.template" "$certbot_config"
if [ -n "$email" ]; then
    printf 'email = %s\n' "$email" >>"$certbot_config"
fi
chmod 600 "$certbot_config"

nginx -t
systemctl reload nginx

challenge_token="smart-gov-preflight-$(date +%s)"
challenge_dir=/var/www/certbot/.well-known/acme-challenge
install -d -m 755 "$challenge_dir"
printf '%s' "$challenge_token" >"${challenge_dir}/${challenge_token}"
trap 'rm -f "${challenge_dir}/${challenge_token}"' EXIT
challenge_response="$(curl --fail --silent --show-error --max-time 15 \
    "http://${domain}/.well-known/acme-challenge/${challenge_token}")"
[ "$challenge_response" = "$challenge_token" ] || die "Public ACME HTTP-01 path verification failed."

certbot_args=(certonly --config "$certbot_config" -d "$domain")
if [ -z "$email" ]; then
    certbot_args+=(--register-unsafely-without-email --agree-tos --non-interactive)
fi
certbot "${certbot_args[@]}"
install -m 755 "${PROJECT_ROOT}/deploy/certbot/nginx-renew-hook.sh" \
    /etc/letsencrypt/renewal-hooks/deploy/smart-gov-nginx.sh

log "TLS certificate is available for ${domain}."
log "Bootstrap routing still targets the legacy API; no application cutover occurred."
