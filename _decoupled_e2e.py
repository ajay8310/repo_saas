"""Live E2E: issue WITHOUT photos, then bulk-upload photos later and attach."""
import base64
import io
import time
import zipfile
import httpx
from PIL import Image, ImageDraw

BASE = "http://localhost:8000/api/v1"


def _photo(color) -> bytes:
    img = Image.new("RGB", (200, 200), (247, 249, 253))
    d = ImageDraw.Draw(img)
    d.ellipse((65, 35, 135, 110), fill=color)
    d.ellipse((40, 120, 160, 270), fill=color)
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()


def _photos_zip(emails) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, e in enumerate(emails):
            z.writestr(f"{e}.png", _photo((100 + i * 30, 130, 180)))
        # one image for a recipient with NO credential -> should be unmatched
        z.writestr("nobody.nocred@example.com.png", _photo((90, 90, 90)))
    return buf.getvalue()


def main() -> None:
    with httpx.Client(timeout=120) as c:
        tok = c.post(f"{BASE}/auth/dev-token", json={"role": "issuer"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        bc = next(b["id"] for b in c.get(f"{BASE}/badges/classes", headers=h).json()
                  if b["status"] == "active")

        emails = ["later.anita@example.com", "later.vikram@example.com"]

        # 1) Issue WITHOUT any photo.
        for e in emails:
            r = c.post(f"{BASE}/badges/issue", headers=h,
                       json={"badge_class_id": bc, "beneficiary_id": e})
            assert r.status_code == 201, r.text
            assert r.json()["has_photo"] is False
        print("ISSUED (no photo):", emails)

        # 2) Later: upload a photos-only ZIP (presign with NO badge class).
        zip_bytes = _photos_zip(emails)
        pr = c.post(f"{BASE}/badges/bulk-issue-zip/presign", headers=h,
                    json={"size_bytes": len(zip_bytes)})
        print("PRESIGN (no class):", pr.status_code)
        assert pr.status_code == 200, pr.text
        url, key = pr.json()["upload_url"], pr.json()["zip_key"]

        put = c.put(url, content=zip_bytes,
                    headers={"Content-Type": "application/zip",
                             "x-amz-server-side-encryption": "aws:kms"})
        assert put.status_code in (200, 204), f"{put.status_code} {put.text[:200]}"

        res = c.post(f"{BASE}/badges/bulk-photos-zip", headers=h, json={"zip_key": key})
        print("ATTACH:", res.status_code, res.json())
        assert res.status_code == 202, res.text
        assert res.json()["total"] == 3  # 2 real + 1 nobody

        # 3) Poll: the two issued recipients should flip to has_photo=True.
        want = set(emails)
        for _ in range(30):
            rows = c.get(f"{BASE}/badges/assertions?limit=200", headers=h).json()
            have = {r["beneficiary_id"]: r["has_photo"] for r in rows if r["beneficiary_id"] in want}
            if len(have) == len(want) and all(have.values()):
                break
            time.sleep(2)
        print("AFTER ATTACH:", have)
        assert all(have.get(e) for e in emails), have

        print("RESULT=OK")


if __name__ == "__main__":
    main()
