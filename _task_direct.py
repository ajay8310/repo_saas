"""Run the attach task synchronously to capture its result/errors directly."""
import asyncio
import io
import uuid
from PIL import Image, ImageDraw

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.services.issuance_service import IssuanceService
from app.services.zip_bulk_service import ZipBulkService
from app.tasks.badge_bulk import _bulk_attach_photos_async

TENANT = "df4392f1-3367-46b6-9b34-0ee04ae9fe8d"


def _png(color):
    img = Image.new("RGB", (180, 180), (247, 249, 253))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 30, 120, 100), fill=color)
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()


async def main():
    settings = get_settings()
    svc = ZipBulkService(db=None, settings=settings)  # only uses _put_staged_photo + s3

    emails = ["later.anita@example.com", "later.vikram@example.com"]
    # Confirm both have issued assertions first.
    async with AsyncSessionLocal() as db:
        iss = IssuanceService(db=db, settings=settings)
        for e in emails:
            rows = await iss.list_assertions_for_beneficiary(uuid.UUID(TENANT), e)
            print("LOOKUP", e, "->", len(rows), "active assertion(s)")

    job_id = str(uuid.uuid4())
    photos = []
    for i, e in enumerate(emails):
        key = svc._put_staged_photo(uuid.UUID(TENANT), job_id, _png((100 + i*40, 120, 190)), "image/png")
        photos.append({"beneficiary_id": e, "photo_key": key, "photo_content_type": "image/png"})

    res = await _bulk_attach_photos_async(job_id, TENANT, photos, "direct_test", None)
    print("RESULT:", res)


if __name__ == "__main__":
    asyncio.run(main())
