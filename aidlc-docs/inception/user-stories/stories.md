# User Stories — Credly-Style Credentialing

**Organization**: Persona-based (Q1=A). **Granularity**: coarse — one story per capability (Q2=A).
**Acceptance criteria**: Given/When/Then for core paths + bullets for edge cases (Q3=C).
**Priority**: none (Q4=B) — all in-scope stories are equal.

Each story is Independent, Negotiable, Valuable, Estimable, Small, Testable (INVEST) and traces to
requirement IDs. `[PBT]` marks invariants the property-based-testing extension must cover.

---

## Tenant Admin (P1)

### S1 — Create/edit a BadgeClass  (FR-1.1, FR-1.2, FR-2.4)
**As a** Tenant Admin, **I want** to create and edit badge templates (name, description, criteria,
tags/skills, alignment URLs, validity period, image), **so that** issuers can award standardized badges.
- **Given** I am an authenticated Tenant Admin, **when** I submit a valid BadgeClass, **then** it is
  created active within my tenant and available for issuance.
- **Given** an existing BadgeClass, **when** I edit its metadata, **then** changes apply to future
  issuances (already-issued assertions are unaffected).
- Edge: reject invalid fields (empty name, bad URL) with 422; BadgeClass is tenant-scoped (RLS) — not
  visible to other tenants. `[PBT: tenant isolation invariant]`

### S2 — Upload badge image  (FR-2.3, FR-3 image handling)
**As a** Tenant Admin, **I want** to upload a PNG/SVG for a BadgeClass, **so that** issued badges have
recognizable art and can be baked.
- **Given** a BadgeClass, **when** I upload a valid image, **then** it is stored (S3) and referenced by
  the class.
- Edge: reject oversized/invalid mime types; malware scan applies as with other uploads.

### S3 — Set issuer profile  (FR-1.2, FR-2.4)
**As a** Tenant Admin, **I want** to set my tenant's issuer profile (name, url, email), **so that**
hosted assertions carry a valid Open Badges issuer and pass validators.
- **Given** issuer profile fields, **when** I save them, **then** the hosted issuer profile document
  reflects them and assertions reference it.
- Edge: assertions cannot be issued for public verification until a minimally valid issuer profile exists.

### S9 — View analytics dashboard  (FR-6.1, FR-6.2)
**As a** Tenant Admin, **I want** issued/accepted/public/verified counts (per BadgeClass, over time)
plus share-channel breakdown and top badges, **so that** I can measure program adoption.
- **Given** activity exists, **when** I open analytics, **then** counts are accurate and tenant-scoped.
- Edge: empty state renders zeros; metrics never include other tenants' data. `[PBT: tenant isolation]`

### S12 — Manage directory visibility  (FR-5.1, FR-5.3)
**As a** Tenant Admin, **I want** to control which BadgeClasses appear in my tenant's public catalog,
**so that** only intended templates are discoverable.
- **Given** a BadgeClass, **when** I toggle its catalog visibility, **then** the public directory
  reflects the change; earner opt-in still governs earner listing.

---

## Issuer (P2)

### S4 — Issue a badge to an earner  (FR-2.1, FR-2.2, FR-1.3, FR-1.4)
**As an** Issuer, **I want** to issue a BadgeClass to an earner (by email/beneficiary_id), **so that**
the earner receives a verifiable badge.
- **Given** an active BadgeClass, **when** I issue to a valid earner, **then** a BadgeAssertion and a
  linked `documents` row are created, audited, and anchored, and the earner is notified.
- **Given** issuance, **then** a hosted OB 2.0 assertion is available at a stable URL.
- Edge: reject issuance for archived class or cross-tenant class (403); expiry derived from class.

### S5 — Bulk issue a badge  (FR-2.6)
**As an** Issuer, **I want** to issue a BadgeClass to many earners at once, **so that** I can award a
cohort efficiently.
- **Given** a roster (CSV/JSON), **when** I submit bulk issuance, **then** each record is processed
  independently and a summary reports successes/failures.
- Edge: one bad row does not block others; batch size limits enforced. `[PBT: record independence]`

### S6 — Revoke a badge  (FR-2.7, FR-7.1)
**As an** Issuer, **I want** to revoke an issued badge with a reason, **so that** invalid credentials
stop verifying.
- **Given** an active assertion, **when** I revoke it with a 1-500 char reason, **then** its status
  becomes revoked and hosted verification reports revoked.
- Edge: double-revoke returns conflict; cross-tenant revoke rejected. `[PBT: revoked never reports valid]`

---

## Earner / Beneficiary (P3)

### S7 — View my wallet  (FR-3.1, FR-3.2, FR-3.4)
**As an** Earner, **I want** to log in (OTP) and see my badges, **so that** I can manage my credentials.
- **Given** I authenticate via OTP, **when** I open my wallet, **then** all my (non-hidden) badges are
  listed with status and issue date.
- Edge: hidden badges are excluded from the default view; wallet shows only my own badges. `[PBT: isolation]`

### S8 — Hide/delete a badge from my wallet  (FR-3.2)
**As an** Earner, **I want** to hide or remove a badge from my wallet view, **so that** I control what
I see.
- **Given** a badge in my wallet, **when** I hide it, **then** it no longer appears by default and is
  not public.
- Edge: hiding never exposes it publicly; deleting is reversible only by re-issuance (documented).

### S10 — Make a badge public  (FR-3.3, FR-4.1, FR-5.2)
**As an** Earner, **I want** to opt a specific badge into public visibility, **so that** it appears on
my public page and (optionally) the directory.
- **Given** a private badge (default), **when** I opt it public, **then** its public page becomes
  accessible and it may be listed for that BadgeClass.
- **Given** a never-opted badge, **then** it is never publicly accessible or listed.
  `[PBT: private-by-default invariant]`
- Edge: opting out re-hides it from all public surfaces.

### S11 — Share a badge  (FR-4.1, FR-4.2, FR-4.3, FR-4.4)
**As an** Earner, **I want** to share a public badge (Open Graph preview, LinkedIn "Add to Profile"
deep link) and have a public profile page, **so that** I can showcase achievements.
- **Given** a public badge, **when** I generate a share link for a channel, **then** the link carries a
  channel tag (for analytics) and the public page renders correct Open Graph meta.
- **Given** my public profile, **then** it lists all my public badges.
- Edge: sharing a non-public badge is not possible; LinkedIn deep link is built from assertion fields
  without any LinkedIn account. `[PBT: share URL round-trip / channel tag preserved]`

---

## Verifier / Public (P4)

### S13 — Fetch & verify a hosted assertion  (FR-2.2, FR-7.1, FR-7.2, NFR-3)
**As a** Verifier, **I want** to fetch a badge's hosted OB 2.0 assertion and confirm validity, **so
that** I can trust the credential.
- **Given** an assertion URL, **when** I fetch it, **then** I receive standards-compliant OB 2.0 JSON
  that passes a third-party validator, referencing a valid issuer profile.
- **Given** verification, **then** the analytics view counter increments.
- Edge: revoked/expired assertions report their state; invalid IDs return not-valid without leaking data.
  `[PBT: assertion serialize→parse round-trip; OB 2.0 shape invariant]`

### S14 — Browse the public directory  (FR-5.1, FR-5.2, FR-5.3, NFR-1)
**As a** member of the public, **I want** to browse a tenant's public badge catalog and (privacy-gated)
public earners, **so that** I can discover credentials.
- **Given** the directory, **when** I search, **then** I see catalog BadgeClasses and only earners who
  opted public.
- Edge: no private data appears; pagination performs at target scale (10M+). `[PBT: only-public listed]`

### S15 — View a public badge / earner page  (FR-4.1, FR-4.3)
**As a** member of the public, **I want** to open a shared badge page or an earner's public profile,
**so that** I can see the achievement and verify it.
- **Given** a public badge link, **when** I open it, **then** I see badge details, issuer, a
  verification link, and correct social preview metadata.
- Edge: links to non-public or revoked badges show an appropriate state, never private fields.

---

## Coverage Check (stories → requirements)
- FR-1 covered by S1, S4. FR-2 by S3, S4, S5, S6, S13. FR-3 by S7, S8, S10. FR-4 by S10, S11, S15.
  FR-5 by S12, S14, S10. FR-6 by S9. FR-7 by S6, S13.
- NFR-1 (scale) exercised by S14; NFR-3 (OB compliance) by S13; NFR-4 (PBT) tags across S1, S5, S6,
  S7, S9, S10, S11, S13, S14.
- All FR-1..FR-7 have at least one covering story. ✔
