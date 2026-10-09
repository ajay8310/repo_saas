# U6 — Live Documents + Dual Credential Downloads (Design)

Backs `aidlc-docs/inception/requirements/u6-dual-credentials-requirements.md`.
Extensions: Security OFF, Resiliency ON, PBT ON.
Approved decisions: Q1=C, no ZIP, Q3=A, issuer+beneficiary, reuse cert permissions.
Design choices: R1 (class PNG + embed), R2 (authenticated AssertionData build),
R3 (extend CertificateService). No DB migration.

---

## 1. OB assertion assembly (authenticated, tenant-scoped)

Add a helper on `CertificateService` that builds the OB2.0 assertion dict from
already-resolved rows (it already loads assertion + class + tenant in
`build_certificate`). It reuses `OpenBadgesSerializer` and mirrors the field
mapping in `PublicBadgeService` — but is NOT gated on `public==True`, so an
issuer/earner can download before publishing.

```python
# certificate_service.py
from app.services.openbadges import (
    AssertionData, BadgeClassData, IssuerProfile, OpenBadgesSerializer,
)
from app.services.issuance_service import new_recipient_salt

def _assertion_doc(self, assertion, badge_class, tenant) -> dict:
    base = f"{self.settings.public_base_url}/api/v1/public/badges"
    issuer = IssuerProfile(
        id_url=f"{base}/issuers/{tenant.id}",
        name=(tenant.issuer_name or tenant.name) if tenant else "Issuer",
        url=tenant.issuer_url if tenant else None,
        email=tenant.issuer_email if tenant else None,
    )
    bc = BadgeClassData(
        id_url=f"{base}/classes/{badge_class.id}",
        name=badge_class.name, description=badge_class.description,
        image_url=None,  # the baked PNG carries the image; JSON references hosted class
        criteria_narrative=badge_class.criteria_narrative,
        criteria_url=badge_class.criteria_url, issuer=issuer,
        tags=list(badge_class.tags or []), alignment=list(badge_class.alignment or []),
    )
    data = AssertionData(
        id_url=f"{base}/assertions/{assertion.id}",
        recipient_identity=assertion.beneficiary_id,
        recipient_salt=new_recipient_salt(),
        issued_on=assertion.issued_at,
        verify_url=f"{base}/assertions/{assertion.id}",
        badge_class=bc, expires=assertion.expires_at,
        revoked=assertion.status == "revoked",
        revocation_reason=assertion.revocation_reason,
    )
    return OpenBadgesSerializer().assertion(data)
```

Two public service methods (ownership-checked like `build_certificate`):

```python
@dataclass(frozen=True, slots=True)
class RenderedBadge:
    content: bytes
    media_type: str
    filename: str

async def build_badge_json(self, tenant_id, assertion_id, actor_id, actor_role,
                           require_owner=None) -> RenderedBadge:
    # set_tenant_context; resolve assertion (+owner check → CertificateNotFound);
    # class + tenant; doc = self._assertion_doc(...); audit(kind=json) + event; commit.
    return RenderedBadge(json.dumps(doc, indent=2).encode(), "application/ld+json",
                         f"badge-{assertion_id}.json")

async def build_badge_png(self, tenant_id, assertion_id, actor_id, actor_role,
                          require_owner=None) -> RenderedBadge:
    # same resolution; require class.image_s3_key; fetch bytes via _fetch_s3;
    # bake; return image/png. Raises BadgeImageNotBakeableError on missing/SVG.
```

## 2. Baking (`app/services/badge_baker.py`, pure + unit/property-testable)

```python
import io, json
from PIL import Image, PngImagePlugin

OB_KEYWORD = "openbadges"

class BadgeImageNotBakeableError(Exception): ...

def bake_png(png_bytes: bytes, assertion_doc: dict) -> bytes:
    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception as exc:
        raise BadgeImageNotBakeableError("badge image is not a readable image") from exc
    if img.format != "PNG":
        raise BadgeImageNotBakeableError("badge image must be a PNG to produce a baked badge")
    meta = PngImagePlugin.PngInfo()
    meta.add_itxt(OB_KEYWORD, json.dumps(assertion_doc))
    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()

def read_baked(png_bytes: bytes) -> dict | None:
    img = Image.open(io.BytesIO(png_bytes))
    raw = (img.info or {}).get(OB_KEYWORD)
    return json.loads(raw) if raw else None
```

- SVG guard is double: the class `image_s3_key` ends in `.svg` → short-circuit
  before fetch; and `img.format != "PNG"` catches anything else. Either path
  raises `BadgeImageNotBakeableError` → router maps to 422.
- `read_baked` exists for the round-trip property test.

## 3. Tenant-wide assertion listing

Add to `IssuanceService`:

```python
async def list_assertions(self, tenant_id, status=None, limit=50, offset=0) -> list[BadgeAssertion]:
    await set_tenant_context(self.db, str(tenant_id))
    stmt = select(BadgeAssertion)
    if status: stmt = stmt.where(BadgeAssertion.status == status)
    stmt = stmt.order_by(BadgeAssertion.issued_at.desc()).limit(limit).offset(offset)
    return list((await self.db.execute(stmt)).scalars().all())
```

Router `GET /badges/assertions` (`badge:read`) resolves class names via a single
keyed lookup (mirror `WalletService.list_wallet`), returns a list of:
`{assertion_id, badge_class_id, badge_name, beneficiary_id, status, issued_at,
expires_at, public, revoked_at}`.

## 4. Endpoints (mirror the certificate routes exactly)

`app/routers/badges.py` (issuer/admin, `badge:certificate`; list uses `badge:read`):
- `GET /badges/assertions` → `AssertionListItem[]`.
- `GET /badges/assertions/{id}/badge.json` → `Response(media_type="application/ld+json", Content-Disposition attachment)`.
- `GET /badges/assertions/{id}/badge.png` → `Response(media_type="image/png", ...)`; maps `BadgeImageNotBakeableError`→422, `CertificateNotFoundError`→404.

`app/routers/wallet.py` (beneficiary, `badge:wallet_certificate`, `require_owner=user.sub`):
- `GET /wallet/{id}/badge.json`, `GET /wallet/{id}/badge.png` — same shapes, ownership-checked.

Audit: `operation="badge:badge_download"`, metadata `{kind: json|png}`; analytics
`viewed` event channel `badge`.

## 5. Frontend

`frontend/src/lib/badges.ts`:
- `interface AssertionListItem { assertion_id; badge_class_id; badge_name; beneficiary_id; status; issued_at; expires_at; public; revoked_at }`
- `listAssertions(): Promise<AssertionListItem[]>` → GET `/badges/assertions`.
- `downloadBadgePng(id)`, `downloadBadgeJson(id)` → GET blobs.
- Generalize `savePdfBlob` → keep it (works for any blob); add `saveBlob(blob, filename)` alias used for png/json.

`frontend/src/lib/wallet.ts`:
- `downloadWalletBadgePng(id)`, `downloadWalletBadgeJson(id)` → GET `/wallet/{id}/badge.png|.json` blobs.

`frontend/src/pages/tenant/DocumentsPage.tsx` (rewrite data source):
- Replace `INITIAL_DOCS`/stub with `useEffect(listAssertions)` → rows; `live` flag + graceful empty state on failure (mirror WalletPage).
- Columns: Credential (assertion id short) · Badge (name) · Beneficiary · Status · Issued · Actions.
- Actions per row: **Certificate** (PDF, existing `downloadCertificate`), **Badge PNG**, **Badge JSON**, and Revoke for active (reuse `revokeAssertion`). Drop the DigiLocker demo column/sim and the JSON stub. Keep Upload/Bulk buttons wired to existing issuance if present; otherwise link to Badges page (issuance lives there). (Decision: remove the fake DigiLocker status column since these are badge assertions, not DigiLocker documents.)
- Search filters client-side over badge name / beneficiary / assertion id.

`frontend/src/pages/beneficiary/WalletPage.tsx`:
- Add two buttons in the action row beside Certificate: **Badge** (PNG) and **JSON**, calling the new wallet helpers + `saveBlob`, following the existing dynamic-import `downloadCertificate` pattern. `data-testid="wallet-badge-png-{id}"` / `wallet-badge-json-{id}"`.

## 6. Testing

- **Unit (backend)**: `bake_png` success; SVG/garbage → `BadgeImageNotBakeableError`; `read_baked` returns the embedded dict; `build_badge_json` field mapping (mock rows); `build_badge_png` missing/SVG image → error; ownership (`require_owner` mismatch → 404); `list_assertions` tenant scoping + ordering; RBAC on the new routes (issuer allowed, verifier denied, beneficiary own-only).
- **Property (Hypothesis)**: bake→read round-trip equals input dict for arbitrary valid assertion dicts + any valid source PNG (generated via Pillow); OB JSON always has required fields; revoked ⇒ `revoked:true`.
- **Integration**: issue → list via `GET /badges/assertions` → download all three (pdf/png/json) → parse the baked PNG back; SVG class → png 422 + json 200; cross-tenant + cross-earner denied.
- **Frontend**: `tsc` clean; the Documents page renders live rows and the three actions.

## 7. Resiliency & compatibility (enabled extensions)
- **Resiliency ON**: JSON download never fails for a resolvable assertion; PNG fails *cleanly* (422) when unbakeable; missing S3 image → 422 not 500; list is paginated. N/A: no new cross-service calls, no DR surface (no schema change).
- **PBT ON**: bake round-trip + OB field invariants above.
- **Security OFF** (not enforced), but we keep RLS, tenant/owner checks, audit, and no-raw-PII posture because it's the surrounding norm.
- **Backward compatible**: certificate + hosted public JSON untouched; no migration.
