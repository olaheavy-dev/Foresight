# FastAPI backend + in-process APScheduler. Built in CI, never on the server (docs/05 §12).
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini features.yaml ./
COPY backend ./backend
COPY backend/entrypoint.sh /usr/local/bin/entrypoint.sh
# Synthetic demo personas for the seed (DEMO-01): only the files the seeder reads. Their CSVs are
# the only statement files allowed in the image (tools/check_image_secrets.py DEMO_DATA).
COPY evals/datasets/P1-base/workspace.json evals/datasets/P1-base/truth_accounts.json ./demo-data/P1-base/
COPY evals/datasets/P1-base/exports/ ./demo-data/P1-base/exports/
COPY evals/datasets/P2-base/workspace.json evals/datasets/P2-base/truth_accounts.json ./demo-data/P2-base/
COPY evals/datasets/P2-base/exports/ ./demo-data/P2-base/exports/
ENV FORESIGHT_DEMO_DATA=/srv/demo-data
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && useradd --system --uid 10001 foresight
USER foresight

ARG BUILD_SHA=local
ENV FORESIGHT_BUILD_SHA=${BUILD_SHA}
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
ENTRYPOINT ["entrypoint.sh"]
