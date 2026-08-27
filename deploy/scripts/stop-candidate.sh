#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command docker
require_command flock
require_command nginx

install -d -o root -g root -m 755 /run/lock
# Take the traffic lock first so cutover and candidate cleanup cannot race.
exec 8>/run/lock/smart-gov-cutover.lock
flock -n 8 || die "Another cutover or legacy-retirement operation is already running."
exec 9>/run/lock/smart-gov-candidate.lock
flock -n 9 || die "Another candidate deployment operation is already running."

# Inspect the loaded configuration, not merely a template or marker. A stale
# stop command must never remove the API currently serving public traffic.
nginx_configuration="$(nginx -T 2>/dev/null)" ||
    die "Unable to inspect the active Nginx configuration before stopping the candidate."
if grep -Fq 'proxy_pass http://127.0.0.1:18001;' <<<"$nginx_configuration"; then
    die "Refusing to stop the candidate while active Nginx traffic still targets port 18001."
fi
unset nginx_configuration

mapfile -t candidate_ids < <(
    docker ps -aq \
        --filter label=com.docker.compose.project=smart-gov-cloud-demo \
        --filter label=com.docker.compose.service=api-candidate
    docker ps -aq \
        --filter label=com.docker.compose.project=smart-gov-cloud-demo \
        --filter label=com.docker.compose.service=material-worker-candidate
)
if [ "${#candidate_ids[@]}" -gt 0 ]; then
    docker stop --time 15 "${candidate_ids[@]}" >/dev/null
    docker rm "${candidate_ids[@]}" >/dev/null
fi
rm -f "${STATE_DIR}/candidate-release"

if ss -H -ltn '( sport = :18001 )' 2>/dev/null | grep -q .; then
    die "Candidate container was removed but loopback port 18001 is still occupied."
fi
log "Parallel API and material-worker candidates were stopped and removed; images, data and canonical services were retained."
