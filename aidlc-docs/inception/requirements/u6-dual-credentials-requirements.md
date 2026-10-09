# U6 — Live Documents + Dual Credential Downloads (Requirements)

**Feature**: For every issued badge assertion, make two credentials downloadable
— (1) the issuer-signed **certificate PDF** (QR + digital signature, already
exists) and (2) the **badge**, offered in its two standard Open Badges forms:
a **baked PNG** (badge artwork with the OB2.0 assertion embedded in the PNG's
`openbadges` iTXt chunk) and the **raw OB2.0 assertion JSON**. Also replace the
**Documents** page's hardcoded demo rows + client-side JSON stub with a live
list of real issued assertions, each row exposing the three downloads. Surface
the badge downloads in the beneficiary **Wallet** too, next to the existing
certificate button.

**Depth**: Standard-plus (new user-facing capability; backend + frontend).
**Extensions**: Security OFF, Resiliency ON, PBT ON.

Confirmed decisions: Q1=C (both JSON + baked PNG), Q2 = no ZIP/batch, Q3=A
(Documents lists real assertions), Q4 = issuer + beneficiary surfaces, Q5 = same
access as the certificate download.

---

## 1. Scope

### In scope
- **Backend badge downloads** per assertion:
  - `badge.json` — the OB2.0 Assertion JSON (via the existing serializer).
  - `badge.png` — the badge class image baked with that assertion JSON embedded.
- **Authenticated download endpoints** mirroring the certificate routes:
  - Issuer/admin: `GET /badges/assertions/{id}/badge.json` and `/badge.png` (`badge:certificate`).
  - Beneficiary: `GET /wallet/{id}/badge.json` and `/badge.png` (`badge:wallet_certificate`, own only).
- **Tenant-wide assertion listing** (new): `IssuanceService.list_assertions(...)` + `GET /badges/assertions` (`badge:read`), returning assertion + badge-class summary (name, image key, status, dates), newest first, paginated.
- **Documents page rewired** to this live list: real rows, search over credential id / beneficiary / badge name, and per-row actions: **Certificate (PDF)**, **Badge (PNG)**, **Badge (JSON)** (plus existing Revoke where applicable). Remove the hardcoded `INITIAL_DOCS` and the JSON stub.
- **Wallet page**: add **Badge (PNG)** and **Badge (JSON)** buttons beside the existing Certificate button, for the earner's own assertions.
- Audit + analytics event on each badge download (mirror the certificate `viewed`/audit pattern).

### Out of scope
- ZIP/bundle downloads (explicitly dropped).
- Baking SVG badge images (OB baking needs raster PNG; SVG source is rejected with a clear error — no rasterizer dependency added).
- Signing/JWS inside the OB assertion JSON (verification remains HostedBadge; the certificate PDF keeps its RS256 signature).
- Making arbitrary generic repository documents produce certificates/badges (Documents now lists badge assertions, per Q3=A).
- Persisting a stable per-recipient salt (OB hashed identity stays non-deterministic across downloads — acceptable).

---

## 2. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-U6-1 | For any badge assertion, an authorized user can download the OB2.0 assertion JSON (`badge.json`), content-type `application/ld+json`, filename `badge-{assertion_id}.json`. |
| FR-U6-2 | For any assertion whose badge class has a **PNG** image, an authorized user can download a baked PNG (`badge.png`) with the same assertion JSON embedded in the PNG `openbadges` iTXt chunk; content-type `image/png`, filename `badge-{assertion_id}.png`. |
| FR-U6-3 | If the badge class has no image, or its image is SVG (not bakeable), `badge.png` returns a clear 422/409 ("badge image must be a PNG to produce a baked badge"), never a 500. The JSON download still works. |
| FR-U6-4 | The baked PNG and the JSON both reflect the assertion's current state (revoked → `revoked:true`; expiry; recipient hashed identity + salt), using the existing OB serializer. |
| FR-U6-5 | Issuer/admin can download badge.json/badge.png for any assertion in their tenant (`badge:certificate`). A beneficiary can download only their own (`badge:wallet_certificate`, ownership enforced like the wallet certificate route). |
| FR-U6-6 | A new authenticated endpoint lists all issued assertions for the caller's tenant (`GET /badges/assertions`, `badge:read`), newest first, with pagination, each item carrying assertion id, badge class id + name, beneficiary id, status, issued/expires, public/revoked flags. |
| FR-U6-7 | The Documents page lists real assertions from FR-U6-6 (replacing demo rows), supports search, and offers per-row Certificate (PDF), Badge (PNG), Badge (JSON) downloads. It degrades gracefully to an empty/)（offline state if the API is unreachable (no crash). |
| FR-U6-8 | The Wallet page shows Badge (PNG) and Badge (JSON) actions beside the existing Certificate action for each of the earner's assertions. |
| FR-U6-9 | Each successful badge download writes an audit entry (actor, assertion, kind=png/json) and a best-effort analytics event, consistent with certificate downloads. |

## 3. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-U6-1 (Security/tenant) | All downloads and the assertion list are tenant-scoped via `set_tenant_context`/RLS; a tenant cannot list or download another tenant's assertions, and a beneficiary cannot download another earner's. |
| NFR-U6-2 (Resiliency) | A missing/unreadable badge image degrades to the FR-U6-3 error for PNG only; JSON always succeeds for a resolvable assertion. No download path 500s on a missing asset. |
| NFR-U6-3 (Resiliency) | Baking never corrupts output: if Pillow can't open the image as PNG, the endpoint returns the FR-U6-3 error rather than a broken file. |
| NFR-U6-4 (Performance) | A single badge.json/png responds within the certificate-download latency envelope. Listing is paginated (default 50) and uses the keyed-lookup pattern (no N+1 join explosion), mirroring `list_wallet`. |
| NFR-U6-5 (PBT) | Property tests assert: baked PNG round-trips (embedded `openbadges` chunk parses back to the same assertion dict); the assertion JSON always contains the required OB fields (`@context`, `type`, `id`, `recipient.hashed`, `badge`, `issuedOn`, `verification`); revoked assertions always carry `revoked:true`. |
| NFR-U6-6 (Compatibility) | Existing certificate endpoints and the hosted public JSON are unchanged; U6 is additive. |
| NFR-U6-7 (Accessibility) | New Documents/Wallet action buttons have discernible labels/titles and are keyboard-operable. |

## 4. RBAC
- Reuse existing permissions: `badge:certificate` (issuer/admin badge downloads + list via `badge:read`), `badge:wallet_certificate` (beneficiary own badge downloads). No new permission.

## 5. Data model
- **No schema change required.** The OB assertion is derived from existing `BadgeAssertion` + `BadgeClass` + `Tenant` rows; the badge image is the class `image_s3_key`. (No migration in U6.)

## 6. API (additions)
- `GET /api/v1/badges/assertions` — list tenant assertions (`badge:read`), paginated.
- `GET /api/v1/badges/assertions/{id}/badge.json` — OB JSON (`badge:certificate`).
- `GET /api/v1/badges/assertions/{id}/badge.png` — baked PNG (`badge:certificate`).
- `GET /api/v1/wallet/{id}/badge.json` — earner OB JSON (`badge:wallet_certificate`, own).
- `GET /api/v1/wallet/{id}/badge.png` — earner baked PNG (`badge:wallet_certificate`, own).

## 7. Acceptance Criteria
1. On the Documents page (issuer), real issued assertions appear; each row downloads a signed certificate PDF, a baked badge PNG, and an OB JSON — all real files, no "demo export" stub.
2. The baked PNG opens as an image and, when parsed, yields the same OB assertion embedded in its `openbadges` chunk; the JSON validates as an OB2.0 Assertion.
3. A beneficiary in the Wallet can download all three for their own badges and cannot access another earner's (404).
4. A badge class with an SVG image returns a clear PNG-not-bakeable error for `badge.png` but still serves `badge.json`.
5. Tenant isolation holds for list + downloads; property tests for bake round-trip and OB field invariants pass; unit/integration tests cover list, both downloads, SVG rejection, ownership, and RBAC.

## 8. Risks / decisions to confirm in design
- **R1 Baking source**: use the class PNG image + embed assertion JSON (standard OB bakery). If a class has no image, `badge.png` is unavailable (JSON still works). **Recommended.** (Alternative: synthesize a placeholder badge image — more work, not requested.)
- **R2 Non-public downloads**: build `AssertionData` from tenant-scoped rows in an authenticated service path (do NOT reuse the `public`-gated `get_hosted_assertion`, so issuers/earners can download even before a badge is made public). **Recommended.**
- **R3 Where the badge-download logic lives**: extend `CertificateService` (it already fetches the class image + assertion + tenant and builds the OB-ish payload) with `build_badge_json` / `build_badge_png`, reusing `_fetch_s3`. **Recommended** over a new service, to avoid duplicating S3/row resolution.
