# Setup, deployment and operations

## Manual development setup (any OS)

```bash
# PostgreSQL: create user + databases
psql -U postgres -c "CREATE USER timetable WITH PASSWORD 'timetable_dev' CREATEDB;"
createdb -U postgres -O timetable timetable
createdb -U postgres -O timetable timetable_test

# Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt                    # exact versions: requirements.lock
cp .env.example .env                                   # adjust DATABASE_URL if needed
alembic upgrade head
python -m app.seed --reset                             # DEMO data, development only
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
python -m app.worker                                   # second terminal

# OCR / conversion tools
#   Ubuntu: sudo apt install tesseract-ocr libreoffice-calc-nogui libreoffice-writer-nogui
#   macOS:  brew install tesseract && brew install --cask libreoffice
#   Windows: install Tesseract (UB Mannheim build) and set TESSERACT_CMD to tesseract.exe

# Mobile
cd mobile && npm ci && npx expo start
```

Reset the dev database at any time with `python -m app.seed --reset` (refuses in production).

## Configuration

All configuration is environment variables (see `backend/.env.example`, `mobile/.env.example`).
Never commit `.env`. The mobile bundle only receives `EXPO_PUBLIC_*` values — no secrets there.

## Production checklist

1. `ENVIRONMENT=production`; strong `JWT_SECRET` (≥32 chars) — the app refuses to start otherwise.
2. Explicit `CORS_ORIGINS`; serve the API only over HTTPS (reverse proxy with TLS, e.g. Caddy/Nginx),
   run uvicorn with `--proxy-headers`.
3. Managed PostgreSQL with automated backups; run `alembic upgrade head` on deploy (the Docker image does).
4. Persistent volume for `STORAGE_DIR` (originals are needed for re-processing); back it up with the DB.
5. Run ≥2 API processes (`WEB_CONCURRENCY`) and ≥1 worker. Rate limits are per process — move the
   limiter to Redis/Postgres if you run many replicas behind a load balancer.
6. Configure SMTP so invitation/reset codes are emailed (in production they are never returned by the API).
7. Create the first Admin account with a one-off script or SQL inside the DB (no demo seed), then
   use the app's Admin screens for everything else.
8. Mobile: set `EXPO_PUBLIC_API_URL` per EAS profile in `mobile/eas.json`; add `extra.eas.projectId`
   (from `eas init`) to enable push notifications; set `EXPO_PUSH_ENABLED=true` on the server.

### Creating the first Admin (production)

```bash
python - <<'PY'
from app.db import session_factory
from app.models import Role, Staff, UserAccount, UserPreference, UserRole
from app.security.passwords import hash_password
with session_factory()() as db:
    u = UserAccount(college_email="registrar@college.edu", display_name="Registrar", timezone_id="Asia/Kolkata",
                    password_hash=hash_password("<a strong temporary password>"), account_status="ACTIVE")
    db.add(u); db.flush()
    db.add(UserRole(user_id=u.user_id, role_id=db.query(Role).filter_by(code="ADMIN").one().role_id))
    db.add(Staff(user_id=u.user_id)); db.add(UserPreference(user_id=u.user_id)); db.commit()
PY
```
Change the password from the app immediately.

## Docker

`docker compose up --build` starts `db`, `api` (runs migrations on start) and `worker` with named
volumes for data and uploads. For production use the same image with real secrets from your
orchestrator, a managed database and TLS in front of `api`.

## Mobile builds

| Goal | Command |
|---|---|
| Try on a phone quickly | `npx expo start` + Expo Go (development only) |
| Development build (needed for push + exact native modules) | `npx eas-cli build --profile development -p android` / `-p ios` |
| iOS simulator build | `npx eas-cli build --profile simulator -p ios` (or `npx expo run:ios` on a Mac with Xcode) |
| Internal test APK / ad-hoc iOS | `npx eas-cli build --profile preview` |
| Store builds | `npx eas-cli build --profile production` then `npx eas-cli submit` |

iOS builds need an Apple Developer account; nothing iOS-specific was built or run in the authoring
environment (only the iOS JS bundle compilation was verified).

## Troubleshooting

| Symptom | Fix |
|---|---|
| App shows "Can't reach the server" in dev | API must listen on `0.0.0.0:8000`; phone on same Wi-Fi; allow port 8000 in the firewall; or set `EXPO_PUBLIC_API_URL=http://<your-LAN-IP>:8000` |
| Uploads stay `QUEUED` | The worker isn't running (`python -m app.worker`) |
| Scanned PDF/photo → `FAILED`/`UNUSABLE` | Install Tesseract; check `TESSERACT_CMD`; use a straight, well-lit photo |
| `.xls`/`.doc` → `CONVERSION_FAILED` | Install LibreOffice; check `SOFFICE_PATH` |
| Everything `UNVERIFIED` after upload | Add rooms/batches/courses/staff short codes or aliases in Admin, then "Re-link" on the review screen |
| "this week" asks for dates | Set the week start in Admin → Institution settings |
| Free time / after-lunch unavailable | Configure working hours / lunch boundary in Institution settings |
| `401 TOKEN_REVOKED` after role change | Expected — roles changed; sign in again |
