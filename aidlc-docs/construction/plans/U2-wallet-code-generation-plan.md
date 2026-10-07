# U2 Wallet — Code Generation Plan

**Single source of truth for U2 code generation.** Full-stack (Q3=B). Brownfield: modify existing
files in place. Application code at workspace root (never aidlc-docs/).

## Unit Context
- **Stories**: S7 (view wallet), S8 (accept — implicit; issuance defaults accepted=true), S9 (hide),
  S10 (delete-from-wallet, Q4=B soft delist), S11 (make public/private, private-by-default),
  S12 (share entry point — URL builder; full sharing UI lands with U3).
- **Depends on**: U1 `badge_assertions` (flags `accepted/hidden/public`), `BadgeClass`,
  `BadgeEventService`, auth (OTP earner identity == `beneficiary_id`), RLS.
- **New tables**: NONE (design: domain-entities.md). Operates on U1 tables via earner flags.
- **Design refs**: U2-wallet/functional-design/* (business-logic-model, business-rules,
  domain-entities, frontend-components).

## Steps

### Backend — Business logic
- [x] **Step 1** — `app/services/wallet_service.py` (`WalletService`):
  - `list_wallet(beneficiary_id, include_hidden=False)` → WalletItem DTOs (assertion + class summary),
    own-assertions-only (identity match + RLS), excludes hidden by default (BR-W1, BR-W2).
  - `hide` / `unhide` (BR-W2). `delete_from_wallet` → sets `hidden=true` + `public=false`, stays
    verifiable (BR-W4, Q4=B).
  - `set_public(public)` → flip public; guard revoked→public = 409 (BR-W5); record "published" event
    on transition to public=true (BR-W6). Private-by-default is the only public=true path (BR-W3).
  - Not-owned → return None → router 404 (BR-W7). `WalletItem` frozen dataclass DTO.

### Backend — API layer
- [x] **Step 2** — `app/routers/wallet.py` (auth, beneficiary role):
  - `GET /wallet?include_hidden=` · `POST /wallet/{assertion_id}/public` (body {public}) ·
    `POST /wallet/{assertion_id}/hide` (body {hidden}) · `DELETE /wallet/{assertion_id}`.
  - Pydantic request/response models; RBAC via new wallet permissions; wired into `app/main.py`.
- [x] **Step 3** — RBAC: added `badge:wallet_read`, `badge:wallet_manage` to `beneficiary` +
  super_admin + tenant_admin + issuer in `app/rbac/permissions.py`.

### Backend — Tests
- [x] **Step 4** — Unit tests `tests/unit/test_wallet_service.py` (9): hide/unhide, delete forces
  public=false, revoked→public guarded (WalletConflictError), not-owned→None, publish/unpublish,
  public_url. Fake async session. **Also fixed a real bug**: DELETE /wallet 204 route needed
  `response_class=Response` (FastAPI forbids a response body on 204).
- [x] **Step 5** — Property tests `tests/property/test_wallet_properties.py` [PBT-03/07] (4):
  delete-always-hidden-and-private, revoked-never-transitions-public, active-publish-sets-public,
  make-private-always-unsets-public — over random status × accepted/hidden/public combos. Wallet
  strategies added to `tests/property/strategies.py`. **13 passed** in the API container.

### Frontend (Q3=B)
- [ ] **Step 6** — `frontend/src/pages/beneficiary/WalletPage.tsx` + `WalletBadgeCard`:
  card grid (image, name, issued/expiry, status, public indicator); public/private toggle;
  hide; delete-from-wallet (confirm); share entry (copy public URL — LinkedIn/social with U3);
  revoked cannot be made public (disabled + tooltip). `data-testid` on interactive elements.
  Wire route + nav (beneficiary). Reuse Modal/Toast/api/AuthContext.
- [ ] **Step 7** — `frontend/src/lib/wallet.ts`: wallet API client + `WalletItem` type + public
  page URL builder.

### Docs
- [ ] **Step 8** — Code summary `aidlc-docs/construction/U2-wallet/code/summary.md`
  (created vs modified, story coverage, verification results).

## Story Traceability
S7→Steps 1,2,6 · S9→1,2,6 · S10→1,2,6 · S11→1,2,6 · S12→6,7 (URL builder; full UI in U3).

## Scope / Estimate
~8 steps. No migration (no new tables). One service, one router, RBAC delta, tests, earner frontend.

## Notes
- Reuses U1 `badge_assertions`; no schema change, so no Alembic migration in U2.
- "Accepted" (S8) is satisfied by U1 issuance default `accepted=true`; no explicit accept endpoint in
  U2 unless requested.
- Share (S12) URL builder is created here; LinkedIn/social share UI is completed in U3.
