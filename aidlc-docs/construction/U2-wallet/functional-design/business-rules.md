# U2 Wallet — Business Rules

- BR-W1: An earner may only view/modify their own assertions (identity match + tenant RLS).
- BR-W2: Wallet default view excludes `hidden=true`; `include_hidden` shows them.
- BR-W3: Private-by-default — issuance sets `public=false`; only `set_public(true)` makes it public.
- BR-W4: `delete_from_wallet` sets `hidden=true` and `public=false`; the assertion stays valid and
  verifiable via its hosted URL (Q4=B). It is a soft, reversible-by-re-publish operation.
- BR-W5: A revoked assertion cannot be made public (guard → 409); it may still be hidden.
- BR-W6: Making an assertion public records a "published" event (analytics).
- BR-W7: Accessing an assertion not owned by the earner returns 404 (uniform; no existence leak).
