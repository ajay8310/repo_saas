# Build and Test — Summary

Covers the Credly-style credentialing work delivered this phase across four units,
built on the existing multi-tenant document/credential platform.

## Units delivered
| Unit | Scope | Status |
|---|---|---|
| U1 Badge Core | OB 2.0 badge classes, issuance (single + bulk), revoke, hosted assertions, issuer profile | ✅ built, live |
| U2 Wallet | earner wallet: view, hide, delete-from-wallet, public/private, share entry | ✅ built, live |
| U4 Certificates | downloadable PDF certs, 4 templates, student photo, per-tenant issuer signing | ✅ built, live |
| U3 Public + Analytics | public directory, earner profiles, sharing (LinkedIn/OG), issuer analytics + async rollup | ✅ built, live |

## Migrations
`005_badges` → `006_certificates` → `007_badge_analytics`. All applied to the live DB; each verified
reversible (upgrade → downgrade → upgrade). DB at `007 (head)`.

## Test results (verified this stage, in the API container) — ALL GREEN
- Full suite `tests/unit` + `tests/property`: **224 passed, 0 failed, 63 warnings (RC=0)**.
- Credly-feature subset (U1–U4): 60 passed.
- Frontend `tsc --noEmit`: **clean**.
- App import: **clean**; new routes present in live OpenAPI (badges, wallet, certificate,
  directory, share, analytics).

### Pre-existing failures fixed
Six failing tests on entry (unrelated to U1–U4) were corrected — all were test-harness issues, not
product bugs: 2× config celery-default (env isolation), 2× audit propagate (sync MagicMock for the
synchronous `Session.add`), 2× rate-limiter (sync MagicMock for the synchronous `redis.pipeline()`).
Details in unit-test-instructions.md.

## Property-based tests (Hypothesis) added
- U1: OB serialize↔parse round-trip, raw-identity-never-leaks, revoked-never-valid, expiry-iff-fixed.
- U2: delete→hidden+private, revoked-never-publishes, publish/unpublish invariants.
- U4: every template emits valid PDF; issuer JWS verifies with own key, rejects foreign key.
- U3: share-URL channel round-trip, masking-never-leaks, aggregation tenant-wide=sum, aggregate
  idempotence `aggregate(aggregate(x))==aggregate(x)`.

## Security / privacy posture
- RLS on every new tenant-scoped table (`badge_classes`, `badge_assertions`, `badge_events`,
  `badge_analytics_daily`); `tenants` is the root (no RLS).
- Earner identity masked on all public surfaces (never raw email).
- Per-IP throttle + short-TTL cache on unauthenticated public routes; uniform 404 for non-public.
- Per-tenant RS256 issuer signing; public key published for verification.
- Malware scanning on badge image + recipient photo uploads (never bypassed).

## Honest limitations (flagged for ops / future work)
- Issuer signing is RS256 JWS over the credential payload (verifiable via published key), **not** a
  PAdES/X.509 embedded visible PDF signature.
- Issuer private keys are vault-sealed when `pii_encryption_enabled`, else stored like the existing
  JWT keys (plaintext column) — harden before production.
- No automated integration/performance suites committed; instruction files above define how to run
  them. Cross-unit flows were exercised against the live stack.
- Rendered certificates are not cached; consider caching if render rate is high.

## How to run everything
```bash
docker compose up -d
docker exec repo_as_saas-api-1 alembic upgrade head
docker exec repo_as_saas-api-1 python -m pytest tests/unit tests/property -q
docker exec frontend npx tsc --noEmit
```
Then open http://localhost:3000 (app) and http://localhost:3000/directory (public directory).
