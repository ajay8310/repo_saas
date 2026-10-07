# U3 Public & Analytics — Business Rules

## Sharing / Public
- BR-P1: A public badge page/profile is served ONLY when `assertion.public=true`; otherwise 404 (Q7=A).
- BR-P2: Earner identity on any public surface is a masked display name or handle, never raw email (Q5=A).
- BR-P3: Open Graph meta uses badge name/description/image and the public page URL.
- BR-P4: LinkedIn deep link is built from assertion/class fields only (no external API/account).
- BR-P5: `build_share_url` tags the URL with a channel and records a "shared" event with that channel.
- BR-P6: A revoked or non-public badge is not shareable; its public page 404s (verify still reports state).

## Directory
- BR-D1: Catalog lists only `directory_visible=true` BadgeClasses for the tenant.
- BR-D2: Public-earner lists include only earners with a `public=true` assertion of that class; masked names.
- BR-D3: Pagination is keyset/seek-based (cursor), sized for 10M+ assertions.

## Analytics
- BR-A1: Events are append-only; services never mutate historical events.
- BR-A2: Aggregation runs every ~2 minutes (Q6=A) and is idempotent (upsert by UNIQUE(tenant,day,class)
  + processed watermark) — safe to re-run without double counting.
- BR-A3: A tenant-wide daily row (badge_class_id = null) equals the sum of per-class rows for each metric.
- BR-A4: All analytics reads are tenant-scoped (RLS); no cross-tenant data.
- BR-A5: `channel_breakdown` accumulates share counts per channel string.
