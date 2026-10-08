# U5 — Certificate Template Designer — Implementation Plan

Backs `aidlc-docs/construction/u5-template-designer/design.md`. Each step is
checked off in the same interaction it's completed. Verification after each
backend group; frontend `tsc` at the end.

## Part A — Backend data & rendering core  ✅ COMPLETE
- [x] A1. Model `app/models/certificate_template.py` (`CertificateTemplate`); re-export in `app/models/__init__.py`; add `custom_template_id` to `BadgeClass`.
- [x] A2. Migration `alembic/versions/008_certificate_templates.py` (renumbered from 007 — 007 was already badge_analytics) — create table + RLS (`_apply_rls`), add `badge_classes.custom_template_id` FK (ON DELETE SET NULL); reversible `downgrade()`. Verified up/down/up clean; table+RLS+FK present in DB.
- [x] A3. Layout validation: `app/services/certificate_layout.py` — pydantic `CertificateLayout`/`PageSettings`/`Block`/`BlockStyle`, `FONT_WHITELIST`, `PLACEHOLDER_WHITELIST`, `validate_layout(layout) -> list[str]`, `layout_has_verification(layout)`, `resolve_placeholders(text, ctx) -> str`.
- [x] A4. Renderer: extended `app/services/certificate_renderer.py` with `render_custom_certificate(ctx, layout, assets)` + per-block draw + normalized→A4 mapping (origin flip) + opacity/rotation + verification-guarantee injection + try/except fallback to classic. Added `CustomAssets` dataclass. Smoke-tested: valid layout→PDF, no-verify layout→injected panel, broken layout→classic fallback, placeholders safe (no `{{}}` leak).
- [x] A5. Config: added `certificate_template_asset_max_bytes` (2 MB), `certificate_template_max_blocks` (60) to `app/config.py`.

## Part B — Backend service & API  ✅ COMPLETE
- [x] B1. Service `app/services/certificate_template_service.py` — CRUD, `upload_asset` (scan + SSE-KMS), `render_preview` + `render_preview_of`, `assign_to_class`, `delete` (archive, 409 if in use), factory. (Fixed: flush before audit so `resource_id` is non-null.)
- [x] B2. Extended `CertificateService.build_certificate` with `_render_with_custom_template`: picks custom vs built-in, fetches template assets, audit metadata `custom:<id>`, falls back to built-in if the template row is missing/inactive.
- [x] B3. RBAC: added `badge:template_manage` to super_admin, tenant_admin, issuer. Verified beneficiary/verifier denied (403).
- [x] B4. Router `app/routers/certificate_templates.py` (create/list/get/update/delete/assets/preview/inline-preview/assign); registered in `app/main.py`; added `custom_template_id` to `BadgeClassResponse`. Custom assignment goes through the dedicated `/certificate-templates/assign` endpoint (cleaner than overloading the admin-only built-in template PUT).
- Verified end-to-end: create 201 → inline preview 200 PDF (5460 B) → assign to seeded class → class carries custom_template_id → certificate download 200 PDF (7634 B, rendered via custom path) → delete-while-assigned 409 → RBAC 403 for beneficiary/verifier.

## Part C — Backend tests + verify  ✅ COMPLETE
- [x] C1. Unit tests `tests/unit/test_certificate_template_service.py` (24: create/update/delete/upload/assign/preview incl. malware-reject + scanner-outage fail-closed + missing/archived + 409-in-use) + `tests/unit/test_certificate_layout.py` (22: geometry bounds, enums, verification detection, placeholder safety).
- [x] C2. Property tests `tests/property/test_template_properties.py` (5): geometry mapping stays on-page (both orientations), no residual `{{...}}` + known-token substitution, verification invariant (signature in metadata + render always PDF, incl. no-verify-block layout).
- [x] C3. New U5 suite: 51 passed. Broader `-k 'template or certificate or badge or wallet or rbac or permission'`: **102 passed, 0 failed**. Migration up/down verified in Part A. No regressions in touched areas.

## Part D — Frontend  ✅ COMPLETE
- [x] D1. `frontend/src/lib/templates.ts` — Block/Layout/CertTemplate types, BLOCK_TYPES/FONTS/PLACEHOLDERS, CRUD + asset upload + preview (inline/saved) + assign helpers, `fileToBase64`, `starterLayout`.
- [x] D2. `frontend/src/pages/tenant/TemplateDesignerPage.tsx` — palette / A4 canvas / properties; pointer drag-move + resize handle; keyboard nudge/delete + ARIA (role=application, labelled, focus ring); live preview (opens server PDF in new tab); save/create; logo + background upload; assign-to-badge; template list open/delete (409-aware); placeholder token chips; "verification always included" note.
- [x] D3. Routing/nav: `App.tsx` route `template-designer` (ISSUING_ROLES) + `Layout.tsx` "Certificate Designer" nav (Palette icon, issuing roles). Badges page template dropdown now has Built-in + "Custom (designer)" optgroups; selecting custom assigns via `custom_template_id`, selecting built-in clears it. Added `custom_template_id` to the frontend `BadgeClass` type.
- [x] D4. `tsc --noEmit` clean (removed one unused import). Frontend container `Up`; `/template-designer` serves HTTP 200 (live Vite HMR picked up the changes).

## Part E — End-to-end verify + docs  ✅ COMPLETE
- [x] E1. Live demo path verified through the Vite proxy (issuer→beneficiary): create template → upload institution logo → saved preview 200 PDF (6214 B) → assign to seeded "Advanced Python — Demo" → certificate download 200 PDF (8388 B) → clear-to-builtin renders 200 (12283 B) → re-assign custom. Downloaded PDF: `%PDF`, IMAGE_COUNT=3 (logo + badge + QR), issuer_signature + verify_url embedded in metadata. Fallback + built-in path confirmed.
- [x] E2. Updated `aidlc-docs/aidlc-state.md` (U5 complete); logged completion in `audit.md`; temp files cleaned (host + container).

## Rollback / safety
- Migration is reversible (drop FK col, drop table). No change to existing
  built-in templates or the `certificate_template` enum. Feature is additive and
  gated behind the new permission; existing certificates keep rendering.
