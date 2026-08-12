"""
Per-tenant document search using PostgreSQL pg_trgm + GIN indexes.

All queries are single-table on `documents` with tenant_id enforced by RLS.
No joins — filters use direct column predicates.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.document import Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Search filter parameters."""

    query: str | None = None  # Full-text search on beneficiary_id
    schema_id: UUID | None = None
    status: str | None = None
    issued_after: date | None = None
    issued_before: date | None = None
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Paginated search result."""

    items: list[dict]
    total: int
    page: int
    page_size: int


class SearchService:
    """Per-tenant document search. Single-table queries only."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, tenant_id: UUID, params: SearchParams) -> SearchResult:
        """Search documents with filters, sorting, and pagination (Req 9.1-9.7).

        All filtering happens on the `documents` table directly.
        RLS enforces tenant isolation via SET LOCAL.
        """
        # Validate date range (Req 9.7)
        if params.issued_after and params.issued_before:
            if params.issued_after > params.issued_before:
                raise InvalidDateRangeError(
                    "issued_after cannot be later than issued_before"
                )

        # Validate page_size
        page_size = max(1, min(params.page_size, 100))
        page = max(1, params.page)
        offset = (page - 1) * page_size

        await set_tenant_context(self.db, str(tenant_id))

        # Build query — single table, no joins
        stmt = select(Document)
        count_stmt = select(func.count(Document.id))

        # Apply filters
        if params.query:
            # Use pg_trgm similarity on beneficiary_id
            stmt = stmt.where(
                Document.beneficiary_id.ilike(f"%{params.query}%")
            )
            count_stmt = count_stmt.where(
                Document.beneficiary_id.ilike(f"%{params.query}%")
            )

        if params.schema_id:
            stmt = stmt.where(Document.schema_id == params.schema_id)
            count_stmt = count_stmt.where(Document.schema_id == params.schema_id)

        if params.status:
            stmt = stmt.where(Document.status == params.status)
            count_stmt = count_stmt.where(Document.status == params.status)

        if params.issued_after:
            stmt = stmt.where(Document.created_at >= params.issued_after)
            count_stmt = count_stmt.where(Document.created_at >= params.issued_after)

        if params.issued_before:
            stmt = stmt.where(Document.created_at <= params.issued_before)
            count_stmt = count_stmt.where(Document.created_at <= params.issued_before)

        # Apply sorting (Req 9.4)
        sort_column = getattr(Document, params.sort_by, Document.created_at)
        if params.sort_order == "asc":
            stmt = stmt.order_by(sort_column.asc())
        else:
            stmt = stmt.order_by(sort_column.desc())

        # Pagination
        stmt = stmt.limit(page_size).offset(offset)

        # Execute
        result = await self.db.execute(stmt)
        documents = result.scalars().all()

        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        items = [
            {
                "credential_id": str(doc.id),
                "schema_id": str(doc.schema_id),
                "schema_version": doc.schema_version,
                "beneficiary_id": doc.beneficiary_id,
                "status": doc.status,
                "issued_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in documents
        ]

        return SearchResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidDateRangeError(Exception):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_search_service(db: AsyncSession = Depends(get_db)) -> SearchService:
    return SearchService(db=db)
