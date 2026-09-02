# U1 Badge Core — Domain Entities

## BadgeClass
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | gen_random_uuid() |
| tenant_id | UUID (FK tenants, NOT NULL) | RLS |
| name | str(255) NOT NULL | |
| description | Text | |
| criteria_narrative | Text | |
| criteria_url | str(1024) nullable | |
| tags | JSONB (list[str]) | skills/tags |
| alignment | JSONB (list[{name,url}]) | external framework alignment |
| image_s3_key | str(1024) nullable | uploaded PNG/SVG |
| validity_days | int nullable | Q2=C: null = non-expiring |
| status | str(32) = 'active' | active | archived |
| directory_visible | bool = false | catalog listing (S12) |
| created_at / updated_at | timestamptz | |

## BadgeAssertion
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | **equals the linked documents.id / credential_id** (Q1=B) |
| tenant_id | UUID (FK, NOT NULL) | RLS |
| badge_class_id | UUID (FK badge_classes, NOT NULL) | |
| beneficiary_id | str(512) NOT NULL | earner email/identity (reused) |
| document_id | UUID (FK documents, NOT NULL) | hybrid link (== id) |
| issued_at | timestamptz NOT NULL | |
| expires_at | timestamptz nullable | Q2=C: issued_at + validity_days, else null |
| status | str(32) = 'active' | active | revoked |
| accepted | bool = true | auto-accept (Q5 earlier) |
| hidden | bool = false | earner hid it (U2) |
| public | bool = false | private-by-default (U2 sets true) |
| revoked_at | timestamptz nullable | |
| revocation_reason | str(500) nullable | |

## IssuerProfile (derived from tenant, not a new table)
- Sourced from tenant fields: issuer_name, issuer_url, issuer_email. Served as OB issuer JSON.

## BadgeEvent (table brought forward into U1 per dependency plan)
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| tenant_id | UUID NOT NULL | RLS |
| event_type | str(32) | issued|accepted|published|shared|verified|viewed|revoked |
| badge_class_id | UUID nullable | |
| assertion_id | UUID nullable | == credential_id |
| channel | str(32) nullable | for shared events |
| created_at | timestamptz NOT NULL | |

## Relationships
- BadgeClass 1—* BadgeAssertion. BadgeAssertion 1—1 documents (shared id). BadgeAssertion *—* BadgeEvent (by assertion_id).

## Testable Properties (PBT-01)
- **Round-trip** [PBT-02]: `openbadges.assertion_json(a) → parse → equivalent assertion identity fields`.
- **Invariant** [PBT-03]: expires_at is null XOR = issued_at + validity_days (never arbitrary).
- **Invariant** [PBT-03]: a revoked assertion's verification status is never `valid`.
- **Invariant** [PBT-03]: assertion.id == document_id == credential_id (single identifier).
- **Generators** [PBT-07]: BadgeClass (valid name, optional validity_days≥1, valid URLs), BadgeAssertion (valid beneficiary email).
