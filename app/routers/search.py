"""
Search endpoint — per-tenant document search with filters.

Requirements: 9.1-9.7
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dependencies.auth import TokenPayload, get_current_user
from app.services.search_service import (
    InvalidDateRangeError,
    SearchParams,
    SearchService,
    get_search_service,
)

router = APIRouter(prefix="/search", tags=["search"])


class SearchResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int


@router.get("", response_model=SearchResponse)
async def search_documents(
    q: str | None = Query(default=None, description="Full-text search query"),
    schema_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    issued_after: date | None = Query(default=None),
    issued_before: date | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: TokenPayload = Depends(get_current_user),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Search documents with filters and pagination (Req 9.1-9.7)."""
    params = SearchParams(
        query=q,
        schema_id=schema_id,
        status=status,
        issued_after=issued_after,
        issued_before=issued_before,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    try:
        result = await service.search(user.tenant_id, params)
    except InvalidDateRangeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_DATE_RANGE", "message": str(exc)},
        )
    return SearchResponse(
        items=result.items,
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
