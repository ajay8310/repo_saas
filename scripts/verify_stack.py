"""
Prove the stack actually works end to end.

This is the gate that everything else waits on. It does not mock anything: it
starts the real app in-process with a TestClient and exercises the path a client
follows, so a pass means the database, RLS policies, migrations, encryption,
storage and audit trail all cooperate.

Checks, in order of dependency:

  1. /health responds.
  2. POST /auth/token with the seeded client credentials returns an RS256 JWT.
     This is the check that the FORCE-RLS bootstrap policy from migration 002
     actually works — without it the api_clients lookup returns no rows and
     authentication is impossible.
  3. The token is accepted by a protected endpoint.
  4. A schema is listed (proves tenant context propagates through a service).
  5. A credential is issued (proves malware scan, KMS encryption, S3 write,
     DB insert, audit entry and anchor commitment in one transaction).
  6. The credential appears in a list scoped to the tenant.
  7. An anchor commitment was recorded for it.
  8. Public verification returns a status without authentication.

Anything that fails prints the response body, because a 500 with no context is
the least useful possible output.

Usage:
    python scripts/verify_stack.py
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.seed_dev import CLIENT_ID, CLIENT_SECRET, SCHEMA_NAME  # noqa: E402

PASS = "  PASS"
FAIL = "  FAIL"

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    if ok:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}" + (f" :: {detail}" if detail else ""))
        _failures.append(label)
    return ok


def body_of(response) -> str:  # noqa: ANN001
    try:
        return json.dumps(response.json())[:400]
    except Exception:  # noqa: BLE001
        return response.text[:400]


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    print("Verifying the stack end to end...\n")

    with TestClient(app) as client:
        # 1. health -----------------------------------------------------
        r = client.get("/health")
        check("health endpoint responds 200", r.status_code == 200, body_of(r))

        # 2. real authentication ---------------------------------------
        r = client.post(
            "/api/v1/auth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
        )
        authed = check(
            "POST /auth/token issues a token for the seeded client",
            r.status_code == 200 and "access_token" in r.json(),
            f"HTTP {r.status_code} {body_of(r)}",
        )
        if not authed:
            print(
                "\n  Authentication failed. The usual cause is the api_clients "
                "RLS lookup: confirm migration 002 applied (it adds the "
                "auth_bootstrap SELECT policy)."
            )
            return 1

        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # The token must be a real RS256 JWT, not the dev-preview fake.
        header_b64 = token.split(".")[0]
        header_b64 += "=" * (-len(header_b64) % 4)
        alg = json.loads(base64.urlsafe_b64decode(header_b64)).get("alg")
        check("token is signed with RS256 (not the demo 'none' token)", alg == "RS256", f"alg={alg}")

        # 3-4. protected read ------------------------------------------
        r = client.get("/api/v1/schemas", headers=headers)
        schemas_ok = check(
            "GET /schemas accepts the token",
            r.status_code == 200,
            f"HTTP {r.status_code} {body_of(r)}",
        )

        schema_id = None
        if schemas_ok and isinstance(r.json(), list):
            for s in r.json():
                if s.get("name") == SCHEMA_NAME:
                    schema_id = s.get("schema_id") or s.get("id")
                    break
            check(f"seeded schema {SCHEMA_NAME!r} is visible", schema_id is not None)

        # 5. issue a credential ----------------------------------------
        credential_id = None
        if schema_id:
            from app.config import get_settings
            from sqlalchemy import create_engine, text

            settings = get_settings()
            # Resolve the tenant's real CMK rather than trusting a caller value.
            sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
            cmk = None
            try:
                engine = create_engine(sync_url)
                with engine.connect() as conn:
                    cmk = conn.execute(
                        text(
                            "SELECT kms_key_arn FROM tenant_encryption_keys "
                            "WHERE status = 'active' LIMIT 1"
                        )
                    ).scalar()
            except Exception as exc:  # noqa: BLE001
                print(f"  note: could not read CMK ({exc}); falling back")

            payload = {
                "schema_id": schema_id,
                "beneficiary_id": "student@demo-university.gov.in",
                "content_base64": base64.b64encode(
                    json.dumps(
                        {
                            "student_name": "Asha Verma",
                            "degree": "B.Tech Computer Science",
                            "graduation_year": 2026,
                            "grade": "A",
                        }
                    ).encode()
                ).decode(),
                "cmk_arn": cmk or "",
            }
            r = client.post("/api/v1/documents", json=payload, headers=headers)
            issued = check(
                "POST /documents issues a credential (scan + KMS + S3 + audit)",
                r.status_code == 201,
                f"HTTP {r.status_code} {body_of(r)}",
            )
            if issued:
                credential_id = r.json().get("credential_id")

        # 6. list it ----------------------------------------------------
        if credential_id:
            r = client.get("/api/v1/documents", headers=headers)
            ids = [d.get("credential_id") for d in r.json()] if r.status_code == 200 else []
            check(
                "the credential appears in GET /documents",
                credential_id in ids,
                f"HTTP {r.status_code}",
            )

            # 7. anchor commitment ------------------------------------
            r = client.get(f"/api/v1/documents/{credential_id}/anchor", headers=headers)
            check(
                "an anchor commitment was recorded at issuance",
                r.status_code == 200 and r.json().get("leaf_hash"),
                f"HTTP {r.status_code} {body_of(r)}",
            )

            # 8. public verification ----------------------------------
            r = client.get(f"/api/v1/verify/{credential_id}")
            check(
                "public verification works without a token",
                r.status_code == 200,
                f"HTTP {r.status_code} {body_of(r)}",
            )

    print()
    if _failures:
        print(f"{len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"  - {f}")
        return 1

    print("All checks passed. The frontend can now be pointed at the API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
