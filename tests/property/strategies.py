"""
Reusable Hypothesis strategies for property-based tests.

Provides generators for domain objects used across all property test modules.
"""

from __future__ import annotations

import string
from uuid import uuid4

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Tenant strategies
# ---------------------------------------------------------------------------

tenant_namespaces = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-_",
    min_size=3,
    max_size=63,
).filter(lambda s: s[0].isalpha())

tenant_domains = st.from_regex(r"[a-z][a-z0-9-]{2,30}\.(com|org|gov|edu|io)", fullmatch=True)

tenant_names = st.text(min_size=1, max_size=255, alphabet=string.printable)

# ---------------------------------------------------------------------------
# Schema strategies
# ---------------------------------------------------------------------------

_field_types = st.sampled_from(["string", "number", "date", "boolean", "enumeration", "file_reference"])

_field_names = st.text(
    alphabet=string.ascii_lowercase + string.digits + "_",
    min_size=1,
    max_size=64,
).filter(lambda s: s[0].isalpha())

_allowed_values = st.lists(
    st.text(min_size=1, max_size=32, alphabet=string.ascii_letters),
    min_size=1,
    max_size=10,
)


@st.composite
def field_definitions(draw, min_fields=1, max_fields=10):
    """Generate a valid list of schema field definitions."""
    count = draw(st.integers(min_value=min_fields, max_value=max_fields))
    fields = []
    used_names = set()

    for _ in range(count):
        name = draw(_field_names.filter(lambda n: n not in used_names))
        used_names.add(name)
        ftype = draw(_field_types)
        required = draw(st.booleans())

        field = {"name": name, "type": ftype, "required": required}
        if ftype == "enumeration":
            field["allowed_values"] = draw(_allowed_values)
        fields.append(field)

    return fields


@st.composite
def invalid_field_definitions(draw):
    """Generate field definitions with at least one invalid entry."""
    strategy = st.one_of(
        # Missing name
        st.just({"type": "string", "required": True}),
        # Invalid type
        st.just({"name": "field1", "type": "invalid_type", "required": True}),
        # Missing required
        st.just({"name": "field2", "type": "number"}),
        # Enum without allowed_values
        st.just({"name": "field3", "type": "enumeration", "required": True}),
        # Empty name
        st.just({"name": "", "type": "string", "required": False}),
    )
    invalid = draw(strategy)
    return [invalid]


# ---------------------------------------------------------------------------
# Document strategies
# ---------------------------------------------------------------------------

beneficiary_ids = st.text(min_size=1, max_size=512, alphabet=string.ascii_letters + string.digits + "@._-")

document_content = st.binary(min_size=1, max_size=1024)

# ---------------------------------------------------------------------------
# Auth strategies
# ---------------------------------------------------------------------------

jwt_expiry_seconds = st.integers(min_value=60, max_value=3600)

otp_codes = st.text(alphabet=string.digits, min_size=6, max_size=6)

roles = st.sampled_from(["super_admin", "tenant_admin", "issuer", "beneficiary", "verifier"])

role_operation_pairs = st.tuples(
    roles,
    st.sampled_from([
        "tenant:create", "tenant:read", "schema:create", "schema:read",
        "document:upload", "document:read", "document:revoke",
        "verification:create", "verification:read",
        "audit:read", "webhook:create", "search:query",
    ]),
)

# ---------------------------------------------------------------------------
# Verification strategies
# ---------------------------------------------------------------------------

token_strings = st.text(min_size=32, max_size=64, alphabet=string.ascii_letters + string.digits + "-_")

verification_expiry_hours = st.integers(min_value=1, max_value=168)

consented_field_lists = st.lists(
    st.text(min_size=1, max_size=32, alphabet=string.ascii_lowercase + "_"),
    min_size=0,
    max_size=20,
)

# ---------------------------------------------------------------------------
# Search strategies
# ---------------------------------------------------------------------------

sort_orders = st.sampled_from(["asc", "desc"])

page_sizes = st.integers(min_value=1, max_value=100)

# ---------------------------------------------------------------------------
# Rate limit strategies
# ---------------------------------------------------------------------------

request_counts = st.integers(min_value=1, max_value=20000)

# ---------------------------------------------------------------------------
# UUID strategy
# ---------------------------------------------------------------------------

uuids = st.builds(uuid4)
