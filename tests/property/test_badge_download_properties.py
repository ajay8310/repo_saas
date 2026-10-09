"""
Property tests for U6 badge downloads (NFR-U6-5).

Properties:
* Bake round-trip: for any valid assertion dict and any valid source PNG,
  read_baked(bake_png(png, doc)) == doc.
* The assertion JSON built from rows always carries the required OB2.0 fields
  (@context, type, id, recipient.hashed, badge, issuedOn, verification).
* A revoked assertion always serializes with revoked == true.
"""

from __future__ import annotations

import io
import os
import string
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st
from PIL import Image

from app.config import get_settings
from app.services.badge_baker import bake_png, read_baked

get_settings.cache_clear()

_json_scalars = st.one_of(
    st.text(max_size=40),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.booleans(),
    st.none(),
)

# Arbitrary JSON-serialisable assertion-like dicts.
_assertion_docs = st.dictionaries(
    keys=st.text(alphabet=string.ascii_letters + "_@", min_size=1, max_size=16),
    values=st.one_of(
        _json_scalars,
        st.lists(_json_scalars, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=8), _json_scalars, max_size=5),
    ),
    min_size=0,
    max_size=10,
)


def _png(w: int, h: int, color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class TestBakeRoundTripProperty:
    @given(
        doc=_assertion_docs,
        w=st.integers(min_value=1, max_value=48),
        h=st.integers(min_value=1, max_value=48),
        r=st.integers(0, 255), g=st.integers(0, 255), b=st.integers(0, 255),
    )
    @h_settings(max_examples=100, deadline=None)
    def test_roundtrip(self, doc: dict, w: int, h: int, r: int, g: int, b: int) -> None:
        baked = bake_png(_png(w, h, (r, g, b)), doc)
        assert baked[:8] == b"\x89PNG\r\n\x1a\n"
        assert read_baked(baked) == doc


def _ctx_rows(status: str):
    tid = uuid4(); cid = uuid4()
    assertion = SimpleNamespace(
        id=uuid4(), badge_class_id=cid, tenant_id=tid,
        beneficiary_id="jane@example.com",
        issued_at=datetime(2026, 10, 8, tzinfo=UTC), expires_at=None,
        status=status, revocation_reason=("x" if status == "revoked" else None),
    )
    badge_class = SimpleNamespace(
        id=cid, name="Advanced Python", description="d", criteria_narrative="c",
        criteria_url=None, tags=[], alignment=[], image_s3_key=None,
    )
    tenant = SimpleNamespace(id=tid, issuer_name="Demo", name="Demo",
                             issuer_url=None, issuer_email=None)
    return assertion, badge_class, tenant


def _service():
    from unittest.mock import MagicMock

    from app.services.certificate_service import CertificateService
    svc = CertificateService(db=SimpleNamespace(), settings=get_settings())
    svc._s3 = MagicMock()
    return svc


class TestAssertionDocProperty:
    @given(status=st.sampled_from(["active", "expired"]))
    @h_settings(max_examples=20)
    def test_required_fields_present(self, status: str) -> None:
        svc = _service()
        doc = svc._assertion_doc(*_ctx_rows(status))
        for key in ("@context", "type", "id", "recipient", "badge", "issuedOn", "verification"):
            assert key in doc, key
        assert doc["recipient"].get("hashed") is True
        assert doc["verification"]["type"] == "HostedBadge"
        assert doc["type"] == "Assertion"

    @given(_dummy=st.integers(min_value=0, max_value=5))
    @h_settings(max_examples=10)
    def test_revoked_always_flagged(self, _dummy: int) -> None:
        svc = _service()
        doc = svc._assertion_doc(*_ctx_rows("revoked"))
        assert doc.get("revoked") is True
