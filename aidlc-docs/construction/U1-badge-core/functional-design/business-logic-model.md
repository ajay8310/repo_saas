# U1 Badge Core — Business Logic Model

## Issuance flow (IssuanceService.issue)
1. Load BadgeClass; assert active + tenant-owned (RLS). Reject archived/cross-tenant → 403/404.
2. Compute expiry: if `validity_days` set → `expires_at = issued_at + validity_days`; else null (Q2=C).
3. Create linked `documents` row (reuse encryption/S3/audit/anchoring). The assertion payload stored
   is the canonical OB assertion JSON (small); credential_id = documents.id.
4. Create BadgeAssertion with id = documents.id (Q1=B), accepted=true, public=false.
5. Audit "document:issue"/"badge:issue"; anchor commitment (reuse).
6. `BadgeEventService.record("issued", badge_class_id, assertion_id)`.
7. Enqueue issuance notification (reuse notification task).
8. Return { assertion_id (=credential_id), assertion_url }.

## Bulk issuance (Q4=A, in U1)
- `bulk_issue` inserts a `bulk_jobs` row, enqueues `bulk_issue_badges` Celery task.
- Task processes each beneficiary in an independent savepoint (record independence); writes per-row
  results to the job summary. One bad row never blocks others.

## Hosted OB 2.0 assertion (OpenBadgesSerializer)
- `assertion_json`: `{ "@context", "type":"Assertion", "id": <assertion_url by credential_id>,
  "recipient": {hashed identity, salted}, "badge": <badge_class_url>, "issuedOn", "expires"?,
  "verification": {"type":"HostedBadge"}, "revoked"?: true, "revocationReason"? }`.
- `badge_class_json`: `{ "type":"BadgeClass", "id", "name", "description", "criteria", "image",
  "issuer": <issuer_url>, "tags", "alignment" }`.
- `issuer_profile_json`: `{ "type":"Issuer"/"Profile", "id", "name", "url", "email" }`.
- Recipient identity is **hashed** (sha256 + salt) per OB 2.0 privacy guidance, not raw email.

## Revocation (Q3=A)
- `revoke(assertion_id, reason)`: set status=revoked, revoked_at, reason (1-500). Reuse existing
  document revoke path. Hosted assertion continues to return HTTP 200 with `revoked:true` +
  `revocationReason` (OB-compliant). Record "revoked" event.
- Double revoke → 409; cross-tenant → 403.

## Verification (public subset in U1)
- `GET /obadges/verify/{credential_id}` → status: valid | revoked | expired | invalid.
  - expired if expires_at < now; revoked if status=revoked; invalid if not found.
- Records "verified"/"viewed" event (async-aggregated in U3, but event append lives here).

## Error handling
- Field validation → 422. Archived/cross-tenant class → 403/404 (uniform, Q7=A). Missing image on
  bake attempt → N/A (baking deferred). KMS/S3 unavailable → 503 (reuse).

## Testable Properties (PBT-01)
- [PBT-02] assertion_json serialize → parse round-trip preserves id/badge/issuedOn/expires.
- [PBT-03] expiry invariant; revoked-never-valid; single-identifier invariant.
- [PBT-11 complementary] example tests for issue/bulk/revoke/verify happy + edge paths.
- [PBT-07] domain generators for BadgeClass/Assertion/bulk rosters.
