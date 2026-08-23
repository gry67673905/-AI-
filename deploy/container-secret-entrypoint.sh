#!/bin/sh
set -eu

read_secret() {
    secret_name="$1"
    variable_name="$2"
    secret_path="/run/secrets/${secret_name}"
    if [ ! -r "$secret_path" ]; then
        echo "Required Docker secret is unavailable: ${secret_name}" >&2
        exit 78
    fi
    secret_value="$(cat "$secret_path")"
    if [ -z "$secret_value" ]; then
        echo "Required Docker secret is empty: ${secret_name}" >&2
        exit 78
    fi
    export "${variable_name}=${secret_value}"
}

require_secret_file() {
    secret_name="$1"
    secret_path="/run/secrets/${secret_name}"
    if [ ! -r "$secret_path" ] || [ ! -s "$secret_path" ]; then
        echo "Required Docker secret is unavailable or empty: ${secret_name}" >&2
        exit 78
    fi
}

prepare_app_runtime() {
    require_secret_file dashscope_api_key
    install -d -o app -g app -m 700 /tmp/smartgov-app-home /tmp/smartgov-app-secrets
    install -o app -g app -m 400 \
        /run/secrets/dashscope_api_key /tmp/smartgov-app-secrets/dashscope_api_key
    export HOME=/tmp/smartgov-app-home
    export USER=app
    export LOGNAME=app
    export DASHSCOPE_API_KEY_FILE=/tmp/smartgov-app-secrets/dashscope_api_key
}

service_kind="${1:-}"
case "$service_kind" in
    api)
        read_secret postgres_password POSTGRES_PASSWORD
        read_secret redis_password REDIS_PASSWORD
        read_secret minio_root_user MINIO_ACCESS_KEY
        read_secret minio_root_password MINIO_SECRET_KEY
        read_secret jwt_signing_key JWT_SIGNING_KEY
        read_secret pii_hmac_key PII_HMAC_KEY
        read_secret pii_encryption_key PII_ENCRYPTION_KEY
        read_secret mcp_internal_token MCP_INTERNAL_TOKEN
        read_secret demo_sms_code DEMO_SMS_CODE
        read_secret demo_provider_ack DEMO_PROVIDER_ACK
        read_secret demo_admin_password DEMO_ADMIN_PASSWORD
        read_secret demo_staff_password DEMO_STAFF_PASSWORD
        read_secret deepseek_api_key DEEPSEEK_API_KEY
        prepare_app_runtime
        export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
        export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST:-redis}:6379/0"
        unset POSTGRES_PASSWORD REDIS_PASSWORD
        # The only host binding is loopback and the public hop is the managed
        # Nginx instance, so forwarded client IPs are trusted for quota keys.
        exec setpriv --reuid=app --regid=app --init-groups \
            sh -c 'alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"'
        ;;
    redis)
        read_secret redis_password REDIS_PASSWORD
        exec redis-server --appendonly yes --requirepass "$REDIS_PASSWORD"
        ;;
    minio)
        read_secret minio_root_user MINIO_ROOT_USER
        read_secret minio_root_password MINIO_ROOT_PASSWORD
        exec minio server /minio_data --console-address :9001
        ;;
    milvus)
        read_secret minio_root_user MINIO_ACCESS_KEY_ID
        read_secret minio_root_password MINIO_SECRET_ACCESS_KEY
        exec milvus run standalone
        ;;
    mock)
        read_secret gov_api_token GOV_API_TOKEN
        exec su node -s /bin/sh -c 'exec node src/server.js'
        ;;
    rag-import)
        read_secret postgres_password POSTGRES_PASSWORD
        read_secret redis_password REDIS_PASSWORD
        prepare_app_runtime
        export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
        export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST:-redis}:6379/0"
        unset POSTGRES_PASSWORD REDIS_PASSWORD
        shift
        [ "$#" -gt 0 ] || {
            echo "RAG importer command is missing." >&2
            exit 64
        }
        exec setpriv --reuid=app --regid=app --init-groups "$@"
        ;;
    mcp)
        read_secret mcp_internal_token MCP_INTERNAL_TOKEN
        read_secret gov_api_token GOV_API_TOKEN
        exec su node -s /bin/sh -c 'exec node src/server.js'
        ;;
    minio-backup)
        read_secret minio_root_user MINIO_ROOT_USER
        read_secret minio_root_password MINIO_ROOT_PASSWORD
        mkdir -p /backup/materials /backup/knowledge
        mc alias set smartgov http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
        mc mirror --overwrite "smartgov/${MATERIALS_BUCKET:-smart-gov-materials}" /backup/materials >/dev/null
        mc mirror --overwrite "smartgov/${KNOWLEDGE_BUCKET:-smart-gov-knowledge}" /backup/knowledge >/dev/null
        printf '%s\n' "MinIO object backup completed."
        ;;
    *)
        echo "Unsupported container entrypoint mode." >&2
        exit 64
        ;;
esac
