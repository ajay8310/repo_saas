"""
Document schema CRUD, versioning, and export service.

All queries filter by tenant_id directly — no joins needed.
RLS enforces isolation at the DB level.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.document import Document
from app.models.schema import DocumentSchema, SchemaVersion

logger = logging.getLogger(__name__)

# Valid field types per Requirement 2.6
_VALID_FIELD_TYPES = {"string", "number", "date", "boolean", "enumeration", "file_reference"}

# Cap on how many conflicting credential IDs we return in a 409 payload, so a
# breaking change on a large schema can't produce an unbounded response.
_MAX_CONFLICT_IDS = 1000


# ---------------------------------------------------------------------------
# Breaking-change detection (Req 2.3)
# ---------------------------------------------------------------------------


def detect_breaking_changes(
    old_fields: list[dict[str, Any]],
    new_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare two field-definition sets and return breaking changes.

    A change is *breaking* when a document that validated against
    ``old_fields`` would no longer validate against ``new_fields``:

    - ``field_removed``          — a field present before is now gone.
      A rename surfaces as a removal plus an addition, which is correct.
    - ``type_changed``           — stored values are the wrong type.
    - ``required_field_added``   — existing documents have no value for it.
    - ``optional_became_required`` — documents that omitted it are now invalid.
    - ``enum_values_removed``    — previously legal values are now illegal.

    Purely additive or relaxing changes are NOT breaking: adding an optional
    field, widening an enumeration, or making a required field optional.

    This is a structural diff — it needs no access to document content, which
    matters because document payloads are encrypted at rest.
    """
    old_by_name = {f["name"]: f for f in old_fields if f.get("name")}
    new_by_name = {f["name"]: f for f in new_fields if f.get("name")}

    breaking: list[dict[str, Any]] = []

    # Fields that disappeared (includes the "old half" of a rename).
    for name in old_by_name:
        if name not in new_by_name:
            breaking.append({"field": name, "change": "field_removed"})

    for name, new_field in new_by_name.items():
        old_field = old_by_name.get(name)

        # Brand-new field that is mandatory — existing documents lack it.
        if old_field is None:
            if new_field.get("required") is True:
                breaking.append({"field": name, "change": "required_field_added"})
            continue

        # Type change invalidates every stored value for this field.
        if new_field.get("type") != old_field.get("type"):
            breaking.append({
                "field": name,
                "change": "type_changed",
                "from": old_field.get("type"),
                "to": new_field.get("type"),
            })

        # Tightening optional -> required.
        if new_field.get("required") is True and old_field.get("required") is not True:
            breaking.append({"field": name, "change": "optional_became_required"})

        # Narrowing an enumeration removes previously-valid values.
        if (
            old_field.get("type") == "enumeration"
            and new_field.get("type") == "enumeration"
        ):
            removed = set(old_field.get("allowed_values") or []) - set(
                new_field.get("allowed_values") or []
            )
            if removed:
                breaking.append({
                    "field": name,
                    "change": "enum_values_removed",
                    "removed_values": sorted(removed),
                })

    return breaking


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

        Rejects breaking changes that would invalidate already-issued documents,
        reporting the conflicting credential IDs. Otherwise increments the
        version monotonically and archives a snapshot of the new definition.
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

        # Breaking-change gate (Req 2.3). A structurally breaking change only
        # actually invalidates anything if documents exist at the current
        # version — on an unused schema the change is safe to apply.
        breaking = detect_breaking_changes(
            schema.field_definitions or [], field_definitions
        )
        if breaking:
            conflicting = await self._get_conflicting_credential_ids(
                schema_id, schema.version
            )
            if conflicting:
                logger.warning(
                    "Rejected breaking schema update: schema_id=%s changes=%d conflicts=%d",
                    schema_id,
                    len(breaking),
                    len(conflicting),
                )
                raise SchemaBreakingChangeError(
                    schema_id=schema_id,
                    breaking_changes=breaking,
                    conflicting_credential_ids=conflicting,
                )

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

    async def _get_conflicting_credential_ids(
        self, schema_id: UUID, schema_version: int
    ) -> list[str]:
        """Return credential IDs issued under the given schema version.

        Single-table query on ``documents`` — no joins. Every document at this
        version conforms to the outgoing definition, so a structurally breaking
        change invalidates all of them.
        """
        result = await self.db.execute(
            select(Document.id)
            .where(
                Document.schema_id == schema_id,
                Document.schema_version == schema_version,
            )
            .order_by(Document.created_at.desc())
            .limit(_MAX_CONFLICT_IDS)
        )
        return [str(row) for row in result.scalars().all()]

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


class SchemaBreakingChangeError(Exception):
    """Raised when a schema update would invalidate already-issued documents.

    Carries the structural diff and the conflicting credential IDs so the API
    layer can return them in a 409 SCHEMA_BREAKING_CHANGE response (Req 2.3).
    """

    def __init__(
        self,
        schema_id: UUID,
        breaking_changes: list[dict],
        conflicting_credential_ids: list[str],
    ) -> None:
        self.schema_id = schema_id
        self.breaking_changes = breaking_changes
        self.conflicting_credential_ids = conflicting_credential_ids
        super().__init__(
            f"Schema update rejected: {len(breaking_changes)} breaking change(s) "
            f"would invalidate {len(conflicting_credential_ids)} document(s)"
        )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_schema_service(db: AsyncSession = Depends(get_db)) -> SchemaService:
    return SchemaService(db=db)
