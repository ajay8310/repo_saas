"""Bulk badge issuance from a ZIP archive of recipients + photos (U4 Q6 / bulk).

An issuer uploads a single ZIP containing:

* a manifest — ``recipients.csv`` or ``recipients.json`` (any ``*.csv`` / ``*.json``
  at the archive root is accepted; the first match wins) listing one row per
  recipient with at least a ``beneficiary_id`` column and an optional ``photo``
  column naming the image file inside the archive, and
* photo images — PNG/JPEG, typically under a ``photos/`` folder, matched to a
  recipient either by the manifest ``photo`` value or, failing that, by the
  recipient id (``<beneficiary_id>.<ext>``) at the root or under ``photos/``.

The single-recipient case is just a ZIP with one manifest row + one photo, so
one mechanism serves both bulk and single uploads.

This service only *parses, validates, and stages*: it writes each matched photo
to a per-job S3 staging prefix and returns a plan (recipient id -> staged photo
key, plus row-level errors). The actual issuance + photo attachment is performed
by the Celery task ``bulk_issue_badges_with_photos`` using the existing
``IssuanceService.issue`` + ``CertificateService.upload_recipient_photo`` paths,
so validation, malware scanning, SSE-KMS storage, audit, and notifications are
identical to the single-issue flow. No parallel storage mechanism.

Security posture: in-memory parsing with an entry-count cap, a decompressed-size
cap (zip-bomb defence), per-photo size + type checks, and a path-traversal guard
on archive entry names.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid as uuid_mod
import zipfile
from dataclasses import dataclass, field
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db

logger = logging.getLogger(__name__)

_PHOTO_EXT_TO_TYPE: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
_MANIFEST_EXTS: tuple[str, ...] = ("csv", "json")


class ZipBulkValidationError(Exception):
    """Raised when the uploaded archive is structurally invalid or too large."""


class ZipBulkServiceUnavailableError(Exception):
    """Raised when staging storage is unavailable."""


@dataclass(frozen=True, slots=True)
class StagedRecipient:
    """One recipient parsed from the manifest and (optionally) its staged photo."""

    beneficiary_id: str
    photo_key: str | None
    photo_content_type: str | None


@dataclass(slots=True)
class ZipBulkPlan:
    """The validated, staged result of parsing a bulk ZIP."""

    job_id: str
    recipients: list[StagedRecipient] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # {"entry"|"row": str, "error": str}

    @property
    def total(self) -> int:
        return len(self.recipients)


@dataclass(frozen=True, slots=True)
class StagedPhoto:
    """A staged photo to attach to a recipient's already-issued credential(s)."""

    beneficiary_id: str
    photo_key: str
    photo_content_type: str


@dataclass(slots=True)
class ZipPhotosPlan:
    """The validated, staged result of parsing a photos-only ZIP."""

    job_id: str
    photos: list[StagedPhoto] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # {"entry": str, "error": str}

    @property
    def total(self) -> int:
        return len(self.photos)


class ZipBulkService:
    """Parse + validate + stage a bulk-issue ZIP of recipients and photos."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._s3 = self._create_s3_client()

    def _create_s3_client(self):
        kwargs: dict = {"region_name": self.settings.aws_region}
        if self.settings.s3_endpoint_url:
            kwargs["endpoint_url"] = self.settings.s3_endpoint_url
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("s3", **kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def presign_upload(self, tenant_id: UUID, size_bytes: int) -> tuple[str, str]:
        """Return a presigned PUT URL + staging key for a direct-to-S3 ZIP upload.

        Enforces the max archive size before issuing the URL (and the limit is
        re-checked server-side when the object is later read). The key lives
        under a per-upload prefix so a failed/abandoned upload is easy to reap.
        """
        if size_bytes <= 0:
            raise ZipBulkValidationError("file size must be greater than zero")
        if size_bytes > self.settings.bulk_zip_max_bytes:
            raise ZipBulkValidationError(
                f"ZIP exceeds the maximum of {self.settings.bulk_zip_max_bytes} bytes"
            )
        upload_id = uuid_mod.uuid4()
        key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/_bulk_uploads/"
            f"{upload_id}/upload.zip"
        )
        try:
            url = self._s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.settings.s3_bucket_name,
                    "Key": key,
                    "ContentType": "application/zip",
                    "ServerSideEncryption": "aws:kms",
                },
                ExpiresIn=self.settings.bulk_zip_presign_ttl_seconds,
            )
        except Exception as exc:
            logger.error("Bulk ZIP presign failed: %s", exc)
            raise ZipBulkServiceUnavailableError("Storage service unavailable") from exc
        return url, key

    def parse_and_stage_from_key(self, tenant_id: UUID, zip_key: str) -> ZipBulkPlan:
        """Read a previously uploaded ZIP from S3 and parse+stage it.

        The key must live under this tenant's bulk-upload prefix (prevents one
        tenant pointing at another's object). Enforces the size cap on the
        stored object, delegates to :meth:`parse_and_stage`, then deletes the
        uploaded ZIP whether parsing succeeds or fails.
        """
        prefix = f"{self.settings.badge_image_prefix}/{tenant_id}/_bulk_uploads/"
        if not zip_key.startswith(prefix) or ".." in zip_key:
            raise ZipBulkValidationError("invalid upload key for this tenant")

        try:
            head = self._s3.head_object(Bucket=self.settings.s3_bucket_name, Key=zip_key)
        except Exception as exc:
            raise ZipBulkValidationError("uploaded ZIP not found — re-upload and try again") from exc
        if head.get("ContentLength", 0) > self.settings.bulk_zip_max_bytes:
            self._delete_quiet(zip_key)
            raise ZipBulkValidationError(
                f"ZIP exceeds the maximum of {self.settings.bulk_zip_max_bytes} bytes"
            )

        try:
            obj = self._s3.get_object(Bucket=self.settings.s3_bucket_name, Key=zip_key)
            zip_bytes = obj["Body"].read()
        except Exception as exc:
            raise ZipBulkServiceUnavailableError("Storage service unavailable") from exc

        try:
            return self.parse_and_stage(tenant_id, zip_bytes)
        finally:
            self._delete_quiet(zip_key)

    def _delete_quiet(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self.settings.s3_bucket_name, Key=key)
        except Exception:
            logger.debug("Could not delete uploaded ZIP %s", key, exc_info=True)

    # ------------------------------------------------------------------
    # Photos-only flow (attach to already-issued credentials, later upload)
    # ------------------------------------------------------------------

    def parse_photos_from_key(self, tenant_id: UUID, zip_key: str) -> ZipPhotosPlan:
        """Read an uploaded photos-only ZIP from S3 and parse+stage it.

        Mirrors :meth:`parse_and_stage_from_key` (tenant-prefix guard, size
        re-check, delete-after-read) but delegates to :meth:`parse_photos`.
        """
        prefix = f"{self.settings.badge_image_prefix}/{tenant_id}/_bulk_uploads/"
        if not zip_key.startswith(prefix) or ".." in zip_key:
            raise ZipBulkValidationError("invalid upload key for this tenant")
        try:
            head = self._s3.head_object(Bucket=self.settings.s3_bucket_name, Key=zip_key)
        except Exception as exc:
            raise ZipBulkValidationError("uploaded ZIP not found — re-upload and try again") from exc
        if head.get("ContentLength", 0) > self.settings.bulk_zip_max_bytes:
            self._delete_quiet(zip_key)
            raise ZipBulkValidationError(
                f"ZIP exceeds the maximum of {self.settings.bulk_zip_max_bytes} bytes"
            )
        try:
            obj = self._s3.get_object(Bucket=self.settings.s3_bucket_name, Key=zip_key)
            zip_bytes = obj["Body"].read()
        except Exception as exc:
            raise ZipBulkServiceUnavailableError("Storage service unavailable") from exc
        try:
            return self.parse_photos(tenant_id, zip_bytes)
        finally:
            self._delete_quiet(zip_key)

    def parse_photos(self, tenant_id: UUID, zip_bytes: bytes) -> ZipPhotosPlan:
        """Parse a photos-only ZIP and stage each image for a later attach.

        Every image entry is treated as a recipient photo. The recipient email
        comes from an optional ``photos.csv``/``photos.json`` map (columns
        ``photo``/``filename`` -> ``beneficiary_id``/``email``) or, failing that,
        from the image filename stem (``alice@example.com.png`` -> that email).
        A manifest is NOT required. Per-image problems are collected in
        ``plan.errors``; the matching to existing assertions happens later in
        the Celery task.
        """
        zf = self._open_zip(zip_bytes)
        infos = self._safe_infos(zf)

        # Optional filename -> email mapping.
        mapping: dict[str, str] = {}
        map_info = next(
            (i for i in infos if i.filename.rsplit("/", 1)[-1].lower()
             in ("photos.csv", "photos.json")),
            None,
        )
        if map_info is not None:
            for row in self._parse_manifest(zf, map_info):
                fname = (row.get("photo") or row.get("filename") or "").strip().rsplit("/", 1)[-1].lower()
                email = (row.get("beneficiary_id") or "").strip()
                if fname and email:
                    mapping[fname] = email

        plan = ZipPhotosPlan(job_id=str(uuid_mod.uuid4()))
        for i in infos:
            if i is map_info:
                continue
            base = i.filename.rsplit("/", 1)[-1]
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            content_type = _PHOTO_EXT_TO_TYPE.get(ext)
            if content_type is None:
                # Silently skip non-image sidecar files (e.g. a stray README).
                continue
            email = mapping.get(base.lower()) or base.rsplit(".", 1)[0].strip()
            if "@" not in email:
                plan.errors.append(
                    {"entry": base, "error": "cannot determine recipient email for this photo"}
                )
                continue
            try:
                content = zf.read(i)
                self._check_photo_bytes(i, content)
                key = self._put_staged_photo(tenant_id, plan.job_id, content, content_type)
            except ZipBulkValidationError as exc:
                plan.errors.append({"entry": base, "error": str(exc)})
                continue
            plan.photos.append(StagedPhoto(email, key, content_type))

        if not plan.photos:
            raise ZipBulkValidationError("no usable photos found in the archive")
        return plan

    # ------------------------------------------------------------------
    # Shared ZIP helpers
    # ------------------------------------------------------------------

    def _open_zip(self, zip_bytes: bytes) -> zipfile.ZipFile:
        if not zip_bytes:
            raise ZipBulkValidationError("archive is empty")
        if len(zip_bytes) > self.settings.bulk_zip_max_bytes:
            raise ZipBulkValidationError("archive exceeds the maximum allowed size")
        try:
            return zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            raise ZipBulkValidationError("file is not a valid ZIP archive") from exc

    def _safe_infos(self, zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > self.settings.bulk_zip_max_entries:
            raise ZipBulkValidationError(
                f"archive has too many entries (max {self.settings.bulk_zip_max_entries})"
            )
        total_uncompressed = sum(max(i.file_size, 0) for i in infos)
        if total_uncompressed > self.settings.bulk_zip_max_uncompressed_bytes:
            raise ZipBulkValidationError("archive decompressed size exceeds the allowed cap")
        for i in infos:
            name = i.filename
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise ZipBulkValidationError(f"unsafe entry path in archive: {name!r}")
        return infos

    def _check_photo_bytes(self, info: zipfile.ZipInfo, content: bytes) -> None:
        if not content:
            raise ZipBulkValidationError(f"photo is empty: {info.filename!r}")
        if len(content) > self.settings.certificate_photo_max_bytes:
            raise ZipBulkValidationError(f"photo exceeds the maximum size: {info.filename!r}")

    def _put_staged_photo(
        self, tenant_id: UUID, job_id: str, content: bytes, content_type: str
    ) -> str:
        key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/_bulk_staging/"
            f"{job_id}/{uuid_mod.uuid4()}.{ 'png' if content_type == 'image/png' else 'jpg' }"
        )
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Bulk photo staging upload failed: %s", exc)
            raise ZipBulkServiceUnavailableError("Storage service unavailable") from exc
        return key

    def parse_and_stage(self, tenant_id: UUID, zip_bytes: bytes) -> ZipBulkPlan:
        """Validate the archive, stage matched photos to S3, return a plan.

        Raises :class:`ZipBulkValidationError` for whole-archive problems (not a
        zip, too big, no manifest, over the record cap). Per-row/photo problems
        are collected into ``plan.errors`` so a mostly-good upload still proceeds.
        """
        if not zip_bytes:
            raise ZipBulkValidationError("archive is empty")
        if len(zip_bytes) > self.settings.bulk_zip_max_bytes:
            raise ZipBulkValidationError("archive exceeds the maximum allowed size")

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            raise ZipBulkValidationError("file is not a valid ZIP archive") from exc

        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > self.settings.bulk_zip_max_entries:
            raise ZipBulkValidationError(
                f"archive has too many entries (max {self.settings.bulk_zip_max_entries})"
            )

        # Zip-bomb guard: reject if declared decompressed size blows the cap.
        total_uncompressed = sum(max(i.file_size, 0) for i in infos)
        if total_uncompressed > self.settings.bulk_zip_max_uncompressed_bytes:
            raise ZipBulkValidationError("archive decompressed size exceeds the allowed cap")

        # Path-traversal / absolute-path guard.
        for i in infos:
            name = i.filename
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise ZipBulkValidationError(f"unsafe entry path in archive: {name!r}")

        manifest_info = self._find_manifest(infos)
        if manifest_info is None:
            raise ZipBulkValidationError(
                "no manifest found — include a recipients.csv or recipients.json at the archive root"
            )

        rows = self._parse_manifest(zf, manifest_info)
        if not rows:
            raise ZipBulkValidationError("manifest contains no records")
        if len(rows) > self.settings.bulk_upload_max_records:
            raise ZipBulkValidationError(
                f"bulk issue exceeds max of {self.settings.bulk_upload_max_records} records"
            )

        # Index non-manifest entries by basename and by stem for photo matching.
        by_name: dict[str, zipfile.ZipInfo] = {}
        by_stem: dict[str, zipfile.ZipInfo] = {}
        for i in infos:
            if i is manifest_info:
                continue
            base = i.filename.rsplit("/", 1)[-1]
            by_name[base.lower()] = i
            stem = base.rsplit(".", 1)[0]
            by_stem[stem.lower()] = i

        plan = ZipBulkPlan(job_id=str(uuid_mod.uuid4()))
        seen: set[str] = set()
        for idx, row in enumerate(rows):
            bid = (row.get("beneficiary_id") or "").strip()
            if not bid:
                plan.errors.append({"row": str(idx + 1), "error": "missing beneficiary_id"})
                continue
            if bid.lower() in seen:
                plan.errors.append({"row": str(idx + 1), "error": f"duplicate beneficiary_id {bid}"})
                continue
            seen.add(bid.lower())

            info = self._match_photo(row, bid, by_name, by_stem)
            if info is None:
                # A recipient without a photo is allowed — the badge still issues.
                plan.recipients.append(StagedRecipient(bid, None, None))
                continue

            try:
                staged = self._stage_photo(tenant_id, plan.job_id, bid, zf, info)
            except ZipBulkValidationError as exc:
                plan.errors.append({"row": str(idx + 1), "error": str(exc)})
                # Issue the badge anyway, without a photo.
                plan.recipients.append(StagedRecipient(bid, None, None))
                continue
            plan.recipients.append(staged)

        if not plan.recipients:
            raise ZipBulkValidationError("no valid recipients found in the archive")
        return plan

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_manifest(self, infos: list[zipfile.ZipInfo]) -> zipfile.ZipInfo | None:
        # Prefer an explicitly named recipients.* at any depth, else the first
        # csv/json. Shallower paths win so a root manifest beats a nested one.
        candidates = [
            i for i in infos if i.filename.rsplit(".", 1)[-1].lower() in _MANIFEST_EXTS
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda i: (i.filename.count("/"), i.filename.lower()))
        named = [i for i in candidates if i.filename.rsplit("/", 1)[-1].lower().startswith("recipients.")]
        return named[0] if named else candidates[0]

    def _parse_manifest(self, zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> list[dict]:
        raw = zf.read(info).decode("utf-8-sig", errors="replace")
        ext = info.filename.rsplit(".", 1)[-1].lower()
        if ext == "json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ZipBulkValidationError(f"manifest JSON is invalid: {exc}") from exc
            if isinstance(data, dict) and "recipients" in data:
                data = data["recipients"]
            if not isinstance(data, list):
                raise ZipBulkValidationError("manifest JSON must be a list of recipient objects")
            return [self._normalize_row(r) for r in data if isinstance(r, dict)]
        # CSV
        reader = csv.DictReader(io.StringIO(raw))
        return [self._normalize_row(dict(r)) for r in reader]

    @staticmethod
    def _normalize_row(row: dict) -> dict:
        # Lower-case keys and strip; accept common aliases for the id column.
        norm = {str(k).strip().lower(): (v if v is None else str(v).strip()) for k, v in row.items()}
        if "beneficiary_id" not in norm:
            for alias in ("email", "beneficiary", "recipient", "recipient_id", "id"):
                if alias in norm:
                    norm["beneficiary_id"] = norm[alias]
                    break
        return norm

    def _match_photo(
        self,
        row: dict,
        bid: str,
        by_name: dict[str, zipfile.ZipInfo],
        by_stem: dict[str, zipfile.ZipInfo],
    ) -> zipfile.ZipInfo | None:
        # 1) explicit manifest "photo" value (basename match)
        photo_ref = (row.get("photo") or "").strip()
        if photo_ref:
            base = photo_ref.rsplit("/", 1)[-1].lower()
            if base in by_name:
                return by_name[base]
        # 2) <beneficiary_id>.<ext> by stem (covers photos/<id>.png and <id>.png)
        return by_stem.get(bid.lower())

    def _stage_photo(
        self,
        tenant_id: UUID,
        job_id: str,
        beneficiary_id: str,
        zf: zipfile.ZipFile,
        info: zipfile.ZipInfo,
    ) -> StagedRecipient:
        ext = info.filename.rsplit(".", 1)[-1].lower()
        content_type = _PHOTO_EXT_TO_TYPE.get(ext)
        if content_type is None:
            raise ZipBulkValidationError(f"unsupported photo type: {info.filename!r}")
        if info.file_size > self.settings.certificate_photo_max_bytes:
            raise ZipBulkValidationError(f"photo exceeds the maximum size: {info.filename!r}")

        content = zf.read(info)
        if not content:
            raise ZipBulkValidationError(f"photo is empty: {info.filename!r}")
        # Re-check actual decompressed length (declared size can lie).
        if len(content) > self.settings.certificate_photo_max_bytes:
            raise ZipBulkValidationError(f"photo exceeds the maximum size: {info.filename!r}")

        staging_key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/_bulk_staging/"
            f"{job_id}/{uuid_mod.uuid4()}.{ 'png' if content_type == 'image/png' else 'jpg' }"
        )
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=staging_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Bulk photo staging upload failed: %s", exc)
            raise ZipBulkServiceUnavailableError("Storage service unavailable") from exc

        return StagedRecipient(beneficiary_id, staging_key, content_type)


async def get_zip_bulk_service(
    db: AsyncSession = Depends(get_db),
) -> ZipBulkService:
    return ZipBulkService(db=db, settings=get_settings())
