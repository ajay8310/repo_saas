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

/** Trigger a browser download of `data` as a JSON file. */
export function downloadAsJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}


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
