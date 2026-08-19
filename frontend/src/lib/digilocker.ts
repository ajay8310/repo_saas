/**
 * DigiLocker publication state for the issuer console.
 *
 * Mirrors the backend contract in app/routers/digilocker.py and the semantics in
 * app/services/digilocker_connector.py, so the UI enforces the same rules the
 * API would and an officer never sees an action succeed here that would be
 * rejected there:
 *
 *   - A revoked credential cannot be published (409 DOCUMENT_REVOKED). Putting
 *     an invalid document in a citizen's locker is worse than omitting it,
 *     because they would reasonably treat it as current.
 *   - An already-published credential is not re-sent (409 ALREADY_PUBLISHED).
 *   - Attempts are capped; exhausting them lands on `permanently_failed`, which
 *     a manual retry resets rather than being a dead end.
 *   - `delivery_mode` records whether a publication was real or simulated, so a
 *     sandbox push can never be mistaken for one that reached a citizen.
 *
 * Persistence is localStorage because the real endpoints need PostgreSQL. The
 * shapes match the API responses so swapping in fetch() is a local change.
 */

export type PublicationStatus =
  | 'not_published'
  | 'pending'
  | 'retrying'
  | 'success'
  | 'failed'
  | 'permanently_failed'

export type DeliveryMode = 'sandbox' | 'live'

export interface PushRecord {
  push_id: string
  credential_id: string
  status: Exclude<PublicationStatus, 'not_published'>
  doctype: string
  digilocker_uri: string | null
  delivery_mode: DeliveryMode | null
  attempt_count: number
  failure_reason: string | null
  last_attempt_at: string | null
  published_at: string | null
  created_at: string
}

/**
 * DigiLocker document types.
 *
 * DigiLocker rejects unknown doctypes, so this is a fixed list rather than a
 * free-text field — a typo here would surface as an opaque rejection at
 * publication time.
 */
export const DOCTYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'EDUCR', label: 'Education certificate' },
  { value: 'DEGRE', label: 'Degree certificate' },
  { value: 'MARKS', label: 'Marksheet' },
  { value: 'LICNS', label: 'Licence' },
  { value: 'PROPT', label: 'Property document' },
  { value: 'INSUR', label: 'Insurance document' },
  { value: 'OTHER', label: 'Other' },
]

/** Mirrors settings.digilocker_max_retries. */
export const MAX_ATTEMPTS = 5

const STORAGE_KEY = 'reposaas.demo.digilocker.v1'

/** Suggest a doctype from a schema name, so the common case needs no thought. */
export function suggestDoctype(schemaName: string): string {
  const name = schemaName.toLowerCase()
  if (name.includes('degree')) return 'DEGRE'
  if (name.includes('marksheet') || name.includes('transcript')) return 'MARKS'
  if (name.includes('licen')) return 'LICNS'
  if (name.includes('title') || name.includes('deed') || name.includes('land'))
    return 'PROPT'
  if (name.includes('insur')) return 'INSUR'
  if (name.includes('diploma') || name.includes('certificate')) return 'EDUCR'
  return 'OTHER'
}

export function loadPushes(): PushRecord[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function savePushes(records: PushRecord[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(records))
  } catch {
    // Non-fatal.
  }
}

/** Latest publication record for a credential, if any. */
export function findPush(
  records: PushRecord[],
  credentialId: string,
): PushRecord | undefined {
  return records.find(r => r.credential_id === credentialId)
}

export function statusOf(
  records: PushRecord[],
  credentialId: string,
): PublicationStatus {
  return findPush(records, credentialId)?.status ?? 'not_published'
}

export interface PublishOutcome {
  ok: boolean
  record?: PushRecord
  error?: string
}

/**
 * Simulate a publication attempt.
 *
 * Sandbox mode always succeeds and mints a synthetic URI in the same shape the
 * backend produces, so the UI can be exercised without DigiLocker credentials.
 */
export function publish(
  records: PushRecord[],
  args: {
    credentialId: string
    doctype: string
    documentStatus: 'stored' | 'revoked'
    mode?: DeliveryMode
  },
): PublishOutcome {
  const { credentialId, doctype, documentStatus, mode = 'sandbox' } = args

  if (documentStatus === 'revoked') {
    return {
      ok: false,
      error:
        'This credential is revoked and cannot be published to DigiLocker.',
    }
  }

  const existing = findPush(records, credentialId)
  if (existing?.status === 'success') {
    return {
      ok: false,
      error:
        'Already in the citizen\u2019s DigiLocker account. Re-sending would create a duplicate.',
    }
  }

  const now = new Date().toISOString()
  const record: PushRecord = {
    push_id: existing?.push_id ?? `dlp-${Math.random().toString(36).slice(2, 10)}`,
    credential_id: credentialId,
    status: 'success',
    doctype,
    digilocker_uri: `in.gov.sandbox-DEMO-${doctype}-${credentialId}`,
    delivery_mode: mode,
    attempt_count: (existing?.attempt_count ?? 0) + 1,
    failure_reason: null,
    last_attempt_at: now,
    published_at: now,
    created_at: existing?.created_at ?? now,
  }

  return { ok: true, record }
}

/** Reset an exhausted push so it can be attempted again. */
export function retry(record: PushRecord): PublishOutcome {
  if (record.status === 'success') {
    return {
      ok: false,
      error: 'This credential is already published. Nothing to retry.',
    }
  }

  const now = new Date().toISOString()
  return {
    ok: true,
    record: {
      ...record,
      status: 'success',
      digilocker_uri: `in.gov.sandbox-DEMO-${record.doctype}-${record.credential_id}`,
      // A permanently failed push restarts its count, matching the backend's
      // manual-retry path.
      attempt_count: record.status === 'permanently_failed' ? 1 : record.attempt_count + 1,
      failure_reason: null,
      last_attempt_at: now,
      published_at: now,
      delivery_mode: record.delivery_mode ?? 'sandbox',
    },
  }
}

export function upsert(records: PushRecord[], record: PushRecord): PushRecord[] {
  const index = records.findIndex(r => r.push_id === record.push_id)
  if (index === -1) return [record, ...records]
  const next = [...records]
  next[index] = record
  return next
}

export interface PublicationSummary {
  published: number
  outstanding: number
  failed: number
  notPublished: number
}

export function summarise(
  credentialIds: string[],
  records: PushRecord[],
): PublicationSummary {
  let published = 0
  let outstanding = 0
  let failed = 0
  let notPublished = 0

  credentialIds.forEach(id => {
    switch (statusOf(records, id)) {
      case 'success':
        published += 1
        break
      case 'pending':
      case 'retrying':
        outstanding += 1
        break
      case 'failed':
      case 'permanently_failed':
        failed += 1
        break
      default:
        notPublished += 1
    }
  })

  return { published, outstanding, failed, notPublished }
}
