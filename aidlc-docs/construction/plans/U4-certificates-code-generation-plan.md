# U4 — Certificates & Issuer Signing — Code Generation Plan

**Single source of truth.** Full-stack. Brownfield: modify existing files in place. Application code at
workspace root. New unit added after the Credly-style U1/U2/U3 units at user request.

## Scope (confirmed Q1–Q8 = A)
- **Q1=A** Built-in certificate templates: `classic`, `modern`, `elegant`, `minimal` (no custom HTML).
- **Q2=A** Template chosen **per badge class** (`certificate_template` column on `badge_classes`).
- **Q3=A** PDF output only.
- **Q4=A** Downloadable by the **earner** (wallet) and the **issuer** (badge admin).
- **Q5=A** Content: badge name, recipient, issuer, issued/expiry dates, criteria, badge image,
  **student photo**, QR → public verification page; revoked → watermark.
- **Q6=A** Recipient **photo** uploaded per assertion → S3, malware-scanned, presigned URL.
- **Q7=A** Per-tenant **RS256 issuer signing keypair**; certificate signed with the issuer key;
  issuer **public key published** at the hosted issuer endpoint for verification.
- **Q8=A** Student photo shown on the public verification page **only when the assertion is public**.

### Design note (QR + photo)
A QR cannot carry a photo (size). The QR encodes the **public verification URL**; that page renders the
**same student photo live from the server** plus badge details, so a scan proves the printed cert matches
the issuer's record. Authenticity rests on the issuer digital signature + the live hosted page.

## Depends on
U1 (`badge_classes`, `badge_assertions`, issuer profile, `public_badges`), existing
`document_renderer` (QR/signing patterns to generalize), `malware_scanner`, S3 client pattern,
`BadgeEventService`.

## Steps

### Backend — Schema & models
- [ ] **Step 1** — Migration `006_certificates.py`:
  - `badge_classes`: ADD `certificate_template VARCHAR(32) NOT NULL DEFAULT 'classic'`
    (CHECK in classic/modern/elegant/minimal).
  - `badge_assertions`: ADD `recipient_photo_s3_key VARCHAR(1024) NULL`.
  - `tenants`: ADD `issuer_signing_public_key TEXT NULL`, `issuer_signing_private_key TEXT NULL`,
    `issuer_key_id VARCHAR(64) NULL`, `issuer_key_generated_at TIMESTAMPTZ NULL`.
    (Private key stored sealed via the vault/`pii_encryption` path when enabled; plaintext column
    otherwise — matches how JWT keys are already handled. Documented in summary.)
  - Reversible downgrade. Update `BadgeClass`, `BadgeAssertion`, `Tenant` models.
- [ ] **Step 2** — Register nothing new in `__init__` (columns only).

### Backend — Services
- [ ] **Step 3** — `app/services/issuer_signing_service.py` (`IssuerSigningService`):
  - `ensure_keypair(tenant_id)` → generate RS256 keypair if absent (cryptography), store on tenant,
    return key id + public key. `sign(tenant_id, payload)` → compact JWS with the issuer key.
    `public_jwk(tenant_id)` / `public_pem(tenant_id)` for publication. Idempotent; audit on generate.
- [ ] **Step 4** — `app/services/certificate_renderer.py` (generalize `document_renderer`):
  - `CertificateContext` dataclass (badge name, recipient display, issuer, issued/expiry, criteria,
    badge image bytes/url, **student photo bytes**, verify URL, status, revoked info, signature JWS).
  - `TEMPLATES: dict[str, Callable]` with `classic`, `modern`, `elegant`, `minimal` renderers
    (reportlab), each embedding the student photo, badge image, and QR → public verify URL; revoked
    watermark. `render_certificate(ctx, template)` dispatches. Signature (issuer JWS) embedded in PDF
    metadata. Reuse `generate_qr_png`.
- [ ] **Step 5** — `app/services/certificate_service.py` (`CertificateService`):
  - `build_certificate(tenant_id, assertion_id, actor_identity, is_earner)` → resolve assertion+class
    (ownership check for earner), fetch student photo + badge image from S3, ensure issuer keypair,
    sign the credential payload with the issuer key, render via the class's `certificate_template`,
    audit + `BadgeEvent('viewed'/'downloaded')`. Returns PDF bytes + filename.
  - `upload_recipient_photo(tenant_id, assertion_id, content, content_type)` → malware scan →
    S3 `badges/{tenant}/{class}/photos/{assertion}.ext` → set `recipient_photo_s3_key`.

### Backend — API & RBAC
- [ ] **Step 6** — Issuer/admin routes in `app/routers/badges.py`:
  - `POST /badges/assertions/{id}/photo` (upload recipient photo) ·
    `GET  /badges/assertions/{id}/certificate` (PDF download) ·
    `PUT  /badges/classes/{id}/template` (set certificate_template).
- [ ] **Step 7** — Earner route in `app/routers/wallet.py`:
  `GET /wallet/{assertion_id}/certificate` (PDF; ownership enforced).
- [ ] **Step 8** — Public: extend `public_badge_service` + `public_badges.py` so the hosted assertion
  response includes the **recipient photo presigned URL + issuer public key reference** when the
  assertion is public (Q8). Add `GET /public/badges/issuers/{tenant_id}/key` (issuer public JWK/PEM).
- [ ] **Step 9** — RBAC: add `badge:certificate` (issuer/tenant_admin/super_admin) and
  `badge:wallet_certificate` (beneficiary) to `app/rbac/permissions.py`; reuse `badge:update` for
  template + photo-by-issuer.

### Backend — Config & tests
- [ ] **Step 10** — `app/config.py`: `certificate_default_template='classic'`,
  `certificate_photo_max_bytes`, allowed photo content types.
- [ ] **Step 11** — Unit tests `tests/unit/test_certificate_renderer.py` (each template renders a
  non-empty PDF; revoked watermark path; missing-photo path) + `test_issuer_signing_service.py`
  (keypair idempotent, sign→verify round-trip with issued public key).
- [ ] **Step 12** — Property tests `tests/property/test_certificate_properties.py` [PBT-07]:
  issuer-signed JWS always verifies with the published public key over random payloads; every
  template name always produces a valid PDF header (%PDF). Strategies added to strategies.py.

### Frontend
- [ ] **Step 13** — `frontend/src/lib/badges.ts` + `wallet.ts`: certificate download (blob),
  photo upload, set-template, template list constant.
- [ ] **Step 14** — Badges admin (`BadgeClassesPage.tsx`): template picker per class (dropdown of 4),
  recipient-photo upload on an assertion, "Download Certificate" action. `data-testid`s.
- [ ] **Step 15** — Wallet page (built in U2 Step 6) gets a "Download Certificate" button per badge.
  (If U2 wallet page not yet present, create it here with the certificate action included.)

### Docs
- [ ] **Step 16** — Code summary `aidlc-docs/construction/U4-certificates/code/summary.md`.

## Verification
Build/import in API container; `alembic upgrade head` then `downgrade -1` reversibility; run new unit +
property tests; frontend `tsc --noEmit`. Clean up temp files.

## Notes / honest constraints
- "Issuer-signed" = per-tenant RS256 JWS over the credential payload, verifiable via the issuer's
  published public key, embedded in PDF metadata + JSON-LD proof. It is **not** a PAdES/embedded X.509
  visible PDF signature (would need provisioned signing certs + pyhanko) — out of scope per Q7=A.
- Private signing keys stored sealed through the existing vault path when `pii_encryption_enabled`,
  else plaintext column (same posture as existing JWT keys). Flagged for ops hardening.
- Photo-in-QR is physically infeasible; QR→live hosted page showing the same photo is the implemented,
  tamper-evident equivalent (confirmed with user).
