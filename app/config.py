"""
Application configuration using Pydantic BaseSettings.

All settings are read from environment variables (or a .env file in development).
Sensitive defaults are intentionally left empty so misconfigured environments
fail fast at startup rather than silently using insecure placeholder values.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the platform.

    Environment-variable names are the uppercase version of each field name
    (e.g. ``DATABASE_URL``, ``REDIS_URL``).  A ``.env`` file is loaded
    automatically when present; environment variables always take precedence.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Extra fields in the .env file are silently ignored.
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    app_name: str = Field(default="Repo SaaS", description="Human-readable application name")
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Runtime environment; controls log verbosity and feature flags",
    )
    debug: bool = Field(default=False, description="Enable debug mode (never True in production)")
    api_v1_prefix: str = Field(default="/api/v1", description="URL prefix for the v1 API")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Root log level"
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        ...,
        description=(
            "Async PostgreSQL DSN.  "
            "Example: postgresql+asyncpg://user:password@host:5432/dbname"
        ),
    )
    database_pool_size: int = Field(default=10, ge=1, le=100, description="SQLAlchemy pool size")
    database_max_overflow: int = Field(
        default=20, ge=0, le=200, description="SQLAlchemy max overflow connections"
    )
    database_pool_timeout: int = Field(
        default=30, ge=1, description="Seconds to wait for a pool connection"
    )
    database_echo: bool = Field(
        default=False, description="Log all SQL statements (development only)"
    )

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_url: str = Field(
        ...,
        description="Redis DSN.  Example: redis://localhost:6379/0",
    )
    redis_pool_size: int = Field(default=20, ge=1, description="Maximum Redis pool connections")

    # ------------------------------------------------------------------
    # Celery
    # ------------------------------------------------------------------
    celery_broker_url: str = Field(
        default="",
        description=(
            "Celery broker URL.  Defaults to redis_url when empty."
        ),
    )
    celery_result_backend: str = Field(
        default="",
        description=(
            "Celery result backend URL.  Defaults to redis_url when empty."
        ),
    )
    celery_task_serializer: str = Field(default="json")
    celery_result_serializer: str = Field(default="json")
    celery_timezone: str = Field(default="UTC")

    @field_validator("celery_broker_url", mode="after")
    @classmethod
    def default_celery_broker(cls, v: str, info) -> str:  # noqa: ANN001
        if not v:
            # Lazily default to redis_url; info.data contains already-validated fields.
            return info.data.get("redis_url", "")
        return v

    @field_validator("celery_result_backend", mode="after")
    @classmethod
    def default_celery_backend(cls, v: str, info) -> str:  # noqa: ANN001
        if not v:
            return info.data.get("redis_url", "")
        return v

    # ------------------------------------------------------------------
    # AWS
    # ------------------------------------------------------------------
    aws_region: str = Field(
        default="ap-south-1",
        description="AWS region for KMS, S3, SES, and SNS",
    )
    aws_access_key_id: str = Field(
        default="",
        description="AWS access key ID (leave empty to use IAM role / instance profile)",
    )
    aws_secret_access_key: str = Field(
        default="",
        description="AWS secret access key (leave empty to use IAM role / instance profile)",
    )

    # S3
    s3_bucket_name: str = Field(
        ...,
        description="S3 bucket where encrypted document content is stored",
    )
    s3_endpoint_url: str = Field(
        default="",
        description=(
            "Override S3 endpoint URL (e.g. LocalStack for testing).  "
            "Leave empty to use the real AWS endpoint."
        ),
    )

    # KMS
    kms_endpoint_url: str = Field(
        default="",
        description="Override KMS endpoint URL (e.g. LocalStack).  Leave empty for real AWS.",
    )

    # SES (email notifications)
    ses_from_email: str = Field(
        default="no-reply@example.com",
        description="Sender address for SES email notifications",
    )
    ses_endpoint_url: str = Field(
        default="",
        description="Override SES endpoint URL.  Leave empty for real AWS.",
    )

    # SNS (SMS notifications)
    sns_endpoint_url: str = Field(
        default="",
        description="Override SNS endpoint URL.  Leave empty for real AWS.",
    )

    # ------------------------------------------------------------------
    # JWT / Auth
    # ------------------------------------------------------------------
    jwt_algorithm: str = Field(
        default="RS256",
        description="JWT signing algorithm.  RS256 is required for production.",
    )
    jwt_private_key: str = Field(
        ...,
        description=(
            "PEM-encoded RSA private key used to sign JWTs.  "
            "Multi-line values must preserve newlines (use a quoted env var or .env file)."
        ),
    )
    jwt_public_key: str = Field(
        ...,
        description="PEM-encoded RSA public key used to verify JWTs.",
    )
    jwt_access_token_expire_seconds: int = Field(
        default=3600,
        ge=60,
        le=3600,
        description="JWT access token lifetime in seconds.  Maximum 3600 (Requirement 8.2).",
    )

    # OTP
    otp_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=600,
        description="OTP time-to-live in seconds (max 600 = 10 minutes, Requirement 4.6).",
    )
    otp_length: int = Field(default=6, ge=4, le=8, description="Number of digits in an OTP code")

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    cors_allowed_origins: list[str] = Field(
        default=["*"],
        description=(
            "List of origins allowed by CORS middleware.  "
            'Use ["*"] only in development; restrict in production.'
        ),
    )
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: list[str] = Field(default=["*"])
    cors_allow_headers: list[str] = Field(default=["*"])

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    rate_limit_default_requests: int = Field(
        default=10_000,
        ge=1,
        description="Default maximum requests per rate-limit window (Requirement 1.9, 8.4)",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="Rolling window size in seconds for the rate limiter",
    )

    # ------------------------------------------------------------------
    # Storage quota
    # ------------------------------------------------------------------
    storage_quota_default_bytes: int = Field(
        default=10 * 1024 ** 3,  # 10 GB
        ge=1024 ** 2,            # 1 MB minimum
        description="Default per-tenant storage quota in bytes",
    )

    # ------------------------------------------------------------------
    # Bulk upload
    # ------------------------------------------------------------------
    bulk_upload_max_records: int = Field(
        default=10_000,
        ge=1,
        description="Maximum records allowed per bulk upload request (Requirement 3.8)",
    )
    bulk_upload_timeout_seconds: int = Field(
        default=1800,  # 30 minutes
        ge=60,
        description="Maximum processing time for a bulk upload job in seconds (Requirement 14.4)",
    )

    # ------------------------------------------------------------------
    # Document upload
    # ------------------------------------------------------------------
    single_upload_timeout_seconds: int = Field(
        default=30,
        ge=5,
        description="Request timeout for single document uploads (Requirement 3.11)",
    )

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    max_failed_auth_attempts: int = Field(
        default=5,
        ge=1,
        description="Consecutive failures before account lockout (Requirement 13.6)",
    )
    auth_lockout_minutes: int = Field(
        default=15,
        ge=1,
        description="Account lockout duration after failed auth attempts (Requirement 13.6)",
    )
    max_failed_mfa_attempts: int = Field(
        default=3,
        ge=1,
        description="Consecutive MFA failures before admin account lockout (Requirement 13.8)",
    )
    mfa_lockout_minutes: int = Field(
        default=30,
        ge=1,
        description="Admin account lockout duration after failed MFA attempts (Requirement 13.8)",
    )
    mfa_challenge_timeout_minutes: int = Field(
        default=5,
        ge=1,
        description="Minutes within which MFA must be completed (Requirement 13.3)",
    )

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    audit_log_retention_years: int = Field(
        default=7,
        ge=1,
        le=99,
        description="Default audit log retention period in years (Requirement 10.4)",
    )

    # ------------------------------------------------------------------
    # Verification tokens
    # ------------------------------------------------------------------
    verification_token_default_expiry_hours: int = Field(
        default=72,
        ge=1,
        le=168,
        description="Default verification token lifetime in hours (Requirement 5.1)",
    )
    verification_token_max_expiry_hours: int = Field(
        default=168,
        ge=1,
        description="Maximum allowed verification token lifetime in hours (Requirement 5.1)",
    )
    verification_base_url: str = Field(
        default="http://localhost:3000",
        description=(
            "Public base URL used to build the verification link embedded in "
            "generated QR codes (Requirement 4.7).  No trailing slash."
        ),
    )

    # ------------------------------------------------------------------
    # Webhook delivery
    # ------------------------------------------------------------------
    webhook_first_retry_delay_seconds: int = Field(
        default=5,
        ge=5,
        le=10,
        description="Seconds before first webhook retry (Requirement 8.9)",
    )
    webhook_max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum webhook delivery retries (Requirement 8.8)",
    )

    # ------------------------------------------------------------------
    # DigiLocker connector
    # ------------------------------------------------------------------
    digilocker_push_timeout_seconds: int = Field(
        default=10,
        ge=1,
        description="Seconds after issuance within which DigiLocker push must be enqueued (Req 12.1)",
    )
    digilocker_max_retries: int = Field(
        default=5,
        ge=0,
        description="Maximum DigiLocker push retry attempts (Requirement 12.2)",
    )
    digilocker_retry_interval_seconds: int = Field(
        default=60,
        ge=60,
        description="Minimum interval between DigiLocker retry attempts (Requirement 12.2)",
    )

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------
    anomaly_detection_window_minutes: int = Field(
        default=10,
        ge=1,
        description="Rolling window for anomalous access detection (Requirement 10.6)",
    )
    anomaly_detection_threshold: int = Field(
        default=500,
        ge=1,
        description="Document retrieval count threshold to trigger anomaly alert (Requirement 10.6)",
    )

    # ------------------------------------------------------------------
    # Data vault (field-level PII protection)
    # ------------------------------------------------------------------
    vault_provider: Literal["local", "kms"] = Field(
        default="local",
        description=(
            "Backend used to seal personal-data fields.  'local' derives keys "
            "from vault_root_key; 'kms' performs envelope encryption via AWS KMS."
        ),
    )
    vault_root_key: str = Field(
        default="",
        description=(
            "Base64 or hex root key (>=32 bytes) for the 'local' vault provider. "
            "Per-tenant keys are HKDF-derived from it; it is never used directly."
        ),
    )
    vault_active_key_id: str = Field(
        default="k1",
        description=(
            "Identifier recorded in every new ciphertext envelope.  Bump this "
            "alongside vault_root_key to rotate; existing values stay readable "
            "because the envelope carries the id it was sealed with."
        ),
    )
    vault_kms_key_arn: str = Field(
        default="",
        description="CMK ARN used when vault_provider is 'kms'.",
    )
    vault_blind_index_key: str = Field(
        default="",
        description=(
            "Base64 or hex HMAC key for deterministic blind indexes.  Rotating "
            "this invalidates every index column and requires a backfill, so it "
            "is kept separate from vault_root_key."
        ),
    )
    pii_encryption_enabled: bool = Field(
        default=False,
        description=(
            "Master switch for sealing personal-data columns.  Off by default so "
            "an existing deployment keeps working until the operator has "
            "provisioned keys and run the backfill."
        ),
    )

    # ------------------------------------------------------------------
    # Malware scanning
    # ------------------------------------------------------------------
    clamav_host: str = Field(
        default="localhost",
        description="ClamAV sidecar host",
    )
    clamav_port: int = Field(
        default=3310,
        ge=1,
        le=65535,
        description="ClamAV sidecar port",
    )


    @model_validator(mode="after")
    def validate_vault_configuration(self) -> Settings:
        """Fail fast when PII encryption is on but unusable.

        Catching this at startup matters more than usual: if the vault is
        misconfigured we must not fall back to writing plaintext personal data,
        and discovering that on the first upload is far too late.
        """
        if not self.pii_encryption_enabled:
            return self

        if not self.vault_blind_index_key:
            raise ValueError(
                "pii_encryption_enabled requires vault_blind_index_key to be set"
            )
        if self.vault_provider == "local" and not self.vault_root_key:
            raise ValueError(
                "vault_provider='local' requires vault_root_key to be set"
            )
        if self.vault_provider == "kms" and not self.vault_kms_key_arn:
            raise ValueError(
                "vault_provider='kms' requires vault_kms_key_arn to be set"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Using ``lru_cache`` ensures the ``.env`` file is parsed at most once per
    process lifetime, while still allowing tests to override settings by
    clearing the cache (``get_settings.cache_clear()``).
    """
    return Settings()  # type: ignore[call-arg]
