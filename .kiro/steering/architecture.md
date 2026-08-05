# Architecture Patterns

## Multi-Tenancy Model

This platform uses **shared database + shared schema + PostgreSQL Row-Level Security (RLS)** as the default isolation strategy.

### How It Works

1. Every tenant-scoped table has a `tenant_id UUID NOT NULL` column with a foreign key to `tenants(id)`.
2. Each table has RLS enabled and forced:
   ```sql
   ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
   ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
   ```
3. A `tenant_isolation` policy on each table enforces:
   ```sql
   CREATE POLICY tenant_isolation ON <table>
     USING (tenant_id = current_setting('app.tenant_id')::uuid)
     WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
   ```
4. The application sets the RLS variable at the start of every request via `SET LOCAL app.tenant_id = '<uuid>'`.

### Tenant Context Flow

```
Request → JWT validation (extracts tenant_id) → request.state.tenant_id
       → TenantContextMiddleware → SET LOCAL app.tenant_id
       → Service layer queries → RLS auto-filters results
```

The `TenantContextMiddleware` in `app/middleware/tenant_context.py` handles this. Public routes (health check, verification endpoints, docs) are skipped.

For service-layer code that needs to explicitly set tenant context within a transaction:

```python
from app.middleware.tenant_context import set_tenant_context

async def some_service_method(db: AsyncSession, tenant_id: UUID):
    await set_tenant_context(db, str(tenant_id))
    # subsequent queries are now scoped to this tenant
```

## Request Lifecycle

1. **Client** sends request with `Authorization: Bearer <JWT>`
2. **CORS middleware** handles preflight / adds headers
3. **Auth dependency** (`get_current_user`) validates JWT, extracts `sub`, `tenant_id`, `roles`, stores `tenant_id` on `request.state`
4. **TenantContextMiddleware** reads `request.state.tenant_id` and stores it for DB session setup
5. **Rate limiter** (when implemented) checks per-tenant quota in Redis
6. **RBAC dependency** (`require_permission`) checks role against permission map
7. **Service layer** executes business logic with DB session (RLS active)
8. **Audit log** records the action asynchronously
9. **Response** returned to client

## Application Factory Pattern

The app is constructed via `create_app()` in `app/main.py`:

```python
from app.main import create_app

app = create_app()
```

This pattern enables:
- Creating isolated app instances in tests with different settings
- Separating configuration from instantiation
- Clean lifespan management (startup/shutdown hooks via `@asynccontextmanager`)

The module-level `app = create_app()` at the bottom of `main.py` is the instance consumed by Uvicorn.

## Dependency Injection

All cross-cutting concerns are wired through FastAPI's `Depends()`:

| Dependency | Location | Purpose |
|-----------|----------|---------|
| `get_db` | `app/db/session.py` | Yields an async DB session |
| `get_current_user` | `app/dependencies/auth.py` | Validates JWT, returns `TokenPayload` |
| `get_current_tenant_id` | `app/dependencies/auth.py` | Extracts `tenant_id` from validated token |
| `require_permission(op)` | `app/rbac/permissions.py` | Enforces RBAC, returns 403 on denial |
| `get_auth_service` | `app/services/auth_service.py` | Provides `AuthService` instance |

### Composing Dependencies

Dependencies can be chained. For example, `get_current_tenant_id` depends on `get_current_user`:

```python
async def get_current_tenant_id(
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> UUID:
    return user.tenant_id
```

### Using RBAC on Routes

Apply permission checks as route-level dependencies:

```python
@router.post(
    "/schemas",
    dependencies=[Depends(require_permission("schema:create"))],
)
async def create_schema(...): ...
```

## Service Layer Pattern

Business logic lives in service classes under `app/services/`. Each service:

1. Is a class with async methods
2. Receives dependencies (DB session, Redis client, etc.) via constructor or method params
3. Has a `get_<service>()` factory function for FastAPI dependency injection
4. Handles domain logic, validation, and orchestration
5. Delegates persistence to SQLAlchemy models/queries

```python
class DocumentService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings

    async def upload(self, tenant_id: UUID, payload: UploadPayload) -> Document:
        await set_tenant_context(self.db, str(tenant_id))
        # validation, encryption, S3 upload, DB insert, audit log
        ...

async def get_document_service(
    db: AsyncSession = Depends(get_db),
) -> DocumentService:
    return DocumentService(db=db, settings=get_settings())
```

## Router Organization

- One router module per domain: `auth.py`, `tenants.py`, `schemas.py`, `documents.py`, `verification.py`, etc.
- Each router uses `APIRouter(prefix="/<resource>", tags=["<resource>"])`
- Routers are registered in `app/main.py` via `app.include_router(router, prefix=settings.api_v1_prefix)`
- Request/response Pydantic models are defined at the top of their router module

## Middleware Stack

Middleware executes in reverse registration order (last registered = first to process):

1. `CORSMiddleware` — handles CORS headers and preflight
2. `TenantContextMiddleware` — sets RLS tenant context from authenticated request state

Additional middleware to be added:
- Rate limiting middleware (Redis token bucket)
- Request ID middleware (correlation IDs for tracing)

## Background Tasks (Celery)

- Celery workers handle async processing: bulk uploads, webhook delivery, notifications, DigiLocker pushes.
- Task definitions live in `app/tasks/`.
- Broker and result backend default to Redis (configurable in `app/config.py`).
- Serialization format: JSON.

## Configuration Management

All configuration is centralized in `app/config.py` using Pydantic `BaseSettings`:

- Reads from environment variables (uppercase field names)
- Loads `.env` file automatically in development
- Validates bounds at startup (e.g., JWT expiry <= 3600s, OTP TTL <= 600s)
- Cached via `@lru_cache` in `get_settings()` for singleton access
- Cross-field defaults handled via `@field_validator` (e.g., Celery broker defaults to Redis URL)

## Error Handling

Global exception handlers are registered in `app/errors/handlers.py`:

| Exception | HTTP Status | Response Shape |
|-----------|-------------|---------------|
| `RequestValidationError` | 422 | `{"code": "VALIDATION_ERROR", "message": "...", "errors": [...]}` |
| `HTTPException` | varies | `{"code": "...", "message": "..."}` (from `detail` dict) |
| Unhandled `Exception` | 500 | `{"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}` |

All error responses follow a consistent JSON structure. Never expose internal details in production error responses.

## API Versioning

- All versioned endpoints live under `/api/v1/` (configurable via `settings.api_v1_prefix`)
- OpenAPI spec served at `/api/v1/openapi.json`
- Docs at `/api/v1/docs` (Swagger UI) and `/api/v1/redoc`
- Health check at `/health` (outside versioned prefix, no auth required)
