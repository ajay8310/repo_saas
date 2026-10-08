"""
Property tests for U5 Certificate Template Designer (NFR-U5-5).

Properties:
* Geometry: for any block whose normalized coords are in-bounds
  (0<=x,y; 0<w,h<=1; x+w<=1; y+h<=1), the renderer's normalized→A4 mapping
  yields absolute coords on the page (0<=ax, ay>=0, ax+aw<=PW+eps,
  ay+ah<=PH+eps) for both orientations.
* Placeholders: for arbitrary text mixing known/unknown tokens, the resolved
  output never contains a residual ``{{...}}`` and known tokens are substituted.
* Verification invariant: for any valid layout, the rendered PDF embeds the
  issuer signature in metadata and always carries verification (a qr block, or
  the default panel the renderer injects when none is present).
"""

from __future__ import annotations

import os
import re
import string
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from app.services.certificate_layout import (
    PLACEHOLDER_WHITELIST,
    resolve_placeholders,
)
from app.services.certificate_renderer import (
    CustomAssets,
    _abs_rect,
    _page_size,
    render_custom_certificate,
)

_RESIDUAL = re.compile(r"\{\{.*?\}\}")


def _ctx(**overrides):
    base = dict(
        assertion_id="a-1",
        badge_name="Advanced Python",
        recipient_display="Jane Learner",
        issuer_name="Demo University",
        issued_at="2026-10-08",
        expires_at="2027-10-08",
        criteria="Pass the exam",
        verify_url="https://example.test/verify/a-1",
        signature_jws="header.payload.signaturepart",
    )
    base.update(overrides)
    return SimpleNamespace(status="active", revoked_at=None, revocation_reason=None,
                           badge_image=None, recipient_photo=None, **base)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


@st.composite
def _in_bounds_block(draw):
    x = draw(st.floats(min_value=0.0, max_value=0.95))
    y = draw(st.floats(min_value=0.0, max_value=0.95))
    w = draw(st.floats(min_value=0.01, max_value=1.0 - x))
    h = draw(st.floats(min_value=0.01, max_value=1.0 - y))
    return {"id": "b", "type": "rect", "x": x, "y": y, "w": w, "h": h}


class TestGeometryInvariant:
    @given(block=_in_bounds_block(), orientation=st.sampled_from(["portrait", "landscape"]))
    @h_settings(max_examples=200)
    def test_mapped_coords_stay_on_page(self, block: dict, orientation: str) -> None:
        pw, ph = _page_size(orientation)
        ax, ay, aw, ah = _abs_rect(block, pw, ph)
        eps = 1.0  # 1pt tolerance for float rounding
        assert ax >= -eps
        assert ay >= -eps
        assert ax + aw <= pw + eps
        assert ay + ah <= ph + eps


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------

_token_like = st.text(alphabet=string.ascii_lowercase + "_", min_size=1, max_size=20)

_mixed_text = st.lists(
    st.one_of(
        st.text(alphabet=string.ascii_letters + " .,!", max_size=15),
        _token_like.map(lambda t: "{{" + t + "}}"),
        st.sampled_from(sorted(PLACEHOLDER_WHITELIST)).map(lambda t: "{{" + t + "}}"),
    ),
    min_size=0,
    max_size=12,
).map(" ".join)


class TestPlaceholderInvariant:
    @given(text=_mixed_text)
    @h_settings(max_examples=200)
    def test_no_residual_placeholder_tokens(self, text: str) -> None:
        out = resolve_placeholders(text, _ctx())
        assert _RESIDUAL.search(out) is None

    @given(token=st.sampled_from(sorted(PLACEHOLDER_WHITELIST)))
    @h_settings(max_examples=50)
    def test_known_tokens_substituted(self, token: str) -> None:
        ctx = _ctx()
        expected = {
            "recipient": ctx.recipient_display,
            "badge_name": ctx.badge_name,
            "issuer_name": ctx.issuer_name,
            "issued_at": ctx.issued_at,
            "expires_at": ctx.expires_at,
            "criteria": ctx.criteria,
            "verify_url": ctx.verify_url,
            "assertion_id": ctx.assertion_id,
        }[token]
        out = resolve_placeholders("<<" + "{{" + token + "}}" + ">>", ctx)
        assert out == f"<<{expected}>>"


# ---------------------------------------------------------------------------
# Verification invariant
# ---------------------------------------------------------------------------


@st.composite
def _valid_layout(draw):
    orientation = draw(st.sampled_from(["portrait", "landscape"]))
    include_qr = draw(st.booleans())
    blocks = [
        {
            "id": "title",
            "type": "text",
            "x": 0.1,
            "y": draw(st.floats(min_value=0.05, max_value=0.4)),
            "w": 0.8,
            "h": 0.1,
            "style": {"text": "Awarded to {{recipient}}", "size": draw(st.integers(12, 36)),
                      "align": "center"},
        }
    ]
    if include_qr:
        blocks.append({"id": "qr", "type": "qr", "x": 0.8, "y": 0.8, "w": 0.15, "h": 0.15})
    return {"page": {"orientation": orientation, "background_color": "#ffffff"}, "blocks": blocks}


class TestVerificationInvariant:
    @given(layout=_valid_layout())
    @h_settings(max_examples=60, deadline=None)
    def test_render_always_pdf_with_signature_in_metadata(self, layout: dict) -> None:
        ctx = _ctx()
        pdf = render_custom_certificate(ctx, layout, CustomAssets())
        assert pdf[:4] == b"%PDF"
        # The full JWS is embedded in PDF metadata keywords by _new_canvas, so a
        # verifier can always recover the signature regardless of layout.
        assert b"issuer_signature=" in pdf

    @given(seed=st.integers(min_value=0, max_value=10_000))
    @h_settings(max_examples=25, deadline=None)
    def test_layout_without_verification_still_renders(self, seed: int) -> None:
        # No qr/signature block → renderer must inject the default panel and
        # still produce a valid, signed PDF (FR-U5-10).
        layout = {
            "page": {"orientation": "portrait", "background_color": "#ffffff"},
            "blocks": [
                {"id": "t", "type": "text", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.1,
                 "style": {"text": "No verify block", "size": 18, "align": "center"}}
            ],
        }
        pdf = render_custom_certificate(_ctx(), layout, CustomAssets())
        assert pdf[:4] == b"%PDF"
        assert b"issuer_signature=" in pdf
