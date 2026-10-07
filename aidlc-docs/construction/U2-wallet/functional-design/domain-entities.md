# U2 Wallet — Domain Entities

U2 introduces **no new tables**. It operates on `badge_assertions` (from U1) via the earner-facing
flags: `accepted`, `hidden`, `public`.

## WalletItem (view/DTO, not persisted)
| Field | Source |
|---|---|
| assertion_id (=credential_id) | badge_assertions.id |
| badge_class (name, image, description) | join badge_classes |
| issued_at, expires_at, status | badge_assertions |
| public | badge_assertions.public |
| hidden | badge_assertions.hidden |
| assertion_url, public_page_url | derived |

## Testable Properties (PBT-01)
- [PBT-03] Wallet list excludes `hidden=true` by default; includes them only when `include_hidden`.
- [PBT-03] Private-by-default: setting/unsetting `public` is the ONLY way `public` changes; issuance
  never sets public=true.
- [PBT-03] `delete_from_wallet` forces `public=false` (Q4=B) while assertion remains verifiable.
- [PBT-07] generator: assertions with random accepted/hidden/public combinations for the earner.
