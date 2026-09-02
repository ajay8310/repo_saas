"""
ORM model package — re-exports all models for convenient imports.

Usage:
    from app.models import Tenant, Document, AuditLog  # etc.
"""

from app.models.anchor import AnchorBatch, DocumentAnchor  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin  # noqa: F401
from app.models.consent import ConsentRecord, ErasureRequest  # noqa: F401
from app.models.digilocker import DigiLockerPush  # noqa: F401
from app.models.document import BulkJob, Document  # noqa: F401
from app.models.notification import NotificationPreference  # noqa: F401
from app.models.schema import DocumentSchema, SchemaVersion  # noqa: F401
from app.models.tenant import ApiClient, Tenant, TenantEncryptionKey  # noqa: F401
from app.models.user import UserAccount  # noqa: F401
from app.models.verification import VerificationToken  # noqa: F401
from app.models.webhook import Webhook, WebhookEvent  # noqa: F401
