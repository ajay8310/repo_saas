# U2 Wallet — Frontend Components

## WalletPage (earner)
- **Purpose**: earner views and manages their badges.
- **Auth**: OTP login (reuse); earner identity from token.
- **State**: list of WalletItems, toggle "show hidden", per-item busy state.
- **Interactions**:
  - View badges (card grid: image, name, issued/expiry, status, public indicator).
  - Toggle a badge **public/private** (calls set_public).
  - **Hide** / **Delete from wallet** (delete also delists public — with confirm).
  - **Share** entry point per public badge (links into U3 sharing: copy public URL, LinkedIn, social).
  - Link to the public badge page / earner profile.
- **Validation/UX**: cannot make a revoked badge public (disabled + tooltip); confirm on delete.
- **API integration**:
  - `GET /api/v1/wallet?include_hidden=`
  - `POST /api/v1/wallet/{assertion_id}/public` (body: {public})
  - `POST /api/v1/wallet/{assertion_id}/hide`
  - `DELETE /api/v1/wallet/{assertion_id}`
  - (U3) share URL builder + LinkedIn deep link

## Component hierarchy
- `WalletPage`
  - `WalletBadgeCard` (per badge: status, public toggle, hide/delete, share)
  - `ShareMenu` (public URL / LinkedIn / social — implemented with U3)
  - `ConfirmDialog`

## Reuse
- Modal, Toast, api client, AuthContext (earner/beneficiary role).
