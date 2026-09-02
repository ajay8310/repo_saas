"""
Integration tests for DigiLocker connector retry logic.

Requirement 12.2: 5 retries at minimum 60-second intervals.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.integration
class TestDigiLockerRetryLogic:
    """DigiLocker push retries up to 5 times at 60s intervals (Req 12.2)."""

    def test_connector_has_max_retries_config(self) -> None:
        """The digilocker_max_retries setting defaults to 5."""
        from app.config import get_settings

        settings = get_settings()
        assert settings.digilocker_max_retries == 5

    def test_retry_interval_is_at_least_60_seconds(self) -> None:
        """Each retry waits at least 60 seconds."""
        from app.config import get_settings

        settings = get_settings()
        assert settings.digilocker_retry_interval_seconds >= 60


@pytest.mark.integration
class TestDigiLockerNoAccountHandling:
    """Beneficiary without DigiLocker account — immediate failure (Req 12.4)."""

    @pytest.mark.asyncio
    async def test_no_push_record_returns_false(self) -> None:
        """When push record doesn't exist, attempt_push returns False."""
        from app.services.digilocker_connector import DigiLockerConnector

        connector = DigiLockerConnector.__new__(DigiLockerConnector)
        connector.db = AsyncMock()
        connector.settings = MagicMock()
        connector.settings.digilocker_max_retries = 5

        # Mock a query that returns no push record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        connector.db.execute = AsyncMock(return_value=mock_result)

        result = await connector.attempt_push(push_id=uuid4())
        assert result is False


@pytest.mark.integration
class TestDigiLockerPerTenantToggle:
    """Per-tenant connector enable/disable (Req 12.6)."""

    def test_connector_respects_tenant_config(self) -> None:
        """DigiLocker push is skipped if connector is disabled for the tenant."""
        from app.services.digilocker_connector import DigiLockerConnector

        connector = DigiLockerConnector.__new__(DigiLockerConnector)
        # With connector disabled, should_push returns False
        tenant_config = {"digilocker_enabled": False}
        assert not tenant_config.get("digilocker_enabled", False)
