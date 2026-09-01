FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies for weasyprint, psycopg2, and cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." && pip cache purge

COPY . .

# ---------------------------------------------------------------------------
# Dev image — includes dev tooling (ruff, pytest, mypy) for hooks and local
# workflows. Used by the api/worker services in docker-compose for development.
# ---------------------------------------------------------------------------
FROM base AS dev

RUN pip install --no-cache-dir -e ".[dev]" && pip cache purge

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------------------------------------------------------------------------
# Production image
# ---------------------------------------------------------------------------
FROM base AS production

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ---------------------------------------------------------------------------
# Celery worker image
# ---------------------------------------------------------------------------
FROM base AS worker

CMD ["celery", "-A", "app.tasks.celery_app:init_celery", "worker", "--loglevel=info", "--concurrency=4"]

# ---------------------------------------------------------------------------
# Celery beat image
# ---------------------------------------------------------------------------
FROM base AS beat

CMD ["celery", "-A", "app.tasks.celery_app:init_celery", "beat", "--loglevel=info"]
