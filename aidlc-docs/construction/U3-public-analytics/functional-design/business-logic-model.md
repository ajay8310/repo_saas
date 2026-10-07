# U3 Public & Analytics — Business Logic Model

## Sharing (SharingService)
- `public_badge_page(credential_id)`: return PublicBadgeView ONLY if assertion.public=true; else 404
  (Q7=A uniform). Includes masked earner name (Q5=A), issuer, verify URL, OG meta.
- `open_graph_meta(credential_id)`: og:title (badge name), og:description, og:image (badge image),
  og:url (public page). For LinkedIn/X/Facebook previews.
- `linkedin_add_to_profile_url(assertion, badge_class)`: build the LinkedIn certification deep link
  from fields (name, issuer, issue date, cert URL, cert id). No LinkedIn API/account.
- `earner_public_profile(earner_ref)`: masked name + that earner's public badges only.
- `build_share_url(credential_id, channel)`: return public page URL with `?ch={channel}`; record
  "shared" event with channel (feeds channel_breakdown).

## Directory (DirectoryService)
- `list_catalog(tenant, query, cursor, limit)`: BadgeClasses with `directory_visible=true`, keyset
  pagination (id/created_at cursor) for 10M+ scale. Text search on name/tags (pg_trgm, reuse pattern).
- `list_public_earners(tenant, badge_class_id, cursor, limit)`: earners with a `public=true` assertion
  of that class; masked names; privacy-gated (never private earners).

## Analytics (Q6=A: aggregate every 1-5 min)
- Write path (from U1/U2/U3): `BadgeEventService.record(event_type, badge_class_id, assertion_id, channel)`
  appends a `badge_events` row (cheap).
- `aggregate_badge_analytics` (Celery beat, every ~2 min): read new events since last watermark,
  upsert into `BadgeAnalyticsDaily` by (tenant, day, badge_class_id); update channel_breakdown for
  shares; also maintain a tenant-wide (badge_class_id=null) row. Idempotent via UNIQUE upsert +
  processed-watermark so re-runs don't double count.
- Read path (AnalyticsService): overview(date range), per_badge, top_badges(metric), channel_breakdown
  — all from the daily rollup (fast, tenant-scoped).

## Verification/view events
- The public verify + page fetch (U1 verify subset / U3 pages) record "verified"/"viewed" events;
  aggregated as above.

## Error handling (Q7=A)
- Non-public or nonexistent public resource → 404 (no existence leak). Revoked state only surfaces on
  the verify endpoint (`revoked:true`), not on the public marketing page (which 404s if not public).

## Testable Properties (PBT-01)
- [PBT-03] only-public-listed across page/profile/directory; directory_visible gating.
- [PBT-02] share URL round-trip (id+channel).
- [PBT-04] aggregation idempotence (re-run == run).
- [PBT-03] rollup consistency (per-badge sums == tenant-wide).
- [PBT-11] example tests: publish→appears in directory; unpublish→gone; share increments channel; verify increments count after aggregation.
