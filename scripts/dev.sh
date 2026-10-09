#!/usr/bin/env bash
# Local development helper (no Docker): uses a locally installed PostgreSQL.
#   scripts/dev.sh setup     create venv, install deps, create DB user/db, migrate
#   scripts/dev.sh seed      reset DB and load DEMO data (synthetic sample, development only)
#   scripts/dev.sh seed-college  reset DB and load the college's real timetable PDF (development only)
#   scripts/dev.sh api       run the API with auto-reload on 0.0.0.0:8000
#   scripts/dev.sh worker    run the background extraction worker
#   scripts/dev.sh test      run backend + mobile tests
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
case "${1:-}" in
  setup)
    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    [ -f .env ] || cp .env.example .env
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='timetable'" | grep -q 1 || \
      sudo -u postgres psql -c "CREATE USER timetable WITH PASSWORD 'timetable_dev' CREATEDB;"
    for db in timetable timetable_test; do
      sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 || sudo -u postgres createdb -O timetable "$db"
    done
    .venv/bin/alembic upgrade head
    (cd "$ROOT/mobile" && npm ci)
    ;;
  seed) .venv/bin/python -m app.seed --reset ;;
  seed-college) shift; .venv/bin/python -m app.seed_college --reset "$@" ;;
  api) exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload ;;
  worker) exec .venv/bin/python -m app.worker ;;
  test)
    .venv/bin/python -m pytest -q
    (cd "$ROOT/mobile" && npx tsc --noEmit && npx jest)
    ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
