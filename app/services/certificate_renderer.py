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
    """Return a reportlab ImageReader for *data*, or None if unusable.

    Normalizes the image to an RGBA PNG first. ReportLab's ImageReader can
    silently fail to place some PNGs (notably palette/transparency variants
    produced by Pillow), so we round-trip through Pillow to a canonical form
    and keep an alpha channel so transparent badge art composites cleanly.
    """
    if not data:
        return None
    from reportlab.lib.utils import ImageReader

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        # Flatten any transparency onto white and emit RGB. ReportLab's
        # drawImage(mask="auto") can silently drop RGBA/palette PNGs; a plain
        # RGB raster always places correctly.
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)
    except Exception:
        logger.debug("Could not read embedded image for certificate", exc_info=True)
        # Fall back to the raw bytes — better a direct attempt than nothing.
        try:
            return ImageReader(io.BytesIO(data))
        except Exception:
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
    """Legacy thin footer (kept for callers that want a one-liner)."""
    from reportlab.lib import colors

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawString(x, y + 5 * _mm(), f"Digitally signed by {ctx.issuer_name}")
    pdf.setFont("Courier", 6)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawString(x, y, f"signature: {ctx.signature_jws[:72]}...")


def _short_sig(jws: str) -> str:
    """A readable fingerprint of the signature (last segment is the sig part)."""
    seg = jws.rsplit(".", 1)[-1]
    cleaned = seg.replace("-", "").replace("_", "")
    return cleaned[:32].upper() if cleaned else "n/a"


# ---------------------------------------------------------------------------
# Decorative primitives — make certificates look formal/real (shared)
# ---------------------------------------------------------------------------


def _draw_ornate_frame(pdf, width, height, outer, inner, mid=None) -> None:
    """A concentric double frame with inset corner ticks — a classic certificate
    border. Colors are hex strings; *mid* adds a thin third rule when given."""
    from reportlab.lib import colors

    mm = _mm()
    pdf.saveState()
    pdf.setStrokeColor(colors.HexColor(outer))
    pdf.setLineWidth(4)
    pdf.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm)
    if mid:
        pdf.setStrokeColor(colors.HexColor(mid))
        pdf.setLineWidth(0.8)
        pdf.rect(13 * mm, 13 * mm, width - 26 * mm, height - 26 * mm)
    pdf.setStrokeColor(colors.HexColor(inner))
    pdf.setLineWidth(1.4)
    pdf.rect(16 * mm, 16 * mm, width - 32 * mm, height - 32 * mm)
    # Corner flourishes: short double rules meeting at each inner corner.
    pdf.setLineWidth(1.0)
    c = 16 * mm
    arm = 14 * mm
    for cx, cy, dx, dy in (
        (c, c, 1, 1), (width - c, c, -1, 1),
        (c, height - c, 1, -1), (width - c, height - c, -1, -1),
    ):
        pdf.line(cx + dx * 4 * mm, cy, cx + dx * (4 * mm + arm), cy)
        pdf.line(cx, cy + dy * 4 * mm, cx, cy + dy * (4 * mm + arm))
    pdf.restoreState()


def _draw_seal(pdf, cx, cy, r, ring_color, accent_color, label="VERIFIED") -> None:
    """A gold medallion: concentric rings, a star burst, and a small label.

    Draws at centre ``(cx, cy)`` with outer radius ``r``. Points-based units."""
    from reportlab.lib import colors

    ring = colors.HexColor(ring_color)
    accent = colors.HexColor(accent_color)
    pdf.saveState()
    # Outer disc (filled, pale) + rings.
    pdf.setFillColor(colors.Color(*_rgb(accent_color), alpha=0.12))
    pdf.circle(cx, cy, r, stroke=0, fill=1)
    pdf.setStrokeColor(ring)
    pdf.setLineWidth(2.2)
    pdf.circle(cx, cy, r, stroke=1, fill=0)
    pdf.setLineWidth(0.8)
    pdf.circle(cx, cy, r * 0.80, stroke=1, fill=0)
    # Star burst (12-point) between the rings.
    import math

    pdf.setFillColor(ring)
    path = pdf.beginPath()
    pts = 12
    r_out, r_in = r * 0.72, r * 0.42
    for i in range(pts * 2):
        ang = math.pi * i / pts
        rad = r_out if i % 2 == 0 else r_in
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.close()
    pdf.drawPath(path, stroke=0, fill=1)
    # Inner disc + label.
    pdf.setFillColor(colors.white)
    pdf.circle(cx, cy, r * 0.30, stroke=0, fill=1)
    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", max(5.0, r * 0.16))
    pdf.drawCentredString(cx, cy - r * 0.06, label)
    pdf.restoreState()


def _draw_ribbon(pdf, cx, top_y, w, h, color) -> None:
    """Two ribbon tails hanging from ``(cx, top_y)`` — pairs with a seal above."""
    from reportlab.lib import colors

    col = colors.HexColor(color)
    dark = colors.Color(*_rgb(color), alpha=0.75)
    pdf.saveState()
    for sign in (-1, 1):
        x0 = cx + sign * w * 0.55
        p = pdf.beginPath()
        p.moveTo(x0 - w / 2, top_y)
        p.lineTo(x0 + w / 2, top_y)
        p.lineTo(x0 + w / 2, top_y - h)
        p.lineTo(x0, top_y - h + h * 0.28)  # notch
        p.lineTo(x0 - w / 2, top_y - h)
        p.close()
        pdf.setFillColor(col if sign < 0 else dark)
        pdf.drawPath(p, stroke=0, fill=1)
    pdf.restoreState()


def _draw_signature_line(pdf, cx, y, w, name, title="Authorised Signatory") -> None:
    """A signature rule with the issuer name below — the human-authority touch."""
    from reportlab.lib import colors

    mm = _mm()
    pdf.saveState()
    pdf.setStrokeColor(colors.HexColor("#334155"))
    pdf.setLineWidth(0.8)
    pdf.line(cx - w / 2, y, cx + w / 2, y)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(colors.HexColor("#1f2937"))
    pdf.drawCentredString(cx, y - 5 * mm, name)
    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(colors.HexColor("#94a3b8"))
    pdf.drawCentredString(cx, y - 9 * mm, title)
    pdf.restoreState()


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _draw_verification_panel(pdf, ctx: CertificateContext, x, y, w) -> None:
    """A clearly visible verification panel: QR + digital-signature details.

    Drawn as a bordered box so the recipient and any verifier can see at a
    glance that the certificate is digitally signed and how to verify it.
    ``(x, y)`` is the bottom-left; ``w`` is the panel width.
    """
    from reportlab.lib import colors

    mm = _mm()
    h = 40 * mm
    qr_size = 32 * mm

    # Panel background + border.
    pdf.saveState()
    pdf.setFillColor(colors.HexColor("#f8fafc"))
    pdf.setStrokeColor(colors.HexColor("#1e3a8a"))
    pdf.setLineWidth(1)
    pdf.roundRect(x, y, w, h, 4, stroke=1, fill=1)
    pdf.restoreState()

    pad = 5 * mm
    qr_x = x + pad
    qr_y = y + (h - qr_size) / 2
    pdf.drawImage(
        _image_reader(_qr_png(ctx.verify_url)), qr_x, qr_y, width=qr_size, height=qr_size
    )
    pdf.setFont("Helvetica", 6.5)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawCentredString(qr_x + qr_size / 2, qr_y - 3.5 * mm, "Scan to verify")

    # Text column to the right of the QR.
    tx = qr_x + qr_size + pad
    ty = y + h - 8 * mm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(colors.HexColor("#166534"))
    # A check mark + statement so the signature is unmistakable.
    pdf.drawString(tx, ty, "\u2714  Digitally signed & verifiable")

    pdf.setFont("Helvetica", 8.5)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawString(tx, ty - 7 * mm, f"Issuer: {ctx.issuer_name}")

    pdf.setFont("Helvetica", 7.5)
    pdf.setFillColor(colors.HexColor("#64748b"))
    pdf.drawString(tx, ty - 12.5 * mm, "Verify at:")
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.setFillColor(colors.HexColor("#1e3a8a"))
    pdf.drawString(tx, ty - 16.5 * mm, _truncate(ctx.verify_url, 62))

    pdf.setFont("Courier", 7)
    pdf.setFillColor(colors.HexColor("#94a3b8"))
    pdf.drawString(tx, ty - 22 * mm, f"RS256 sig: {_short_sig(ctx.signature_jws)}")


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
# Template: classic — formal, decorative frame + gold seal/ribbon (serif)
# ---------------------------------------------------------------------------

_NAVY = "#1e3a8a"
_GOLD = "#b8860b"
_INK = "#1f2937"


def _render_classic(ctx: CertificateContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4

    mm = _mm()
    pdf, buf = _new_canvas(ctx)
    width, height = A4

    # Decorative navy+gold concentric frame with corner flourishes.
    _draw_ornate_frame(pdf, width, height, outer=_NAVY, inner=_NAVY, mid=_GOLD)

    # Issuer name (gold, letter-spaced-feel via a thin rule under it).
    pdf.setFillColor(colors.HexColor(_GOLD))
    pdf.setFont("Times-Bold", 15)
    pdf.drawCentredString(width / 2, height - 34 * mm, ctx.issuer_name.upper())
    pdf.setStrokeColor(colors.HexColor(_GOLD))
    pdf.setLineWidth(0.6)
    pdf.line(width / 2 - 34 * mm, height - 37 * mm, width / 2 + 34 * mm, height - 37 * mm)

    # Title — serif, formal.
    pdf.setFillColor(colors.HexColor(_NAVY))
    pdf.setFont("Times-Bold", 34)
    pdf.drawCentredString(width / 2, height - 56 * mm, "Certificate of Achievement")

    pdf.setFont("Times-Italic", 13)
    pdf.setFillColor(colors.HexColor("#4b5563"))
    pdf.drawCentredString(width / 2, height - 70 * mm, "This is proudly presented to")

    # Recipient — large serif with an underline rule.
    pdf.setFont("Times-BoldItalic", 30)
    pdf.setFillColor(colors.HexColor(_INK))
    pdf.drawCentredString(width / 2, height - 88 * mm, ctx.recipient_display)
    pdf.setStrokeColor(colors.HexColor("#d1d5db"))
    pdf.setLineWidth(0.6)
    pdf.line(width / 2 - 70 * mm, height - 92 * mm, width / 2 + 70 * mm, height - 92 * mm)

    pdf.setFont("Times-Roman", 13)
    pdf.setFillColor(colors.HexColor("#4b5563"))
    pdf.drawCentredString(width / 2, height - 104 * mm, "in recognition of earning the badge")
    pdf.setFont("Times-Bold", 18)
    pdf.setFillColor(colors.HexColor(_NAVY))
    pdf.drawCentredString(width / 2, height - 115 * mm, ctx.badge_name)

    if ctx.criteria:
        pdf.setFont("Times-Italic", 10)
        pdf.setFillColor(colors.HexColor("#6b7280"))
        pdf.drawCentredString(width / 2, height - 124 * mm, _truncate(ctx.criteria, 95))

    # Recipient photo (left) and the badge medallion image (right).
    _draw_photo(pdf, ctx, 30 * mm, 78 * mm, 30 * mm)
    badge_img = _image_reader(ctx.badge_image)
    if badge_img:
        pdf.drawImage(badge_img, width - 60 * mm, 78 * mm, width=30 * mm,
                      height=30 * mm, preserveAspectRatio=True, mask="auto")

    # Gold seal + ribbon, centred low on the page.
    seal_cx, seal_cy, seal_r = width / 2, 96 * mm, 15 * mm
    _draw_ribbon(pdf, seal_cx, seal_cy - seal_r * 0.4, 9 * mm, 16 * mm, _NAVY)
    _draw_seal(pdf, seal_cx, seal_cy, seal_r, ring_color=_GOLD, accent_color=_NAVY)

    # Issued/expiry line.
    pdf.setFont("Times-Roman", 10)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, 70 * mm, f"Issued: {ctx.issued_at}"
                          + (f"      Expires: {ctx.expires_at}" if ctx.expires_at else ""))

    # Signature line (left of the verification panel area).
    _draw_signature_line(pdf, 56 * mm, 58 * mm, 50 * mm, ctx.issuer_name)

    _draw_verification_panel(pdf, ctx, 24 * mm, 20 * mm, width - 48 * mm)
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

    sky = "#0ea5e9"
    pdf.setFillColor(colors.HexColor(sky))
    pdf.rect(0, 0, 20 * mm, height, stroke=0, fill=1)
    # Thin accent bar across the top for a finished, framed feel.
    pdf.rect(20 * mm, height - 8 * mm, width - 20 * mm, 8 * mm, stroke=0, fill=1)

    # Seal in the top-right so it reads as an award, not a memo.
    _draw_seal(pdf, width - 40 * mm, height - 36 * mm, 13 * mm, ring_color=sky, accent_color="#0f172a")

    pdf.setFillColor(colors.HexColor(sky))
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
    pdf.drawString(32 * mm, 70 * mm, f"Issued: {ctx.issued_at}"
                   + (f"   |   Expires: {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_verification_panel(pdf, ctx, 32 * mm, 20 * mm, width - 56 * mm)
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

    gold = "#b8860b"
    deep = "#7c5e10"

    # Thin gold double frame with corner flourishes.
    _draw_ornate_frame(pdf, width, height, outer=gold, inner=deep, mid=gold)

    pdf.setFillColor(colors.HexColor(deep))
    pdf.setFont("Times-Bold", 13)
    pdf.drawCentredString(width / 2, height - 34 * mm, ctx.issuer_name)
    pdf.setStrokeColor(colors.HexColor(gold))
    pdf.setLineWidth(0.5)
    pdf.line(width / 2 - 32 * mm, height - 37 * mm, width / 2 + 32 * mm, height - 37 * mm)

    pdf.setFillColor(colors.HexColor("#1f2937"))
    pdf.setFont("Times-Bold", 32)
    pdf.drawCentredString(width / 2, height - 56 * mm, "Certificate of Excellence")

    # Seal at the top-centre area for the elegant look.
    _draw_seal(pdf, width / 2, height - 86 * mm, 15 * mm, ring_color=gold, accent_color=deep)

    pdf.setFont("Times-Italic", 12)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, height - 112 * mm, "awarded to")
    pdf.setFont("Times-BoldItalic", 28)
    pdf.setFillColor(colors.HexColor(deep))
    pdf.drawCentredString(width / 2, height - 127 * mm, ctx.recipient_display)
    pdf.setStrokeColor(colors.HexColor("#e5e7eb"))
    pdf.setLineWidth(0.5)
    pdf.line(width / 2 - 60 * mm, height - 131 * mm, width / 2 + 60 * mm, height - 131 * mm)

    pdf.setFont("Times-Roman", 12)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(width / 2, height - 142 * mm, f"for the achievement of {ctx.badge_name}")

    _draw_photo(pdf, ctx, 30 * mm, 76 * mm, 28 * mm)

    pdf.setFont("Times-Roman", 10)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawCentredString(width / 2, 68 * mm, f"Issued {ctx.issued_at}"
                          + (f"   ·   Expires {ctx.expires_at}" if ctx.expires_at else ""))

    _draw_signature_line(pdf, width - 56 * mm, 58 * mm, 50 * mm, ctx.issuer_name)
    _draw_verification_panel(pdf, ctx, 24 * mm, 20 * mm, width - 48 * mm)
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

    _draw_photo(pdf, ctx, 24 * mm, 66 * mm, 28 * mm)
    _draw_verification_panel(pdf, ctx, 24 * mm, 20 * mm, width - 48 * mm)
    return _finish(pdf, buf, ctx, width, height)


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


_TEMPLATES: dict[str, Callable[[CertificateContext], bytes]] = {
    "classic": _render_classic,
    "modern": _render_modern,
    "elegant": _render_elegant,
    "minimal": _render_minimal,
}


# ---------------------------------------------------------------------------
# Custom (issuer-designed) templates — data-driven rendering (U5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CustomAssets:
    """Designer-uploaded assets resolved to bytes for a custom render."""

    logo: bytes | None = None
    background: bytes | None = None


def render_custom_certificate(
    ctx: CertificateContext,
    layout: dict,
    assets: CustomAssets | None = None,
) -> bytes:
    """Render a certificate from an issuer-designed *layout* (U5).

    *layout* is the validated JSON (``{"page": {...}, "blocks": [...]}``) with
    normalized (0..1, top-left origin) coordinates. Any failure falls back to the
    classic built-in so a download never 500s (NFR-U5-2). The verification QR +
    signature are always present: if the layout omits both, a default panel is
    injected at the bottom (FR-U5-10). The RS256 JWS is embedded in metadata by
    ``_new_canvas`` as for every template.
    """
    try:
        return _render_custom(ctx, layout, assets or CustomAssets())
    except Exception:
        logger.warning(
            "Custom certificate render failed; falling back to classic",
            exc_info=True,
        )
        return _render_classic(ctx)


def _page_size(orientation: str):
    from reportlab.lib.pagesizes import A4, landscape

    return landscape(A4) if orientation == "landscape" else A4


def _abs_rect(block: dict, pw: float, ph: float) -> tuple[float, float, float, float]:
    """Map a normalized (top-left origin) block to absolute ReportLab coords.

    Returns ``(x, y, w, h)`` with a bottom-left origin, clamped on-page.
    """
    nx = _clamp01(block.get("x", 0.0))
    ny = _clamp01(block.get("y", 0.0))
    nw = _clamp01(block.get("w", 0.0))
    nh = _clamp01(block.get("h", 0.0))
    aw = nw * pw
    ah = nh * ph
    ax = nx * pw
    ay = ph - (ny * ph) - ah  # flip origin
    return ax, max(ay, 0.0), aw, ah


def _clamp01(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f < 0 else 1.0 if f > 1 else f


def _render_custom(ctx: CertificateContext, layout: dict, assets: CustomAssets) -> bytes:
    from reportlab.lib import colors

    from app.services.certificate_layout import (
        layout_has_verification,
        resolve_placeholders,
    )

    page = layout.get("page") or {}
    orientation = page.get("orientation", "portrait")
    width, height = _page_size(orientation)

    pdf, buf = _new_canvas(ctx)
    pdf.setPageSize((width, height))

    # Page background: solid color, then optional full-bleed image.
    bg_color = page.get("background_color", "#ffffff")
    try:
        pdf.setFillColor(colors.HexColor(bg_color))
        pdf.rect(0, 0, width, height, stroke=0, fill=1)
    except Exception:
        logger.debug("Invalid background_color %r; skipping", bg_color)
    if page.get("background_image") and assets.background:
        reader = _image_reader(assets.background)
        if reader is not None:
            pdf.drawImage(reader, 0, 0, width=width, height=height,
                          preserveAspectRatio=False, mask="auto")

    blocks = layout.get("blocks") or []
    for block in sorted(
        (b for b in blocks if isinstance(b, dict)),
        key=lambda b: b.get("z", 0),
    ):
        _draw_block(pdf, ctx, block, assets, width, height, resolve_placeholders)

    # Verification guarantee: inject a default panel if the design omitted both
    # a qr and a signature block.
    if not layout_has_verification(layout):
        _draw_verification_panel(pdf, ctx, 24 * _mm(), 16 * _mm(), width - 48 * _mm())

    return _finish(pdf, buf, ctx, width, height)


def _draw_block(pdf, ctx, block, assets, pw, ph, resolve) -> None:
    """Draw one layout block. Isolated in save/restore so one bad block can't
    corrupt canvas state for the rest of the page."""

    btype = block.get("type")
    style = block.get("style") or {}
    ax, ay, aw, ah = _abs_rect(block, pw, ph)

    pdf.saveState()
    try:
        opacity = block.get("opacity", 1.0)
        if isinstance(opacity, (int, float)) and 0.0 <= opacity < 1.0:
            pdf.setFillAlpha(float(opacity))
            pdf.setStrokeAlpha(float(opacity))
        rotation = block.get("rotation", 0.0)
        if rotation:
            # Rotate about the block centre so position stays intuitive.
            cx, cy = ax + aw / 2, ay + ah / 2
            pdf.translate(cx, cy)
            pdf.rotate(float(rotation))
            pdf.translate(-cx, -cy)

        if btype == "text":
            _draw_text_block(pdf, ctx, style, ax, ay, aw, ah, resolve)
        elif btype == "recipient_photo":
            _draw_image_block(pdf, _image_reader(ctx.recipient_photo), style, ax, ay, aw, ah)
        elif btype == "badge_image":
            _draw_image_block(pdf, _image_reader(ctx.badge_image), style, ax, ay, aw, ah)
        elif btype == "logo":
            _draw_image_block(pdf, _image_reader(assets.logo), style, ax, ay, aw, ah)
        elif btype == "qr":
            _draw_qr_block(pdf, ctx, style, ax, ay, aw, ah)
        elif btype == "signature":
            _draw_verification_panel(pdf, ctx, ax, ay, aw)
        elif btype == "line":
            _draw_line_block(pdf, style, ax, ay, aw, ah)
        elif btype == "rect":
            _draw_rect_block(pdf, style, ax, ay, aw, ah)
    except Exception:
        logger.debug("Skipping malformed block %r", block, exc_info=True)
    finally:
        pdf.restoreState()


def _draw_text_block(pdf, ctx, style, ax, ay, aw, ah, resolve) -> None:
    from reportlab.lib import colors

    raw = style.get("text", "") or ""
    text = resolve(raw, ctx)
    if not text:
        return
    font = style.get("font", "Helvetica")
    size = float(style.get("size", 14))
    align = style.get("align", "left")
    color = style.get("color", "#111827")
    pdf.setFont(font, size)
    try:
        pdf.setFillColor(colors.HexColor(color))
    except Exception:
        pdf.setFillColor(colors.black)
    # Baseline near the vertical centre of the box.
    ty = ay + ah / 2 - size / 3
    if align == "center":
        pdf.drawCentredString(ax + aw / 2, ty, text)
    elif align == "right":
        pdf.drawRightString(ax + aw, ty, text)
    else:
        pdf.drawString(ax, ty, text)


def _draw_image_block(pdf, reader, style, ax, ay, aw, ah) -> None:
    from reportlab.lib import colors

    if style.get("border"):
        try:
            pdf.setStrokeColor(colors.HexColor(style.get("border_color", "#d1d5db")))
        except Exception:
            pdf.setStrokeColor(colors.HexColor("#d1d5db"))
        pdf.setLineWidth(1)
        pdf.rect(ax, ay, aw, ah, stroke=1, fill=0)
    if reader is None:
        # Graceful placeholder so a missing asset never 500s the render.
        pdf.setFillColor(colors.HexColor("#f1f5f9"))
        pdf.rect(ax, ay, aw, ah, stroke=0, fill=1)
        return
    pdf.drawImage(reader, ax, ay, width=aw, height=ah,
                  preserveAspectRatio=True, anchor="c", mask="auto")


def _draw_qr_block(pdf, ctx, style, ax, ay, aw, ah) -> None:
    from reportlab.lib import colors

    size = min(aw, ah)
    qx = ax + (aw - size) / 2
    pdf.drawImage(_image_reader(_qr_png(ctx.verify_url)), qx, ay, width=size, height=size)
    caption = style.get("caption", "Scan to verify")
    if caption:
        pdf.setFont("Helvetica", 7)
        pdf.setFillColor(colors.HexColor("#475569"))
        pdf.drawCentredString(ax + aw / 2, ay - 3.5 * _mm(), caption)


def _draw_line_block(pdf, style, ax, ay, aw, ah) -> None:
    from reportlab.lib import colors

    try:
        pdf.setStrokeColor(colors.HexColor(style.get("color", "#111827")))
    except Exception:
        pdf.setStrokeColor(colors.black)
    pdf.setLineWidth(float(style.get("line_width", 1)))
    # Draw along the diagonal of the box (so a thin, wide box is a horizontal rule).
    pdf.line(ax, ay + ah / 2, ax + aw, ay + ah / 2)


def _draw_rect_block(pdf, style, ax, ay, aw, ah) -> None:
    from reportlab.lib import colors

    fill = 1 if style.get("fill") else 0
    try:
        c = colors.HexColor(style.get("color", "#111827"))
    except Exception:
        c = colors.black
    pdf.setStrokeColor(c)
    if fill:
        pdf.setFillColor(c)
    pdf.setLineWidth(float(style.get("line_width", 1)))
    pdf.rect(ax, ay, aw, ah, stroke=1, fill=fill)
