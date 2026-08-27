#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '[smart-gov-ip-cert] %s\n' "$*"
}

die() {
    printf '[smart-gov-ip-cert] ERROR: %s\n' "$*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "Run IP certificate renewal as root."
for command_name in flock grep openssl stat systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || die "Required renewal command is unavailable: ${command_name}"
done

install -d -o root -g root -m 755 /run/lock
exec 9>/run/lock/smart-gov-ip-cert.lock
flock -n 9 || die "Another IP certificate issue or renewal operation is already running."
export SMART_GOV_IP_CERT_LOCK_HELD=1

lego_bin=/usr/local/bin/lego-v5
[ -x "$lego_bin" ] && [ ! -L "$lego_bin" ] || die "Pinned lego v5 binary is unavailable or unsafe."
"$lego_bin" --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "Pinned lego binary is not version 5.4.0."

ip_file=/etc/lego-smart-gov/ip-address
config_path=/etc/lego-smart-gov/production-ip/.lego.yml
[ -s "$ip_file" ] && [ ! -L "$ip_file" ] || die "Stored IP identity is missing or unsafe."
[ -s "$config_path" ] && [ ! -L "$config_path" ] || die "Production lego IP configuration is missing or unsafe."
public_ipv4="$(<"$ip_file")"
[[ "$public_ipv4" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "Stored IP identity is invalid."
live_cert="/etc/letsencrypt/live/${public_ipv4}/fullchain.pem"
[ -s "$live_cert" ] || die "Live IP certificate is missing."
challenge_dir=/var/www/smart-gov-acme/.well-known/acme-challenge
[ -d "$challenge_dir" ] && [ ! -L "$challenge_dir" ] ||
    die "HTTP-01 challenge directory is missing or unsafe."
[ "$(stat -c '%U:%G' "$challenge_dir")" = root:root ] ||
    die "HTTP-01 challenge directory ownership is unsafe."
chmod 755 /var/www/smart-gov-acme /var/www/smart-gov-acme/.well-known "$challenge_dir"

if openssl x509 -in "$live_cert" -noout -checkend 259200 >/dev/null; then
    log "IP certificate has more than three days remaining; no renewal was attempted."
    exit 0
fi

log "Running the short-lived IP certificate renewal through the persistent HTTP-01 webroot."
"$lego_bin" --config "$config_path" &
lego_pid=$!
# The service intentionally keeps UMask=0077 so ACME account and certificate
# private keys remain root-only. HTTP-01 token files are public by design,
# however, and Nginx workers must be able to read them. Restrict this watcher
# to root-owned regular files in the dedicated challenge directory; never
# change permissions under the private Lego storage tree.
(
    while kill -0 "$lego_pid" 2>/dev/null; do
        for challenge_file in "$challenge_dir"/*; do
            [ -f "$challenge_file" ] && [ ! -L "$challenge_file" ] || continue
            chmod 644 -- "$challenge_file"
        done
        sleep 0.05
    done
) &
challenge_watcher_pid=$!
if wait "$lego_pid"; then
    lego_status=0
else
    lego_status=$?
fi
wait "$challenge_watcher_pid" || true
[ "$lego_status" -eq 0 ] || exit "$lego_status"
openssl x509 -in "$live_cert" -noout -checkip "$public_ipv4" >/dev/null ||
    die "Deployed renewal does not contain the required IP subjectAltName."
openssl x509 -in "$live_cert" -noout -checkend 259200 >/dev/null ||
    die "Deployed renewal still has fewer than three days remaining."
systemctl is-active --quiet nginx || die "Nginx is not active after certificate renewal."
log "Short-lived IP certificate renewal check completed without stopping Nginx."
