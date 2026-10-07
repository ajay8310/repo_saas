# U1 Badge Core — Frontend Components

## BadgeClassesPage (tenant admin)
- **Purpose**: manage badge templates + issue badges.
- **State**: list of BadgeClasses (paginated), selected class, modals (create/edit, issue, bulk-issue).
- **Interactions**:
  - Create/Edit BadgeClass form (name, description, criteria narrative+URL, tags, alignment, validity_days, image upload).
  - Archive (deactivate) a class.
  - Toggle `directory_visible`.
  - Issue to one earner (email); Bulk issue (paste/upload roster).
  - Revoke an assertion (reason 1-500).
- **Form validation**: name required; validity_days ≥ 1 or blank; email format for issue; reason length on revoke.
- **API integration**:
  - `GET/POST /api/v1/badge-classes`, `PATCH/DELETE /api/v1/badge-classes/{id}`
  - `POST /api/v1/badge-classes/{id}/image`
  - `POST /api/v1/badge-classes/{id}/issue`, `/bulk-issue`
  - `POST /api/v1/assertions/{id}/revoke`
  - `PUT /api/v1/issuer-profile`

## IssuerProfile section (within admin settings or BadgeClassesPage)
- Fields: issuer_name, issuer_url, issuer_email. Saved via `PUT /api/v1/issuer-profile`.
- Note: issuance blocked until valid (BR-4) — show inline guidance.

## Component hierarchy
- `BadgeClassesPage`
  - `BadgeClassTable` (rows + actions)
  - `BadgeClassFormModal`
  - `IssueBadgeModal`
  - `BulkIssueModal`
  - `RevokeModal`
  - `IssuerProfilePanel`

## Reuse
- Existing Modal, Toast/useToast, api client, AuthContext (RBAC gating to tenant_admin/issuer).
