"""
Unit tests for app.config — Settings validation and defaults.

These tests verify that the Pydantic BaseSettings model:
- Enforces required fields
- Applies correct default values
- Enforces validated bounds (e.g. JWT expiry ≤ 3600)

Requirements covered: 8.1 (config foundation), 8.2 (JWT max 3600 s).
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

# Ensure clean settings for each test.
from app.config import Settings, get_settings

# Minimal valid overrides used across tests.
VALID_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost/db",
    "redis_url": "redis://localhost:6379/0",
    "s3_bucket_name": "test-bucket",
    "jwt_private_key": "-----BEGIN RSA PRIVATE KEY-----\nPLACEHOLDER\n-----END RSA PRIVATE KEY-----",
    "jwt_public_key": "-----BEGIN PUBLIC KEY-----\nPLACEHOLDER\n-----END PUBLIC KEY-----",
}


class TestRequiredFields:
    """Missing required fields should raise ValidationError."""

    def test_missing_database_url_raises(self) -> None:
        cfg = {k: v for k, v in VALID_BASE.items() if k != "database_url"}
        with pytest.raises(ValidationError) as exc_info:
            Settings(**cfg)
        assert "database_url" in str(exc_info.value)

    def test_missing_redis_url_raises(self) -> None:
        cfg = {k: v for k, v in VALID_BASE.items() if k != "redis_url"}
        with pytest.raises(ValidationError) as exc_info:
            Settings(**cfg)
        assert "redis_url" in str(exc_info.value)

    def test_missing_s3_bucket_raises(self) -> None:
        cfg = {k: v for k, v in VALID_BASE.items() if k != "s3_bucket_name"}
        with pytest.raises(ValidationError) as exc_info:
            Settings(**cfg)
        assert "s3_bucket_name" in str(exc_info.value)

    def test_missing_jwt_private_key_raises(self) -> None:
        cfg = {k: v for k, v in VALID_BASE.items() if k != "jwt_private_key"}
        with pytest.raises(ValidationError) as exc_info:
            Settings(**cfg)
        assert "jwt_private_key" in str(exc_info.value)

    def test_missing_jwt_public_key_raises(self) -> None:
        cfg = {k: v for k, v in VALID_BASE.items() if k != "jwt_public_key"}
        with pytest.raises(ValidationError) as exc_info:
            Settings(**cfg)
        assert "jwt_public_key" in str(exc_info.value)


class TestDefaults:
    """Verify that default values match requirements."""

    def setup_method(self) -> None:
        self.settings = Settings(**VALID_BASE)

    def test_jwt_access_token_expire_seconds_default(self) -> None:
        # Requirement 8.2: maximum 3600 seconds
        assert self.settings.jwt_access_token_expire_seconds == 3600

    def test_otp_ttl_default_is_600(self) -> None:
        # Requirement 4.6: OTP expires after 10 minutes (600 seconds)
        assert self.settings.otp_ttl_seconds == 600

    def test_rate_limit_default(self) -> None:
        # Requirement 1.9 / 8.4: default 10,000 requests per window
        assert self.settings.rate_limit_default_requests == 10_000

    def test_rate_limit_window_default(self) -> None:
        assert self.settings.rate_limit_window_seconds == 60

    def test_bulk_upload_max_records_default(self) -> None:
        # Requirement 3.8: maximum 10,000 records per bulk upload
        assert self.settings.bulk_upload_max_records == 10_000

    def test_audit_log_retention_default_is_7_years(self) -> None:
        # Requirement 10.4: minimum 7 years retention
        assert self.settings.audit_log_retention_years == 7

    def test_verification_token_default_expiry(self) -> None:
        # Requirement 5.1: default 72 hours
        assert self.settings.verification_token_default_expiry_hours == 72

    def test_max_failed_auth_attempts_default(self) -> None:
        # Requirement 13.6: 5 consecutive failures trigger lockout
        assert self.settings.max_failed_auth_attempts == 5

    def test_auth_lockout_minutes_default(self) -> None:
        # Requirement 13.6: 15-minute lockout
        assert self.settings.auth_lockout_minutes == 15

    def test_max_failed_mfa_attempts_default(self) -> None:
        # Requirement 13.8: 3 failures trigger admin lockout
        assert self.settings.max_failed_mfa_attempts == 3

    def test_mfa_lockout_minutes_default(self) -> None:
        # Requirement 13.8: 30-minute admin lockout
        assert self.settings.mfa_lockout_minutes == 30

    def test_environment_default_is_development(self) -> None:
        assert self.settings.environment == "development"

    def test_api_v1_prefix_default(self) -> None:
        assert self.settings.api_v1_prefix == "/api/v1"

    def test_jwt_algorithm_default(self) -> None:
        assert self.settings.jwt_algorithm == "RS256"


class TestBounds:
    """Settings outside allowed bounds should raise ValidationError."""

    def _make(self, **overrides) -> Settings:
        return Settings(**{**VALID_BASE, **overrides})

    def test_jwt_expiry_cannot_exceed_3600(self) -> None:
        # Requirement 8.2: JWT expiry must be ≤ 3600 seconds.
        with pytest.raises(ValidationError):
            self._make(jwt_access_token_expire_seconds=3601)

    def test_jwt_expiry_minimum_60(self) -> None:
        with pytest.raises(ValidationError):
            self._make(jwt_access_token_expire_seconds=59)

    def test_otp_ttl_maximum_600(self) -> None:
        with pytest.raises(ValidationError):
            self._make(otp_ttl_seconds=601)

    def test_audit_log_retention_minimum_1(self) -> None:
        with pytest.raises(ValidationError):
            self._make(audit_log_retention_years=0)

    def test_audit_log_retention_maximum_99(self) -> None:
        with pytest.raises(ValidationError):
            self._make(audit_log_retention_years=100)

    def test_verification_token_max_expiry_168(self) -> None:
        with pytest.raises(ValidationError):
            self._make(verification_token_default_expiry_hours=169)

    def test_db_pool_size_minimum_1(self) -> None:
        with pytest.raises(ValidationError):
            self._make(database_pool_size=0)


class TestCeleryDefaults:
    """Celery broker/backend should default to redis_url."""

    def test_celery_broker_defaults_to_redis_url(self) -> None:
        s = Settings(**VALID_BASE)
        assert s.celery_broker_url == VALID_BASE["redis_url"]

    def test_celery_backend_defaults_to_redis_url(self) -> None:
        s = Settings(**VALID_BASE)
        assert s.celery_result_backend == VALID_BASE["redis_url"]

    def test_celery_broker_can_be_overridden(self) -> None:
        custom_broker = "amqp://guest:guest@localhost//"
        s = Settings(**{**VALID_BASE, "celery_broker_url": custom_broker})
        assert s.celery_broker_url == custom_broker


class TestGetSettingsSingleton:
    """get_settings() should return the same cached instance."""

    def test_returns_settings_instance(self) -> None:
        get_settings.cache_clear()
        # Inject required vars so Settings() doesn't fail
        for key, val in VALID_BASE.items():
            os.environ[key.upper()] = val
        s = get_settings()
        assert isinstance(s, Settings)

    def test_cached_instance_is_same_object(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
