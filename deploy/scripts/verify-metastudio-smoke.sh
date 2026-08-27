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
grep -Fq -- '--ws-max-size 1100000' "${PROJECT_ROOT}/deploy/container-secret-entrypoint.sh" ||
    die "Cloud Uvicorn WebSocket message size is not pinned for document capture."
for secret_name in \
    metastudio_app_key \
    metastudio_huawei_access_key \
    metastudio_huawei_secret_key \
    vision_dashscope_api_key; do
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
vision_sessions = "/api/v1/integrations/metastudio/vision-sessions"
vision_ws = "/api/v1/integrations/metastudio/vision/ws"
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

    for session_path in (client_sessions, vision_sessions):
        sessions = list(re.finditer(
            r"location\s+=\s+" + re.escape(session_path)
            + r"\s*\{(?P<body>.*?)\n\s*\}",
            text,
            flags=re.S,
        ))
        if len(sessions) != 1:
            raise SystemExit(
                f"{path.name}: exact {session_path} location is missing/duplicated"
            )
        session_body = sessions[0].group("body")
        if (
            "client_max_body_size 4k;" not in session_body
            or not re.search(
                r"limit_req\s+zone=smartgov_(?:ip_)?metastudio_sessions"
                r"\s+burst=3\s+nodelay;",
                session_body,
            )
        ):
            raise SystemExit(f"{path.name}: session body/rate limit is not pinned")
    if not re.search(
        r"limit_req_zone\s+\$binary_remote_addr\s+"
        r"zone=smartgov_(?:ip_)?metastudio_sessions:10m\s+rate=1r/s;",
        text,
    ):
        raise SystemExit(f"{path.name}: client-session 1r/s IP zone is missing")

    ws_locations = list(re.finditer(
        r"location\s+=\s+" + re.escape(vision_ws)
        + r"\s*\{(?P<body>.*?)\n\s*\}",
        text,
        flags=re.S,
    ))
    if len(ws_locations) != 1:
        raise SystemExit(f"{path.name}: exact vision WebSocket route is missing/duplicated")
    ws_body = ws_locations[0].group("body")
    ws_required = (
        "proxy_http_version 1.1;",
        "proxy_set_header Upgrade $http_upgrade;",
        'proxy_set_header Connection "upgrade";',
        "proxy_buffering off;",
        "proxy_request_buffering off;",
        "proxy_cache off;",
        "proxy_read_timeout 1900s;",
        "access_log /var/log/nginx/smart-gov-vision-ws.log",
        "error_log /dev/null crit;",
    )
    if any(item not in ws_body for item in ws_required):
        raise SystemExit(f"{path.name}: vision WebSocket hardening is incomplete")
    if not re.search(
        r"limit_conn\s+smartgov_(?:ip_)?vision_ws\s+2;", ws_body
    ):
        raise SystemExit(f"{path.name}: vision WebSocket connection limit is missing")

    ws_format = re.search(
        r"log_format\s+(?P<name>smartgov_(?:ip_)?vision_ws)\s+"
        r"(?P<body>.*?);",
        text,
        flags=re.S,
    )
    if ws_format is None:
        raise SystemExit(f"{path.name}: dedicated vision WebSocket log format is missing")
    ws_tokens = set(re.findall(r"\$[A-Za-z0-9_]+", ws_format.group("body")))
    if ws_tokens & {"$args", "$query_string", "$request", "$request_uri", "$http_authorization"}:
        raise SystemExit(f"{path.name}: vision WebSocket log can expose credentials")
    if "$uri" not in ws_tokens:
        raise SystemExit(f"{path.name}: vision WebSocket log must retain normalized path")

    generic = re.search(r"location\s+/api/\s*\{(?P<body>.*?)\n\s*\}", text, flags=re.S)
    if generic is None or 'proxy_set_header Upgrade "";' not in generic.group("body") \
            or 'proxy_set_header Connection "";' not in generic.group("body"):
        raise SystemExit(f"{path.name}: generic API route must reject WebSocket upgrade forwarding")

    exposed = set(re.findall(
        r"location\s+=\s+(/api/v1/integrations/metastudio/[^\s{]+)", text
    ))
    if exposed != {callback, client_sessions, vision_sessions, vision_ws}:
        raise SystemExit(f"{path.name}: unexpected MetaStudio Nginx route is exposed")
    if "127.0.0.1:18000" in text or "127.0.0.1:18001" in text:
        raise SystemExit(f"{path.name}: Nginx template contains a non-templated upstream")
    if "proxy_pass http://127.0.0.1:__UPSTREAM_PORT__;" not in text:
        raise SystemExit(f"{path.name}: Nginx upstream placeholder is missing")
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

# Anonymous exchange is intentionally permitted only for a live, grounded
# OPEN_SERVICE_NAVIGATION intent. These fixed, well-formed UUIDs cannot match
# a live session or intent and must therefore be concealed as not found.
exchange_status="$(request_status \
    --request POST \
    --header 'Content-Type: application/json' \
    --data '{"session_id":"00000000-0000-0000-0000-000000000000","chat_id":"smoke"}' \
    "${base_url}/api/v1/integrations/metastudio/action-intents/00000000-0000-0000-0000-000000000000/exchange")"
[ "$exchange_status" = 404 ] || die "Unknown anonymous action exchange was not concealed with 404."

vision_session_status="$(request_status \
    --request POST \
    --header 'Content-Type: application/json' \
    --data '{"client_session_id":"00000000-0000-0000-0000-000000000000"}' \
    "${base_url}/api/v1/integrations/metastudio/vision-sessions")"
[ "$vision_session_status" = 401 ] || die "Unauthenticated vision session was not rejected with 401."

vision_ws_status="$(request_status \
    --http1.1 \
    --header 'Connection: Upgrade' \
    --header 'Upgrade: websocket' \
    --header 'Sec-WebSocket-Version: 13' \
    --header 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
    "${base_url}/api/v1/integrations/metastudio/vision/ws")"
[ "$vision_ws_status" = 403 ] || die "Unauthenticated vision WebSocket was not rejected with 403."

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

    vision_log=/var/log/nginx/smart-gov-vision-ws.log
    [ -e "$vision_log" ] || die "Dedicated vision WebSocket access log does not exist."
    [ ! -L "$vision_log" ] || die "Dedicated vision WebSocket access log must not be a symlink."
    before_size="$(stat -c '%s' "$vision_log")"
    auth_sentinel=vision-log-sentinel-do-not-record
    runtime_status="$(request_status \
        --http1.1 \
        --header 'Connection: Upgrade' \
        --header 'Upgrade: websocket' \
        --header 'Sec-WebSocket-Version: 13' \
        --header 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
        --header "Authorization: Bearer ${auth_sentinel}" \
        "${base_url}/api/v1/integrations/metastudio/vision/ws")"
    [ "$runtime_status" = 403 ] || die "Synthetic invalid vision WebSocket was not rejected with 403."
    new_log="$(tail -c "+$((before_size + 1))" "$vision_log")"
    [[ "$new_log" == *"uri=/api/v1/integrations/metastudio/vision/ws"* ]] ||
        die "Vision WebSocket request was not observed in the dedicated access log."
    [[ "$new_log" != *"$auth_sentinel"* && "${new_log,,}" != *"authorization"* ]] ||
        die "Vision WebSocket access log exposed authorization material."
    unset auth_sentinel new_log
fi

log "MetaStudio zero-cost smoke passed; Huawei Cloud calls=0 and response bodies were not printed."
