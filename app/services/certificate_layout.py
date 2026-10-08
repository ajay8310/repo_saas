"""Certificate layout schema, validation, and placeholder resolution (U5).

A certificate template's ``layout`` is a single JSON object describing an A4
page and a list of positioned blocks. Coordinates are normalized fractions of
the page (0..1), top-left origin in the editor; the renderer converts to
ReportLab's bottom-left origin.

This module is pure (no DB/network) so it is trivially unit- and property-
testable. It provides:

* pydantic models (:class:`CertificateLayout`, :class:`PageSettings`,
  :class:`Block`) for structural validation on save,
* :func:`validate_layout` — a tolerant checker returning a list of human-readable
  issues (empty = valid) used by the service and property tests, and
* :func:`resolve_placeholders` — safe ``{{token}}`` substitution where unknown
  tokens resolve to empty strings (never leaked literally).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:  # avoid a runtime import cycle with the renderer
    from app.services.certificate_renderer import CertificateContext

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

# ReportLab built-in Type-1 fonts — always available, zero bundling risk.
FONT_WHITELIST: frozenset[str] = frozenset(
    {
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-Oblique",
        "Times-Roman",
        "Times-Bold",
        "Times-Italic",
        "Courier",
        "Courier-Bold",
    }
)

# Tokens resolvable from a CertificateContext at render time.
PLACEHOLDER_WHITELIST: frozenset[str] = frozenset(
    {
        "recipient",
        "badge_name",
        "issuer_name",
        "issued_at",
        "expires_at",
        "criteria",
        "verify_url",
        "assertion_id",
    }
)

BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "text",
        "recipient_photo",
        "badge_image",
        "logo",
        "qr",
        "signature",
        "line",
        "rect",
    }
)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Geometry tolerance so floating-point sums like 0.1 + 0.9 don't spuriously fail.
_EPS = 1e-4

MIN_FONT_SIZE = 6.0
MAX_FONT_SIZE = 96.0


# ---------------------------------------------------------------------------
# Pydantic models (structural validation)
# ---------------------------------------------------------------------------


class BlockStyle(BaseModel):
    """Type-specific style. All optional; the renderer applies sensible defaults."""

    text: str | None = None
    font: str | None = None
    size: float | None = Field(default=None, ge=MIN_FONT_SIZE, le=MAX_FONT_SIZE)
    color: str | None = None
    align: Literal["left", "center", "right"] | None = None
    caption: str | None = None
    border: bool | None = None
    border_color: str | None = None
    line_width: float | None = Field(default=None, ge=0.1, le=20.0)
    fill: bool | None = None

    @field_validator("color", "border_color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is not None and not _HEX_COLOR.match(v):
            raise ValueError("color must be a #rrggbb hex string")
        return v

    @field_validator("font")
    @classmethod
    def _check_font(cls, v: str | None) -> str | None:
        if v is not None and v not in FONT_WHITELIST:
            raise ValueError(f"font must be one of {sorted(FONT_WHITELIST)}")
        return v


class Block(BaseModel):
    """A single positioned element on the page."""

    id: str = Field(..., min_length=1, max_length=64)
    type: Literal[
        "text", "recipient_photo", "badge_image", "logo", "qr", "signature", "line", "rect"
    ]
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., gt=0.0, le=1.0)
    h: float = Field(..., gt=0.0, le=1.0)
    z: int = Field(default=0, ge=0, le=1000)
    rotation: float = Field(default=0.0, ge=-360.0, le=360.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    style: BlockStyle = Field(default_factory=BlockStyle)

    @field_validator("x")
    @classmethod
    def _noop(cls, v: float) -> float:  # bounds handled cross-field below
        return v


class PageSettings(BaseModel):
    orientation: Literal["portrait", "landscape"] = "portrait"
    background_color: str = "#ffffff"
    background_image: bool = False

    @field_validator("background_color")
    @classmethod
    def _check_bg(cls, v: str) -> str:
        if not _HEX_COLOR.match(v):
            raise ValueError("background_color must be a #rrggbb hex string")
        return v


class CertificateLayout(BaseModel):
    page: PageSettings = Field(default_factory=PageSettings)
    blocks: list[Block] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tolerant validation (used by the service + property tests)
# ---------------------------------------------------------------------------


def validate_layout(layout: dict[str, Any], max_blocks: int = 60) -> list[str]:
    """Return a list of human-readable issues; empty means valid.

    Performs the structural checks pydantic does *plus* the cross-field geometry
    bound (``x+w <= 1``, ``y+h <= 1``) that a per-field validator can't express.
    Unknown placeholder tokens are NOT errors here (they resolve to empty at
    render), but malformed structure, out-of-range geometry, bad enums, and
    oversized block counts are.
    """
    issues: list[str] = []

    try:
        model = CertificateLayout.model_validate(layout)
    except Exception as exc:  # pydantic ValidationError or type errors
        return [f"layout structure invalid: {exc}"]

    if len(model.blocks) > max_blocks:
        issues.append(f"too many blocks: {len(model.blocks)} > {max_blocks}")

    seen_ids: set[str] = set()
    for i, b in enumerate(model.blocks):
        where = f"block[{i}] (id={b.id!r})"
        if b.id in seen_ids:
            issues.append(f"{where}: duplicate block id")
        seen_ids.add(b.id)
        if b.x + b.w > 1.0 + _EPS:
            issues.append(f"{where}: x+w={b.x + b.w:.4f} exceeds page width (1.0)")
        if b.y + b.h > 1.0 + _EPS:
            issues.append(f"{where}: y+h={b.y + b.h:.4f} exceeds page height (1.0)")
        if b.type == "text" and not (b.style.text and b.style.text.strip()):
            issues.append(f"{where}: text block requires non-empty style.text")

    return issues


def layout_has_verification(layout: dict[str, Any]) -> bool:
    """True if the layout already includes a qr or signature block.

    The renderer injects a default verification panel when this is False, so the
    QR + signature guarantee (FR-U5-10) always holds.
    """
    blocks = layout.get("blocks") or []
    return any(
        isinstance(b, dict) and b.get("type") in ("qr", "signature") for b in blocks
    )


# ---------------------------------------------------------------------------
# Placeholder resolution
# ---------------------------------------------------------------------------


def placeholder_values(ctx: CertificateContext) -> dict[str, str]:
    """Map whitelisted tokens to their string values from a render context."""
    return {
        "recipient": ctx.recipient_display or "",
        "badge_name": ctx.badge_name or "",
        "issuer_name": ctx.issuer_name or "",
        "issued_at": ctx.issued_at or "",
        "expires_at": ctx.expires_at or "",
        "criteria": ctx.criteria or "",
        "verify_url": ctx.verify_url or "",
        "assertion_id": ctx.assertion_id or "",
    }


def resolve_placeholders(text: str, ctx: CertificateContext) -> str:
    """Replace ``{{token}}`` with values from *ctx*.

    Known tokens are substituted; unknown tokens resolve to an empty string so
    no raw ``{{...}}`` ever leaks onto a rendered certificate (FR-U5-5).
    """
    if not text:
        return ""
    values = placeholder_values(ctx)

    def _sub(m: re.Match[str]) -> str:
        token = m.group(1)
        return values.get(token, "")

    return _PLACEHOLDER.sub(_sub, text)
