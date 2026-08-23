#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
"${SCRIPT_DIR}/preflight.sh" "$@"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
temporary_key="$(mktemp)"
trap 'rm -f "$temporary_key"' EXIT
curl -4 --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors \
    https://download.docker.com/linux/ubuntu/gpg -o "$temporary_key"
gpg --show-keys "$temporary_key" >/dev/null
install -m 0644 "$temporary_key" /etc/apt/keyrings/docker.asc

# shellcheck disable=SC1091
. /etc/os-release
docker_arch="$(dpkg --print-architecture)"
printf '%s\n' \
    "deb [arch=${docker_arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    >/etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

docker version --format 'Docker client {{.Client.Version}}, server {{.Server.Version}}'
docker compose version
log "Docker installation completed. Nginx, ACME configuration and legacy application units were not changed."
