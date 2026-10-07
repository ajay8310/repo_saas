# U4 Certificates & Issuer Signing — Code Generation Summary

Downloadable, issuer-signed certificates with issuer-selectable templates, a
recipient photo on the certificate and public page, and per-tenant signing keys.

## Created files
- `alembic/versions/006_certificates.py` — adds `badge_classes.certificate_template`
  (CHECK classic|modern|elegant|minimal), `badge_assertions.recipient_photo_s3_key`,
  and tenant issuer-signing-key columns. Reversible.
- `app/services/issuer_signing_service.py` — per-tenant RS256 keypair (generate/idempotent),
  `sign`, `public_pem`/`public_jwk_reference`. Private key sealed via vault when PII encryption on.
- `app/services/certificate_renderer.py` — `CertificateContext` + 4 templates (classic/modern/
  elegant/minimal); embeds student photo, badge image, QR→public verify page; revoked watermark;
  issuer signature in PDF metadata.
- `app/services/certificate_service.py` — `build_certificate` (resolve, fetch images, sign with
  issuer key, render) + `upload_recipient_photo` (malware-scanned → S3).
- `tests/unit/test_certificate_renderer.py` (10), `tests/unit/test_issuer_signing_service.py` (3),
  `tests/property/test_certificate_properties.py` (3).
- `frontend/src/lib/wallet.ts` — wallet API client + earner certificate download.
- `frontend/src/pages/beneficiary/WalletPage.tsx` — recipient wallet (U2 S7/S9/S10/S11/S12) +
  certificate download (U4).

## Modified files
- `app/models/tenant.py` — issuer signing key columns.
- `app/models/badge.py` — `certificate_template` on BadgeClass, `recipient_photo_s3_key` on BadgeAssertion.
- `app/services/badge_service.py` — allow `certificate_template` in update whitelist.
- `app/services/public_badge_service.py` — hosted assertion exposes recipient photo presigned URL
  (only when public, Q8) + issuer key URL; `get_issuer_public_key`.
- `app/routers/badges.py` — list templates, set template, upload photo, download certificate (issuer).
- `app/routers/wallet.py` — earner certificate download (ownership-checked).
- `app/routers/public_badges.py` — issuer public-key endpoint.
- `app/rbac/permissions.py` — `badge:certificate`, `badge:wallet_certificate`.
- `app/config.py` — `certificate_default_template`, `certificate_photo_max_bytes`.
- `frontend/src/lib/badges.ts` — templates, photo upload, certificate download, PDF save helper.
- `frontend/src/pages/tenant/BadgeClassesPage.tsx` — per-class certificate template picker.
- `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx` — Wallet route + nav.
- `tests/property/strategies.py` — certificate + signing-payload strategies.

## Verification performed
- Full app import in API container: RC=0.
- `pytest` U4 unit + property: **16 passed**.
- Frontend `tsc --noEmit`: CLEAN_NO_ERRORS.
- Migration applied to live DB (see below).

## Decisions honoured
Q1=A template set · Q2=A per-class template · Q3=A PDF · Q4=A earner+issuer download ·
Q5=A full content · Q6=A photo upload to S3 (scanned) · Q7=A per-tenant RS256 issuer signature,
public key published · Q8=A photo public only when assertion public.

## Honest constraints
- "Issuer-signed" = per-tenant RS256 JWS over the credential payload, verifiable with the issuer's
  published public key (embedded in PDF metadata). Not a PAdES/X.509 embedded visible PDF signature.
- A QR cannot carry a photo; the QR links to the hosted page that shows the same photo live — the
  tamper-evident equivalent (confirmed with user).
- Issuer private keys sealed via vault when `pii_encryption_enabled`, else plaintext column (same
  posture as platform JWT keys). Flagged for ops hardening.

## Note
This unit also delivered the previously-pending U2 wallet frontend (WalletPage + wallet.ts + route/nav).
