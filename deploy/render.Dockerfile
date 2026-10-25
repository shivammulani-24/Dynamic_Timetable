# Single-service image for free hosting (Render): API + web app + upload processing in one container.
# Build context: repository root.  Local check:  docker build -f deploy/render.Dockerfile .

# ---- 1. Web app (the same Expo app, exported for browsers; calls the API on its own origin) ----
FROM node:22-slim AS web
WORKDIR /mobile
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile/ ./
ENV EXPO_PUBLIC_API_URL=same-origin
RUN npx expo export --platform web --output-dir /web

# ---- 2. API server ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract for scanned PDFs / photos. (LibreOffice for legacy .xls/.doc is left out to keep the free
# instance small; .xlsx/.docx/.pdf/images work.)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install -r requirements.lock
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
# Demo data source (used only when ALLOW_DEMO_SEED=true and the database is empty)
COPY backend/tests/fixtures/reference/college_timetable.pdf ./tests/fixtures/reference/college_timetable.pdf
COPY --from=web /web ./web
COPY deploy/start.sh ./start.sh

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/storage && chown -R appuser /data \
    && chmod +x /app/start.sh
USER appuser
ENV STORAGE_DIR=/data/storage WEB_DIST_DIR=/app/web RUN_WORKER_IN_PROCESS=true
EXPOSE 8000
CMD ["/app/start.sh"]
