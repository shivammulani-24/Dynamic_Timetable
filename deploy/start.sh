#!/bin/sh
# Container start-up: migrate, optionally load demo data into an empty database, then serve.
set -e
alembic upgrade head
if [ "${ALLOW_DEMO_SEED:-false}" = "true" ]; then
  python -m app.seed_college --if-empty
fi
# One process: free instances have little memory, and the upload worker runs inside it.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
     --proxy-headers --forwarded-allow-ips '*'
