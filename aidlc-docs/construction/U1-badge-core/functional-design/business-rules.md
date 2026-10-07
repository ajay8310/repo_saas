# U1 Badge Core — Business Rules

- BR-1: A BadgeClass belongs to exactly one tenant; all reads/writes are RLS-scoped.
- BR-2: `name` is required (1-255). `validity_days`, if set, must be ≥ 1. `criteria_url`/`alignment`
  URLs, if set, must be valid URLs. Invalid → 422.
- BR-3: Only `active` BadgeClasses may be issued from. Archived classes reject issuance (403/404 uniform).
- BR-4: Issuance requires a minimally valid issuer profile (name + url) on the tenant; otherwise
  issuance is blocked (assertions must be verifiable per strict OB 2.0). → 409/422 with clear message.
- BR-5: `expires_at` = `issued_at + validity_days` when set, else null. Never arbitrary. (Q2=C)
- BR-6: `credential_id == assertion.id == documents.id` — one public identifier. (Q1=B)
- BR-7: Recipient identity in the hosted assertion is a salted SHA-256 hash, never raw email (OB privacy).
- BR-8: Revocation is one-way (active → revoked). Double revoke → 409. Cross-tenant revoke → 403.
- BR-9: Revoked assertion returns HTTP 200 with `revoked:true` + `revocationReason`. (Q3=A)
- BR-10: Expired assertion reports `expired` on verify; not deleted.
- BR-11: Bulk issuance ≤ platform bulk limit; each row independent; partial success allowed.
- BR-12: New assertions are `accepted=true` (auto), `public=false` (private-by-default), `hidden=false`.
- BR-13: Every state-changing operation writes an audit entry (reuse) and a BadgeEvent.
- BR-14: Image upload is malware-scanned (reuse); reject non-image mime / oversize → 422.
