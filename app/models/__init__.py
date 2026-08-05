"""
ORM model package — re-exports all models for convenient imports.

Usage:
    from app.models import Tenant, Document, AuditLog  # etc.
"""

from app.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin  # noqa: F401
from app.models.tenant import Tenant, TenantEncryptionKey, ApiClient  # noqa: F401
from app.models.user import UserAccount  # noqa: F401
from app.models.schema import DocumentSchema, SchemaVersion  # noqa: F401
from app.models.document import Document, BulkJob  # noqa: F401
from app.models.verification import VerificationToken  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.webhook import Webhook, WebhookEvent  # noqa: F401
from app.models.notification import NotificationPreference  # noqa: F401
from app.models.digilocker import DigiLockerPush  # noqa: F401
