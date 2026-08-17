"""
Document rendering — PDF and JSON-LD output with embedded QR code and proof.

Produces the beneficiary-facing artefacts for a stored credential:

- ``render_pdf``     — A4 certificate with the credential ID, field table, a
  QR code linking to the public verification page, and a truncated proof digest.
- ``render_json_ld`` — W3C-VC-shaped JSON-LD document with a detached RS256
  ``proof`` block over the credential payload.

On "digitally signed" (Req 4.7): this signs the *credential payload* with the
platform's RS256 key, which any holder of the public key can verify. It is not
a PAdES/embedded-certificate PDF signature — that needs a signing certificate
and a library such as pyhanko, neither of which is provisioned here.

Requirements: 4.7
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# JSON-LD contexts for the emitted verifiable credential.
_JSONLD_CONTEXTS = [
    "https://www.w3.org/2018/credentials/v1",
    "https://w3id.org/security/suites/jws-2020/v1",
]


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Everything needed to render a credential, already decrypted."""

    credential_id: str
    issuer_name: str
    schema_name: str
    schema_version: int
    beneficiary_id: str
    issued_at: str
    status: str = "stored"
    revoked_at: str | None = None
    revocation_reason: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_verification_url(credential_id: str) -> str:
    """Public URL a verifier lands on after scanning the QR code."""
    from app.config import get_settings

    base = get_settings().verification_base_url.rstrip("/")
    return f"{base}/verify/{credential_id}"


def generate_qr_png(data: str, box_size: int = 6) -> bytes:
    """Render *data* as a PNG QR code and return the raw bytes."""
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


def _credential_payload(ctx: RenderContext) -> dict[str, Any]:
    """Canonical credential body that gets signed and embedded."""
    return {
        "credential_id": ctx.credential_id,
        "issuer": ctx.issuer_name,
        "schema": ctx.schema_name,
        "schema_version": ctx.schema_version,
        "beneficiary_id": ctx.beneficiary_id,
        "issued_at": ctx.issued_at,
        "status": ctx.status,
        "fields": ctx.fields,
    }


def sign_payload(payload: dict[str, Any]) -> str:
    """Sign *payload* with the platform RS256 key, returning a compact JWS."""
    from jose import jwt

    from app.config import get_settings

    settings = get_settings()
    return jwt.encode(
        payload,
        settings.jwt_private_key,
        algorithm=settings.jwt_algorithm,
    )


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def render_pdf(ctx: RenderContext) -> bytes:
    """Render the credential as a single-page A4 PDF (Req 4.7).

    The page always carries the credential ID and a QR code pointing at the
    public verification URL, so the document is checkable offline-to-online.
    Revoked credentials get a prominent watermark.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    verification_url = build_verification_url(ctx.credential_id)
    proof = sign_payload(_credential_payload(ctx))

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    pdf.setTitle(f"{ctx.schema_name} — {ctx.credential_id}")
    pdf.setAuthor(ctx.issuer_name)
    pdf.setSubject(f"Credential {ctx.credential_id}")
    # Full proof lives in metadata so it survives a round-trip.
    pdf.setKeywords([f"credential_id={ctx.credential_id}", f"proof={proof}"])

    # --- Header band ---
    pdf.setFillColor(colors.HexColor("#0074c5"))
    pdf.rect(0, height - 30 * mm, width, 30 * mm, stroke=0, fill=1)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, height - 19 * mm, ctx.issuer_name)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, height - 25 * mm, "Verified Digital Credential")

    # --- Title ---
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(20 * mm, height - 48 * mm, ctx.schema_name)

    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawString(
        20 * mm,
        height - 55 * mm,
        f"Credential ID: {ctx.credential_id}   |   Schema v{ctx.schema_version}",
    )
    pdf.drawString(20 * mm, height - 60 * mm, f"Issued: {ctx.issued_at}")
    pdf.drawString(20 * mm, height - 65 * mm, f"Beneficiary: {ctx.beneficiary_id}")

    # --- Field table ---
    y = height - 82 * mm
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, "Credential Details")
    y -= 3 * mm
    pdf.setStrokeColor(colors.HexColor("#e5e7eb"))
    pdf.line(20 * mm, y, width - 20 * mm, y)
    y -= 7 * mm

    if ctx.fields:
        for key, value in ctx.fields.items():
            if y < 70 * mm:  # leave room for the QR block
                break
            pdf.setFont("Helvetica", 9)
            pdf.setFillColor(colors.HexColor("#6b7280"))
            pdf.drawString(22 * mm, y, str(key).replace("_", " ").title())
            pdf.setFont("Helvetica-Bold", 10)
            pdf.setFillColor(colors.HexColor("#111827"))
            pdf.drawString(85 * mm, y, str(value))
            y -= 7 * mm
    else:
        pdf.setFont("Helvetica-Oblique", 9)
        pdf.setFillColor(colors.HexColor("#9ca3af"))
        pdf.drawString(22 * mm, y, "No field data disclosed.")

    # --- QR code + verification block ---
    qr_size = 34 * mm
    qr_x = width - 20 * mm - qr_size
    qr_y = 32 * mm
    pdf.drawImage(
        ImageReader(io.BytesIO(generate_qr_png(verification_url))),
        qr_x,
        qr_y,
        width=qr_size,
        height=qr_size,
    )
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor("#6b7280"))
    pdf.drawCentredString(qr_x + qr_size / 2, qr_y - 4 * mm, "Scan to verify")

    pdf.setFont("Helvetica", 8)
    pdf.drawString(20 * mm, 44 * mm, "Verify this credential at:")
    pdf.setFont("Helvetica-Bold", 8)
    pdf.setFillColor(colors.HexColor("#0074c5"))
    pdf.drawString(20 * mm, 39 * mm, verification_url)

    # Truncated proof digest — full JWS is in the PDF metadata.
    pdf.setFont("Courier", 6)
    pdf.setFillColor(colors.HexColor("#9ca3af"))
    pdf.drawString(20 * mm, 32 * mm, f"proof: {proof[:64]}...")

    # --- Revoked watermark ---
    if ctx.status == "revoked":
        pdf.saveState()
        pdf.setFillColor(colors.Color(0.86, 0.15, 0.15, alpha=0.28))
        pdf.setFont("Helvetica-Bold", 68)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(32)
        pdf.drawCentredString(0, 0, "REVOKED")
        pdf.restoreState()

        pdf.setFont("Helvetica-Bold", 9)
        pdf.setFillColor(colors.HexColor("#b91c1c"))
        revoked_line = f"Revoked on {ctx.revoked_at or 'unknown date'}"
        if ctx.revocation_reason:
            revoked_line += f" — {ctx.revocation_reason}"
        pdf.drawString(20 * mm, 25 * mm, revoked_line)

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# JSON-LD rendering
# ---------------------------------------------------------------------------


def render_json_ld(ctx: RenderContext) -> bytes:
    """Render the credential as a signed JSON-LD verifiable credential (Req 4.7)."""
    payload = _credential_payload(ctx)
    proof = sign_payload(payload)

    doc: dict[str, Any] = {
        "@context": _JSONLD_CONTEXTS,
        "id": f"urn:credential:{ctx.credential_id}",
        "type": ["VerifiableCredential"],
        "issuer": {"name": ctx.issuer_name},
        "issuanceDate": ctx.issued_at,
        "credentialSchema": {
            "name": ctx.schema_name,
            "version": ctx.schema_version,
        },
        "credentialSubject": {
            "id": ctx.beneficiary_id,
            **ctx.fields,
        },
        "credentialStatus": {
            "type": "RevocationStatus",
            "status": ctx.status,
            "verificationUrl": build_verification_url(ctx.credential_id),
        },
        "proof": {
            "type": "JsonWebSignature2020",
            "created": ctx.issued_at,
            "proofPurpose": "assertionMethod",
            "jws": proof,
        },
    }

    if ctx.status == "revoked":
        doc["credentialStatus"]["revokedAt"] = ctx.revoked_at
        doc["credentialStatus"]["revocationReason"] = ctx.revocation_reason

    return json.dumps(doc, indent=2, default=str).encode()
