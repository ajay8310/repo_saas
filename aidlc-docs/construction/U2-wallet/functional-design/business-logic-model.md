# U2 Wallet — Business Logic Model

Earner identity = existing `beneficiary_id` via OTP login (reuse auth). All operations scoped to the
authenticated earner's own assertions (and tenant RLS).

## list_wallet(beneficiary_id, include_hidden=False)
- Return the earner's assertions joined to badge_class summary; exclude hidden unless include_hidden.
- Only the earner's own assertions (identity match + RLS). Never other earners' badges.

## hide(assertion_id) / unhide
- Set `hidden=true/false`. Hiding removes from default wallet view; does NOT change validity or public.

## delete_from_wallet(assertion_id)  (Q4=B)
- Soft operation: set `hidden=true` AND `public=false` (delist from public surfaces), but the
  assertion remains valid and verifiable via its hosted URL. Record "unpublished" if it was public.

## set_public(assertion_id, public: bool)
- Flip `public`. On true → record "published" event. On false → delist.
- Enforces private-by-default: this is the only path that sets public=true.

## Events
- publish → BadgeEventService.record("published", ...); unpublish handled implicitly (no event or a
  "published" with value semantics — kept simple: only record on transition to public=true).

## Error handling
- Assertion not owned by earner → 404 (uniform, don't reveal existence). Revoked assertion can still
  be hidden but cannot be made public (guard) → 409.

## Testable Properties (PBT-01)
- [PBT-03] hidden excluded by default; delete forces public=false; private-by-default holds.
- [PBT-11] example tests: hide→list, publish→public page reachable, delete→public page 404 but verify still works.
