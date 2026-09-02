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

CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "worker", "--loglevel=info", "--concurrency=4"]

# ---------------------------------------------------------------------------
# Celery beat image
# ---------------------------------------------------------------------------
FROM base AS beat

CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "beat", "--loglevel=info"]

# ---------------------------------------------------------------------------
# MCP server image — isolated environment for the Model Context Protocol
# server that exposes platform operations as agent tools.
#
# The mcp SDK requires a newer pydantic than the platform's pinned 2.7.1, so it
# lives in its own image (installing ".[mcp]" here upgrades pydantic/starlette
# for THIS image only — the api/worker/production images keep their pins).
#
# Runs over stdio: an MCP client (e.g. Kiro) launches it via
#   docker run -i --rm --network repo_as_saas_default repo_as_saas-mcp
# stdin/stdout carry the MCP protocol; there is no exposed port.
# ---------------------------------------------------------------------------
FROM base AS mcp

# The base image already has the app installed with its pinned deps. The mcp
# SDK needs newer pydantic/pydantic-settings than those pins, so we install
# mcp directly and let pip upgrade just those two transitive deps. We do NOT
# reinstall the app via ".[mcp]" here, because re-reading the core "=="
# dependency pins alongside mcp's ">=" ranges makes resolution impossible.
#
# The MCP server only exercises the service layer (SQLAlchemy + boto3 + the
# domain services), which is compatible with pydantic v2.x >= 2.10. FastAPI
# request-model handling is not used by the stdio MCP server.
RUN pip install --no-cache-dir "mcp>=1.2,<2" \
    "pydantic>=2.10,<3" "pydantic-settings>=2.6,<3" \
    && pip cache purge

# Point service clients at the compose network hostnames by default. These can
# be overridden at `docker run` time with -e for other environments.
ENV DATABASE_URL=postgresql+asyncpg://reposaaas:reposaaas@postgres:5432/reposaaas \
    REDIS_URL=redis://redis:6379/0 \
    S3_ENDPOINT_URL=http://localstack:4566 \
    KMS_ENDPOINT_URL=http://localstack:4566

# stdio transport — no EXPOSE. Keep STDOUT clean for the protocol; logs go to
# STDERR via the logging config in app.mcp.server.
CMD ["python", "-m", "app.mcp"]
