# Story → Unit Map — Credly-Style Credentialing

Merged decomposition (Q1=B): 3 units. All 15 stories assigned; every story maps to exactly one unit.

## U1 — Badge Core
| Story | Title | Notes |
|---|---|---|
| S1 | Create/edit BadgeClass | BadgeService |
| S2 | Upload badge image | BadgeService + S3 + malware scan |
| S3 | Set issuer profile | tenant issuer profile → OB issuer JSON |
| S4 | Issue a badge | IssuanceService + linked documents row + OB assertion |
| S5 | Bulk issue a badge | IssuanceService.bulk + `bulk_issue_badges` (Q4=A: stays in U1) |
| S6 | Revoke a badge | IssuanceService.revoke; public verify reflects revoked |
| S13 | Fetch & verify hosted assertion | OpenBadgesSerializer + public verify subset |

## U2 — Wallet
| Story | Title | Notes |
|---|---|---|
| S7 | View my wallet | WalletService.list (exclude hidden) |
| S8 | Hide/delete from wallet | WalletService.hide/delete |
| S10 | Make a badge public | WalletService.set_public — private-by-default enforced; emits "published" |

## U3 — Public & Analytics (Sharing + Directory + Analytics)
| Story | Title | Notes |
|---|---|---|
| S11 | Share a badge | SharingService: OG meta, LinkedIn deep-link, earner profile, channel-tagged URL |
| S15 | View public badge / earner page | SharingService public views |
| S14 | Browse public directory | DirectoryService catalog + privacy-gated earners |
| S12 | Manage directory visibility | DirectoryService + BadgeClass directory-visible flag (admin action; lives with directory logic) |
| S9 | View analytics dashboard | badge_events + aggregate task + AnalyticsService + dashboard |

## Coverage Check
- U1: S1, S2, S3, S4, S5, S6, S13 (7)
- U2: S7, S8, S10 (3)
- U3: S9, S11, S12, S14, S15 (5)
- Total 15/15 stories assigned. ✔ No story unassigned; no story in two units.

## Requirement traceability (unchanged)
- FR-1/FR-2/FR-7 → U1; FR-3 → U2; FR-4/FR-5/FR-6 → U3.
