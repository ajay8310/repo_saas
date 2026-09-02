# Requirements Verification Questions — Credly-Style Credentialing Features

Feature set (from scope answers): Open Badges issuing (2.0 baseline, design for 3.0/VC), recipient
wallet, social-sharing metadata, public badge directory, analytics dashboard. Full-stack change,
built via AI-DLC. Please fill in each `[Answer]:` tag and tell me you're done.

---

## A. Functional — Badges & Issuing

## Question 1
How should a "badge" relate to the existing `documents` / `document_schemas` model?

A) New first-class **BadgeClass** (template) + **BadgeAssertion** (issued instance) tables, linked to a tenant; independent of documents

B) Reuse `document_schemas` as badge templates and `documents` as assertions (extend existing tables)

C) Hybrid — new BadgeClass table for template/skills/criteria, but each issued badge also creates a linked `documents` row for storage/audit reuse

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 2
What metadata must a BadgeClass hold? (choose all that apply — list letters)

A) name, description, criteria (narrative + URL), tags/skills, image

B) alignment to external standards/frameworks (e.g., skill framework URLs)

C) expiry/validity period for issued badges

D) issuer profile fields (issuer name, url, email) at tenant level

E) all of the above

X) Other (please describe after [Answer]: tag below)

[Answer]: E

## Question 3
Badge image handling?

A) Tenant uploads a PNG/SVG per BadgeClass; store in S3; bake Open Badges assertion metadata into the PNG on issuance

B) Store image only; serve hosted (unbaked) assertions via URL (no baking)

C) Both — hosted assertion always; baked PNG on download

X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

## B. Functional — Recipient Wallet

## Question 4
Recipient (earner) identity model?

A) Reuse existing `beneficiary_id` (email) — earner accesses wallet via OTP login already in the platform

B) New dedicated earner account with its own profile (display name, avatar, public handle)

C) Both — link earner accounts to beneficiary_id

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
Accept/decline flow for issued badges?

A) Auto-accepted on issue; earner may hide/delete from wallet

B) Pending → earner explicitly accepts or declines before it appears publicly

C) Configurable per tenant

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## C. Functional — Sharing & Directory

## Question 6
Public sharing surface for an accepted badge?

A) Public badge page per assertion (Open Graph meta for LinkedIn/X/Facebook previews) + verification link

B) A + LinkedIn "Add to Profile" URL builder (deep link; no LinkedIn API/account needed)

C) A + B + shareable earner profile page listing all public badges

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 7
Public badge directory scope?

A) Per-tenant public catalog of BadgeClasses (templates) only

B) Catalog of templates + searchable list of public earners per badge (privacy-gated by earner consent)

C) Platform-wide directory across all tenants

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 8
Earner privacy default for directory/public pages?

A) Private by default; earner opts in to make a badge public

B) Public by default; earner opts out

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## D. Functional — Analytics

## Question 9
Analytics metrics to expose (tenant admin dashboard)?

A) Issued count, accepted count, public/shared count, verification/view count — per BadgeClass and over time

B) A + share-channel breakdown (which channel a share URL was built for) + top badges

C) Minimal — issued & accepted counts only

X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## E. Non-Functional

## Question 10
Scale expectation for badges (drives indexing/pagination design)?

A) Small — up to ~10k assertions per tenant

B) Medium — up to ~1M assertions per tenant

C) Large — 10M+ (needs careful indexing/partitioning)

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 11
Open Badges compliance strictness?

A) Pragmatic — OB 2.0-shaped JSON, verifiable via our endpoints (not formally certified)

B) Strict OB 2.0 — hosted verification, valid issuer profile at `.well-known`, third-party validator-passing

C) Strict + design 3.0/VC path (signed assertions) as a documented future increment

X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

## F. Resiliency (RESILIENCY-02) — required decision

## Question 12: RTO/RPO Goals and Disaster Recovery Strategy
What are your Recovery Time Objective (RTO) and Recovery Point Objective (RPO) goals for this feature's data (badges, assertions, wallet)?

A) RPO/RTO: Hours — Backup & Restore (lowest cost). Suitable for non-critical workloads.

B) RPO/RTO: 10s of minutes — Pilot Light ($$).

C) RPO/RTO: Minutes — Warm Standby ($$$).

D) RPO/RTO: Near real-time — Active/Active ($$$$).

E) N/A — Single-region multi-zone is acceptable; rely on existing DB backups.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 13: Regional Topology (RESILIENCY-08)
Fault-isolation topology for this feature?

A) Single-region, multi-zone (tolerates zone failure) — matches the existing deployment

B) Multi-region active-passive

C) Multi-region active-active

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 14: Incident Response (RESILIENCY-15)
How are production incidents handled?

A) Use the existing platform incident/on-call process (reference it) — no new process

B) No formal process — propose a lightweight one

X) Other (please describe after [Answer]: tag below)

[Answer]: B
