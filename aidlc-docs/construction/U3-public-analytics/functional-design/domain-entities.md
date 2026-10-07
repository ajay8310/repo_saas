# U3 Public & Analytics — Domain Entities

Reuses `badge_assertions`, `badge_classes`, and `badge_events` (from U1). Adds the analytics rollup.

## BadgeAnalyticsDaily (new)
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| tenant_id | UUID NOT NULL | RLS |
| day | date NOT NULL | rollup bucket |
| badge_class_id | UUID nullable | null = tenant-wide row |
| issued_count | int = 0 | |
| accepted_count | int = 0 | |
| published_count | int = 0 | |
| shared_count | int = 0 | |
| verified_count | int = 0 | |
| viewed_count | int = 0 | |
| channel_breakdown | JSONB | {channel: count} for shares |
| updated_at | timestamptz | |
| UNIQUE(tenant_id, day, badge_class_id) | | idempotent upsert key |

## View/DTOs (not persisted)
- **PublicBadgeView**: badge name/description/image, issuer name/url, issued_on, status, verify URL,
  earner display name (masked, Q5=A). Only when assertion.public=true.
- **EarnerProfileView**: masked display name + list of that earner's public badges.
- **BadgeClassPublic**: catalog entry (name, image, description, criteria) for directory-visible classes.
- **PublicEarner**: masked display name for a public earner of a given BadgeClass.
- **AnalyticsOverview / BadgeAnalytics / BadgeRank**: read models over BadgeAnalyticsDaily.

## Earner display-name derivation (Q5=A)
- `mask(email)`: e.g., `m***a@e***.com` OR a tenant-configured public handle if present. Never raw email.

## Testable Properties (PBT-01)
- [PBT-03] Only `public=true` assertions appear in any public view / directory / profile.
- [PBT-03] Directory catalog lists only `directory_visible=true` classes.
- [PBT-02] share-URL round-trip: build_share_url(id, channel) → parse → same id + channel.
- [PBT-03] aggregation invariant: sum of per-badge daily counts == tenant-wide daily counts per metric.
- [PBT-04] aggregation idempotence: re-running aggregate over the same events yields identical rollup
  (upsert on UNIQUE key) — `aggregate(aggregate(x)) == aggregate(x)`.
- [PBT-07] generators: event streams (mixed types/channels), assertions with random public flags.
