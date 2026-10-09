/** Badge (Credly-style) types and API client helpers. Mirrors app/routers/badges.py. */

import axios from 'axios'

import api from './api'

export interface BadgeClass {
  id: string
  name: string
  description: string | null
  criteria_narrative: string | null
  criteria_url: string | null
  tags: string[]
  alignment: Record<string, string>[]
  image_s3_key: string | null
  validity_days: number | null
  status: 'active' | 'inactive'
  directory_visible: boolean
  certificate_template: CertificateTemplate
  custom_template_id?: string | null
  created_at: string | null
}

export interface Assertion {
  assertion_id: string
  badge_class_id: string
  beneficiary_id: string
  status: 'active' | 'revoked' | 'expired'
  issued_at: string | null
  expires_at: string | null
  public: boolean
  revoked_at: string | null
  revocation_reason: string | null
  has_photo?: boolean
}

export interface IssuerProfile {
  issuer_name: string | null
  issuer_url: string | null
  issuer_email: string | null
}

export interface BadgeClassInput {
  name: string
  description?: string | null
  criteria_narrative?: string | null
  criteria_url?: string | null
  tags?: string[]
  alignment?: Record<string, string>[]
  validity_days?: number | null
}

/** Max recipients per bulk issue — mirrors backend bulk_upload_max_records. */
export const BULK_ISSUE_MAX = 10_000

// --- Badge class CRUD ---

export async function listBadgeClasses(): Promise<BadgeClass[]> {
  const { data } = await api.get<BadgeClass[]>('/badges/classes')
  return data
}

export async function createBadgeClass(input: BadgeClassInput): Promise<BadgeClass> {
  const { data } = await api.post<BadgeClass>('/badges/classes', input)
  return data
}

export async function updateBadgeClass(
  id: string,
  input: Partial<BadgeClassInput>,
): Promise<BadgeClass> {
  const { data } = await api.patch<BadgeClass>(`/badges/classes/${id}`, input)
  return data
}

export async function deactivateBadgeClass(id: string): Promise<BadgeClass> {
  const { data } = await api.post<BadgeClass>(`/badges/classes/${id}/deactivate`)
  return data
}

export async function setBadgeVisibility(id: string, visible: boolean): Promise<BadgeClass> {
  const { data } = await api.post<BadgeClass>(`/badges/classes/${id}/visibility`, { visible })
  return data
}

export async function uploadBadgeImage(
  id: string,
  contentBase64: string,
  contentType: 'image/png' | 'image/svg+xml',
): Promise<BadgeClass> {
  const { data } = await api.post<BadgeClass>(`/badges/classes/${id}/image`, {
    content_base64: contentBase64,
    content_type: contentType,
  })
  return data
}

// --- Issuance ---

export interface IssuePhoto {
  base64: string
  contentType: 'image/png' | 'image/jpeg'
}

export async function issueBadge(
  badgeClassId: string,
  beneficiaryId: string,
  photo?: IssuePhoto,
): Promise<Assertion> {
  const { data } = await api.post<Assertion>('/badges/issue', {
    badge_class_id: badgeClassId,
    beneficiary_id: beneficiaryId,
    ...(photo ? { photo_base64: photo.base64, photo_content_type: photo.contentType } : {}),
  })
  return data
}

export async function bulkIssueBadges(
  badgeClassId: string,
  beneficiaryIds: string[],
): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post('/badges/bulk-issue', {
    badge_class_id: badgeClassId,
    beneficiary_ids: beneficiaryIds,
  })
  return data
}

export interface BulkIssueZipResult {
  job_id: string
  status: string
  total: number
  with_photo: number
  errors: { row?: string; entry?: string; error: string }[]
}

interface BulkIssueZipPresign {
  upload_url: string
  zip_key: string
  max_bytes: number
}

/**
 * Bulk-issue from a ZIP of recipients + photos via a presigned S3 upload.
 *
 * Three steps: (1) ask the API for a presigned PUT URL (size-checked, <=100 MB),
 * (2) PUT the raw .zip straight to S3, (3) tell the API to process the uploaded
 * key. The ZIP holds a recipients.csv/json manifest plus photo images matched
 * per recipient; a one-row manifest + one photo is the single-upload case.
 *
 * ``onProgress`` (0..1) reports the direct-to-S3 upload progress.
 */
export async function bulkIssueZip(
  badgeClassId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<BulkIssueZipResult> {
  // 1) Presign (server enforces the max size before granting a URL).
  const { data: presign } = await api.post<BulkIssueZipPresign>(
    '/badges/bulk-issue-zip/presign',
    { badge_class_id: badgeClassId, size_bytes: file.size },
  )

  // 2) Upload the raw ZIP directly to S3 (not through the API). The headers
  //    must match what the presigned URL was signed with.
  await axios.put(presign.upload_url, file, {
    headers: {
      'Content-Type': 'application/zip',
      'x-amz-server-side-encryption': 'aws:kms',
    },
    onUploadProgress: e => {
      if (onProgress && e.total) onProgress(e.loaded / e.total)
    },
  })

  // 3) Hand the uploaded key back for parsing + issuance.
  const { data } = await api.post<BulkIssueZipResult>('/badges/bulk-issue-zip', {
    badge_class_id: badgeClassId,
    zip_key: presign.zip_key,
  })
  return data
}

export interface BulkPhotosZipResult {
  job_id: string
  status: string
  total: number
  errors: { entry?: string; beneficiary_id?: string; error: string }[]
}

/**
 * Attach a ZIP of photos to already-issued credentials (later, decoupled upload).
 *
 * Same presigned-S3 upload as the issue flow, but no badge class is required
 * (optional ``badgeClassId`` scopes the attach to one class). Each image is
 * matched to the recipient's existing credential(s) by email — filename stem
 * (``alice@example.com.png``) or an optional photos.csv/json map.
 */
export async function bulkPhotosZip(
  file: File,
  badgeClassId?: string,
  onProgress?: (fraction: number) => void,
): Promise<BulkPhotosZipResult> {
  const { data: presign } = await api.post<BulkIssueZipPresign>(
    '/badges/bulk-issue-zip/presign',
    { size_bytes: file.size },
  )
  await axios.put(presign.upload_url, file, {
    headers: {
      'Content-Type': 'application/zip',
      'x-amz-server-side-encryption': 'aws:kms',
    },
    onUploadProgress: e => {
      if (onProgress && e.total) onProgress(e.loaded / e.total)
    },
  })
  const { data } = await api.post<BulkPhotosZipResult>('/badges/bulk-photos-zip', {
    zip_key: presign.zip_key,
    ...(badgeClassId ? { badge_class_id: badgeClassId } : {}),
  })
  return data
}

export async function revokeAssertion(
  assertionId: string,
  reason: string,
): Promise<Assertion> {
  const { data } = await api.post<Assertion>(`/badges/assertions/${assertionId}/revoke`, {
    reason,
  })
  return data
}

// --- Issuer profile ---

export async function getIssuerProfile(): Promise<IssuerProfile> {
  const { data } = await api.get<IssuerProfile>('/badges/issuer-profile')
  return data
}

export async function setIssuerProfile(profile: IssuerProfile): Promise<IssuerProfile> {
  const { data } = await api.put<IssuerProfile>('/badges/issuer-profile', profile)
  return data
}

/** Public hosted-assertion URL (unauthenticated verification target). */
export function hostedAssertionUrl(assertionId: string): string {
  return `/api/v1/public/badges/assertions/${assertionId}`
}

// --- Certificates & templates (U4) ---

export const CERTIFICATE_TEMPLATES = ['classic', 'modern', 'elegant', 'minimal'] as const
export type CertificateTemplate = (typeof CERTIFICATE_TEMPLATES)[number]

export async function setCertificateTemplate(
  badgeClassId: string,
  template: CertificateTemplate,
): Promise<BadgeClass> {
  const { data } = await api.put<BadgeClass>(`/badges/classes/${badgeClassId}/template`, {
    certificate_template: template,
  })
  return data
}

export async function uploadRecipientPhoto(
  assertionId: string,
  contentBase64: string,
  contentType: 'image/png' | 'image/jpeg',
): Promise<{ status: string; photo_key: string }> {
  const { data } = await api.post(`/badges/assertions/${assertionId}/photo`, {
    content_base64: contentBase64,
    content_type: contentType,
  })
  return data
}

/** Download the issuer-signed certificate PDF (issuer/admin view). */
export async function downloadCertificate(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/badges/assertions/${assertionId}/certificate`, {
    responseType: 'blob',
  })
  return data as Blob
}

/** Trigger a browser download for a blob (PDF, PNG, JSON — any content). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** @deprecated use saveBlob — kept for existing callers. */
export const savePdfBlob = saveBlob

// --- Issued assertions (Documents list) + badge downloads (U6) ---

export interface AssertionListItem {
  assertion_id: string
  badge_class_id: string
  badge_name: string
  beneficiary_id: string
  status: 'active' | 'revoked' | 'expired'
  issued_at: string | null
  expires_at: string | null
  public: boolean
  revoked_at: string | null
  has_photo: boolean
}

/** List all issued assertions for the tenant (issuer Documents list). */
export async function listAssertions(): Promise<AssertionListItem[]> {
  const { data } = await api.get<AssertionListItem[]>('/badges/assertions')
  return data
}

/** Download the baked Open Badges PNG for an assertion (issuer view). */
export async function downloadBadgePng(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/badges/assertions/${assertionId}/badge.png`, {
    responseType: 'blob',
  })
  return data as Blob
}

/** Download the Open Badges 2.0 assertion JSON for an assertion (issuer view). */
export async function downloadBadgeJson(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/badges/assertions/${assertionId}/badge.json`, {
    responseType: 'blob',
  })
  return data as Blob
}
