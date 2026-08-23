#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_root
require_command awk
require_command sha256sum
require_command tar
require_command install

archive=""
checksums=""
confirmed=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --archive) archive="${2:-}"; shift 2 ;;
        --checksums) checksums="${2:-}"; shift 2 ;;
        --confirm-install) confirmed=true; shift ;;
        *) die "Unknown lego installer option: $1" ;;
    esac
done

[ "$confirmed" = true ] || die "Pass --confirm-install after reviewing the pinned release."
[ -f "$archive" ] && [ ! -L "$archive" ] || die "The lego release archive is missing or unsafe."
[ -f "$checksums" ] && [ ! -L "$checksums" ] || die "The lego checksum manifest is missing or unsafe."

manifest_sha=42b78c70371e7a71c9a8b1e5a75fb6bb33faf16e5408a02e7c0b4f4dff3edca8
asset_name=lego_v5.4.0_linux_amd64.tar.gz
actual_manifest_sha="$(sha256sum "$checksums" | awk '{print $1}')"
[ "$actual_manifest_sha" = "$manifest_sha" ] || die "The official checksum manifest digest does not match the pinned value."

expected_archive_sha="$(awk -v name="$asset_name" '$2 == name { print $1 }' "$checksums")"
[[ "$expected_archive_sha" =~ ^[0-9a-f]{64}$ ]] || die "The release archive is absent from the official checksum manifest."
actual_archive_sha="$(sha256sum "$archive" | awk '{print $1}')"
[ "$actual_archive_sha" = "$expected_archive_sha" ] || die "The release archive digest does not match the official manifest."

while IFS= read -r archive_member; do
    [ -n "$archive_member" ] || die "The verified release archive contains an empty member name."
    case "$archive_member" in
        /*) die "The verified release archive contains an absolute path." ;;
    esac
    IFS='/' read -r -a path_parts <<<"$archive_member"
    for path_part in "${path_parts[@]}"; do
        [ "$path_part" != ".." ] || die "The verified release archive contains a parent-directory traversal."
    done
done < <(tar -tzf "$archive")

temporary_dir="$(mktemp -d /tmp/lego-v5-install.XXXXXX)"
cleanup() {
    case "$temporary_dir" in
        /tmp/lego-v5-install.*) rm -rf -- "$temporary_dir" ;;
        *) printf '[smart-gov] ERROR: Refusing to remove an unexpected temporary path.\n' >&2 ;;
    esac
}
trap cleanup EXIT INT TERM
tar -xzf "$archive" -C "$temporary_dir"
[ -x "${temporary_dir}/lego" ] || die "The verified release archive does not contain the lego binary."
"${temporary_dir}/lego" --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "The verified release binary does not report version 5.4.0."
source_binary_sha="$(sha256sum "${temporary_dir}/lego" | awk '{print $1}')"

install -o root -g root -m 755 "${temporary_dir}/lego" /usr/local/bin/lego-v5
[ ! -L /usr/local/bin/lego-v5 ] || die "Installed lego binary unexpectedly became a symbolic link."
installed_binary_sha="$(sha256sum /usr/local/bin/lego-v5 | awk '{print $1}')"
[ "$installed_binary_sha" = "$source_binary_sha" ] || die "Installed lego binary digest differs from the verified source."
/usr/local/bin/lego-v5 --version 2>&1 | grep -Eq 'version[[:space:]]+5\.4\.0([[:space:]]|$)' ||
    die "Installed lego binary failed its version check."

log "Verified lego v5.4.0 installed independently as /usr/local/bin/lego-v5."
