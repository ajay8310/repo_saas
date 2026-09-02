# Story Generation Plan — Credly-Style Credentialing

Product-owner plan for converting `requirements.md` (FR-1..FR-7) into user stories + personas.
Please answer the questions at the bottom (fill `[Answer]:` tags), then tell me you're done. I'll
resolve any ambiguities, get your approval of this plan, then generate the stories.

## Methodology / Execution Checklist (to run after approval)
- [x] Define personas in `personas.md`: Tenant Admin, Issuer, Earner (Beneficiary), Verifier (+ Super Admin note).
- [x] Draft user stories in `stories.md` using INVEST + "As a / I want / so that" format.
- [x] Organize stories using the approach selected in Q1 below (persona-based).
- [x] Write acceptance criteria per story (Given/When/Then + edge bullets), traceable to FR IDs.
- [x] Map each persona to its stories.
- [x] Tag stories that carry PBT-relevant invariants (privacy-by-default, revocation, OB round-trip) for the testing extension.
- [x] Cross-check every FR-1..FR-7 requirement is covered by at least one story.

## Mandatory Artifacts
- [x] `aidlc-docs/inception/user-stories/personas.md`
- [x] `aidlc-docs/inception/user-stories/stories.md`

## Candidate Story Map (for reference; finalized after approval)
- **Tenant Admin**: create/edit BadgeClass, upload badge image, set issuer profile, view analytics, manage directory visibility.
- **Issuer**: issue badge (single/bulk), revoke badge.
- **Earner**: OTP login, view wallet, hide/delete badge, opt a badge public, share (LinkedIn/OG), view public profile.
- **Verifier / Public**: fetch hosted assertion, verify validity, browse public directory, view public badge page.

---

## Planning Questions

## Question 1
Preferred story breakdown/organization?

A) Persona-based (group stories by Tenant Admin / Issuer / Earner / Verifier)

B) Feature-based (group by Badges / Wallet / Sharing / Directory / Analytics)

C) User-journey-based (issue → accept → publish → share → verify)

D) Hybrid — persona-grouped, with an epic per feature area

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
Story granularity?

A) Coarse — one story per capability (~12-16 stories total)

B) Medium — split by meaningful variations (~20-30 stories)

C) Fine — every distinct action a separate story (30+)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
Acceptance-criteria format?

A) Given/When/Then (Gherkin-style)

B) Bulleted checklist of conditions

C) Given/When/Then for core paths + bullets for edge cases

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 4
Should stories include priority (MoSCoW) to guide construction order?

A) Yes — tag each story Must/Should/Could

B) No — treat all in-scope stories as equal for now

X) Other (please describe after [Answer]: tag below)

[Answer]: B
