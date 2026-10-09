"""Re-check anita's has_photo after giving the attach job more time."""
import httpx

BASE = "http://localhost:8000/api/v1"
with httpx.Client(timeout=30) as c:
    tok = c.post(f"{BASE}/auth/dev-token", json={"role": "issuer"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    rows = c.get(f"{BASE}/badges/assertions?limit=300", headers=h).json()
    want = {"later.anita@example.com", "later.vikram@example.com"}
    for r in rows:
        if r["beneficiary_id"] in want:
            print(r["beneficiary_id"], "has_photo=", r["has_photo"], "status=", r["status"])
