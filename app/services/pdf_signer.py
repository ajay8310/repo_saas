"""Embedded PAdES PDF signing (pyHanko).

Produces a *true* PDF digital signature embedded in the document — the kind a
PDF viewer (Adobe Reader, etc.) shows in its signature panel — as opposed to the
JWS-over-hash recorded alongside the assertion.

Signing material is the tenant's own RSA private key + a self-signed X.509 cert
(see :class:`app.services.issuer_signing_service.IssuerSigningService`). The
trust chain is therefore the issuer's own certificate: a verifier that trusts
the published issuer cert sees a cryptographically valid signature over the exact
PDF bytes. (A publicly-trusted CA-issued cert — so viewers show "trusted" with no
manual step — is an ops/procurement upgrade; drop a CA cert+key in here and this
same code signs with it.)

The call is synchronous (pyHanko is sync) and CPU-light; callers invoke it from
async code via a thread or directly (signing a single PDF is fast).
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


class PdfSignError(Exception):
    """Raised when the PDF cannot be PAdES-signed."""


def sign_pdf_pades(
    pdf_bytes: bytes,
    private_key_pem: str,
    cert_pem: str,
    field_name: str = "IssuerSignature",
    reason: str = "Issued and signed by the credential issuer",
    location: str = "",
    signer_name: str = "",
    signed_date: str = "",
    visible: bool = True,
) -> bytes:
    """Return *pdf_bytes* with an embedded PAdES-B signature.

    When *visible* is true (the default) a signature appearance is drawn in the
    bottom-right of the first page: a green check mark plus "Digitally Signed by
    {signer_name}" and the date. The stamp is *backed by the real embedded
    signature* — it is not decoration — so a verifier sees both a visible mark
    and a cryptographically valid signature over the exact PDF bytes.

    Note on trust: the issuer cert is self-signed by default, so a PDF viewer
    reports the signature as "valid but not trusted" until the issuer cert is
    trusted (or replaced with a CA/AATL-issued cert). The visible tick reflects
    that a genuine signature is present; it does not assert CA-level trust.

    Raises :class:`PdfSignError` on any signing failure so the caller can decide
    whether to fail the issuance or fall back.
    """
    try:
        from asn1crypto import keys as asn1_keys
        from asn1crypto import x509 as asn1_x509
        from cryptography.hazmat.primitives import serialization
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign import signers
        from pyhanko.sign.fields import SigFieldSpec, append_signature_field
    except Exception as exc:  # pragma: no cover - import/env guard
        raise PdfSignError(f"PDF signing library unavailable: {exc}") from exc

    try:
        # Load the RSA private key via cryptography, then hand pyHanko an
        # asn1crypto PrivateKeyInfo + Certificate (its native in-memory types).
        key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"), password=None
        )
        key_der = key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        signing_key = asn1_keys.PrivateKeyInfo.load(key_der)
        signing_cert = asn1_x509.Certificate.load(_pem_to_der(cert_pem))
        try:
            from pyhanko_certvalidator.registry import SimpleCertificateStore

            cert_registry = SimpleCertificateStore()
        except Exception:
            cert_registry = None
        signer = signers.SimpleSigner(
            signing_key=signing_key,
            signing_cert=signing_cert,
            cert_registry=cert_registry,
        )
    except Exception as exc:
        raise PdfSignError(f"could not load signing material: {exc}") from exc

    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))

        stamp_style = None
        if visible:
            box = _bottom_right_box(writer)
            if box is None:
                # Could not read the first page geometry — fall back to an
                # invisible field rather than fail.
                visible = False
            else:
                stamp_style = _signature_stamp_style(signer_name, signed_date)
                append_signature_field(
                    writer,
                    SigFieldSpec(sig_field_name=field_name, box=box, on_page=0),
                )

        if not visible:
            # Invisible signature field (zero-area box): still a real signature,
            # just no drawn appearance.
            append_signature_field(
                writer,
                SigFieldSpec(sig_field_name=field_name, box=(0, 0, 0, 0)),
            )

        meta = signers.PdfSignatureMetadata(
            field_name=field_name,
            reason=reason,
            location=location or None,
        )
        if stamp_style is not None:
            from pyhanko.sign.signers import PdfSigner

            pdf_signer = PdfSigner(meta, signer=signer, stamp_style=stamp_style)
            out = pdf_signer.sign_pdf(writer)
        else:
            out = signers.sign_pdf(writer, meta, signer=signer)
        return out.getvalue()
    except PdfSignError:
        raise
    except Exception as exc:
        raise PdfSignError(f"PAdES signing failed: {exc}") from exc


# Signature-appearance geometry (PDF points; 72pt = 1 inch).
_STAMP_W = 200
_STAMP_H = 56
_STAMP_MARGIN = 36


def _bottom_right_box(writer) -> tuple[int, int, int, int] | None:
    """Return a (x1, y1, x2, y2) box in the bottom-right of the first page.

    Reads the first page's MediaBox so the stamp lands inside the page
    regardless of its size/orientation. Returns ``None`` if the geometry can't
    be read (caller then signs invisibly).
    """
    try:
        root = writer.root
        pages = root["/Pages"]
        first = pages["/Kids"][0].get_object()
        media = first.get("/MediaBox") or pages.get("/MediaBox")
        x0, y0, x1, y1 = (float(v) for v in media)
        page_w = x1 - x0
        right = x0 + page_w - _STAMP_MARGIN
        left = right - _STAMP_W
        bottom = y0 + _STAMP_MARGIN
        top = bottom + _STAMP_H
        return (int(left), int(bottom), int(right), int(top))
    except Exception:
        return None


def _signature_stamp_style(signer_name: str, signed_date: str):
    """Build a signature appearance: a green check + signer + date.

    The whole appearance is pre-rendered to a PNG (Pillow) and handed to pyHanko
    as the stamp *background* so it draws exactly as designed — a green tick and
    text, independent of PDF font quirks. ``stamp_text`` is left empty because
    the image already carries the text.
    """
    from PIL import Image
    from pyhanko.pdf_utils.images import PdfImage
    from pyhanko.stamp import TextStampStyle

    png = _stamp_png(signer_name, signed_date)
    pil_img = Image.open(io.BytesIO(png))
    pil_img.load()
    return TextStampStyle(
        stamp_text="",
        background=PdfImage(pil_img),
        border_width=0,
    )


def _stamp_png(signer_name: str, signed_date: str) -> bytes:
    """Render the signature-appearance PNG: green check + text lines.

    Drawn at 4x and downscaled with LANCZOS for crisp edges. Transparent
    background so it sits cleanly over the certificate.
    """
    from PIL import Image, ImageDraw, ImageFont

    SS = 4
    w, h = _STAMP_W * SS, _STAMP_H * SS
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)

    green = (22, 139, 74)
    ink = (33, 37, 41)
    pad = 8 * SS

    # Rounded card so it reads as a signature block.
    d.rounded_rectangle(
        [1 * SS, 1 * SS, w - 1 * SS, h - 1 * SS],
        radius=6 * SS,
        outline=(210, 214, 218),
        width=1 * SS,
        fill=(255, 255, 255, 235),
    )

    # Green check mark drawn as two strokes inside a left-aligned square.
    box = h - 2 * pad
    cx0 = pad
    cy0 = pad
    stroke = max(2, 3 * SS)
    d.line(
        [
            (cx0 + box * 0.12, cy0 + box * 0.55),
            (cx0 + box * 0.40, cy0 + box * 0.82),
        ],
        fill=green,
        width=stroke,
    )
    d.line(
        [
            (cx0 + box * 0.40, cy0 + box * 0.82),
            (cx0 + box * 0.88, cy0 + box * 0.20),
        ],
        fill=green,
        width=stroke,
    )

    # Text block to the right of the tick.
    name = (signer_name or "the credential issuer").strip()
    date = (signed_date or "").strip()
    tx = cx0 + box + pad

    def _font(size: int):
        for n in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(n, size)
            except Exception:
                continue
        return ImageFont.load_default()

    f_title = _font(11 * SS)
    f_body = _font(9 * SS)

    y = pad - 2 * SS
    d.text((tx, y), "Digitally Signed", font=f_title, fill=green)
    y += 14 * SS
    d.text((tx, y), f"by {name}"[:38], font=f_body, fill=ink)
    if date:
        y += 12 * SS
        d.text((tx, y), date, font=f_body, fill=ink)

    out = img.resize((_STAMP_W, _STAMP_H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _pem_to_der(pem: str) -> bytes:
    """Strip PEM armor and base64-decode to DER."""
    import base64

    body = "".join(
        line for line in pem.strip().splitlines() if not line.startswith("-----")
    )
    return base64.b64decode(body)
