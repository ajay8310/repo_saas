# Technology Stack

## Programming Languages
- **Python** — 3.12 — backend service, workers, MCP server.
- **TypeScript** — ~5.4 — frontend SPA.
- **SQL** (PostgreSQL dialect) — migrations, RLS policies, triggers.

## Frameworks & Core Libraries (backend)
- **FastAPI** 0.111.0 — web framework / OpenAPI.
- **Uvicorn** 0.29.0 — ASGI server.
- **SQLAlchemy** 2.0.30 (asyncio) + **asyncpg** 0.29.0 — async ORM/DB.
- **psycopg2-binary** 2.9.9 — sync driver for Alembic.
- **Alembic** 1.13.1 — migrations.
- **Celery** 5.4.0 (redis) — task queue.
- **Redis** 5.0.4 client — cache/broker/rate-limit.
- **Pydantic** 2.7.1 / **pydantic-settings** 2.2.1 — models/config.
- **python-jose** 3.3.0 — RS256 JWT.
- **passlib[bcrypt]** 1.7.4 — hashing.
- **pyotp** 2.9.0 — TOTP MFA.
- **cryptography** 42.0.7 — AES-256-GCM.
- **boto3/botocore** 1.34.102 — AWS SDK.
- **reportlab / weasyprint / pyld / qrcode / Pillow** — document rendering (PDF, JSON-LD, QR).
- **httpx** 0.27.0 — outbound HTTP (webhooks, DigiLocker).
- **clamd** 1.0.2 — ClamAV client.
- **mcp** (extra, ≥1.2,<2) — MCP SDK (isolated image only).

## Frameworks & Libraries (frontend)
- **React** 18, **React Router** 6, **Vite** 5, **TailwindCSS** 3, **axios**, **lucide-react**, **clsx**.

## Infrastructure
- **PostgreSQL 16** — primary datastore, RLS, partitioning, pg_trgm.
- **Redis 7** — cache, Celery broker/result backend, rate limiter.
- **AWS S3** — encrypted document storage (SSE-KMS).
- **AWS KMS** — per-tenant CMKs for envelope encryption.
- **AWS SES / SNS** — email / SMS notifications.
- **ClamAV** — malware scanning sidecar.
- **LocalStack** — AWS emulation in dev/test.
- **Docker / Docker Compose** — containerization & orchestration.
- Optional **EVM chain** — ledger anchoring (provider-based).

## Build Tools
- **pip / setuptools** (pyproject.toml) — backend packaging; extras `[dev]`, `[mcp]`.
- **npm + Vite** — frontend build.
- **Docker multi-stage build** — base/dev/production/worker/beat/mcp.

## Testing Tools
- **pytest** 8.2.0 + **pytest-asyncio** 0.23.6 + **pytest-mock** 3.14.0 + **pytest-cov** 5.0.0.
- **Hypothesis** 6.100.2 — property-based testing.
- **ruff** 0.4.4 — lint/format; **mypy** 1.10.0 — type checking.
