# Functional Design Plan — All Units (U1, U2, U3)

Per Q2=B (design all units first), this single plan covers Functional Design for U1 Badge Core,
U2 Wallet, and U3 Public & Analytics. Detailed business logic, domain entities, business rules, and
frontend components — technology-agnostic. PBT-01 (property identification) is included because the
Property-Based Testing extension is enabled.

Please answer the questions, then tell me you're done. I'll resolve ambiguities, then (on approval)
generate the functional-design artifacts per unit.

## Methodology / Execution Checklist (run after approval)
- [ ] U1: business-logic-model.md, business-rules.md, domain-entities.md, frontend-components.md
- [ ] U2: business-logic-model.md, business-rules.md, domain-entities.md, frontend-components.md
- [ ] U3: business-logic-model.md, business-rules.md, domain-entities.md, frontend-components.md
- [ ] Each unit: "Testable Properties" section (PBT-01) identifying property categories
- [ ] Validate against requirements FR-1..FR-7 and stories S1-S15

## Known design inputs (already decided — for reference, not re-asked)
- Hybrid: each assertion also creates a linked `documents` row. Private-by-default public exposure.
  Auto-accept to wallet. OB 2.0 strict; baking deferred. Async analytics via events → daily rollup.
  Fine-grained services. Dedicated public router. Scale 10M+. DR=Backup&Restore, single-region MZ.

---

## Questions

## Question 1  (U1 — assertion identity / hosted URL)
How should a hosted assertion be addressed in its public URL?

A) By BadgeAssertion UUID (e.g., /obadges/assertions/{assertion_id})

B) By the linked credential_id (documents.id) — single ID shared with the document

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 2  (U1 — expiry semantics)
When a BadgeClass has a validity period, how is assertion expiry computed?

A) expires_at = issued_at + validity period (fixed at issue time)

B) No expiry unless the BadgeClass sets one; open-ended otherwise

C) Both supported: class may define a fixed period OR be non-expiring

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 3  (U1 — revocation visibility)
On revocation, what does the hosted assertion return?

A) HTTP 200 with `revoked: true` + revocation reason in the OB verification object (OB-compliant)

B) HTTP 410 Gone

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4  (U2 — delete-from-wallet semantics)
"Delete from wallet" (S8) should:

A) Soft-hide only (assertion remains valid & verifiable; just removed from earner's default view)

B) Also force public=false (delisting from any public surface) but keep it verifiable

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 5  (U3 — directory earner identity)
How should a public earner be represented in the directory/profile (privacy)?

A) Show a derived display name only (e.g., masked email or a public handle), never raw email

B) Show raw beneficiary_id (email) — simplest, less private

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6  (U3 — analytics freshness)
Acceptable analytics latency (async aggregation)?

A) Near-real-time-ish: aggregate every 1-5 minutes

B) Periodic: aggregate every 15-60 minutes

C) Daily rollup is enough

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 7  (cross-unit — error handling for public endpoints)
For public endpoints hitting a non-public/nonexistent/revoked resource, prefer:

A) Uniform 404 for non-public or nonexistent (don't reveal existence); revoked shows revoked state on the verify endpoint only

B) Distinct codes (403 for exists-but-private, 404 for nonexistent)

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A
