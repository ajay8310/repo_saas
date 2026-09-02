# Component Inventory

## Application Packages
- `app/` (FastAPI service) — HTTP API, middleware, routers, services, tasks.
- `app/services/` — 14 domain services + `anchoring/` and `vault/` subpackages.
- `app/tasks/` — Celery worker/beat tasks (bulk upload, notifications, webhooks, digilocker, anomaly detection, retention, anchoring, dispatch).
- `app/mcp/` — MCP server exposing 6 platform tools.
- `frontend/` — React/Vite/TypeScript SPA (admin/tenant/issuer UI).

## Infrastructure Packages
- `alembic/` (migrations) — schema, RLS policies, triggers, partitions, extensions.
- `docker-compose.yml` / `docker-compose.test.yml` — service orchestration (dev + test).
- `Dockerfile` — multi-stage: base, dev, production, worker, beat, mcp.
- `.github/workflows/ci.yml` — CI pipeline.
- `.kiro/hooks/` — 5 agent hooks (lint python/frontend, tests after task, migration reminder, sensitive-write guard).

## Shared Packages / Modules
- `app/models/` — SQLAlchemy models (12 model modules + base).
- `app/config.py` — centralized settings.
- `app/db/`, `app/dependencies/`, `app/errors/`, `app/rbac/` — cross-cutting concerns.

## Test Packages
- `tests/unit/` — fast, isolated unit tests.
- `tests/property/` — Hypothesis property-based tests (Tier 1 + Tier 2).
- `tests/integration/` — Docker-dependent integration tests (tenant lifecycle, RLS isolation, bulk upload, search performance, digilocker, notifications, post-deployment checks).
- `tests/smoke/` — post-deployment smoke tests.

## Non-AIDLC Documentation (informational)
- `.kiro/specs/generic-document-repository-saas/` — pre-existing Kiro spec (requirements.md, design.md, tasks.md).
- `.kiro/steering/` — architecture, coding-conventions, security, database, testing, project-overview, core-workflow steering rules.

## Total Count (approximate)
- **Total Packages/Areas**: 5 application + 5 infrastructure + shared modules + 4 test suites
- **Application**: 5 (api, services, tasks, mcp, frontend)
- **Infrastructure**: 5 (alembic, compose x2, Dockerfile, CI, hooks)
- **Shared**: models, config, db, dependencies, errors, rbac
- **Test**: 4 suites (unit, property, integration, smoke)
