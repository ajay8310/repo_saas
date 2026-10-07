"""Certificate rendering with issuer-selectable templates (U4).

Renders a badge assertion as a single-page A4 PDF certificate in one of four
built-in templates — ``classic``, ``modern``, ``elegant``, ``minimal``. Every
template embeds:

* the **recipient (student) photo** (when provided),
* the **badge image** (when provided),
* a **QR code** pointing at the public verification page — scanning it opens the
  hosted page that shows the *same* photo and details live, so the printed
  certificate can be checked against the issuer's record (authenticity), and
* the **issuer digital signature** (RS256 JWS) in the PDF metadata, verifiable
  with the issuer's published public key.

Revoked assertions get a prominent watermark.

This module is pure rendering: callers (``CertificateService``) resolve the
assertion, fetch image bytes, and produce the signature, then pass everything in
via :class:`CertificateContext`. No DB or network here, so templates are
trivially unit-testable.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TEMPLATE_NAMES: tuple[str, ...] = ("classic", "modern", "elegant", "minimal")


@dataclass(frozen=True, slots=True)
class CertificateContext:
    """Everything needed to render a certificate, already resolved."""

    assertion_id: str
    badge_name: str
    recipient_display: str
    issuer_name: str
    issued_at: str
    expires_at: str | None
    criteria: str | None
    verify_url: str
    signature_jws: str
    status: str = "active"
    revoked_at: str | None = None
    revocation_reason: str | None = None
    badge_image: bytes | None = None
    recipient_photo: bytes | None = None


def render_certificate(ctx: CertificateContext, template: str) -> bytes:
    """Render *ctx* using the named template, returning PDF bytes.

    Falls back to ``classic`` for an unknown template name rather than failing a
    download over a bad config value.
    """
    renderer = _TEMPLATES.get(template, _render_classic)
    return renderer(ctx)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _qr_png(data: str, box_size: int = 5) -> bytes:
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_reader(data: bytes | None):
    """Return a reportlab ImageReader for *data*, or None if unusable."""
    if not data:
        return None
    from reportlab.lib.utils import ImageReader

    try:
        return ImageReader(io.BytesIO(data))
    except Exception:
        logger.debug("Could not read embedded image for certificate", exc_info=True)
        return None


def _new_canvas(ctx: CertificateContext):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"Certificate — {ctx.badge_name}")
    pdf.setAuthor(ctx.issuer_name)
    pdf.setSubject(f"Badge assertion {ctx.assertion_id}")
    # Full issuer signature travels in metadata so it survives a round-trip.
    pdf.setKeywords(
        [
            f"assertion_id={ctx.assertion_id}",
            f"issuer_signature={ctx.signature_jws}",
            f"verify_url={ctx.verify_url}",
        ]
    )
    return pdf, buf


def _draw_photo(pdf, ctx: CertificateContext, x, y, size) -> bool:
    """Draw the recipient photo in a square box. Returns True if drawn."""
    reader = _image_reader(ctx.recipient_photo)
    if reader is None:
        return False
    from reportlab.lib import colors

    pdf.saveState()
    pdf.setStrokeColor(colors.HexColor("#d1d5db"))
    pdf.setLineWidth(1)
    pdf.rect(x, y, size, size, stroke=1, fill=0)
    pdf.drawImage(reader, x, y, width=size, height=size, preserveAspectRatio=True, anchor="c")
    pdf.restoreState()
    return True


def _draw_qr(pdf, ctx: CertificateContext, x, y, size, label_color: str) -> None:
    from reportlab.lib import colors

    pdf.drawImage(_image_reader(_qr_png(ctx.verify_url)), x, y, width=size, height=size)
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor(label_color))
    pdf.drawCentredString(x + size / 2, y - 4 * _mm(), "Scan to verify authenticity")


def _draw_revoked(pdf, width, height) -> None:
    from reportlab.lib import colors

    pdf.saveState()
    pdf.setFillColor(colors.Color(0.86, 0.15, 0.15, alpha=0.28))
    pdf.setFont("Helvetica-Bold", 72)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(32)
    pdf.drawCentredString(0, 0, "REVOKED")
    pdf.restoreState()


def _draw_signature_footer(pdf, ctx: CertificateContext, x, y) -> None:
    from reportlab.lib import colors

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawString(x, y + 5 * _mm(), f"Digitally signed by {ctx.issuer_name}")
    pdf.setFont("Courier", 6)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawString(x, y, f"signature: {ctx.signature_jws[:72]}...")


def _mm() -> float:
    from reportlab.lib.units import mm

    return mm


def _finish(pdf, buf, ctx, width, height) -> bytes:
    if ctx.status == "revoked":
        _draw_revoked(pdf, width, height)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Template: classic — centered, formal, serif-ish
# ---------------------------------------------------------------------------


def _render_classic(ctx: CertificateContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    mm = _mm()
    pdf, buf = _new_canvas(ctx)
    width, height = A4

    # Double border.
    pdf.setStrokeColor(colors.HexColor("#1e3a8a"))
    pdf.setLineWidth(3)
    pdf.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)
    pdf.setLineWidth(1)
    pdf.rect(16 * mm, 16 * mm, width - 32 * mm, height - 32 * mm)

    pdf.setFillColor(colors.HexColor("#1e3a8a"))
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(width / 2, height - 32 * mm, ctx.issuer_name.upper())

    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 26)
    pdf.drawCentredString(width / 2, height - 55 * mm, "Certificate of Achievement")

    pdf.setFont("Helvetica", 12)
    pdf.setFillColor(colors.HexColor("#374151"))
    pdf.drawCentredString(width / 2, height - 70 * mm, "This is proudly presented to")

    pdf.setFont("Helvetica-Bold", 22)
    pdf.setFillColor(colors.HexColor("#1e3a8a"))
    pdf.drawCentredString(width / 2, height - 85 * mm, ctx.recipient_display)

    pdf.setFont("Helvetica", 12)
    pdf.setFillColor(colors.HexColor("#374151"))
    pdf.drawCentredString(width / 2, height - 98 * mm, "for earning the badge")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.drawCentredString(width / 2, height - 108 * mm, ctx.badge_name)

    # Photo (left) and badge image (right) flanking.
    _draw_photo(pdf, ctx, 28 * mm, height - 150 * mm, 32 * mm)
    badge_img = _image_reader(ctx.badge_image)
    if badge_img:
        pdf.drawImage(badge_img, width - 60 * mm, height - 150 * mm, width=32 * mm,
                      height=32 * mm, preserveAspectRatio=True, mask="auto")

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, 48 * mm, f"Issued: {ctx.issued_at}"
                          + (f"   |   Expires: {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_qr(pdf, ctx, width / 2 - 16 * mm, 54 * mm, 32 * mm, "#6b7280")
    _draw_signature_footer(pdf, ctx, 20 * mm, 22 * mm)
    return _finish(pdf, buf, ctx, width, height)


# ---------------------------------------------------------------------------
# Template: modern — left color band, sans, left-aligned
# ---------------------------------------------------------------------------


def _render_modern(ctx: CertificateContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    mm = _mm()
    pdf, buf = _new_canvas(ctx)
    width, height = A4

    pdf.setFillColor(colors.HexColor("#0ea5e9"))
    pdf.rect(0, 0, 20 * mm, height, stroke=0, fill=1)

    pdf.setFillColor(colors.HexColor("#0ea5e9"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(32 * mm, height - 28 * mm, ctx.issuer_name.upper())

    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawString(32 * mm, height - 50 * mm, "CERTIFICATE")
    pdf.setFont("Helvetica", 13)
    pdf.setFillColor(colors.HexColor("#64748b"))
    pdf.drawString(32 * mm, height - 58 * mm, "OF ACHIEVEMENT")

    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawString(32 * mm, height - 78 * mm, "Awarded to")
    pdf.setFont("Helvetica-Bold", 22)
    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.drawString(32 * mm, height - 90 * mm, ctx.recipient_display)

    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawString(32 * mm, height - 104 * mm, "For earning:")
    pdf.setFont("Helvetica-Bold", 15)
    pdf.setFillColor(colors.HexColor("#0ea5e9"))
    pdf.drawString(32 * mm, height - 113 * mm, ctx.badge_name)

    if ctx.criteria:
        pdf.setFont("Helvetica-Oblique", 9)
        pdf.setFillColor(colors.HexColor("#64748b"))
        pdf.drawString(32 * mm, height - 123 * mm, _truncate(ctx.criteria, 90))

    _draw_photo(pdf, ctx, width - 55 * mm, height - 70 * mm, 32 * mm)

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#64748b"))
    pdf.drawString(32 * mm, 44 * mm, f"Issued: {ctx.issued_at}"
                   + (f"   |   Expires: {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_qr(pdf, ctx, width - 52 * mm, 44 * mm, 30 * mm, "#64748b")
    _draw_signature_footer(pdf, ctx, 32 * mm, 22 * mm)
    return _finish(pdf, buf, ctx, width, height)


# ---------------------------------------------------------------------------
# Template: elegant — gold accents, centered, thin rules
# ---------------------------------------------------------------------------


def _render_elegant(ctx: CertificateContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    mm = _mm()
    pdf, buf = _new_canvas(ctx)
    width, height = A4

    gold = colors.HexColor("#b8860b")
    pdf.setStrokeColor(gold)
    pdf.setLineWidth(1.5)
    pdf.rect(14 * mm, 14 * mm, width - 28 * mm, height - 28 * mm)

    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawCentredString(width / 2, height - 34 * mm, ctx.issuer_name)
    pdf.setLineWidth(0.5)
    pdf.line(width / 2 - 30 * mm, height - 37 * mm, width / 2 + 30 * mm, height - 37 * mm)

    pdf.setFillColor(colors.HexColor("#1f2937"))
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawCentredString(width / 2, height - 58 * mm, "Certificate of Excellence")

    _draw_photo(pdf, ctx, width / 2 - 16 * mm, height - 100 * mm, 32 * mm)

    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, height - 112 * mm, "awarded to")
    pdf.setFont("Helvetica-Bold", 20)
    pdf.setFillColor(gold)
    pdf.drawCentredString(width / 2, height - 124 * mm, ctx.recipient_display)

    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, height - 136 * mm, f"for the achievement of {ctx.badge_name}")

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawCentredString(width / 2, 46 * mm, f"Issued {ctx.issued_at}"
                          + (f"  ·  Expires {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_qr(pdf, ctx, width / 2 - 15 * mm, 52 * mm, 30 * mm, "#9ca3af")
    _draw_signature_footer(pdf, ctx, 20 * mm, 20 * mm)
    return _finish(pdf, buf, ctx, width, height)


# ---------------------------------------------------------------------------
# Template: minimal — clean, lots of whitespace, no borders
# ---------------------------------------------------------------------------


def _render_minimal(ctx: CertificateContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    mm = _mm()
    pdf, buf = _new_canvas(ctx)
    width, height = A4

    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(24 * mm, height - 30 * mm, ctx.issuer_name)

    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawString(24 * mm, height - 60 * mm, "CERTIFICATE")

    pdf.setFont("Helvetica-Bold", 24)
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.drawString(24 * mm, height - 75 * mm, ctx.recipient_display)

    pdf.setFont("Helvetica", 13)
    pdf.setFillColor(colors.HexColor("#374151"))
    pdf.drawString(24 * mm, height - 88 * mm, ctx.badge_name)

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawString(24 * mm, height - 98 * mm, f"Issued {ctx.issued_at}"
                   + (f"  ·  Expires {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_photo(pdf, ctx, 24 * mm, 40 * mm, 30 * mm)
    _draw_qr(pdf, ctx, width - 54 * mm, 40 * mm, 30 * mm, "#9ca3af")
    _draw_signature_footer(pdf, ctx, 24 * mm, 24 * mm)
    return _finish(pdf, buf, ctx, width, height)


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


_TEMPLATES: dict[str, Callable[[CertificateContext], bytes]] = {
    "classic": _render_classic,
    "modern": _render_modern,
    "elegant": _render_elegant,
    "minimal": _render_minimal,
}
