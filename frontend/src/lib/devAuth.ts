/**
 * Development-only auth helper.
 *
 * Mints an unsigned, client-side-only JWT-shaped token so the UI can be
 * browsed without a running backend. The payload is what AuthContext reads
 * (sub / tenant_id / roles / exp).
 *
 * This is NOT a real credential: it is never sent to or accepted by the API.
 * All call sites are gated behind `import.meta.env.DEV`, so this code is
 * tree-shaken out of production builds.
 */

export type DemoRole =
  | 'super_admin'
  | 'tenant_admin'
  | 'issuer'
  | 'beneficiary'
  | 'verifier'

const DEMO_SUBJECTS: Record<DemoRole, string> = {
  super_admin: 'platform.admin@reposaas.io',
  tenant_admin: 'admin@edu.gov.in',
  issuer: 'registrar@edu.gov.in',
  beneficiary: 'john.doe@email.com',
  verifier: 'hr@employer.com',
}

/** Build a fake token for the given role. Dev preview only. */
export function mintDemoToken(role: DemoRole): string {
  const header = { alg: 'none', typ: 'JWT' }
  const payload = {
    sub: DEMO_SUBJECTS[role],
    tenant_id: '00000000-0000-0000-0000-000000000001',
    roles: [role],
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 60 * 60 * 8,
  }

  const encode = (obj: unknown) => btoa(JSON.stringify(obj))
  return `${encode(header)}.${encode(payload)}.demo-not-a-real-signature`
}

export const DEMO_ROLES: DemoRole[] = [
  'super_admin',
  'tenant_admin',
  'issuer',
  'beneficiary',
]
