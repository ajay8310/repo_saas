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
) -> bytes:
    """Return *pdf_bytes* with an embedded PAdES-B signature.

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
        # Create an invisible signature field (box of zero area) so we don't
        # disturb the tenant's existing visual design.
        append_signature_field(
            writer,
            SigFieldSpec(sig_field_name=field_name, box=(0, 0, 0, 0)),
        )
        meta = signers.PdfSignatureMetadata(
            field_name=field_name,
            reason=reason,
            location=location or None,
        )
        out = signers.sign_pdf(writer, meta, signer=signer)
        return out.getvalue()
    except Exception as exc:
        raise PdfSignError(f"PAdES signing failed: {exc}") from exc


def _pem_to_der(pem: str) -> bytes:
    """Strip PEM armor and base64-decode to DER."""
    import base64

    body = "".join(
        line for line in pem.strip().splitlines() if not line.startswith("-----")
    )
    return base64.b64decode(body)
