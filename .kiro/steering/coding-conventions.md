# Coding Conventions

## Python Version and Language Features

- Target **Python 3.12+**. Use modern syntax freely: `type X = ...` aliases, `match` statements, `X | Y` union syntax in type hints, `list[str]` instead of `typing.List[str]`.
- Use `from __future__ import annotations` at the top of every module for PEP 563 deferred evaluation of annotations.

## Formatting and Linting

- **Formatter/Linter:** ruff (configured in `pyproject.toml`)
- **Line length:** 100 characters max
- **Target version:** `py312`
- **Enabled rule sets:** `E` (pycodestyle), `F` (pyflakes), `I` (isort), `UP` (pyupgrade), `B` (bugbear), `SIM` (simplify)
- **Type checking:** mypy with `python_version = "3.12"`, `ignore_missing_imports = true`

Run before committing:
```bash
ruff check . --fix
ruff format .
mypy app/
```

## Import Ordering

Imports are sorted by ruff's isort integration. The canonical order is:

```python
# 1. __future__ imports
from __future__ import annotations

# 2. Standard library
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, AsyncGenerator

# 3. Third-party
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 4. Local application
from app.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import TokenPayload, get_current_user
from app.models import Document, Tenant
```

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case` | `auth_service.py`, `tenant_context.py` |
| Classes | `PascalCase` | `TokenPayload`, `AuthService`, `TenantContextMiddleware` |
| Functions / methods | `snake_case` | `get_current_user`, `issue_token` |
| Constants | `UPPER_SNAKE_CASE` | `ROLE_PERMISSIONS`, `_PUBLIC_PREFIXES` |
| Private/internal | Leading underscore | `_bearer_scheme`, `_register_routes` |
| FastAPI routers | `router` (module-level) | `router = APIRouter(...)` |
| Pydantic models | `PascalCase`, suffixed by intent | `TokenRequest`, `TokenResponse`, `OTPVerifyBody` |
| SQLAlchemy models | `PascalCase`, singular noun | `Tenant`, `Document`, `AuditLog` |
| DB table names | `snake_case`, plural | `tenants`, `audit_logs`, `webhook_events` |
| Alembic revisions | Numeric prefix + description | `001_initial_schema.py` |

## Type Annotations

- Annotate all function parameters and return types.
- Use `Mapped[T]` for SQLAlchemy column types.
- Use `Annotated[T, Depends(...)]` for FastAPI dependency injection type narrowing.
- Use `X | None` instead of `Optional[X]`.
- Use frozen dataclasses with `slots=True` for immutable value objects:

```python
@dataclass(frozen=True, slots=True)
class TokenPayload:
    sub: str
    tenant_id: UUID
    roles: list[str]
    exp: int
```

## Docstrings

- Every module has a module-level docstring explaining its purpose and listing key exports.
- Classes and public functions use docstrings. Keep them concise.
- Reference requirement IDs in docstrings where applicable: `"""Issue a JWT (Req 8.2, 8.3)."""`
- Use `# noqa: <code>` comments sparingly and only with justification.

## Code Structure Patterns

### Module Organization

Each module follows this internal structure:
```python
"""Module docstring."""

from __future__ import annotations

# imports (ordered per above)

# module-level constants
# module-level logger: logger = logging.getLogger(__name__)

# classes / functions (public first, then private helpers)
```

### FastAPI Router Modules

```python
"""Router docstring listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.services.some_service import SomeService, get_some_service

router = APIRouter(prefix="/resource", tags=["resource"])

# --- Request / Response models ---

class CreateResourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

class ResourceResponse(BaseModel):
    id: str
    name: str

# --- Endpoints ---

@router.post("/", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_resource(
    body: CreateResourceRequest,
    service: SomeService = Depends(get_some_service),
) -> ResourceResponse:
    """Create a new resource (Req X.Y)."""
    ...
```

### Service Classes

- Services encapsulate business logic and are injected into routers via `Depends()`.
- Each service has a corresponding `get_<service>` factory function for dependency injection.
- Services receive DB sessions and other dependencies through their constructor or methods.

### Error Responses

Always use structured error dictionaries with `code` and `message` keys:
```python
raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "INVALID_TOKEN", "message": "Token is invalid or expired."},
    headers={"WWW-Authenticate": "Bearer"},
)
```

## Field Validation in Pydantic Models

- Use `Field(...)` for required fields with constraints (`min_length`, `max_length`, `ge`, `le`, `pattern`).
- Use `Field(default=...)` for optional fields with defaults.
- Use `field_validator` (mode `"after"`) for cross-field or computed defaults.
- Keep request/response models colocated with their router module.

## Logging

- Use `logging.getLogger(__name__)` at module level.
- Log security events (auth failures, permission denials) at `WARNING` level.
- Log unexpected errors at `ERROR` level.
- Never log sensitive data (tokens, passwords, PII).
