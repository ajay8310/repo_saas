"""MCP server exposing the Repo SaaS platform as agent-accessible tools.

Design notes
------------
- Uses the official ``mcp`` Python SDK's ``FastMCP`` helper (stdio transport).
- Each tool opens its own ``AsyncSessionLocal`` session, mirroring the
  request-scoped session pattern used by the FastAPI routers. Tenant isolation
  is enforced at the DB level (RLS) by the service layer's
  ``set_tenant_context`` calls, so every tool takes an explicit ``tenant_id``.
- Tools return JSON-serialisable dicts. Domain errors are caught and returned
  as ``{"error": ...}`` so the agent gets a structured failure rather than an
  exception trace.
- This server is read/write against the same database the API uses. In
  production, gate it behind an authenticating transport or run it only in a
  trusted control plane. Never expose it unauthenticated to the public.

Tools
-----
- ``search_documents``      — filtered, paginated search within a tenant
- ``get_document``          — fetch a single document's metadata
- ``verify_credential``     — public validity check (valid/revoked/invalid)
- ``issue_credential``      — issue a new document to a beneficiary
- ``revoke_credential``     — revoke an issued document
- ``list_beneficiary_documents`` — list documents for one beneficiary
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def _parse_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a valid UUID, got: {value!r}") from exc


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO date (YYYY-MM-DD), got: {value!r}") from exc


def build_server():  # noqa: C901 - tool registration is naturally long
    """Construct and return the FastMCP server instance.

    Imported lazily inside the function so that importing ``app.mcp`` does not
    require the ``mcp`` package to be installed (e.g. during unit tests that
    only touch the service layer).
    """
    from mcp.server.fastmcp import FastMCP

    from app.config import get_settings
    from app.db.session import AsyncSessionLocal
    from app.services.document_service import (
        DocumentAlreadyRevokedError,
        DocumentNotFoundError,
        DocumentService,
        DocumentValidationError,
    )
    from app.services.search_service import (
        InvalidDateRangeError,
        SearchParams,
        SearchService,
    )
    from app.services.verification_service import VerificationService

    mcp = FastMCP("repo-saas")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @mcp.tool()
    async def search_documents(
        tenant_id: str,
        query: str | None = None,
        schema_id: str | None = None,
        status: str | None = None,
        issued_after: str | None = None,
        issued_before: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Search documents within a tenant namespace.

        Filters by beneficiary (substring), schema, status, and issuance date
        range. Returns paginated metadata only — never document content.
        """
        try:
            params = SearchParams(
                query=query,
                schema_id=_parse_uuid(schema_id, "schema_id") if schema_id else None,
                status=status,
                issued_after=_parse_date(issued_after, "issued_after"),
                issued_before=_parse_date(issued_before, "issued_before"),
                sort_by=sort_by,
                sort_order="asc" if sort_order == "asc" else "desc",
                page=page,
                page_size=page_size,
            )
            async with AsyncSessionLocal() as db:
                svc = SearchService(db=db)
                result = await svc.search(_parse_uuid(tenant_id, "tenant_id"), params)
            return {
                "items": result.items,
                "total": result.total,
                "page": result.page,
                "page_size": result.page_size,
            }
        except (ValueError, InvalidDateRangeError) as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("search_documents failed")
            return {"error": f"internal error: {exc}"}

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_document(tenant_id: str, credential_id: str) -> dict[str, Any]:
        """Fetch a single document's metadata by credential ID.

        Returns metadata only (no decrypted content). Every access is audited.
        """
        try:
            async with AsyncSessionLocal() as db:
                svc = DocumentService(db=db, settings=get_settings())
                doc = await svc.get_document(
                    tenant_id=_parse_uuid(tenant_id, "tenant_id"),
                    credential_id=_parse_uuid(credential_id, "credential_id"),
                    actor_id="mcp-agent",
                    actor_role="issuer",
                )
            if doc is None:
                return {"found": False}
            return {
                "found": True,
                "credential_id": str(doc.id),
                "schema_id": str(doc.schema_id),
                "schema_version": doc.schema_version,
                "beneficiary_id": doc.beneficiary_id,
                "status": doc.status,
                "issued_at": doc.created_at.isoformat() if doc.created_at else None,
                "revoked_at": doc.revoked_at.isoformat() if doc.revoked_at else None,
                "revocation_reason": doc.revocation_reason,
            }
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover
            logger.exception("get_document failed")
            return {"error": f"internal error: {exc}"}

    @mcp.tool()
    async def list_beneficiary_documents(
        tenant_id: str,
        beneficiary_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List all documents issued to a given beneficiary within a tenant."""
        try:
            async with AsyncSessionLocal() as db:
                svc = DocumentService(db=db, settings=get_settings())
                docs = await svc.list_documents_for_beneficiary(
                    tenant_id=_parse_uuid(tenant_id, "tenant_id"),
                    beneficiary_id=beneficiary_id,
                    limit=limit,
                    offset=offset,
                )
            return {
                "beneficiary_id": beneficiary_id,
                "count": len(docs),
                "documents": [
                    {
                        "credential_id": str(d.id),
                        "schema_id": str(d.schema_id),
                        "status": d.status,
                        "issued_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in docs
                ],
            }
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover
            logger.exception("list_beneficiary_documents failed")
            return {"error": f"internal error: {exc}"}

    # ------------------------------------------------------------------
    # Verification (public — no auth needed)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def verify_credential(credential_id: str) -> dict[str, Any]:
        """Publicly verify a credential's validity.

        Returns only a status: ``valid``, ``revoked``, or ``invalid``.
        No beneficiary details or document fields are ever returned.
        """
        try:
            async with AsyncSessionLocal() as db:
                svc = VerificationService(db=db)
                result = await svc.verify_credential_public(
                    _parse_uuid(credential_id, "credential_id")
                )
            return result
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover
            logger.exception("verify_credential failed")
            return {"error": f"internal error: {exc}"}

    # ------------------------------------------------------------------
    # Issuance
    # ------------------------------------------------------------------

    @mcp.tool()
    async def issue_credential(
        tenant_id: str,
        schema_id: str,
        beneficiary_id: str,
        content: str,
        cmk_arn: str,
    ) -> dict[str, Any]:
        """Issue a new credential/document to a beneficiary.

        ``content`` is the raw document payload (typically a JSON string). It is
        malware-scanned, encrypted, and stored. Returns the new credential ID.

        ``cmk_arn`` is the tenant's KMS Customer Master Key ARN used for
        envelope encryption.
        """
        try:
            async with AsyncSessionLocal() as db:
                svc = DocumentService(db=db, settings=get_settings())
                result = await svc.upload_document(
                    tenant_id=_parse_uuid(tenant_id, "tenant_id"),
                    schema_id=_parse_uuid(schema_id, "schema_id"),
                    beneficiary_id=beneficiary_id,
                    content=content.encode("utf-8"),
                    cmk_arn=cmk_arn,
                    actor_id="mcp-agent",
                    actor_role="issuer",
                )
            return {"credential_id": result.credential_id, "status": result.status}
        except (ValueError, DocumentValidationError) as exc:
            return {"error": str(exc)}
        except Exception as exc:  # pragma: no cover
            logger.exception("issue_credential failed")
            return {"error": f"internal error: {exc}"}

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    @mcp.tool()
    async def revoke_credential(
        tenant_id: str,
        credential_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Revoke an issued credential.

        ``reason`` must be 1-500 characters. Notifies the beneficiary and fires
        webhooks. Returns the new status.
        """
        try:
            async with AsyncSessionLocal() as db:
                svc = DocumentService(db=db, settings=get_settings())
                doc = await svc.revoke_document(
                    tenant_id=_parse_uuid(tenant_id, "tenant_id"),
                    credential_id=_parse_uuid(credential_id, "credential_id"),
                    reason=reason,
                    actor_id="mcp-agent",
                    actor_role="issuer",
                )
            return {
                "credential_id": str(doc.id),
                "status": doc.status,
                "revoked_at": doc.revoked_at.isoformat() if doc.revoked_at else None,
            }
        except (ValueError, DocumentValidationError) as exc:
            return {"error": str(exc)}
        except DocumentNotFoundError:
            return {"error": "credential not found"}
        except DocumentAlreadyRevokedError:
            return {"error": "credential is already revoked"}
        except Exception as exc:  # pragma: no cover
            logger.exception("revoke_credential failed")
            return {"error": f"internal error: {exc}"}

    return mcp


def run() -> None:
    """Entry point: build the server and serve over stdio.

    Logs are forced to STDERR so STDOUT carries only MCP protocol frames — a
    stray print/log on STDOUT corrupts the stdio transport.
    """
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server = build_server()
    server.run()
