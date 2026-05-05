#!/usr/bin/env bash
set -euo pipefail

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:=vpn_pix}"
: "${POSTGRES_DB:=vpn_pix}"

echo "[entrypoint] waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
TRIES=0
MAX_TRIES=60
until pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
    TRIES=$((TRIES + 1))
    if [ "${TRIES}" -ge "${MAX_TRIES}" ]; then
        echo "[entrypoint] postgres did not become ready in time"
        exit 1
    fi
    sleep 1
done
echo "[entrypoint] postgres is ready"

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] running seeds..."
python -m app.seeds

echo "[entrypoint] starting service: $*"
exec "$@"
