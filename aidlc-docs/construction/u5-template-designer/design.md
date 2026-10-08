# U5 — Certificate Template Designer (Functional + NFR Design)

Backs `aidlc-docs/inception/requirements/u5-template-designer-requirements.md`.
Extensions: Security OFF, Resiliency ON, PBT ON.

Approved decisions: (R1) ReportLab data-driven renderer; (R2) PDF preview; (R3)
PNG/JPEG logo; (R5) `custom_template_id` FK; coordinates normalized (R3-geom).

---

## 1. Layout JSON schema (`layout` JSONB)

A template's `layout` is a single JSON object. Coordinates are **normalized
fractions of the page** (0..1), origin top-left in the *editor*; the renderer
converts to ReportLab's bottom-left origin.

```jsonc
{
  "page": {
    "orientation": "landscape",      // or "portrait"
    "background_color": "#ffffff",   // hex
    "background_image": true          // whether to draw background_s3_key full-bleed
  },
  "blocks": [
    {
      "id": "b1",                    // stable client id
      "type": "text",               // text|recipient_photo|badge_image|logo|qr|signature|line|rect
      "x": 0.1, "y": 0.08,           // top-left, fraction of page W/H
      "w": 0.8, "h": 0.1,            // size, fraction of page W/H
      "z": 2,                        // z-order (draw ascending)
      "rotation": 0,                 // degrees, optional
      "opacity": 1.0,                // 0..1, optional
      "style": {                     // type-specific; see below
        "text": "{{recipient}}",
        "font": "Helvetica-Bold",
        "size": 22,                  // points
        "color": "#1e3a8a",
        "align": "center"            // left|center|right
      }
    }
  ]
}
```

### Per-type `style`
- **text**: `text` (string with placeholders), `font` (enum, see §5), `size`
  (pt, 6..96), `color` (hex), `align`.
- **recipient_photo / badge_image / logo**: optional `border` (bool),
  `border_color` (hex); image fit = contain within (w,h). `logo` reads
  `logo_s3_key`; `badge_image` reads the badge class image; `recipient_photo`
  reads the assertion photo.
- **qr**: draws the `verify_url` QR; optional `caption` (default "Scan to verify").
- **signature**: draws the verification panel (issuer line + "✔ Digitally
  signed & verifiable" + verify URL + RS256 fingerprint). Fixed internal layout,
  scaled to (w,h).
- **line / rect**: `color` (hex), `line_width` (pt), `fill` (bool, rect only).

### Validation (on save + before render)
- `orientation ∈ {portrait, landscape}`; colors match `^#[0-9a-fA-F]{6}$`.
- Every block: known `type`; `0 ≤ x,y ≤ 1`, `0 < w,h ≤ 1`, `x+w ≤ 1.0001`,
  `y+h ≤ 1.0001`; `font ∈ FONT_WHITELIST`; `size` in range; `align` valid.
- Text placeholders ⊆ `PLACEHOLDER_WHITELIST` (unknown tokens allowed but
  resolve to empty at render — never leaked literally).
- Asset keys (`logo_s3_key`, `background_s3_key`) must match the tenant's
  asset-prefix and exist (ownership check) when referenced.
- **Verification guarantee (FR-U5-10)**: if no `qr` block AND no `signature`
  block is present, the renderer appends a default verification panel at the
  page bottom. Validation warns but does not block (render always safe).

A pydantic model `LayoutModel` (with `PageModel`, `BlockModel`, `BlockStyle`)
performs structural validation; geometry/placeholder checks live in a pure
`validate_layout(layout) -> list[str]` helper (unit + property tested).

---

## 2. Data model & migration (`007_certificate_templates`)

New table **`certificate_templates`** (tenant-scoped, RLS forced):

| column | type | notes |
|---|---|---|
| id | UUID PK | `gen_random_uuid()` |
| tenant_id | UUID FK→tenants(id) CASCADE | NOT NULL |
| name | VARCHAR(255) | NOT NULL |
| orientation | VARCHAR(16) | NOT NULL default `portrait`; CHECK in (portrait,landscape) |
| layout | JSONB | NOT NULL default `'{}'` |
| logo_s3_key | VARCHAR(1024) | nullable |
| background_s3_key | VARCHAR(1024) | nullable |
| version | INTEGER | NOT NULL default 1 |
| status | VARCHAR(16) | NOT NULL default `active`; CHECK in (active,archived) |
| created_at / updated_at | timestamptz | server defaults, onupdate |

RLS: `ENABLE` + `FORCE` + `tenant_isolation` policy (USING/WITH CHECK on
`tenant_id = current_setting('app.tenant_id')::uuid`) — via the steering
`_apply_rls` pattern.

**`badge_classes`**: add `custom_template_id UUID NULL REFERENCES
certificate_templates(id) ON DELETE SET NULL`. Selection rule at render:
`if custom_template_id is not None: render custom else: render builtin(certificate_template)`.
The existing `certificate_template` CHECK constraint is left unchanged (built-ins
only); custom is signalled purely by the FK — no enum overload (R5).

`downgrade()` drops the FK column then the table (reverse order).

Model: `app/models/certificate_template.py` → `CertificateTemplate(Base,
UUIDPrimaryKeyMixin, TimestampMixin)`; re-export from `app/models/__init__.py`;
add `custom_template_id` mapped column to `BadgeClass`.

---

## 3. Rendering: data-driven ReportLab (`_render_custom`)

Extend `certificate_renderer.py` without disturbing the four built-ins.

- `render_certificate(ctx, template)` stays the entry for built-ins. Add
  `render_custom_certificate(ctx, layout, assets)` where `assets` carries
  `logo: bytes|None`, `background: bytes|None` (badge image + recipient photo
  already live on `ctx`).
- Coordinate mapping: page = A4 in chosen orientation → `(PW, PH)` in points.
  For a block with normalized `(x, y, w, h)` (top-left origin):
  `abs_w = w*PW`, `abs_h = h*PH`, `abs_x = x*PW`,
  `abs_y = PH - (y*PH) - abs_h`  (flip to bottom-left origin).
- Draw order: background color → background image (full-bleed) → blocks sorted
  by `z` ascending. Apply `opacity`/`rotation` via `saveState`/`translate`/
  `rotate`/`setFillAlpha` where supported.
- Block renderers reuse existing helpers: `_draw_photo`, QR via `_qr_png`,
  signature via a size-parametrized `_draw_verification_panel`. Text uses
  `drawString`/`drawCentredString`/`drawRightString` by `align`; font via
  `pdfmetrics` (whitelist). Images via `_image_reader` (PNG/JPEG; SVG skipped
  with graceful placeholder box).
- Placeholder resolution: `_resolve_placeholders(text, ctx) -> str` replaces
  whitelisted tokens from `ctx`; unknown `{{...}}` → `""`.
- **Resiliency (NFR-U5-2)**: wrap the whole custom render in try/except; on any
  failure, log and fall back to `_render_classic(ctx)` so a download never 500s.
  Missing asset bytes → draw a light placeholder rect, continue.
- **Verification guarantee**: after drawing blocks, if neither a qr nor a
  signature block was present, draw the default `_draw_verification_panel` at the
  bottom. The RS256 JWS continues to be embedded in PDF metadata by `_new_canvas`.

`CertificateService.build_certificate` changes: after resolving `badge_class`,
if `badge_class.custom_template_id` is set, load the `CertificateTemplate`,
fetch `logo`/`background` bytes via `_fetch_s3`, and call
`render_custom_certificate(ctx, template.layout, assets)`; else keep the current
built-in path. Audit metadata records `{"template": "custom:<id>"}` or the
built-in name.

---

## 4. Services, API, assets

### Service `app/services/certificate_template_service.py`
`CertificateTemplateService(db, settings)` mirroring `BadgeService`:
- `create(tenant_id, name, orientation, layout, actor)` — validates layout, inserts, audits.
- `list(tenant_id)`, `get(tenant_id, id)`.
- `update(tenant_id, id, name?, orientation?, layout?, actor)` — validates, bumps `version`, audits.
- `upload_asset(tenant_id, id, kind, content, content_type, actor)` — `kind ∈ {logo, background}`; type ∈ {png,jpeg}; size ≤ settings cap; **malware scan (fails closed → 503)**; `put_object` SSE-KMS at key `badges/{tenant}/templates/{template_id}/{kind}-{uuid}.{ext}`; set `logo_s3_key`/`background_s3_key`; audit.
- `render_preview(tenant_id, id|inline_layout, actor)` — build a `CertificateContext` from **sample data** + fetch this template's assets, call `render_custom_certificate`, return PDF bytes. No persistence; no analytics event.
- `assign_to_class(tenant_id, badge_class_id, template_id|None, actor)` — set/clear `custom_template_id` on the badge class (via `BadgeService.update_badge_class` extension or a direct setter); audits.
- `delete(tenant_id, id, actor)` — if any badge class references it → 409 with guidance; else archive (status=archived) or hard-delete per final call (design: **archive**, keep history).
- Factory `get_certificate_template_service(db=Depends(get_db))`.

### Router `app/routers/certificate_templates.py` (prefix `/certificate-templates`)
All write routes `dependencies=[Depends(require_permission("badge:template_manage"))]`;
reads use `badge:read`.
- `POST /` create · `GET /` list · `GET /{id}` read · `PUT /{id}` update ·
  `POST /{id}/assets` upload (base64) · `POST /{id}/preview` → PDF Response ·
  `POST /preview` → PDF from an inline (unsaved) layout for live editing ·
  `DELETE /{id}`.
- Extend `PUT /badges/classes/{id}/template` body to accept either
  `{certificate_template: <builtin>}` or `{custom_template_id: <uuid>|null}`.
Register in `app/main.py` with the api_v1 prefix.

### RBAC
Add `"badge:template_manage"` to `super_admin`, `tenant_admin`, **`issuer`**
in `ROLE_PERMISSIONS`. (Issuer gets the new permission directly; `badge:update`
is left as-is so we don't broaden unrelated admin surface.)

### Config (`app/config.py`)
`certificate_template_asset_max_bytes` (default 2 MB), `certificate_template_max_blocks`
(default 60). Reuse `badge_image_prefix`, `s3_bucket_name`, `presigned_url_ttl_seconds`.

---

## 5. Fonts & placeholders

- `FONT_WHITELIST = {Helvetica, Helvetica-Bold, Helvetica-Oblique, Times-Roman,
  Times-Bold, Times-Italic, Courier, Courier-Bold}` (ReportLab built-ins — zero
  bundling risk). Room to register bundled TTFs later behind the same whitelist.
- `PLACEHOLDER_WHITELIST = {recipient, badge_name, issuer_name, issued_at,
  expires_at, criteria, verify_url, assertion_id}` — resolved from
  `CertificateContext`.

---

## 6. Frontend

### Lib `frontend/src/lib/templates.ts`
Types `CertTemplate`, `Block`, `BlockType`, `Layout`; helpers `listTemplates`,
`getTemplate`, `createTemplate`, `updateTemplate`, `uploadTemplateAsset`,
`previewTemplate` (inline layout → blob), `assignTemplateToClass`,
`deleteTemplate`. Reuse `savePdfBlob`. Follows the axios `/api/v1` + bearer
pattern.

### Page `frontend/src/pages/tenant/TemplateDesignerPage.tsx`
Three-pane designer (palette / A4 canvas / properties) as mocked:
- Canvas renders blocks as absolutely-positioned divs over an A4-ratio surface;
  pointer drag to move, handles to resize, click to select, Delete to remove,
  z-order controls. Keyboard: arrows nudge, Tab cycles selection, Enter edits
  text (NFR-U5-7 accessibility: focusable, ARIA labels, focus ring).
- Palette adds blocks; Page controls (orientation, bg color, bg upload);
  Properties edits the selected block (position/size as 0..1, style fields,
  logo/image upload for image blocks).
- Toolbar: **Preview** (POST inline layout → PDF shown in an embedded
  `<object>`/new tab), **Save** (create/update), template name field, template
  list (open/duplicate/delete), and **Assign to badge class** picker.
- A "required verification" chip reminds that QR/signature are always included.

### Routing & nav
- `App.tsx`: add `<Route path="template-designer" ...ISSUING_ROLES...>`.
- `Layout.tsx`: add a nav item "Certificate Designer" shown for issuing roles.
- Badges page: the per-badge "Certificate:" dropdown gains a "Custom: <name>"
  group listing the tenant's saved templates (assign via `custom_template_id`),
  plus a link to the designer.

---

## 7. Testing (incl. PBT)

- **Unit (backend)**: layout validation (bounds, enums, placeholder whitelist);
  template CRUD + version bump; asset upload (type/size reject, scan fail→503);
  assignment set/clear; render selection (custom vs builtin); graceful fallback
  on bad layout/missing asset (no 500); permission enforcement (issuer allowed,
  verifier/beneficiary denied); tenant isolation (cross-tenant 404).
- **Property (Hypothesis, NFR-U5-5)**:
  - *Geometry*: for blocks with `0≤x,y`, `0<w,h`, `x+w≤1`, `y+h≤1`, mapped
    absolute coords are within `[0,PW]×[0,PH]` and `abs_y≥0`.
  - *Placeholders*: for arbitrary text mixing known/unknown tokens, output
    contains no residual `{{...}}` and known tokens are substituted.
  - *Verification invariant*: rendered PDF for any valid layout always embeds
    the signature in metadata and includes a QR (block or injected default).
- **Integration**: end-to-end create→assign→download via the app; preview
  endpoint returns a valid PDF; cross-tenant denied.
- **Frontend**: `tsc` clean; a light render/interaction test for the canvas if
  the harness allows.

---

## 8. Resiliency & compatibility summary (enabled extensions)

- **Resiliency ON**: render never 500s (fallback to classic); assets degrade to
  placeholders; uploads fail closed on scanner outage; preview is side-effect
  free. N/A: no new cross-service calls, no new DR surface beyond one RLS table
  (covered by existing backup).
- **PBT ON**: geometry + placeholder + verification invariants above.
- **Security extension OFF**: not enforced per user opt-out; nonetheless we keep
  the established posture (RLS, malware scan, tenant-scoped asset keys, no PII in
  logs) because it is the surrounding code's norm.
- **Backward compatible**: built-in templates and existing `certificate_template`
  string untouched; custom is additive via nullable FK.
