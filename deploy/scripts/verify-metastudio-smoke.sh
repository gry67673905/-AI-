#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

base_url="http://127.0.0.1:18000"
skip_http=false
through_nginx=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base-url) base_url="${2:-}"; shift 2 ;;
        --skip-http) skip_http=true; shift ;;
        --through-nginx) through_nginx=true; shift ;;
        *) die "Unknown MetaStudio smoke option: $1" ;;
    esac
done

require_cloud_files
if metastudio_enabled; then
    require_secrets
fi
require_metastudio_config
require_command python3

grep -Fq -- '--no-access-log' "${PROJECT_ROOT}/deploy/container-secret-entrypoint.sh" ||
    die "Cloud Uvicorn access logging can expose MetaStudio callback query authentication."
for secret_name in \
    metastudio_app_key \
    metastudio_huawei_access_key \
    metastudio_huawei_secret_key; do
    grep -Fq "/tmp/smartgov-app-secrets/${secret_name}" \
        "${PROJECT_ROOT}/deploy/container-secret-entrypoint.sh" ||
        die "MetaStudio secret ${secret_name} is not copied to the non-root API runtime."
done

python3 - \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-ip-https.conf.template" \
    "${PROJECT_ROOT}/deploy/nginx/smart-gov-https.conf.template" <<'PY'
import re
import sys
from pathlib import Path

callback = "/api/v1/integrations/metastudio/llm"
client_sessions = "/api/v1/integrations/metastudio/client-sessions"
for raw_path in sys.argv[1:]:
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    locations = list(re.finditer(
        r"location\s+=\s+" + re.escape(callback) + r"\s*\{(?P<body>.*?)\n\s*\}",
        text,
        flags=re.S,
    ))
    if len(locations) != 1:
        raise SystemExit(f"{path.name}: exact MetaStudio callback location is missing/duplicated")
    body = locations[0].group("body")
    required = (
        "proxy_buffering off;",
        "proxy_cache off;",
        "proxy_set_header Connection \"\";",
        "client_max_body_size 128k;",
        "access_log /var/log/nginx/smart-gov-metastudio-callback.log",
        "error_log /dev/null crit;",
    )
    if any(item not in body for item in required):
        raise SystemExit(f"{path.name}: callback SSE/log hardening is incomplete")

    format_match = re.search(
        r"log_format\s+(?P<name>smartgov_[A-Za-z0-9_]*metastudio_callback)\s+"
        r"(?P<body>.*?);",
        text,
        flags=re.S,
    )
    if format_match is None:
        raise SystemExit(f"{path.name}: dedicated callback log format is missing")
    tokens = set(re.findall(r"\$[A-Za-z0-9_]+", format_match.group("body")))
    forbidden = {"$args", "$query_string", "$request", "$request_uri"}
    if tokens & forbidden:
        raise SystemExit(f"{path.name}: callback log format can expose query authentication")
    if "$uri" not in tokens:
        raise SystemExit(f"{path.name}: callback log must retain the normalized path")

    rate_limit_locations = list(re.finditer(
        r"location\s+@rate_limit_json\s*\{(?P<body>.*?)\n\s*\}",
        text,
        flags=re.S,
    ))
    if len(rate_limit_locations) != 1:
        raise SystemExit(f"{path.name}: shared structured 429 location is missing/duplicated")
    rate_body = rate_limit_locations[0].group("body")
    if (
        f"smart-gov-rate-limit.log {format_match.group('name')};" not in rate_body
        or "error_log /dev/null crit;" not in rate_body
    ):
        raise SystemExit(f"{path.name}: 429 internal redirect can expose callback query authentication")

    sessions = list(re.finditer(
        r"location\s+=\s+" + re.escape(client_sessions) + r"\s*\{(?P<body>.*?)\n\s*\}",
        text,
        flags=re.S,
    ))
    if len(sessions) != 1:
        raise SystemExit(f"{path.name}: exact MetaStudio client-session location is missing/duplicated")
    session_body = sessions[0].group("body")
    if (
        "client_max_body_size 4k;" not in session_body
        or not re.search(r"limit_req\s+zone=smartgov_(?:ip_)?metastudio_sessions\s+burst=3\s+nodelay;", session_body)
    ):
        raise SystemExit(f"{path.name}: client-session body/rate limit is not pinned")
    if not re.search(
        r"limit_req_zone\s+\$binary_remote_addr\s+"
        r"zone=smartgov_(?:ip_)?metastudio_sessions:10m\s+rate=1r/s;",
        text,
    ):
        raise SystemExit(f"{path.name}: client-session 1r/s IP zone is missing")

    exposed = set(re.findall(
        r"location\s+=\s+(/api/v1/integrations/metastudio/[^\s{]+)", text
    ))
    if exposed != {callback, client_sessions}:
        raise SystemExit(f"{path.name}: unexpected MetaStudio Nginx route is exposed")
PY

if [ "$skip_http" = true ]; then
    log "MetaStudio static smoke passed; no HTTP or Huawei Cloud request was made."
    exit 0
fi

require_command curl
python3 - "$base_url" <<'PY'
import sys
from urllib.parse import urlsplit

value = urlsplit(sys.argv[1])
if value.scheme not in {"http", "https"} or not value.hostname:
    raise SystemExit("MetaStudio smoke base URL must be an HTTP(S) origin.")
if value.username is not None or value.password is not None or value.query or value.fragment:
    raise SystemExit("MetaStudio smoke base URL must not contain credentials, query or fragment.")
if value.path not in {"", "/"}:
    raise SystemExit("MetaStudio smoke base URL must not contain a path.")
PY

base_url="${base_url%/}"
request_status() {
    curl --noproxy '*' --silent --show-error \
        --output /dev/null --write-out '%{http_code}' --max-time 15 "$@"
}

# Missing MSS_A query authentication is rejected before consultation, LLM,
# RAG or any Huawei Cloud call. No response body is printed.
callback_status="$(request_status \
    --request POST \
    --header 'Content-Type: application/json' \
    --data '{"messages":[{"content":"synthetic smoke"}],"app_id":"smoke","user":"smoke","session_id":"smoke","is_stream":true}' \
    "${base_url}/api/v1/integrations/metastudio/llm")"
[ "$callback_status" = 400 ] || die "Unauthenticated MetaStudio callback was not rejected with 400."

# Exchange requires an application bearer token; the fixed synthetic ID can
# never trigger a provider request without authentication.
exchange_status="$(request_status \
    --request POST \
    --header 'Content-Type: application/json' \
    --data '{"session_id":"00000000-0000-0000-0000-000000000000","chat_id":"smoke"}' \
    "${base_url}/api/v1/integrations/metastudio/action-intents/00000000-0000-0000-0000-000000000000/exchange")"
[ "$exchange_status" = 401 ] || die "Unauthenticated action exchange was not rejected with 401."

if ! metastudio_enabled; then
    session_status="$(request_status \
        --request POST \
        --header 'Content-Type: application/json' \
        --data '{}' \
        "${base_url}/api/v1/integrations/metastudio/client-sessions")"
    [ "$session_status" = 503 ] || die "Disabled MetaStudio client session was not rejected with 503."
fi

if [ "$through_nginx" = true ]; then
    [[ "$base_url" == https://* ]] || die "--through-nginx requires an HTTPS base URL."
    require_root
    callback_log=/var/log/nginx/smart-gov-metastudio-callback.log
    [ -e "$callback_log" ] || die "Dedicated MetaStudio callback access log does not exist."
    [ ! -L "$callback_log" ] || die "Dedicated MetaStudio callback access log must not be a symlink."
    before_size="$(stat -c '%s' "$callback_log")"
    fake_secret=7c74c7e52b944ed8ae835ef2ad870b2552599606f533454daa79fa1c663c8e31
    fake_time=18f000000000
    runtime_status="$(request_status \
        --request POST \
        --header 'Content-Type: application/json' \
        --data '{"messages":[{"content":"synthetic smoke"}],"app_id":"smoke","user":"smoke","session_id":"smoke","is_stream":false}' \
        "${base_url}/api/v1/integrations/metastudio/llm?secret=${fake_secret}&time_stamp=${fake_time}")"
    [ "$runtime_status" = 400 ] || die "Synthetic invalid callback was not rejected with 400."
    new_log="$(tail -c "+$((before_size + 1))" "$callback_log")"
    [[ "$new_log" == *"uri=/api/v1/integrations/metastudio/llm"* ]] ||
        die "MetaStudio callback request was not observed in the dedicated access log."
    [[ "$new_log" != *"$fake_secret"* && "$new_log" != *"time_stamp"* ]] ||
        die "MetaStudio callback access log exposed query authentication."
    unset fake_secret fake_time new_log
fi

log "MetaStudio zero-cost smoke passed; Huawei Cloud calls=0 and response bodies were not printed."
