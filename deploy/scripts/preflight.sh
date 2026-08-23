#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

domain="${SMART_GOV_DOMAIN:-}"
public_ipv4="${PUBLIC_IPV4:-}"
security_group_confirmed="${HTTPS_SECURITY_GROUP_CONFIRMED:-false}"
minimum_memory_gib="${MINIMUM_MEMORY_GIB:-8}"
minimum_disk_gib="${MINIMUM_DISK_GIB:-20}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --public-ipv4) public_ipv4="${2:-}"; shift 2 ;;
        --https-security-group-confirmed) security_group_confirmed=true; shift ;;
        --minimum-memory-gib) minimum_memory_gib="${2:-}"; shift 2 ;;
        --minimum-disk-gib) minimum_disk_gib="${2:-}"; shift 2 ;;
        *) die "Unknown preflight option: $1" ;;
    esac
done

failures=0
fail() {
    printf '[preflight] FAIL: %s\n' "$*" >&2
    failures=$((failures + 1))
}
pass() {
    printf '[preflight] PASS: %s\n' "$*"
}
info() {
    printf '[preflight] INFO: %s\n' "$*"
}

if [ "$(uname -s)" != "Linux" ]; then
    fail "Cloud deployment requires Linux."
else
    pass "Linux host detected."
fi

case "$(uname -m)" in
    x86_64|amd64) pass "Supported x86_64 architecture detected." ;;
    *) fail "This deployment has only been qualified on x86_64." ;;
esac

memory_kib="$(awk '/^MemTotal:/{print $2}' /proc/meminfo)"
available_kib="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
required_memory_kib=$((minimum_memory_gib * 1024 * 1024))
if [ "$memory_kib" -lt "$required_memory_kib" ]; then
    fail "MemTotal is below ${minimum_memory_gib} GiB; Docker installation and stack startup are blocked."
else
    pass "MemTotal satisfies the ${minimum_memory_gib} GiB gate."
fi
info "MemAvailable is $((available_kib / 1024)) MiB."

available_disk_kib="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2{print $4}')"
required_disk_kib=$((minimum_disk_gib * 1024 * 1024))
if [ "$available_disk_kib" -lt "$required_disk_kib" ]; then
    fail "Available disk is below ${minimum_disk_gib} GiB."
else
    pass "Available disk satisfies the ${minimum_disk_gib} GiB gate."
fi

if [ -n "$domain" ]; then
    if [[ ! "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || [[ "$domain" != *.* ]]; then
        fail "When supplied, --domain must be a valid DNS hostname."
    fi
else
    info "No DNS hostname supplied; raw-IPv4 HTTPS provisioning may be used."
fi
if ! validate_ipv4 "$public_ipv4"; then
    fail "The server public IPv4 must be supplied with --public-ipv4."
fi

if [ -n "$domain" ] && [ -n "$public_ipv4" ]; then
    resolved_ipv4="$(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u || true)"
    if grep -Fxq "$public_ipv4" <<<"$resolved_ipv4"; then
        pass "DNS A record resolves to the supplied server IPv4."
    else
        fail "DNS does not resolve to the supplied server IPv4."
    fi
fi

if [ "$security_group_confirmed" != "true" ]; then
    fail "Cloud security-group ingress for TCP 443 must be explicitly confirmed."
else
    pass "Operator confirmed cloud security-group ingress for TCP 443."
fi

if ss -H -ltn '( sport = :18000 )' 2>/dev/null | grep -q .; then
    if command -v docker >/dev/null 2>&1 &&
        docker ps --format '{{.Ports}}' 2>/dev/null | grep -q '127.0.0.1:18000->8000'; then
        info "Port 18000 is already owned by the cloud demo stack."
    else
        fail "Loopback port 18000 is already occupied by another process."
    fi
else
    pass "Loopback port 18000 is available for the new API."
fi

if systemctl is-active --quiet ai-companion-api.service 2>/dev/null; then
    info "Legacy ai-companion-api.service is active and was not changed."
fi
if systemctl is-active --quiet ai-companion-guides.timer 2>/dev/null; then
    info "Legacy ai-companion-guides.timer is active and was not changed."
fi

if command -v docker >/dev/null 2>&1; then
    info "Docker is installed: $(docker --version 2>/dev/null || true)"
else
    info "Docker is not installed. Run install-docker.sh only after this preflight passes."
fi

if [ "$failures" -ne 0 ]; then
    printf '[preflight] BLOCKED: %d deployment gate(s) failed. No service was modified.\n' "$failures" >&2
    exit 2
fi

printf '[preflight] READY: infrastructure installation may proceed.\n'
