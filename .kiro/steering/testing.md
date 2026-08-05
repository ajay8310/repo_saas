# Testing Standards

## Test Runner and Configuration

- **Framework:** pytest 8.2.x with pytest-asyncio 0.23.x
- **Async mode:** `asyncio_mode = "auto"` (all async tests run without explicit `@pytest.mark.asyncio`)
- **Output:** `-v --tb=short` (verbose with short tracebacks)
- **Coverage:** pytest-cov (target: meaningful coverage, not arbitrary percentage)

Configuration lives in `pyproject.toml` under `[tool.pytest.ini_options]`.

## Test Directory Structure

```
tests/
├── __init__.py
├── unit/              # Fast, isolated, no external dependencies
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_main.py
│   └── test_<module>.py
├── integration/       # Requires Docker Compose (PostgreSQL, Redis, S3)
│   └── __init__.py
├── property/          # Hypothesis property-based tests
│   └── __init__.py
└── smoke/             # Post-deployment sanity checks
    └── __init__.py
```

## Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.property
@pytest.mark.smoke
```

Run specific categories:
```bash
pytest -m unit          # Fast, CI-friendly
pytest -m integration   # Requires Docker services
pytest -m property      # Hypothesis-based
pytest -m smoke         # Post-deployment
```

## Running Tests

```bash
# All tests
pytest

# Unit tests only (fast, no external deps)
pytest tests/unit/

# With coverage
pytest --cov=app --cov-report=term-missing tests/unit/

# Single file
pytest tests/unit/test_config.py -v
```

## Test Organization Conventions

### Class-Based Grouping

Group related tests into classes. Each class tests one concern:

```python
class TestRequiredFields:
    """Missing required fields should raise ValidationError."""

    def test_missing_database_url_raises(self) -> None:
        ...

    def test_missing_redis_url_raises(self) -> None:
        ...


class TestDefaults:
    """Verify that default values match requirements."""

    def setup_method(self) -> None:
        self.settings = Settings(**VALID_BASE)

    def test_jwt_access_token_expire_seconds_default(self) -> None:
        assert self.settings.jwt_access_token_expire_seconds == 3600
```

### Naming

- Test files: `test_<module_name>.py` mirroring the source module
- Test classes: `Test<Concern>` (e.g., `TestHealthCheck`, `TestBounds`, `TestCORSMiddleware`)
- Test methods: `test_<behavior_under_test>` — descriptive, reads as a sentence

### Module Docstrings

Every test module starts with a docstring explaining what's tested and which requirements are covered:

```python
"""
Unit tests for app.config — Settings validation and defaults.

Requirements covered: 8.1 (config foundation), 8.2 (JWT max 3600 s).
"""
```

## Environment Setup for Tests

Tests that import application code need valid environment variables. Set them at the top of the test module before importing app modules:

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----")

# Clear settings cache so overrides take effect
from app.config import get_settings
get_settings.cache_clear()
```

Always clear the `get_settings` cache when overriding env vars to avoid stale singleton state.

## Fixtures

### Module-Scoped TestClient

For endpoint tests, use a module-scoped `TestClient`:

```python
@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a synchronous test client for the FastAPI app."""
    test_app = create_app()
    return TestClient(test_app, raise_server_exceptions=True)
```

### Async Fixtures

For integration tests requiring async DB sessions:

```python
@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()
```

## Unit Test Patterns

### Testing Pydantic Settings/Models

- Test required fields raise `ValidationError` when missing
- Test default values match requirement specifications
- Test boundary conditions (min/max validators)
- Use a `VALID_BASE` dict as the minimal valid config, then exclude/override individual fields

```python
VALID_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost/db",
    "redis_url": "redis://localhost:6379/0",
    "s3_bucket_name": "test-bucket",
    "jwt_private_key": "...",
    "jwt_public_key": "...",
}

def test_jwt_expiry_cannot_exceed_3600(self) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**VALID_BASE, "jwt_access_token_expire_seconds": 3601})
```

### Testing Endpoints

- Assert status codes, content types, and response body structure
- Test both success and error paths
- Verify error responses follow the standard JSON structure (`code`, `message`)

```python
class TestHealthCheck:
    def test_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_body_contains_status_ok(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
```

### Testing Services

- Mock external dependencies (DB, Redis, S3, KMS)
- Test business logic in isolation
- Verify audit log entries are created for state-changing operations

## Property-Based Testing (Hypothesis)

Property tests validate invariants that must hold for all valid inputs. Each property test:

1. Has a clear property statement in the docstring
2. References the requirement it validates
3. Uses Hypothesis strategies to generate inputs

```python
from hypothesis import given, strategies as st

@given(expiry=st.integers(min_value=60, max_value=3600))
def test_jwt_expiry_always_bounded(expiry: int) -> None:
    """Property 27: JWT expiry is always ≤ 3600 seconds (Req 8.2)."""
    settings = Settings(**{**VALID_BASE, "jwt_access_token_expire_seconds": expiry})
    assert settings.jwt_access_token_expire_seconds <= 3600
```

## Integration Test Patterns

Integration tests require running services (PostgreSQL, Redis). They verify:

- Database queries with RLS enforcement
- End-to-end request flows through the full middleware stack
- Celery task execution
- S3/KMS operations (via LocalStack)

Use Docker Compose to spin up dependencies. Mark with `@pytest.mark.integration`.

## What to Test for Each New Feature

When implementing a new feature, write tests that cover:

1. **Happy path** — valid input produces expected output
2. **Validation errors** — invalid input returns 422 with field-level errors
3. **Auth failures** — missing/invalid/expired token returns 401
4. **Permission denied** — wrong role returns 403
5. **Tenant isolation** — tenant A cannot access tenant B's data
6. **Edge cases** — empty collections, max lengths, boundary values
7. **Requirement-specific invariants** — property tests for documented constraints
