# U6 — Live Documents + Dual Credential Downloads — Implementation Plan

Backs `aidlc-docs/construction/u6-dual-credentials/design.md`. Checkboxes updated
in the same interaction work completes. No DB migration.

## Part A — Backend badge build + baking  ✅ COMPLETE
- [x] A1. `app/services/badge_baker.py` — `bake_png`, `read_baked`, `BadgeImageNotBakeableError`, `OB_KEYWORD="openbadges"`. Verified bake→read round-trip; SVG/garbage/empty rejected.
- [x] A2. Extended `CertificateService`: `RenderedBadge` dataclass, `_assertion_doc` (OB2.0 via `OpenBadgesSerializer`), `build_badge_json`, `build_badge_png` (fetches class PNG, bakes; raises `BadgeImageNotBakeableError` on missing/SVG), `_resolve_for_badge` (ownership check), `_record_badge_download` (audit `badge:badge_download` + `viewed`/channel=badge event). Verified OB required fields, recipient hashed, HostedBadge verification, revoked flag.
- [x] A3. `IssuanceService.list_assertions(tenant_id, status?, limit, offset)` — tenant-scoped, newest first.
- Verified: all Part A smoke checks pass; `import app.main` (+ all routers) clean. (Note: badge_baker + openbadges imports in certificate_service.py were reverted once by the editor reformat; re-added and grep-confirmed.)

## Part B — Endpoints  ✅ COMPLETE
- [x] B1. `app/routers/badges.py`: `GET /badges/assertions` (`badge:read`, per-class name lookup) + `AssertionListItem`; `GET /badges/assertions/{id}/badge.json` + `/badge.png` (`badge:certificate`), 404 not-found, 422 not-bakeable. Imported `BadgeImageNotBakeableError`.
- [x] B2. `app/routers/wallet.py`: `GET /wallet/{id}/badge.json` + `/badge.png` (`badge:wallet_certificate`, `require_owner=user.sub`).
- Verified live: list 200; issuer badge.json 200 (valid OB2.0 @context/type/badge/verification=HostedBadge); issuer badge.png 200 image/png (2640 B); baked PNG round-trips (read_baked → type=Assertion, badge name); wallet json+png 200; cross-owner 404; classes with no/missing image → 422 (correct).
- Also fixed `app/seed_demo.py`: added `_ensure_badge_image` so a LocalStack S3 reset (DB row survives) re-attaches the demo badge image — found during Part B that the seeded image object was absent (NoSuchKey), which is what produced the 422; U6 code was correct.

## Part C — Backend tests + verify  ✅ COMPLETE
- [x] C1. `tests/unit/test_badge_baker.py` (11: bake valid PNG, keyword, embed, round-trip, read-none, reject empty/SVG/garbage/JPEG) + `tests/unit/test_badge_download_service.py` (11: build_badge_json ok/404/owner-mismatch/revoked, build_badge_png ok+roundtrip/no-image/SVG/fetch-fail/owner-mismatch, list_assertions rows/empty).
- [x] C2. `tests/property/test_badge_download_properties.py` (3: bake→read round-trip for arbitrary dict + any PNG; OB required-fields invariant; revoked-always-flagged). RBAC reuse (`badge:certificate`/`badge:wallet_certificate`) covered by existing permission-map property tests + the live cross-owner 404.
- [x] C3. New U6 suite: 25 passed. Broader sweep `-k 'badge or certificate or wallet or template or assertion'`: **121 passed, 0 failed**. No regressions.

## Part D — Frontend  ✅ COMPLETE
- [x] D1. `lib/badges.ts`: `AssertionListItem`, `listAssertions`, `downloadBadgePng`, `downloadBadgeJson`, `saveBlob` (+ `savePdfBlob` alias kept). `lib/wallet.ts`: `downloadWalletBadgePng/Json`.
- [x] D2. Rewrote `DocumentsPage.tsx` → "Issued Credentials": live `listAssertions`, columns Credential/Badge/Beneficiary/Status/Issued/Downloads, per-row PDF + Badge-PNG + Badge-JSON + Revoke, loading/empty/error states, search, "Issue from Badges" link. Dropped demo rows, JSON stub, DigiLocker column, and the upload/bulk modals (issuance lives on Badges page). PNG 422 shows a clear "add a PNG badge image" message.
- [x] D3. `WalletPage.tsx`: added Badge (PNG) + JSON buttons beside Certificate; handlers via dynamic import + saveBlob; 422 message for no-PNG.
- [x] D4. `tsc --noEmit` clean. All 4 modules serve 200; live proxy downloads verified: list 10 rows; cert PDF 7845 B, badge PNG 2640 B, badge JSON 1253 B.

## Part E — End-to-end verify + docs  ✅ COMPLETE
- [x] E1. Live via :3000 proxy: issuer list → 10 rows; issuer downloads PDF 200 (7845 B) + badge PNG 200 (2640 B) + badge JSON 200 (1253 B, valid OB2.0 @context/type/badge/verification=HostedBadge/recipient.hashed); downloaded PNG round-trips (read_baked → Assertion + badge name); no-image class → PNG 422 + JSON 200 (graceful); beneficiary wallet PDF+PNG+JSON all 200; cross-owner → 404.
- [x] E2. Updated `aidlc-docs/aidlc-state.md` (U6 complete); logged in `audit.md`; temp files cleaned (host + container).

## Rollback / safety
- Additive only; no migration. New endpoints + frontend wiring. Certificate and
  hosted public JSON paths untouched. Reverting = remove the new routes/helpers
  and restore the Documents demo rows (git).
