# Unit Test Instructions

Fast, isolated tests (no live external services). Run inside the API container.

## Run all unit tests
```bash
docker exec repo_as_saas-api-1 python -m pytest tests/unit -q
```

## Run only the Credly-feature unit tests (U1–U4)
```bash
docker exec repo_as_saas-api-1 python -m pytest \
  tests/unit/test_openbadges.py \
  tests/unit/test_badge_event_service.py \
  tests/unit/test_wallet_service.py \
  tests/unit/test_certificate_renderer.py \
  tests/unit/test_issuer_signing_service.py \
  tests/unit/test_share_service.py \
  tests/unit/test_identity_masking.py -q
```

## Coverage per unit
| Unit | File | What it covers |
|---|---|---|
| U1 | test_openbadges.py | OB 2.0 serialize, salted-hash recipient, expiry/revoke, parse round-trip |
| U1 | test_badge_event_service.py | event-type validation guard |
| U2 | test_wallet_service.py | hide/unhide, delete→private, revoked-can't-publish (409), not-owned→None |
| U4 | test_certificate_renderer.py | all 4 templates emit valid PDF, revoked watermark, missing-image, bad-template fallback |
| U4 | test_issuer_signing_service.py | RS256 keypair generation, sign/verify round-trip, foreign-key rejection |
| U3 | test_share_service.py | LinkedIn deep link, OG meta, channel URL round-trip |
| U3 | test_identity_masking.py | email masked (never leaks local part), handle pass-through |

## Verified status (this stage) — ALL GREEN
- Full `tests/unit` + `tests/property`: **224 passed, 0 failed, 63 warnings** (`RC=0`).
- Credly-feature subset (U1–U4): 60 passed.

## Pre-existing failures — FIXED
Six tests unrelated to U1–U4 were failing on entry to this stage; all were test-harness issues (not
product bugs) and have been corrected:
| Test | Fix applied |
|---|---|
| test_config.py::...celery_broker_defaults_to_redis_url | isolate env (clear `REDIS_URL`/`CELERY_*`, `_env_file=None`) so the kwarg drives the default |
| test_config.py::...celery_backend_defaults_to_redis_url | same |
| test_audit_properties.py::...failed_audit_insert_propagates_exception | `db.add` mocked with sync `MagicMock` (Session.add is sync; AsyncMock swallowed the side_effect) |
| test_audit_properties.py::...record_does_not_commit_independently | `db.add = MagicMock()` to avoid un-awaited-coroutine warning |
| test_tier2_properties.py::...rate_limiter_blocks_when_over_limit | `redis.pipeline = MagicMock(return_value=pipe)` (pipeline() is sync, not a coroutine) |
| test_tier2_properties.py::...rate_limiter_allows_under_limit | same |
| test_tier2_properties.py::...audit_failure_propagates_to_caller | sync `MagicMock` for `db.add` |

Remaining 63 warnings are deprecation notices (passlib `crypt`, jose `utcnow`, reportlab `ast`) and a
few benign "coroutine never awaited" in untouched tier2 tests — non-blocking.
