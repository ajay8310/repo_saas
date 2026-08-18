/**
 * Client-side stand-in for the verification service.
 *
 * Tokens are persisted in localStorage so a token minted on My Documents can
 * be consumed on the public Verify page (including in another tab). This
 * mirrors the backend contract in app/services/verification_service.py:
 * single-use, time-bounded, and disclosing only consented fields.
 */

const STORE_KEY = 'reposaas.demo.verification_tokens.v1'

export interface StoredToken {
  token: string
  credential_id: string
  consented_fields: string[]
  expires_at: string
  used_at: string | null
}

export interface CredentialInfo {
  issuer_name: string
  schema_name: string
  status: 'stored' | 'revoked'
  issued_at: string
  revoked_at?: string
  /** Values used to populate disclosed fields on verification. */
  field_values: Record<string, string>
}

/** Demo credential registry — the union of what the app's pages display. */
export const DEMO_CREDENTIALS: Record<string, CredentialInfo> = {
  'cred-001': {
    issuer_name: 'State University', schema_name: 'B.Tech Degree Certificate',
    status: 'stored', issued_at: '2025-06-01',
    field_values: {
      student_name: 'John Doe', degree: 'B.Tech Computer Science',
      graduation_year: '2025', grade: 'A', institution: 'State University',
    },
  },
  'cred-002': {
    issuer_name: 'Engineering Council', schema_name: 'Professional License',
    status: 'stored', issued_at: '2025-05-28',
    field_values: { holder_name: 'Jane Smith', licence_no: 'PE-88213' },
  },
  'cred-003': {
    issuer_name: 'State University', schema_name: 'Degree Certificate',
    status: 'revoked', issued_at: '2025-04-15', revoked_at: '2025-07-15',
    field_values: { student_name: 'Bob Wilson' },
  },
  'cred-004': {
    issuer_name: 'Land Registry Office', schema_name: 'Land Title Deed',
    status: 'stored', issued_at: '2025-03-20',
    field_values: { survey_no: 'SR-4471', area_sqm: '820' },
  },
  'cred-005': {
    issuer_name: 'Engineering Council', schema_name: 'Professional License',
    status: 'stored', issued_at: '2025-02-10',
    field_values: { holder_name: 'Charlie Davis', licence_no: 'PE-90114' },
  },
  'cred-007': {
    issuer_name: 'Engineering Council',
    schema_name: 'Professional Engineering License',
    status: 'stored', issued_at: '2025-03-15',
    field_values: {
      holder_name: 'John Doe', licence_no: 'PE-77420',
      discipline: 'Civil', valid_until: '2030-03-15',
    },
  },
  'cred-012': {
    issuer_name: 'State Polytechnic', schema_name: 'Diploma in Computer Science',
    status: 'revoked', issued_at: '2024-12-20', revoked_at: '2025-05-02',
    field_values: { holder_name: 'John Doe', year: '2024' },
  },
}


function readAll(): StoredToken[] {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as StoredToken[]) : []
  } catch {
    return [] // Corrupt storage shouldn't break the page.
  }
}

function writeAll(tokens: StoredToken[]): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(tokens))
  } catch {
    // Storage full or blocked — tokens just won't survive navigation.
  }
}

/** URL-safe random token, mirroring the backend's 32 random bytes. */
function randomToken(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/** Issue a single-use verification token (Req 5.1). */
export function issueToken(
  credentialId: string,
  consentedFields: string[],
  expiryHours: number,
): StoredToken {
  const record: StoredToken = {
    token: randomToken(),
    credential_id: credentialId,
    consented_fields: [...consentedFields],
    expires_at: new Date(Date.now() + expiryHours * 3600 * 1000).toISOString(),
    used_at: null,
  }
  // Keep the store bounded so repeated demoing can't fill localStorage.
  writeAll([record, ...readAll()].slice(0, 50))
  return record
}

export type VerifyStatus =
  | 'valid'
  | 'revoked'
  | 'invalid'
  | 'expired'
  | 'used'

export interface VerificationResult {
  valid: boolean
  status: VerifyStatus
  issuer_name?: string
  schema_name?: string
  issued_at?: string
  revoked_at?: string
  /** Present only when a token disclosed specific fields. */
  fields?: Record<string, string>
  /** True when resolved via a token rather than a public credential lookup. */
  via_token: boolean
}

const NOT_FOUND: VerificationResult = {
  valid: false,
  status: 'invalid',
  via_token: false,
}


/**
 * Public credential check (Req 5.6, 5.10).
 *
 * Returns validity status only — never document fields, no auth required.
 */
export function lookupCredential(credentialId: string): VerificationResult {
  const cred = DEMO_CREDENTIALS[credentialId.trim().toLowerCase()]
  if (!cred) return NOT_FOUND

  return {
    valid: cred.status === 'stored',
    status: cred.status === 'revoked' ? 'revoked' : 'valid',
    issuer_name: cred.issuer_name,
    schema_name: cred.schema_name,
    issued_at: cred.issued_at,
    revoked_at: cred.revoked_at,
    via_token: false,
  }
}

/**
 * Consume a verification token (Req 5.2, 5.3, 5.4, 5.8).
 *
 * Single-use: the token is marked used on first successful consumption, so a
 * replay returns `used`. Invalid, expired, and used tokens never disclose
 * document data (Req 5.5).
 */
export function consumeToken(rawToken: string): VerificationResult {
  const token = rawToken.trim()
  const all = readAll()
  const record = all.find(t => t.token === token)

  if (!record) return NOT_FOUND

  if (record.used_at) {
    return { valid: false, status: 'used', via_token: true }
  }
  if (new Date(record.expires_at).getTime() < Date.now()) {
    return { valid: false, status: 'expired', via_token: true }
  }

  const cred = DEMO_CREDENTIALS[record.credential_id]
  if (!cred) return NOT_FOUND

  // Mark used atomically before returning any data.
  record.used_at = new Date().toISOString()
  writeAll(all)

  // Disclose only the fields the beneficiary consented to.
  const fields: Record<string, string> = {}
  record.consented_fields.forEach(f => {
    if (cred.field_values[f] !== undefined) fields[f] = cred.field_values[f]
  })

  return {
    valid: cred.status === 'stored',
    status: cred.status === 'revoked' ? 'revoked' : 'valid',
    issuer_name: cred.issuer_name,
    schema_name: cred.schema_name,
    issued_at: cred.issued_at,
    revoked_at: cred.revoked_at,
    fields: record.consented_fields.length ? fields : undefined,
    via_token: true,
  }
}

/** Heuristic: credential IDs look like `cred-001`; anything else is a token. */
export function looksLikeCredentialId(input: string): boolean {
  return /^cred-[0-9a-z-]+$/i.test(input.trim())
}

/** Resolve either a credential ID or a token. */
export function verifyInput(input: string): VerificationResult {
  const trimmed = input.trim()
  if (!trimmed) return NOT_FOUND
  return looksLikeCredentialId(trimmed)
    ? lookupCredential(trimmed)
    : consumeToken(trimmed)
}
