/** Shared document types and client-side helpers for the documents view. */

export interface DocumentRow {
  credential_id: string
  schema_name: string
  beneficiary_id: string
  status: 'stored' | 'revoked'
  issued_at: string
}

export interface BulkRecord {
  beneficiary_id: string
  [key: string]: string
}

export interface BulkOutcome {
  total: number
  succeeded: BulkRecord[]
  failed: { index: number; reason: string }[]
}

/** Schemas available to issue against (mirrors the Schemas page). */
export const SCHEMA_OPTIONS = [
  'Degree Certificate',
  'Professional License',
  'Land Title Deed',
] as const

/**
 * Seed documents for the demo.
 *
 * Shared through localStorage rather than held in one page's state: the
 * DigiLocker view has to show the same credentials as the Documents view, and a
 * credential issued in one must be publishable from the other.
 */
export const SAMPLE_DOCUMENTS: DocumentRow[] = [
  { credential_id: 'cred-001', schema_name: 'Degree Certificate', beneficiary_id: 'john.doe@email.com', status: 'stored', issued_at: '2025-06-01' },
  { credential_id: 'cred-002', schema_name: 'Professional License', beneficiary_id: 'jane.smith@email.com', status: 'stored', issued_at: '2025-05-28' },
  { credential_id: 'cred-003', schema_name: 'Degree Certificate', beneficiary_id: 'bob.wilson@email.com', status: 'revoked', issued_at: '2025-04-15' },
  { credential_id: 'cred-004', schema_name: 'Land Title Deed', beneficiary_id: 'alice.brown@email.com', status: 'stored', issued_at: '2025-03-20' },
  { credential_id: 'cred-005', schema_name: 'Professional License', beneficiary_id: 'charlie.davis@email.com', status: 'stored', issued_at: '2025-02-10' },
]

const DOCUMENTS_KEY = 'reposaas.demo.documents.v1'

/** Load the shared demo document list, seeding it on first use. */
export function loadDocuments(): DocumentRow[] {
  try {
    const raw = window.localStorage.getItem(DOCUMENTS_KEY)
    if (!raw) return [...SAMPLE_DOCUMENTS]
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) && parsed.length ? parsed : [...SAMPLE_DOCUMENTS]
  } catch {
    // Private browsing or a corrupted value shouldn't break the page.
    return [...SAMPLE_DOCUMENTS]
  }
}

export function saveDocuments(docs: DocumentRow[]): void {
  try {
    window.localStorage.setItem(DOCUMENTS_KEY, JSON.stringify(docs))
  } catch {
    // Persistence is a convenience here, not a requirement.
  }
}

/** Generate a short credential ID for locally-created rows. */
export function generateCredentialId(existing: DocumentRow[]): string {
  const max = existing.reduce((acc, d) => {
    const m = d.credential_id.match(/cred-(\d+)/)
    return m ? Math.max(acc, Number(m[1])) : acc
  }, 0)
  return `cred-${String(max + 1).padStart(3, '0')}`
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

// Download helpers live in lib/download.ts; re-exported here so existing
// document-page imports keep working.
export { downloadAsCsv, downloadAsJson } from './download'


/** Max records per bulk upload — mirrors backend Req 3.8. */
export const BULK_MAX_RECORDS = 10_000

export class BulkParseError extends Error {}

/**
 * Parse pasted/uploaded bulk content into records.
 *
 * Accepts a JSON array of objects, or CSV with a header row. Requires a
 * `beneficiary_id` column/key, matching the backend's validation (Req 3.4).
 */
export function parseBulkContent(raw: string): BulkRecord[] {
  const text = raw.trim()
  if (!text) throw new BulkParseError('Content is empty.')

  let records: BulkRecord[]

  if (text.startsWith('[')) {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      throw new BulkParseError('Invalid JSON.')
    }
    if (!Array.isArray(parsed)) {
      throw new BulkParseError('JSON must be an array of objects.')
    }
    records = parsed as BulkRecord[]
  } else {
    const lines = text.split(/\r?\n/).filter(l => l.trim())
    if (lines.length < 2) {
      throw new BulkParseError('CSV needs a header row plus at least one record.')
    }
    const headers = lines[0].split(',').map(h => h.trim())
    records = lines.slice(1).map(line => {
      const cells = line.split(',').map(c => c.trim())
      return headers.reduce((acc, h, i) => {
        acc[h] = cells[i] ?? ''
        return acc
      }, {} as BulkRecord)
    })
  }

  if (records.length > BULK_MAX_RECORDS) {
    throw new BulkParseError(
      `${records.length} records exceeds the ${BULK_MAX_RECORDS.toLocaleString()} limit.`,
    )
  }
  return records
}

/** Validate parsed records the way the backend would, without persisting. */
export function evaluateBulk(records: BulkRecord[]): BulkOutcome {
  const succeeded: BulkRecord[] = []
  const failed: { index: number; reason: string }[] = []

  records.forEach((rec, i) => {
    const id = (rec.beneficiary_id ?? '').trim()
    if (!id) {
      failed.push({ index: i, reason: 'beneficiary_id is missing or empty' })
      return
    }
    if (!id.includes('@')) {
      failed.push({ index: i, reason: `invalid beneficiary_id: "${id}"` })
      return
    }
    succeeded.push({ ...rec, beneficiary_id: id })
  })

  return { total: records.length, succeeded, failed }
}
