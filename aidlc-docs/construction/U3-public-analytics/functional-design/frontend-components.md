# U3 Public & Analytics — Frontend Components

## Public Badge Page (unauthenticated)
- **Purpose**: shareable page for a single public badge.
- **Rendered with Open Graph meta** (og:title/description/image/url) for social previews.
- **Content**: badge image/name/description, issuer, issued date, masked earner name, "Verify" link, status.
- **Route**: `/public/badges/{credential_id}`. If not public → 404 page.
- **API**: `GET /api/v1/obadges/badge-page/{credential_id}` (or SSR meta) + `GET /api/v1/obadges/verify/{credential_id}`.

## Earner Public Profile (unauthenticated)
- **Purpose**: list of an earner's public badges.
- **Content**: masked display name + grid of public badges (link to each public page).
- **Route**: `/public/earners/{ref}`. **API**: `GET /api/v1/obadges/earner/{ref}`.

## Directory (unauthenticated)
- **Purpose**: browse a tenant's public catalog + public earners.
- **Content**: searchable list of directory-visible BadgeClasses; drill into a class → public earners.
- **Pagination**: cursor-based (load more).
- **Route**: `/public/directory/{tenant}`. **API**: `GET /api/v1/obadges/directory/{tenant}?q=&cursor=`,
  `GET /api/v1/obadges/directory/{tenant}/{badge_class_id}/earners?cursor=`.

## BadgeAnalyticsPage (tenant admin)
- **Purpose**: dashboard of program metrics.
- **State**: date range, selected badge (or all), overview totals, time series, top badges, channel breakdown.
- **Content/Charts**: issued/accepted/published/shared/verified/viewed over time; top badges table;
  channel breakdown (bar/pie).
- **API**: `GET /api/v1/badge-analytics/overview?from=&to=`, `/per-badge/{id}`, `/top?metric=`, `/channels`.

## Share affordances (used by U2 WalletPage)
- `ShareMenu`: copy public URL, "Add to LinkedIn" (deep link), share to X/Facebook (channel-tagged URLs).

## Component hierarchy
- Public: `PublicBadgePage`, `EarnerProfilePage`, `DirectoryPage` (+ `DirectoryEarnerList`).
- Admin: `BadgeAnalyticsPage` (+ `MetricCards`, `TimeSeriesChart`, `TopBadgesTable`, `ChannelBreakdown`).
- Shared: `ShareMenu`.

## Reuse
- api client, charts (lightweight/existing), AuthContext (analytics = tenant_admin; public pages = none).
