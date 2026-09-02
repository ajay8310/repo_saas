# Component Methods — Credly-Style Credentialing

Method signatures (I/O types) only. Detailed business rules come in Functional Design (per unit).
All service methods take/return domain types; tenant context set via `set_tenant_context` (RLS).

## BadgeService
- `create_badge_class(tenant_id: UUID, data: BadgeClassInput) -> BadgeClass`
- `update_badge_class(tenant_id: UUID, badge_class_id: UUID, data: BadgeClassInput) -> BadgeClass`
- `deactivate_badge_class(tenant_id: UUID, badge_class_id: UUID) -> BadgeClass`
- `get_badge_class(tenant_id: UUID, badge_class_id: UUID) -> BadgeClass | None`
- `list_badge_classes(tenant_id: UUID, limit: int, offset: int) -> list[BadgeClass]`
- `set_directory_visibility(tenant_id: UUID, badge_class_id: UUID, visible: bool) -> BadgeClass`
- `attach_image(tenant_id: UUID, badge_class_id: UUID, image_bytes: bytes, mime: str) -> BadgeClass`

## IssuanceService
- `issue(tenant_id: UUID, badge_class_id: UUID, beneficiary_id: str, actor_id: str) -> IssueResult{assertion_id, credential_id, assertion_url}`
- `bulk_issue(tenant_id: UUID, badge_class_id: UUID, beneficiary_ids: list[str], actor_id: str) -> BulkJobRef{job_id}`
- `revoke(tenant_id: UUID, assertion_id: UUID, reason: str, actor_id: str) -> BadgeAssertion`
- `get_assertion(tenant_id: UUID, assertion_id: UUID) -> BadgeAssertion | None`

## OpenBadgesSerializer
- `assertion_json(assertion: BadgeAssertion, badge_class: BadgeClass, issuer: IssuerProfile) -> dict`  (OB 2.0)
- `badge_class_json(badge_class: BadgeClass, issuer_url: str) -> dict`
- `issuer_profile_json(tenant_issuer: IssuerProfile) -> dict`
- `verification_status(assertion: BadgeAssertion) -> {status: valid|revoked|expired|invalid, revoked_at?}`
- (deferred Q5=B) `bake_png(image: bytes, assertion_url: str) -> bytes`  — future increment
- (seam) `assertion_vc_json(...)` — documented OB 3.0/VC extension point, not implemented now

## WalletService
- `list_wallet(tenant_id: UUID, beneficiary_id: str, include_hidden: bool = False) -> list[WalletItem]`
- `hide(tenant_id: UUID, beneficiary_id: str, assertion_id: UUID) -> BadgeAssertion`
- `delete_from_wallet(tenant_id: UUID, beneficiary_id: str, assertion_id: UUID) -> None`
- `set_public(tenant_id: UUID, beneficiary_id: str, assertion_id: UUID, public: bool) -> BadgeAssertion`

## SharingService
- `public_badge_page(assertion_id: UUID) -> PublicBadgeView | None`  (only if public)
- `open_graph_meta(assertion_id: UUID) -> dict`
- `linkedin_add_to_profile_url(assertion: BadgeAssertion, badge_class: BadgeClass) -> str`
- `earner_public_profile(beneficiary_ref: str) -> EarnerProfileView`  (public badges only)
- `build_share_url(assertion_id: UUID, channel: str) -> str`  (records shared event with channel)

## DirectoryService
- `list_catalog(tenant_id: UUID, query: str | None, cursor: str | None, limit: int) -> Page[BadgeClassPublic]`
- `list_public_earners(tenant_id: UUID, badge_class_id: UUID, cursor: str | None, limit: int) -> Page[PublicEarner]`

## AnalyticsService
- `overview(tenant_id: UUID, date_from: date, date_to: date) -> AnalyticsOverview`
- `per_badge(tenant_id: UUID, badge_class_id: UUID, date_from: date, date_to: date) -> BadgeAnalytics`
- `top_badges(tenant_id: UUID, metric: str, limit: int) -> list[BadgeRank]`
- `channel_breakdown(tenant_id: UUID, date_from: date, date_to: date) -> dict[str, int]`

## BadgeEventService
- `record(tenant_id: UUID, event_type: str, badge_class_id: UUID, assertion_id: UUID | None, channel: str | None) -> None`

## Celery Tasks
- `aggregate_badge_analytics()` — periodic; rolls BadgeEvent → BadgeAnalyticsDaily.
- `bulk_issue_badges(job_id, tenant_id, badge_class_id, beneficiary_ids, actor_id)` — independent per-row processing.

## Router endpoints (signatures summarized)
### badges (auth: tenant_admin/issuer)
- `POST /api/v1/badge-classes`, `GET/PATCH/DELETE /api/v1/badge-classes/{id}`, `GET /api/v1/badge-classes`
- `POST /api/v1/badge-classes/{id}/image`
- `POST /api/v1/badge-classes/{id}/issue`, `POST /api/v1/badge-classes/{id}/bulk-issue`
- `POST /api/v1/assertions/{id}/revoke`
- `PUT /api/v1/issuer-profile`

### wallet (auth: beneficiary/OTP)
- `GET /api/v1/wallet`, `POST /api/v1/wallet/{assertion_id}/hide`, `DELETE /api/v1/wallet/{assertion_id}`, `POST /api/v1/wallet/{assertion_id}/public`

### public_badges (UNAUTH)
- `GET /api/v1/obadges/assertions/{id}` (OB 2.0 JSON), `GET /api/v1/obadges/badge-classes/{id}`, `GET /api/v1/obadges/issuers/{tenant_id}`
- `GET /api/v1/obadges/verify/{assertion_id}`
- `GET /public/badges/{assertion_id}` (HTML page w/ OG meta), `GET /public/earners/{ref}`, `GET /public/directory/{tenant}`

### badge_analytics (auth: tenant_admin)
- `GET /api/v1/badge-analytics/overview`, `/per-badge/{id}`, `/top`, `/channels`
