# Components — Credly-Style Credentialing

Design decisions: fine-grained services (Q1=A), dedicated public router (Q2=A), async analytics
aggregation (Q3=B), full frontend (Q4=A), baking deferred (Q5=B).

## Data Models (new)

### BadgeClass (model)
- **Purpose**: Tenant-scoped badge template.
- **Responsibilities**: Hold name, description, criteria (narrative+URL), tags/skills, alignment URLs,
  image reference (S3 key), validity/expiry period, status (active/archived), directory-visible flag.
- **Interfaces**: SQLAlchemy model; RLS `tenant_id`.

### BadgeAssertion (model)
- **Purpose**: Tenant-scoped issued instance of a BadgeClass to an earner.
- **Responsibilities**: Reference badge_class_id, beneficiary_id, linked `documents.id` (credential),
  issued_at, expires_at, status (active/revoked), accepted flag (auto-true), hidden flag,
  public flag (default false), revoked_at/reason.
- **Interfaces**: SQLAlchemy model; RLS `tenant_id`; FKs to badge_classes, documents.

### BadgeEvent (model)  — analytics source (Q3=B)
- **Purpose**: Append-only event stream for analytics aggregation.
- **Responsibilities**: Record event_type (issued|accepted|published|shared|verified|viewed),
  badge_class_id, assertion_id (nullable), channel (nullable, for shares), created_at.
- **Interfaces**: SQLAlchemy model; RLS `tenant_id`; consumed by async aggregator.

### BadgeAnalyticsDaily (model)  — aggregated rollup
- **Purpose**: Per-tenant, per-BadgeClass, per-day aggregated counts (produced by Celery task).
- **Responsibilities**: Store day, badge_class_id, counts by event_type, channel breakdown (JSONB).
- **Interfaces**: SQLAlchemy model; RLS `tenant_id`; read by AnalyticsService.

## Services (new, fine-grained — Q1=A)

### BadgeService
- **Purpose**: BadgeClass template lifecycle.
- **Responsibilities**: create/update/deactivate BadgeClass; validate fields; manage image reference;
  expose issuer-profile data (from tenant); directory-visibility toggle.

### IssuanceService
- **Purpose**: Issue and revoke assertions.
- **Responsibilities**: single + bulk issuance; create BadgeAssertion + linked `documents` row; audit;
  anchor commitment; enqueue notification + issued event; revoke (reason) + revoked event.

### OpenBadgesSerializer (module/helper)
- **Purpose**: Build standards-compliant OB 2.0 JSON.
- **Responsibilities**: assertion JSON, BadgeClass JSON, issuer profile JSON; stable hosted URLs;
  verification object; (documented VC/3.0 extension seam; baking deferred per Q5=B).

### WalletService
- **Purpose**: Earner-facing wallet.
- **Responsibilities**: list earner's assertions (exclude hidden); hide/delete; set public flag
  (opt-in); enforce private-by-default; emit accepted/published events.

### SharingService
- **Purpose**: Public sharing surfaces.
- **Responsibilities**: public badge page data; Open Graph metadata; LinkedIn "Add to Profile"
  deep-link builder; earner public profile; channel-tagged share URL + shared event.

### DirectoryService
- **Purpose**: Public discovery.
- **Responsibilities**: per-tenant BadgeClass catalog (directory-visible only); privacy-gated public
  earners per BadgeClass; keyset pagination for scale.

### AnalyticsService
- **Purpose**: Read-side analytics.
- **Responsibilities**: query BadgeAnalyticsDaily for issued/accepted/public/verify counts over time,
  channel breakdown, top badges; tenant-scoped.

### BadgeEventService (helper)
- **Purpose**: Write-side event emission.
- **Responsibilities**: append BadgeEvent rows (called by other services); no aggregation (that's the
  Celery task).

## Celery Tasks (new)
- **aggregate_badge_analytics** (periodic): roll up BadgeEvent → BadgeAnalyticsDaily (Q3=B).
- **bulk_issue_badges**: process bulk issuance rows independently (reuse bulk pattern).

## Routers (new)
- **badges** (authenticated): BadgeClass CRUD, image upload, issue/bulk/revoke, issuer profile — Tenant Admin/Issuer (RBAC).
- **wallet** (authenticated, earner/OTP): list, hide/delete, public toggle.
- **public_badges** (UNAUTHENTICATED — Q2=A): hosted assertion JSON, issuer profile, public badge page, earner public profile, directory, verify. Exposes only opted-public data.
- **badge_analytics** (authenticated, Tenant Admin): dashboard metrics.

## Frontend (new — Q4=A)
- **BadgeClassesPage** (admin): manage templates + image upload + directory toggle.
- **BadgeAnalyticsPage** (admin): dashboard.
- **WalletPage** (earner): badges, hide/delete, public toggle, share actions.
- **Public pages**: public badge page, earner profile, directory (Open Graph meta).

## Reused Components (no change)
documents, audit, anchoring, encryption/S3, notification, OTP auth (dependencies/auth), RLS middleware,
rate limiter, malware scanner (for image upload).
