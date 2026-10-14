"""
Unit tests for app.services.pdf_signer — embedded PAdES signature with a
visible appearance (green tick + issuer + date).

Covers: a real signature is embedded over the PDF bytes, the visible stamp
appearance is generated, and the invisible fallback still signs.
"""

from __future__ import annotations

import datetime
import io

import pytest

from app.services.pdf_signer import PdfSignError, _stamp_png, sign_pdf_pades


def _make_key_and_cert() -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Demo University")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return priv_pem, cert_pem


def _make_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(120, 700, "Certificate of Achievement")
    c.showPage()
    c.save()
    return buf.getvalue()


class TestStampImage:
    """The signature appearance PNG renders with issuer + date."""

    def test_stamp_png_is_valid_png(self) -> None:
        png = _stamp_png("Demo University", "24 Aug 2026")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_stamp_png_handles_missing_name(self) -> None:
        png = _stamp_png("", "")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


class TestVisibleSignature:
    """A real PAdES signature with a visible appearance is embedded."""

    def setup_method(self) -> None:
        self.priv, self.cert = _make_key_and_cert()
        self.pdf = _make_pdf()

    def test_visible_signature_embeds_one_signature(self) -> None:
        from pyhanko.pdf_utils.reader import PdfFileReader

        signed = sign_pdf_pades(
            self.pdf,
            private_key_pem=self.priv,
            cert_pem=self.cert,
            signer_name="Demo University",
            signed_date="24 Aug 2026",
            visible=True,
        )
        assert len(signed) > len(self.pdf)
        assert b"/ByteRange" in signed
        r = PdfFileReader(io.BytesIO(signed))
        assert len(r.embedded_signatures) == 1

    def test_invisible_signature_still_signs(self) -> None:
        from pyhanko.pdf_utils.reader import PdfFileReader

        signed = sign_pdf_pades(
            self.pdf,
            private_key_pem=self.priv,
            cert_pem=self.cert,
            visible=False,
        )
        r = PdfFileReader(io.BytesIO(signed))
        assert len(r.embedded_signatures) == 1

    def test_bad_key_raises_pdf_sign_error(self) -> None:
        with pytest.raises(PdfSignError):
            sign_pdf_pades(
                self.pdf,
                private_key_pem="-----BEGIN RSA PRIVATE KEY-----\nnope\n-----END RSA PRIVATE KEY-----",
                cert_pem=self.cert,
            )
