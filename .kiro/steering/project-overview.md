# Project Overview

## What This Is

Repo SaaS is a **Generic Multi-Tenant SaaS Document and Credential Repository Platform** — a domain-agnostic digital depository that enables organizations (government departments, institutions, regulatory bodies) to onboard as tenants, define custom document schemas, upload structured credential records for beneficiaries, and provide secure verification access to third parties.

## Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.12+ |
| Web Framework | FastAPI | 0.111.x |
| ASGI Server | Uvicorn | 0.29.x |
| ORM | SQLAlchemy (async) | 2.0.x |
| Migrations | Alembic | 1.13.x |
| Database | PostgreSQL (with RLS) | 16 |
| Cache / Queue Broker | Redis | 7.x |
| Task Queue | Celery | 5.4.x |
| Object Storage | AWS S3 (SSE-KMS) | — |
| Key Management | AWS KMS | — |
| Auth Tokens | python-jose (RS256 JWT) | 3.3.x |
| Password Hashing | passlib (bcrypt) | 1.7.x |
| MFA | pyotp (TOTP/RFC 6238) | 2.9.x |
| Validation | Pydantic / pydantic-settings | 2.7.x / 2.2.x |
| HTTP Client | httpx | 0.27.x |
| Linting | ruff | 0.4.x |
| Type Checking | mypy | 1.10.x |
| Testing | pytest / pytest-asyncio / hypothesis | 8.2.x / 0.23.x / 6.100.x |

## Project Layout

```
repo_saas/
├── app/
│   ├── main.py              # FastAPI app factory, health check, router wiring
│   ├── config.py            # Pydantic BaseSettings (all env vars)
│   ├── __init__.py
│   ├── db/
│   │   ├── session.py       # Async engine, session factory, get_db dependency
│   │   └── __init__.py
│   ├── dependencies/
│   │   ├── auth.py          # JWT validation dependency (get_current_user)
│   │   └── __init__.py
│   ├── errors/
│   │   ├── handlers.py      # Global exception handlers (422, HTTP, unhandled)
│   │   └── __init__.py
│   ├── middleware/
│   │   ├── tenant_context.py # RLS tenant isolation middleware
│   │   └── __init__.py
│   ├── models/
│   │   ├── base.py          # DeclarativeBase, UUID PK mixin, Timestamp mixin
│   │   ├── tenant.py        # Tenant, TenantEncryptionKey, ApiClient
│   │   ├── user.py          # UserAccount
│   │   ├── schema.py        # DocumentSchema, SchemaVersion
│   │   ├── document.py      # Document, BulkJob
│   │   ├── verification.py  # VerificationToken
│   │   ├── audit.py         # AuditLog
│   │   ├── webhook.py       # Webhook, WebhookEvent
│   │   ├── notification.py  # NotificationPreference
│   │   ├── digilocker.py    # DigiLockerPush
│   │   └── __init__.py      # Re-exports all models
│   ├── rbac/
│   │   ├── permissions.py   # Role permission map, require_permission dependency
│   │   └── __init__.py
│   ├── routers/             # FastAPI APIRouter modules (one per domain)
│   │   ├── auth.py
│   │   └── __init__.py
│   ├── services/            # Business logic (one service class per domain)
│   │   ├── auth_service.py
│   │   └── __init__.py
│   └── tasks/               # Celery task definitions
│       └── __init__.py
├── alembic/
│   ├── env.py               # Async migration runner
│   ├── script.py.mako
│   └── versions/            # Migration scripts (numbered sequentially)
├── tests/
│   ├── unit/                # Fast, no external deps
│   ├── integration/         # Requires Docker Compose (DB, Redis)
│   ├── property/            # Hypothesis property-based tests
│   └── smoke/               # Post-deployment sanity checks
├── pyproject.toml           # Dependencies, tool config (ruff, mypy, pytest)
├── alembic.ini
└── .env.example             # Template for local development env vars
```

## Key Design Principles

1. **Multi-tenancy via PostgreSQL RLS** — Every tenant-scoped table has a `tenant_id` column. Row-Level Security policies enforce isolation at the database level using `SET LOCAL app.tenant_id = '<uuid>'` at transaction start.

2. **Configuration via environment** — All settings live in `app/config.py` as a Pydantic `BaseSettings` class. The app fails fast at startup if required config is missing.

3. **App factory pattern** — `create_app()` in `app/main.py` constructs and returns the FastAPI instance, making it easy to create isolated instances for testing.

4. **Dependency injection** — FastAPI's `Depends()` is used consistently for DB sessions, auth validation, RBAC checks, and service instantiation.

5. **Async-first** — All DB operations use SQLAlchemy's async engine (`asyncpg`). Services and route handlers are async.

6. **Immutable audit trail** — All significant platform actions are recorded in a partitioned, append-only `audit_logs` table with a database trigger preventing modification.

## How to Run

```bash
# Install dependencies
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env with your local PostgreSQL, Redis, and key values

# Run migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest
```

## Spec Reference

The full requirements, design, and implementation tasks are documented in:
- `.kiro/specs/generic-document-repository-saas/requirements.md`
- `.kiro/specs/generic-document-repository-saas/design.md`
- `.kiro/specs/generic-document-repository-saas/tasks.md`
