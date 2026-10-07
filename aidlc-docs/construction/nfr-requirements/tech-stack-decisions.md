# Tech Stack Decisions — Badge Feature

## Principle
Reuse the existing platform stack. The badge feature introduces **no new frameworks**; it adds
domain code and a small number of libraries that are already present.

## Backend
| Concern | Decision | Notes |
|---|---|---|
| Web framework | FastAPI 0.111 (existing) | new routers: badges, wallet, public_badges, badge_analytics |
| ORM / DB | SQLAlchemy 2.0 async + PostgreSQL 16 (existing) | new tables; RLS; **partitioning** for badge_assertions & badge_events (Q2=B) |
| Migrations | Alembic (existing) | new migration `005_badges.py` (tables, RLS, triggers, partitions) |
| Cache / broker | Redis 7 (existing) | short-TTL cache for public reads (Q4=A); per-IP throttle counters (Q3=A) |
| Async tasks | Celery 5.4 (existing) | `bulk_issue_badges`, `aggregate_badge_analytics` (beat, ~2 min) |
| Object storage | S3 (existing) | badge images (versioning enabled for DR) |
| Encryption | KMS envelope (existing) | reused via documents linkage |
| Open Badges | **Standard-library JSON** + existing `qrcode`/`Pillow` | OB 2.0 assertion/class/issuer JSON; no new dep. Baking deferred. |
| PDF/QR | reportlab/qrcode/Pillow (existing) | QR on public pages if needed |

## Testing (PBT-09)
- **Property-based framework: Hypothesis 6.100** (already in `[dev]` extras). Satisfies PBT-09
  (custom generators, shrinking, seed reproducibility, pytest integration).
- Example-based: pytest 8.2 + pytest-asyncio (existing).

## Frontend
| Concern | Decision |
|---|---|
| Framework | React 18 + Vite + TypeScript + Tailwind (existing) |
| New pages | BadgeClassesPage, WalletPage, BadgeAnalyticsPage, public badge/earner/directory pages |
| Charts | lightweight/existing approach; no heavy new charting dep unless needed |
| Accessibility | WCAG 2.1 AA target (Q5=A) |

## New/Confirmed Libraries
- No mandatory new backend libraries. (OB baking would need a PNG-iTXt helper — **deferred**, Q5 in App Design.)
- No new frontend frameworks.

## Rationale
- Minimizing new dependencies keeps the pinned-version stability of the platform intact and avoids the
  kind of dependency divergence seen with the MCP extra. The feature is additive and convention-aligned.
