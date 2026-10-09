"""Open Badges 2.0 PNG "baking" (U6).

Baking embeds an Open Badges Assertion JSON into a PNG image's metadata so the
image becomes a self-contained, portable, verifiable badge. Per the Open Badges
bakery spec, the assertion is stored in an iTXt chunk whose keyword is
``openbadges``.

This module is pure (no DB/network/S3) so it is trivially unit- and property-
testable. Callers (``CertificateService``) resolve the badge-class PNG bytes and
the assertion dict, then pass both in.

Only raster PNG images can be baked: SVG badge art (which the badge-class image
upload also permits) cannot carry PNG metadata, so :func:`bake_png` raises
:class:`BadgeImageNotBakeableError` for anything Pillow can't open as a PNG.
"""

from __future__ import annotations

import io
import json
import logging

logger = logging.getLogger(__name__)

# Keyword required by the Open Badges bakery spec for the embedded assertion.
OB_KEYWORD = "openbadges"


class BadgeImageNotBakeableError(Exception):
    """Raised when the source image cannot be baked (missing, unreadable, or not PNG)."""


def bake_png(png_bytes: bytes, assertion_doc: dict) -> bytes:
    """Return *png_bytes* with *assertion_doc* embedded in an ``openbadges`` iTXt chunk.

    Raises :class:`BadgeImageNotBakeableError` if the bytes are not a readable
    PNG (e.g. empty, corrupt, or an SVG), so the caller can surface a clean 422
    rather than producing a broken file.
    """
    if not png_bytes:
        raise BadgeImageNotBakeableError("badge image is empty")

    from PIL import Image, PngImagePlugin

    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception as exc:  # noqa: BLE001 — any decode failure is "not bakeable"
        raise BadgeImageNotBakeableError("badge image is not a readable image") from exc

    if img.format != "PNG":
        raise BadgeImageNotBakeableError(
            "badge image must be a PNG to produce a baked badge"
        )

    meta = PngImagePlugin.PngInfo()
    meta.add_itxt(OB_KEYWORD, json.dumps(assertion_doc))

    out = io.BytesIO()
    img.save(out, format="PNG", pnginfo=meta)
    return out.getvalue()


def read_baked(png_bytes: bytes) -> dict | None:
    """Return the embedded Open Badges assertion dict, or ``None`` if absent.

    Inverse of :func:`bake_png`; used by verification tooling and the round-trip
    property test.
    """
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(png_bytes))
    except Exception:
        return None
    raw = (img.info or {}).get(OB_KEYWORD)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("Baked PNG openbadges chunk is not valid JSON", exc_info=True)
        return None
