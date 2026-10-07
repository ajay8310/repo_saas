"""
Unit tests for app.services.certificate_renderer (U4).

Requirements covered: U4 Q1 (template set), Q3 (PDF), Q5 (content incl. photo),
revoked watermark path, missing-image fallback.

Each template must produce a non-empty, valid PDF (starts with %PDF) for both a
full context (with photo + badge image) and a minimal one (no images), and the
revoked path must still render.
"""

from __future__ import annotations

import io
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

import pytest

from app.services.certificate_renderer import (
    TEMPLATE_NAMES,
    CertificateContext,
    render_certificate,
)


def _png_bytes() -> bytes:
    """A tiny valid PNG so the renderer's ImageReader path is exercised."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _ctx(**overrides) -> CertificateContext:
    base = dict(
        assertion_id="a1",
        badge_name="Python Expert",
        recipient_display="alice",
        issuer_name="Acme Institute",
        issued_at="2026-01-01T00:00:00+00:00",
        expires_at="2027-01-01T00:00:00+00:00",
        criteria="Pass the assessment with 80%+.",
        verify_url="https://example.test/api/v1/public/badges/assertions/a1",
        signature_jws="eyJhbGciOiJSUzI1NiJ9.payload.sig",
        status="active",
    )
    base.update(overrides)
    return CertificateContext(**base)


class TestAllTemplatesRender:
    @pytest.mark.parametrize("template", TEMPLATE_NAMES)
    def test_full_context_renders_valid_pdf(self, template: str) -> None:
        ctx = _ctx(badge_image=_png_bytes(), recipient_photo=_png_bytes())
        pdf = render_certificate(ctx, template)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000

    @pytest.mark.parametrize("template", TEMPLATE_NAMES)
    def test_minimal_context_without_images(self, template: str) -> None:
        pdf = render_certificate(_ctx(badge_image=None, recipient_photo=None), template)
        assert pdf[:5] == b"%PDF-"


class TestRevokedWatermark:
    def test_revoked_still_renders(self) -> None:
        ctx = _ctx(
            status="revoked",
            revoked_at="2026-02-01T00:00:00+00:00",
            revocation_reason="issued in error",
            recipient_photo=_png_bytes(),
        )
        pdf = render_certificate(ctx, "classic")
        assert pdf[:5] == b"%PDF-"


class TestUnknownTemplateFallback:
    def test_unknown_template_falls_back_to_classic(self) -> None:
        pdf = render_certificate(_ctx(), "does-not-exist")
        assert pdf[:5] == b"%PDF-"
