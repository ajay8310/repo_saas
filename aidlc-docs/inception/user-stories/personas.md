# Personas — Credly-Style Credentialing

## P1 — Tenant Admin ("Asha, Program Manager")
- **Role**: Manages a tenant's badge program.
- **Goals**: Define BadgeClasses, set the issuer profile, upload badge art, monitor adoption via analytics, control directory visibility.
- **Characteristics**: Non-developer; comfortable with admin UI; cares about brand consistency and reporting.
- **Pain points**: Wants issuance to be reliable and standards-compliant without understanding Open Badges internals.

## P2 — Issuer ("Ravi, Certification Officer")
- **Role**: Issues and revokes badges to earners within a tenant.
- **Goals**: Issue a badge to one or many earners quickly; revoke when needed with a reason.
- **Characteristics**: Operational user; often does bulk issuance from a roster.
- **Pain points**: Needs confidence that earners are notified and that revocation is reflected in verification.

## P3 — Earner / Beneficiary ("Meera, Learner")
- **Role**: Receives badges; owns her wallet and public presence.
- **Goals**: See earned badges, decide which to make public, share to LinkedIn/social, present a public profile.
- **Characteristics**: Logs in via OTP (existing identity); privacy-conscious; motivated by shareability.
- **Pain points**: Wants control over what is public; expects previews to render nicely when shared.

## P4 — Verifier / Public ("Sam, Recruiter")
- **Role**: Third party verifying a badge, or a member of the public browsing the directory.
- **Goals**: Confirm a badge is valid (not revoked/expired); discover badges/earners in the directory.
- **Characteristics**: Unauthenticated; arrives via a share link or QR; needs a trustworthy yes/no.
- **Pain points**: Must not see anything the earner hasn't opted to make public.

## Note — Super Admin
The platform Super Admin persona (from the existing system) governs tenants but has no
badge-feature-specific stories in this increment; badge governance is delegated to Tenant Admin.

## Persona → Story Map
- **P1 Tenant Admin**: S1, S2, S3, S9, S12
- **P2 Issuer**: S4, S5, S6
- **P3 Earner**: S7, S8, S10, S11
- **P4 Verifier/Public**: S13, S14, S15
