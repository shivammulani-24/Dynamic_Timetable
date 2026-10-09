# API and worker image (same image, different command).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract for OCR; LibreOffice (calc+writer, headless) only for legacy .xls/.doc conversion.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr libreoffice-calc-nogui libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.lock
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/storage && chown -R appuser /data
USER appuser
ENV STORAGE_DIR=/data/storage
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-4} --proxy-headers"]
