"""
Document schema CRUD, versioning, and export service.

All queries filter by tenant_id directly — no joins needed.
RLS enforces isolation at the DB level.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.schema import DocumentSchema, SchemaVersion

logger = logging.getLogger(__name__)

# Valid field types per Requirement 2.6
_VALID_FIELD_TYPES = {"string", "number", "date", "boolean", "enumeration", "file_reference"}


class SchemaService:
    """Manages document schema lifecycle with versioning."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_schema(
        self,
        tenant_id: UUID,
        name: str,
        field_definitions: list[dict[str, Any]],
    ) -> DocumentSchema:
        """Create a new document schema (Req 2.1, 2.2).

        Validates field definitions before persisting.
        """
        self._validate_field_definitions(field_definitions)
        await set_tenant_context(self.db, str(tenant_id))

        schema = DocumentSchema(
            tenant_id=tenant_id,
            name=name,
            version=1,
            status="active",
            field_definitions=field_definitions,
        )
        self.db.add(schema)
        await self.db.flush()

        # Store initial version snapshot
        version = SchemaVersion(
            tenant_id=tenant_id,
            schema_id=schema.id,
            version=1,
            field_definitions=field_definitions,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(schema)
        return schema

    async def get_schema(self, tenant_id: UUID, schema_id: UUID) -> DocumentSchema | None:
        """Get a schema by ID within tenant scope."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(DocumentSchema).where(DocumentSchema.id == schema_id)
        )
        return result.scalar_one_or_none()

    async def list_schemas(self, tenant_id: UUID) -> list[DocumentSchema]:
        """List all schemas for a tenant."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(DocumentSchema).order_by(DocumentSchema.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_schema(
        self,
        tenant_id: UUID,
        schema_id: UUID,
        field_definitions: list[dict[str, Any]],
    ) -> DocumentSchema:
        """Update schema with new field definitions (Req 2.3, 2.4).

        Increments version and archives the previous definition.
        Does NOT check for breaking changes against existing documents here —
        that validation should be done by the caller if needed.
        """
        self._validate_field_definitions(field_definitions)
        await set_tenant_context(self.db, str(tenant_id))

        result = await self.db.execute(
            select(DocumentSchema).where(DocumentSchema.id == schema_id)
        )
        schema = result.scalar_one_or_none()
        if schema is None:
            raise SchemaNotFoundError(schema_id)

        if schema.status != "active":
            raise SchemaInactiveError(schema_id)

        # Increment version
        new_version = schema.version + 1
        schema.version = new_version
        schema.field_definitions = field_definitions

        # Archive new version snapshot
        version = SchemaVersion(
            tenant_id=tenant_id,
            schema_id=schema_id,
            version=new_version,
            field_definitions=field_definitions,
        )
        self.db.add(version)
        await self.db.commit()
        await self.db.refresh(schema)
        return schema

    async def deactivate_schema(self, tenant_id: UUID, schema_id: UUID) -> DocumentSchema:
        """Deactivate a schema — prevent new documents (Req 2.5)."""
        await set_tenant_context(self.db, str(tenant_id))

        result = await self.db.execute(
            select(DocumentSchema).where(DocumentSchema.id == schema_id)
        )
        schema = result.scalar_one_or_none()
        if schema is None:
            raise SchemaNotFoundError(schema_id)

        schema.status = "deactivated"
        await self.db.commit()
        await self.db.refresh(schema)
        return schema

    async def get_versions(self, tenant_id: UUID, schema_id: UUID) -> list[SchemaVersion]:
        """Get version history for a schema (Req 2.4)."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(SchemaVersion)
            .where(SchemaVersion.schema_id == schema_id)
            .order_by(SchemaVersion.version.desc())
        )
        return list(result.scalars().all())

    async def export_schema(self, tenant_id: UUID, schema_id: UUID) -> dict[str, Any]:
        """Export schema as JSON (Req 2.7)."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(DocumentSchema).where(DocumentSchema.id == schema_id)
        )
        schema = result.scalar_one_or_none()
        if schema is None:
            raise SchemaNotFoundError(schema_id)

        return {
            "id": str(schema.id),
            "name": schema.name,
            "version": schema.version,
            "status": schema.status,
            "field_definitions": schema.field_definitions,
            "created_at": schema.created_at.isoformat(),
        }

    def _validate_field_definitions(self, fields: list[dict[str, Any]]) -> None:
        """Validate field definitions per Req 2.2."""
        errors = []
        for i, field in enumerate(fields):
            name = field.get("name")
            ftype = field.get("type")
            required = field.get("required")

            if not name or not isinstance(name, str) or not name.strip():
                errors.append({"index": i, "field": "name", "message": "name must be a non-empty string"})
            if ftype not in _VALID_FIELD_TYPES:
                errors.append({"index": i, "field": "type", "message": f"type must be one of: {', '.join(sorted(_VALID_FIELD_TYPES))}"})
            if not isinstance(required, bool):
                errors.append({"index": i, "field": "required", "message": "required must be a boolean"})
            if ftype == "enumeration":
                allowed = field.get("allowed_values", [])
                if not allowed or not isinstance(allowed, list):
                    errors.append({"index": i, "field": "allowed_values", "message": "enumeration fields must have non-empty allowed_values list"})

        if errors:
            raise SchemaValidationError(errors)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaNotFoundError(Exception):
    def __init__(self, schema_id: UUID) -> None:
        self.schema_id = schema_id
        super().__init__(f"Schema not found: {schema_id}")


class SchemaInactiveError(Exception):
    def __init__(self, schema_id: UUID) -> None:
        self.schema_id = schema_id
        super().__init__(f"Schema is deactivated: {schema_id}")


class SchemaValidationError(Exception):
    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        super().__init__(f"Schema validation failed: {len(errors)} error(s)")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_schema_service(db: AsyncSession = Depends(get_db)) -> SchemaService:
    return SchemaService(db=db)
