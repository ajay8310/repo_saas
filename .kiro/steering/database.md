# Database Patterns

## Stack

- **Database:** PostgreSQL 16
- **ORM:** SQLAlchemy 2.0 (async mode via `asyncpg`)
- **Migrations:** Alembic with async runner
- **Connection pool:** SQLAlchemy's built-in pool (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`)

## Async Engine and Session

The async engine and session factory are defined in `app/db/session.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

The `get_db` dependency yields a session and ensures it's closed after the request:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

## SQLAlchemy Model Patterns

### Base and Mixins

All models inherit from `Base` (in `app/models/base.py`):

```python
class Base(DeclarativeBase):
    pass
```

Two reusable mixins:

- **`UUIDPrimaryKeyMixin`** — UUID primary key with `gen_random_uuid()` server default
- **`TimestampMixin`** — `created_at` and `updated_at` with server defaults and `onupdate`

### Model Structure

```python
from app.models.base import Base, UUIDPrimaryKeyMixin

class Document(Base, UUIDPrimaryKeyMixin):
    """Tenant-scoped encrypted document record."""

    __tablename__ = "documents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    schema_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_schemas.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="stored")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### Conventions for Models

| Aspect | Rule |
|--------|------|
| Primary key | Always UUID via `UUIDPrimaryKeyMixin` |
| Table names | Plural snake_case matching the migration DDL |
| Tenant scoping | `tenant_id` column with `ForeignKey("tenants.id", ondelete="CASCADE")` |
| Timestamps | Use `DateTime(timezone=True)` with `server_default=func.now()` |
| Status fields | `String(32)` with `server_default` matching the CHECK constraint in the migration |
| Nullable | Explicitly set `nullable=True` or `nullable=False` on every column |
| Relationships | Use `Mapped[list["Related"]]` with `relationship(back_populates="...")` |
| Type annotations | Always use `Mapped[T]` with `mapped_column(...)` |

### Model Registration

All models are re-exported from `app/models/__init__.py` for convenient imports:

```python
from app.models import Tenant, Document, AuditLog
```

Add new models to `__init__.py` when creating them.

## Row-Level Security (RLS)

### Per-Request Tenant Isolation

Every request that hits a tenant-scoped table must have `app.tenant_id` set:

```python
from app.middleware.tenant_context import set_tenant_context

# Inside a service method:
await set_tenant_context(db, str(tenant_id))
result = await db.execute(select(Document))  # automatically filtered by RLS
```

### RLS Policy Pattern (in migrations)

```python
def _apply_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = current_setting('app.tenant_id')::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
    """)
```

Every new tenant-scoped table **must** call `_apply_rls()` in its migration.

### Tables Without RLS

Only `tenants` itself is not tenant-scoped (it's the root entity). All other tables must have RLS.

## Alembic Migrations

### Configuration

- `alembic.ini` points to the Alembic env script
- `alembic/env.py` reads `DATABASE_URL` from app config and converts `asyncpg` to `psycopg2` for migration execution
- Migrations run using an async engine (`async_engine_from_config`)

### Creating New Migrations

```bash
# Auto-generate (after updating models):
alembic revision --autogenerate -m "add_new_table"

# Manual (for complex DDL like RLS, triggers, partitions):
alembic revision -m "add_custom_feature"
```

### Migration Naming

Prefix with sequential number: `001_initial_schema.py`, `002_add_search_indexes.py`, etc.

### Migration Best Practices

1. **Always include RLS** for new tenant-scoped tables
2. **Use raw SQL** (`op.execute(...)`) for PostgreSQL-specific features (RLS policies, triggers, partitions, extensions)
3. **Include both `upgrade()` and `downgrade()`** functions
4. **Test migrations** by running `alembic upgrade head` then `alembic downgrade -1` to verify reversibility
5. **Never modify a released migration** — create a new one instead

### Running Migrations

```bash
# Apply all pending
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history
```

## PostgreSQL Extensions

The platform uses these extensions (created in migration 001):

- **`pgcrypto`** — `gen_random_uuid()` for UUID generation
- **`pg_trgm`** — Trigram similarity for text search with GIN indexes

## Partitioning

`audit_logs` is partitioned by month using `PARTITION BY RANGE (created_at)`:

- Monthly partitions are pre-created (e.g., `audit_logs_y2025m01`)
- A `DEFAULT` partition catches rows that don't match any defined range
- RLS is applied to the parent table; partitions inherit it

When creating new partitions (e.g., for a new year), add them via a migration.

## Triggers

### Audit Immutability

The `prevent_audit_modification()` trigger function prevents UPDATE and DELETE on `audit_logs`:

```sql
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log entries cannot be modified or deleted';
END;
$$ LANGUAGE plpgsql;
```

### Storage Quota Enforcement

The `check_quota_before_insert()` trigger function on `documents` rejects inserts that would exceed a tenant's configured storage quota by checking against the `tenant_storage_usage` materialized view.

## Materialized Views

- **`tenant_storage_usage`** — aggregates document count and total bytes per tenant
- Refresh periodically or after bulk operations

## Query Patterns

### Basic Tenant-Scoped Query

```python
async def get_documents_for_beneficiary(
    db: AsyncSession, tenant_id: UUID, beneficiary_id: str
) -> list[Document]:
    await set_tenant_context(db, str(tenant_id))
    result = await db.execute(
        select(Document).where(Document.beneficiary_id == beneficiary_id)
    )
    return list(result.scalars().all())
```

### Insert Pattern

```python
async def create_document(db: AsyncSession, tenant_id: UUID, **kwargs) -> Document:
    await set_tenant_context(db, str(tenant_id))
    doc = Document(tenant_id=tenant_id, **kwargs)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc
```

### Transaction Management

- The `get_db` dependency provides a session per request
- Use `await db.commit()` explicitly after writes
- Use `await db.rollback()` in error paths
- For operations spanning multiple steps, wrap in `async with db.begin():` for automatic rollback on exception
