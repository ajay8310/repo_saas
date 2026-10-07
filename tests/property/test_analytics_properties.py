"""
Property tests for U3 Public & Analytics.

Properties:
* [PBT-02] share-URL round-trip: a URL tagged with a channel parses back to the
  same channel.
* [PBT-03] masking never leaks: a masked email never contains the local part.
* [PBT-03] aggregation invariant: the tenant-wide total per metric equals the
  sum of per-class totals.
* [PBT-04] aggregation idempotence: aggregating an event stream, then feeding the
  resulting rollup back through the same fold, yields identical counts
  (``aggregate(aggregate(x)) == aggregate(x)``).

The aggregation here is a pure reference fold that mirrors the counting logic in
AnalyticsAggregator (group by (day, class, type), tenant-wide = sum). It lets us
prove the business invariants deterministically without a live database; the DB
upsert path is exercised in integration.
"""

from __future__ import annotations

import os
from collections import defaultdict

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("JWT_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nX\n-----END RSA PRIVATE KEY-----")
os.environ.setdefault("JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")

from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from app.services.identity_masking import mask_identity
from app.services.share_service import parse_channel_from_share_url

_METRICS = ("issued", "accepted", "published", "shared", "verified", "viewed")

# An event is (day_bucket:int, class_id:str, event_type:str).
_events = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=5),
        st.sampled_from(["c1", "c2", "c3"]),
        st.sampled_from(_METRICS),
    ),
    min_size=0,
    max_size=200,
)


def _aggregate(events: list[tuple[int, str, str]]) -> dict:
    """Reference fold: {(day, class_or_None): {metric: count}}.

    Produces per-class rows and a tenant-wide row (class=None) that is the sum
    across classes per (day, metric) — mirroring AnalyticsAggregator / BR-A3.
    """
    per_class: dict[tuple[int, str | None], dict[str, int]] = defaultdict(
        lambda: {m: 0 for m in _METRICS}
    )
    for day, class_id, etype in events:
        per_class[(day, class_id)][etype] += 1
    # Tenant-wide rows = sum across classes per day.
    for (day, class_id), counts in list(per_class.items()):
        if class_id is None:
            continue
        tw = per_class[(day, None)]
        for m in _METRICS:
            tw[m] += counts[m]
    return {k: dict(v) for k, v in per_class.items()}


def _rollup_to_events(rollup: dict) -> list[tuple[int, str, str]]:
    """Expand a per-class rollup back into an event stream (ignoring tenant-wide)."""
    events: list[tuple[int, str, str]] = []
    for (day, class_id), counts in rollup.items():
        if class_id is None:
            continue
        for metric, n in counts.items():
            events.extend([(day, class_id, metric)] * n)
    return events


class TestShareRoundTrip:
    @given(channel=st.sampled_from(["linkedin", "twitter", "facebook", "email", "link"]))
    @h_settings(max_examples=40)
    def test_channel_round_trip(self, channel: str) -> None:
        url = f"https://host/api/v1/public/badges/assertions/x?channel={channel}"
        assert parse_channel_from_share_url(url) == channel


class TestMaskingNeverLeaks:
    @given(
        local=st.text(min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
        domain=st.sampled_from(["example.com", "acme.org", "school.edu"]),
    )
    @h_settings(max_examples=60)
    def test_local_part_never_appears(self, local: str, domain: str) -> None:
        masked = mask_identity(f"{local}@{domain}")
        assert local not in masked


class TestAggregationInvariants:
    @given(events=_events)
    @h_settings(max_examples=80)
    def test_tenant_wide_equals_sum_of_classes(self, events: list) -> None:
        rollup = _aggregate(events)
        days = {day for (day, _c) in rollup}
        for day in days:
            for metric in _METRICS:
                tenant_wide = rollup.get((day, None), {}).get(metric, 0)
                per_class_sum = sum(
                    counts[metric]
                    for (d, c), counts in rollup.items()
                    if d == day and c is not None
                )
                assert tenant_wide == per_class_sum

    @given(events=_events)
    @h_settings(max_examples=80)
    def test_idempotent(self, events: list) -> None:
        once = _aggregate(events)
        # Re-expand the per-class rollup and re-aggregate: identical result.
        twice = _aggregate(_rollup_to_events(once))
        assert once == twice
