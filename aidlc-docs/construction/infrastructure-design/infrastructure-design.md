# Infrastructure Design — Badge Feature (U1, U2, U3)

Decisions: Q1=A new S3 prefix (existing bucket), Q2=A existing beat schedule, Q3=B **separate public
gateway** for unauthenticated routes, Q4=A presigned S3 URLs for images.

## Logical → Infrastructure Mapping

| Logical component | Infrastructure |
|---|---|
| Authenticated routers (badges, wallet, badge_analytics) | Existing **api** container/ingress |
| Unauthenticated `public_badges` routes | **New `public-gateway` container** (Q3=B) — same image, runs only the public router, own ingress/port |
| badge_classes / badge_assertions / badge_events / badge_analytics_daily | Existing **PostgreSQL 16** (migration 005; partitions) |
| Cache, per-IP throttle, aggregation watermark | Existing **Redis 7** (new key namespaces) |
| Badge images | Existing **S3** bucket, new prefix `badges/{tenant_id}/{badge_class_id}` (Q1=A), **versioning on** |
| Envelope encryption | Existing **KMS** (via documents linkage) |
| `bulk_issue_badges`, `aggregate_badge_analytics` | Existing **Celery worker** + **beat** (new schedule entry, Q2=A) |
| Malware scan (image upload) | Existing **ClamAV** |

## Separate Public Gateway (Q3=B)
- **What**: a new container built from the **same application image**, started with a command/flag that
  mounts only the `public_badges` router (assertion JSON, issuer profile, public pages, directory,
  verify). Read-mostly (only append-only view/verify events).
- **Why (isolation)**: contain blast radius of untrusted public traffic; scale/throttle public reads
  independently; keep authenticated admin/issuer/earner APIs on a separate host.
- **Connectivity**: reaches **PostgreSQL** (read + append events) and **Redis** (cache, per-IP throttle).
- **Security posture**: no auth issuance here; serves only `public=true`/`directory_visible=true` data;
  per-IP throttle applied at this gateway.
- **Trade-off (documented)**: adds a deployable + its own ingress and DB/Redis connections. Acceptable
  per user choice for public-surface isolation. In dev/compose it's one extra service; in production it
  would sit behind its own ingress/LB rule.

## Presigned Image URLs (Q4=A)
- Public pages request a **short-lived presigned S3 URL** (e.g., 5-15 min) from the gateway for the
  badge image; the browser fetches directly from S3. Offloads image bandwidth from the app.
- Cache the presigned URL briefly (< its TTL) alongside the page payload.

## Migration
- `alembic/versions/005_badges.py`: tables + RANGE partitions + RLS policies + indexes; reversible.

## No topology change
- Single-region, multi-zone (AVAIL-2). No new regions, no new managed services beyond a second
  container of the existing image. DR = existing PG backups + S3 versioning (AVAIL-1).
