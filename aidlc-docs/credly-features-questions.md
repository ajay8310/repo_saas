# Credly-Style Features — Scope Questions

You asked to add the additional features Credly (by Pearson) has. That is a large set of distinct
subsystems. To build the right things well (rather than a broad, half-working sprawl), please pick
the scope. Fill in the [Answer]: tags and tell me you're done.

## Question 1
Which features do you want? (Choose one bundle; you can run this again later for more.)

A) Core credentialing standard — **Open Badges** issuing (badge classes, hosted assertions, issuer profile, standards-compliant verification). Highest-value, self-contained, no external accounts needed.

B) Recipient experience — **recipient wallet** (earner accounts, "my badges", accept/decline) + **social sharing** metadata (Open Graph, LinkedIn "Add to Profile" URL builder).

C) Discovery & insights — **public badge directory** + **analytics dashboard** (issuance/acceptance/share metrics).

D) A + B (standard issuing plus recipient wallet & sharing) — the most cohesive "Credly-like" MVP.

E) Everything feasible without external third-party accounts (A + B + C), as an incremental build.

X) Other (please describe after [Answer]: tag below)

[Answer]: E

## Question 2
Open Badges version target (if A/D/E chosen)?

A) Open Badges 2.0 (JSON, widely supported, simpler)

B) Open Badges 3.0 / W3C Verifiable Credentials (modern, needs issuer signing keys/DIDs)

C) Both / not sure — recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: C

## Question 3
How should we run this build?

A) Through the **AI-DLC workflow** (Requirements Analysis → Design → Units → per-unit Construction with your extension settings: Security off, Resiliency on, PBT on). Structured, checkpointed.

B) Direct implementation — skip the formal AI-DLC stages and just build it, with a brief plan first.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4
Scope of change — acceptable to add new DB tables + migrations, new models, services, routers, and
frontend pages?

A) Yes — add whatever is needed (new Alembic migration, models, services, routers, UI)

B) Backend only for now (no frontend changes)

C) Keep it minimal — new tables only if unavoidable

X) Other (please describe after [Answer]: tag below)

[Answer]: A
