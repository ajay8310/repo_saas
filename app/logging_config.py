"""
Logging configuration.

``log_level`` was a declared setting that nothing read — there was no
``basicConfig`` or ``dictConfig`` anywhere, so the application ran on the root
logger's defaults and WARNING-level security events were the only thing visible.

Two deliberate choices:

*JSON in non-development.* Structured records are what a log aggregator can
actually query, and correlating a tenant's requests across workers is the main
reason to read these logs at all.

*A redaction filter.* The conventions file says never log tokens, passwords, or
PII, but a convention is not an enforcement mechanism — one careless f-string in
a rarely hit error path is enough. The filter scrubs values that look like
bearer tokens, JWTs, or vault envelopes from every record regardless of which
module emitted it. It is a backstop, not a licence to log carelessly.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

# Bearer tokens, JWTs, and vault envelopes are all long opaque strings with
# recognisable shapes. Matching the shape avoids relying on the key name.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*")
_VAULT_RE = re.compile(r"\bv1:[a-z]+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+")
_REDACTED = "[REDACTED]"


def scrub(text: str) -> str:
    """Remove credential-shaped substrings from *text*."""
    text = _JWT_RE.sub(_REDACTED, text)
    text = _BEARER_RE.sub(f"Bearer {_REDACTED}", text)
    return _VAULT_RE.sub(_REDACTED, text)


class RedactionFilter(logging.Filter):
    """Scrub credential material from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Render once so args-based formatting is covered too, then drop
            # args to avoid re-formatting the scrubbed string downstream.
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging raise
            return True

        scrubbed = scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        # Correlation fields, when the caller supplied them.
        for field in ("tenant_id", "request_id", "actor_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install handlers, formatter, and the redaction filter on the root logger.

    Idempotent: existing handlers are replaced, so calling this from both the
    API lifespan and a worker entrypoint is safe.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
        )
    )
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)

    # Uvicorn installs its own handlers; route them through ours so access logs
    # get the same redaction and formatting.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = [handler]
        uv.propagate = False
