# Requirements — Credly-Style Credentialing Features

## Intent Analysis
- **User request**: Add the additional features that Credly (by Pearson) has, feasible without external third-party accounts.
- **Request type**: New Feature (major capability set)
- **Scope estimate**: System-wide — new DB tables + migration, models, services, routers, Celery tasks, frontend pages.
- **Complexity estimate**: Complex — Open Badges standards compliance, recipient wallet, sharing, public directory, analytics.
- **Depth**: Comprehensive.
- **Extensions in effect**: Security = disabled; Resiliency = enabled; Property-Based Testing = enabled.

## Feature Summary
Add a badge/credential capability layered on the existing multi-tenant repository: tenants define
**BadgeClasses** (templates), issue **BadgeAssertions** to earners (reusing beneficiary identity),
earners view them in a **wallet**, opt individual badges into **public pages / directory**, share via
**Open Graph + LinkedIn deep links**, and tenant admins see **analytics**. Assertions are
**Open Badges 2.0**-compliant (hosted verification, valid issuer profile), with a documented path to
**OB 3.0 / W3C Verifiable Credentials** (signed) as a future increment.

---

## Functional Requirements

### FR-1 Badge model (Q1=C, Q2=E)
- FR-1.1 Introduce a first-class **BadgeClass** (template) table, tenant-scoped (RLS), holding: name,
  description, criteria (narrative + URL), tags/skills, image reference, alignment URLs (external
  frameworks), validity/expiry period, and status (active/archived).
- FR-1.2 Issuer profile fields (issuer name, url, email) are held at the **tenant** level and used in
  assertion issuer metadata.
- FR-1.3 Introduce a **BadgeAssertion** (issued instance) table, tenant-scoped, referencing a
  BadgeClass and an earner (`beneficiary_id`), with issued_at, expires_at (derived from class),
  status (active/revoked), acceptance state, and public-visibility flag.
- FR-1.4 **Hybrid storage**: each issued assertion also creates a linked `documents` row so existing
  storage, audit, anchoring, and revocation machinery is reused. The BadgeAssertion references the
  `documents.id` (credential_id).

### FR-2 Badge issuance (Q3=C, Q11=C)
- FR-2.1 Issue a badge to an earner: validate BadgeClass is active and belongs to the tenant; create
  assertion + linked document row; audit; anchor commitment; enqueue notification.
- FR-2.2 Serve a **hosted Open Badges 2.0 assertion** JSON at a stable URL for every assertion.
- FR-2.3 On download, produce a **baked PNG** (OB assertion embedded) in addition to hosted JSON.
- FR-2.4 Provide a valid **issuer profile** document and a `.well-known`/hosted issuer endpoint so
  assertions pass third-party OB 2.0 validators (strict compliance).
- FR-2.5 Design assertion generation so an **OB 3.0 / W3C VC (signed)** representation can be added
  later without schema breakage (documented extension path; not built now).
- FR-2.6 Support bulk issuance of a BadgeClass to many earners (reuse existing bulk pipeline pattern).
- FR-2.7 Support **revocation** of an assertion (reuse existing revocation + reason + notification);
  revoked assertions report revoked status via hosted verification.

### FR-3 Recipient wallet (Q4=A, Q5=A, Q8=A)
- FR-3.1 Earner identity reuses existing `beneficiary_id` (email) with the platform's OTP login.
- FR-3.2 Issued badges are **auto-added** to the earner's wallet (auto-accept); the earner may
  **hide/delete** a badge from their wallet view.
- FR-3.3 **Privacy default is private**: an assertion is NOT publicly visible or listed in the
  directory until the earner **explicitly opts it in** (public-visibility flag = true). Auto-accept
  governs only the earner-facing wallet, never public exposure.
- FR-3.4 Wallet endpoint lists an earner's badges (active/hidden), with per-badge public toggle.

### FR-4 Sharing (Q6=C)
- FR-4.1 **Public badge page** per assertion (only if opted public) rendering Open Graph meta tags
  for LinkedIn/X/Facebook link previews, plus a verification link and (optionally) baked image.
- FR-4.2 **LinkedIn "Add to Profile" URL builder** — construct the LinkedIn certification deep link
  from assertion fields (no LinkedIn API/account required).
- FR-4.3 **Shareable earner profile page** listing all of that earner's public badges.
- FR-4.4 Share actions produce a share URL tagged with the target **channel** (for analytics).

### FR-5 Public directory (Q7=B, Q8=A)
- FR-5.1 Per-tenant **public catalog of BadgeClasses** (templates), searchable.
- FR-5.2 Per BadgeClass, a **searchable list of public earners** — gated so only earners who opted
  that badge public appear.
- FR-5.3 Directory respects the private-by-default rule (FR-3.3).

### FR-6 Analytics (Q9=B)
- FR-6.1 Tenant-admin dashboard metrics per BadgeClass and over time: **issued**, **accepted**
  (in-wallet), **public/shared**, **verification/view** counts.
- FR-6.2 **Share-channel breakdown** (which channel each share URL was built for) and **top badges**.
- FR-6.3 Metrics are tenant-scoped (RLS) and derived from event counters (issue/accept/publish/
  share/verify events).

### FR-7 Verification (extends existing)
- FR-7.1 Hosted assertion verification returns validity (valid/revoked/expired/invalid) per OB 2.0
  semantics, reusing existing public-verification patterns.
- FR-7.2 A verification/view increments the analytics view counter (FR-6.1).

---

## Non-Functional Requirements

### NFR-1 Scale & performance (Q10=C)
- Target **10M+ assertions per tenant**. Requires: indexed foreign keys (tenant_id, badge_class_id,
  beneficiary_id), keyset/seek pagination for wallet & directory, and consideration of partitioning
  `badge_assertions` (e.g., by tenant or issued_at) — to be decided in Infrastructure/NFR Design.
- Directory and wallet list queries p95 < 1s at target scale; hosted assertion fetch p95 < 500ms.

### NFR-2 Multi-tenancy & isolation
- All new tables carry `tenant_id NOT NULL` with RLS enabled + forced and a `tenant_isolation`
  policy, consistent with existing architecture. Public endpoints (assertion JSON, public pages,
  directory) are unauthenticated but expose only opted-public data.

### NFR-3 Standards compliance (Q11=C)
- Strict **Open Badges 2.0**: valid issuer profile, hosted assertions, verification — passing a
  third-party OB validator. Documented, non-breaking path to **OB 3.0 / W3C VC (signed)**.

### NFR-4 Testing (PBT extension enabled)
- Property-based tests (Hypothesis) MUST cover, at minimum:
  - **PBT-02 round-trip**: OB assertion serialize → parse = identity; baked-PNG embed → extract = identity.
  - **PBT-03 invariant**: private-by-default (a never-opted-public assertion never appears in
    directory/public queries); revoked assertion never reports valid.
  - **PBT-07 generators**: domain generators for BadgeClass/Assertion respecting constraints.
- Complemented by example-based tests for critical paths (issue, accept, publish, verify, revoke).

### NFR-5 Resiliency (Resiliency extension enabled — user decisions)
- **RESILIENCY-01 (criticality)**: Badge feature classified **Medium** business criticality
  (value-add credentialing; not the core issuance path).
- **RESILIENCY-02 (RTO/RPO) [Q12=A]**: **Backup & Restore** strategy — RTO/RPO in **hours**. Relies
  on existing automated PostgreSQL backups and S3 versioning for badge images.
- **RESILIENCY-08 (topology) [Q13=A]**: **Single-region, multi-zone**, matching the existing
  deployment. No cross-region DR for this feature.
- **RESILIENCY-15 (incident response) [Q14=B]**: No formal process exists — a **lightweight incident
  response + Correction-of-Errors** process is to be proposed during NFR Design and referenced by
  alerting.
- Other RESILIENCY rules (auto-scaling, circuit breaking, health checks, observability) inherit the
  existing platform's mechanisms; feature-specific applicability assessed in NFR/Infrastructure Design.

### NFR-6 Security (Security extension disabled by user)
- Security-baseline rules are **not enforced** per user opt-out. Existing platform security (JWT,
  RBAC, RLS, encryption) still applies to new authenticated endpoints by reuse; public endpoints
  expose only opted-public data.

---

## Out of Scope (deferred, require external accounts/decisions)
- Live LinkedIn API integration (only deep-link URL building is in scope).
- Real W3C VC signing with DIDs / OB 3.0 issuance (design path only).
- LMS/HR connectors (LTI, SCORM, Workday, etc.).
- Endorsement graph and skills-taxonomy management beyond simple tags/alignment URLs.
- Email marketing campaigns beyond existing notification service.

## Key Requirements Summary
- New **BadgeClass** + **BadgeAssertion** tables (RLS), each assertion linked to a `documents` row.
- **Strict OB 2.0** hosted assertions + issuer profile + baked PNG; OB 3.0/VC as documented future path.
- **Wallet** on existing beneficiary/OTP identity; **auto-accept** to wallet but **private by default**
  for public exposure.
- **Public pages, LinkedIn deep-link, earner profile, per-tenant directory** with privacy-gated earners.
- **Analytics** with channel breakdown; target **10M+ assertions/tenant**.
- **Resiliency**: Backup & Restore, single-region multi-zone, propose lightweight IR.
- **PBT** enforced on serialization round-trips and privacy/revocation invariants.
