# U5 — Visual Certificate Template Designer (Requirements)

**Feature**: A browser-based visual (drag-and-drop) designer that lets an issuer
build and save their own certificate layout — positioning text, images, the
recipient photo, the badge image, an **institution logo**, and the
verification QR/signature — then assign that custom template to a badge class so
every certificate for that class renders from the saved design.

**Depth**: Comprehensive (new, complex, user-facing capability).
**Extensions in effect**: Security Baseline OFF, Resiliency Baseline ON, PBT ON.

---

## 1. Problem & Intent

Today certificates render from one of four hardcoded ReportLab layouts
(`classic | modern | elegant | minimal`). Issuers can only *pick* one; they
cannot *design* their own, and there is no institution-logo element. The output
looks generic. Issuers need to produce branded certificates that match their
institution's identity.

**User's explicit asks**
1. A place in the **issuer login** to configure and design certificate templates.
2. The issuer can **design their own** template (drag-and-drop — Option B).
3. The template must support **uploading the institution logo**.

---

## 2. Scope

### In scope
- A `CertificateTemplate` entity per tenant: a saved, named, versioned layout.
- A visual designer page (issuing roles) with a WYSIWYG A4 canvas:
  - Add / move / resize / delete **blocks**.
  - Block types: `text` (static or data-bound via placeholders), `recipient_photo`,
    `badge_image`, `logo` (institution logo), `qr` (verification), `signature`
    (the "digitally signed & verifiable" panel), `line`/`rect` (decoration).
  - Per-block style: font family (from a built-in safe set), size, weight,
    color, alignment, opacity, rotation, z-order.
  - Page-level: background color and optional full-bleed **background image**.
- **Asset uploads**: institution logo and background image, stored in S3
  (SSE-KMS), malware-scanned (fails closed), size/type validated.
- **Data binding** via placeholders resolved at render time:
  `{{recipient}}`, `{{badge_name}}`, `{{issuer_name}}`, `{{issued_at}}`,
  `{{expires_at}}`, `{{criteria}}`, `{{verify_url}}`, `{{assertion_id}}`.
- **Live preview**: render the current design to a PDF (or PNG) with sample
  data, shown in the designer without saving.
- **Assign** a saved custom template to a badge class (replaces the enum string
  with a reference to the custom template; built-ins remain selectable).
- **Server-side rendering** of the saved layout via a new data-driven renderer
  that extends the existing ReportLab path (keeps QR + signature + metadata
  invariants intact).
- CRUD + list + duplicate for templates; soft delete (cannot delete a template
  in use by a badge class without reassignment).

### Out of scope (this unit)
- Multi-page certificates (single A4 page, portrait or landscape).
- Arbitrary web-font upload (only a curated, PDF-safe font set initially).
- Rich text within a single text block (one style per block).
- SVG logo embedding (PNG/JPEG only initially — ReportLab limitation; SVG
  rasterization is a later enhancement).
- Template marketplace / cross-tenant sharing.

---

## 3. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-U5-1 | Issuing users (super_admin, tenant_admin, issuer) can create a certificate template with a name and an A4 layout (portrait or landscape). |
| FR-U5-2 | A template is a tenant-scoped record holding a validated JSON layout (list of blocks + page settings) and references to uploaded asset keys (logo, background). |
| FR-U5-3 | The designer supports adding, selecting, moving, resizing, deleting, and reordering (z-index) blocks on the canvas. |
| FR-U5-4 | Supported block types: text, recipient_photo, badge_image, logo, qr, signature, line, rect. Each has position (x, y, w, h as page-normalized fractions 0..1) and type-specific style. |
| FR-U5-5 | Text blocks support static text and/or placeholder tokens resolved from assertion/badge/tenant data at render time. Unknown tokens render as empty, never raw. |
| FR-U5-6 | Issuers can upload an institution logo image; it is stored in S3 (SSE-KMS), malware-scanned, type-restricted to PNG/JPEG, size-limited. A logo block renders it. |
| FR-U5-7 | Issuers can set a page background color and optionally upload a background image (same storage/scan/validation rules). |
| FR-U5-8 | The designer provides a live preview rendered server-side with representative sample data, returned as a PDF/PNG, without persisting the design. |
| FR-U5-9 | A saved custom template can be assigned to a badge class; the certificate build path renders that class's certificates from the custom layout. Built-in templates remain assignable. |
| FR-U5-10 | Every rendered certificate — custom or built-in — MUST still include the verification QR (of verify_url) and the issuer digital-signature panel, and embed the RS256 JWS in PDF metadata. The designer cannot remove these verification guarantees (a qr block and signature block are required; if omitted, the renderer injects a default verification panel). |
| FR-U5-11 | Templates are listable, editable, duplicable, and deletable. A template referenced by any badge class cannot be hard-deleted; it is soft-deleted/archived or deletion is blocked with guidance to reassign. |
| FR-U5-12 | Layout JSON is validated on save (schema, block bounds within page, known block types, placeholder whitelist, asset-key ownership) and rejected with field-level 422 errors otherwise. |
| FR-U5-13 | Templates are versioned: editing a template bumps its version; existing issued certificates re-render from the current assigned template (no immutable snapshot required this unit, but version is recorded for audit). |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-U5-1 (Security/tenant) | All template records and assets are tenant-scoped with RLS; a tenant can never read/render another tenant's template or asset. Asset keys are validated to belong to the caller's tenant before use. |
| NFR-U5-2 (Resiliency) | Rendering degrades gracefully: a missing/unreadable asset renders a placeholder, not a 500. An invalid stored layout falls back to the default built-in template rather than failing the download (mirrors current unknown-template fallback). |
| NFR-U5-3 (Resiliency) | Asset uploads fail closed on malware-scan unavailability (503), never bypass scanning (mirrors existing uploads). |
| NFR-U5-4 (Performance) | A single certificate renders within the current download latency envelope; live preview returns within ~2 s for a typical layout. Heavy/batch rendering (if later needed) uses Celery. |
| NFR-U5-5 (PBT) | Property-based tests assert layout-geometry invariants (e.g. any block with in-bounds normalized coords maps to on-page absolute coords; required verification elements always present in output) and placeholder-resolution safety (no unresolved `{{...}}` leaks; unknown tokens → empty). |
| NFR-U5-6 (Compatibility) | Existing badge classes keep working: `certificate_template` continues to accept the four built-in names; custom assignment is additive and backward compatible. |
| NFR-U5-7 (Accessibility) | The designer UI is keyboard-operable (select/move blocks via keyboard, focus-visible, ARIA labels on controls) and color-contrast compliant for its own chrome. |

## 5. RBAC

- New permission: `badge:template_manage` (create/update/delete/assign custom templates and upload designer assets).
- Grant to: `super_admin`, `tenant_admin`, and **`issuer`** (so issuers can design, per the user's explicit ask — note issuer currently lacks `badge:update`; the new permission is granted directly rather than widening `badge:update`).
- `badge:read` continues to gate listing templates and reading one.
- Preview and render stay within the tenant via `get_current_user` + `set_tenant_context`.

## 6. Data Model (additions)

- **New table `certificate_templates`** (tenant-scoped, RLS):
  - `id` (UUID PK), `tenant_id` FK → tenants (CASCADE), `name`, `orientation`
    (`portrait|landscape`), `layout` (JSONB — page settings + blocks),
    `logo_s3_key` (nullable), `background_s3_key` (nullable), `version` (int),
    `status` (`active|archived`), timestamps.
  - RLS `tenant_isolation` policy (ENABLE + FORCE), per database steering.
- **`badge_classes`**: add nullable `custom_template_id` UUID FK →
  `certificate_templates(id)`. When set, it takes precedence over the
  `certificate_template` string. The existing CHECK constraint on
  `certificate_template` is relaxed to also allow the sentinel `custom` (or we
  select-custom purely by `custom_template_id IS NOT NULL`; final choice in design).
- Migration `007_certificate_templates` (reversible).

## 7. API (additions, under `/api/v1/badges` or new `/api/v1/certificate-templates`)

- `POST /certificate-templates` — create (name, orientation, layout).
- `GET /certificate-templates` — list for tenant.
- `GET /certificate-templates/{id}` — read one.
- `PUT /certificate-templates/{id}` — update layout/name (bumps version).
- `POST /certificate-templates/{id}/assets` — upload logo/background (base64 + type), returns asset key.
- `POST /certificate-templates/{id}/preview` — render sample PDF/PNG (no persist).
- `DELETE /certificate-templates/{id}` — archive/delete (blocked if in use).
- `PUT /badges/classes/{id}/template` — extended to accept either a built-in name or `{"custom_template_id": "..."}`.

## 8. Acceptance Criteria

1. An issuer, from the issuer login, can open a "Template Designer", drag blocks onto an A4 canvas, upload an institution logo, place it, add text with `{{recipient}}`/`{{badge_name}}`, preview it, and save it with a name.
2. Assigning that template to a badge class and downloading a certificate for an assertion of that class produces a PDF that visually matches the design, with the recipient name, badge name, logo, and the verification QR + signature panel present.
3. A tenant cannot see or render another tenant's template or assets.
4. An invalid or missing asset degrades gracefully (placeholder), never a 500; an invalid stored layout falls back to the default built-in.
5. Property tests pass for geometry/placeholder invariants; unit + integration tests cover CRUD, assignment, render, tenant isolation, malware-scan fail-closed, and permission enforcement.

## 9. Risks / Decisions to confirm in Design

- **R1 Renderer approach**: extend ReportLab with a data-driven `_render_custom(ctx, layout)` (consistent with existing templates, bottom-left origin math) vs. adopt the installed-but-unused WeasyPrint (HTML/CSS→PDF). **Recommendation: ReportLab data-driven** — one engine, keeps QR/signature/watermark/metadata logic unified, no second rendering stack to maintain. (If you prefer HTML/CSS flexibility, we can switch; it adds a second engine.)
- **R2 Preview format**: PDF (exact) vs PNG (faster inline display). **Recommendation: PDF**, shown in an embedded viewer; optionally a PNG first-page thumbnail later.
- **R3 Coordinate model**: normalized fractions (0..1) stored, mapped to A4 mm at render — resolution-independent and canvas-friendly. **Recommendation: normalized.**
- **R4 Fonts**: curated PDF-safe set first (Helvetica/Times/Courier families; optionally register 1–2 bundled TTFs like a serif display + sans). Font upload deferred.
- **R5 Custom selection mechanism**: `custom_template_id` FK presence vs. sentinel string. **Recommendation: FK presence** (cleaner; avoids overloading the enum), keep `certificate_template` for built-ins.
