# =============================================================================
# Backend image — shared by the API, Celery worker, Celery beat, and migrate
# services. Each ECS service runs this same image with a different container
# command (see deploy/ecs/*.task.json). Build context is the repo root:
#
#   docker build -f deploy/backend/Dockerfile -t <ecr>/repo-saas-backend:<tag> .
#
# The default CMD runs the API; worker/beat/migrate override it in ECS.
# =============================================================================

FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies for weasyprint, psycopg2, and cryptography.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    libffi-dev libcairo2 libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." && pip cache purge

# Copy application source and migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

# Default command runs the API. ECS task definitions override this for the
# worker (celery worker), beat (celery beat), and migrate (alembic upgrade).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
