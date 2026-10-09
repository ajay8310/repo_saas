import app.routers.badges  # noqa: F401
import app.services.zip_bulk_service  # noqa: F401
import app.tasks.badge_bulk  # noqa: F401
from app.tasks.badge_bulk import bulk_attach_photos  # noqa: F401
from app.services.zip_bulk_service import ZipPhotosPlan, StagedPhoto  # noqa: F401

print("OK")
