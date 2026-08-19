/**
 * Content for the public landing page.
 *
 * Kept out of the JSX so copy can be reviewed and edited without touching
 * layout — which matters here because several claims are compliance-adjacent
 * and need sign-off rather than casual rewording.
 *
 * A deliberate constraint on the wording throughout: the platform provides
 * capabilities that *support* GIGW and DPDP obligations. It is never described
 * as "compliant" or "certified", because both require organisational process
 * and third-party audit that no amount of code can deliver.
 */

import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  BellRing,
  Boxes,
  Building2,
  Database,
  Fingerprint,
  Gauge,
  KeyRound,
  Layers,
  Link2,
  Lock,
  QrCode,
  RefreshCw,
  Scale,
  ScrollText,
  Search,
  Share2,
  ShieldCheck,
  Smartphone,
  Trash2,
  Upload,
  UserCheck,
  Webhook,
} from 'lucide-react'

export interface Feature {
  icon: LucideIcon
  title: string
  body: string
  /** Short technical detail — the thing an evaluator actually wants to know. */
  detail?: string
}

export interface FeatureGroup {
  id: string
  eyebrow: string
  heading: string
  intro: string
  features: Feature[]
}

export const HERO_STATS: { value: string; label: string }[] = [
  { value: 'AES-256-GCM', label: 'Envelope encryption per document' },
  { value: 'RFC 6962', label: 'Merkle inclusion proofs' },
  { value: 'Row-level', label: 'PostgreSQL tenant isolation' },
  { value: '10,000', label: 'Credentials per bulk job' },
]

export const FEATURE_GROUPS: FeatureGroup[] = [
  {
    id: 'issuance',
    eyebrow: 'Issue',
    heading: 'Credentials from schema to signed artefact',
    intro:
      'Define a document type once, then issue against it one record at a time or ten thousand in a batch. Every credential is scanned, encrypted, and rendered into something a citizen can actually use.',
    features: [
      {
        icon: Layers,
        title: 'Versioned schemas',
        body:
          'Six field types with required flags and enumerated values. Editing a schema that already has issued documents is checked for breaking changes before it is allowed.',
        detail:
          'Field removal, type narrowing, and new required fields are refused with a 409 rather than silently invalidating history.',
      },
      {
        icon: Upload,
        title: 'Single and bulk issuance',
        body:
          'Issue interactively or submit a batch of up to 10,000 records. Each record is processed independently, so one bad row never fails the rest.',
        detail:
          'Batches run on a worker and report progress, success and failure counts, and per-row errors.',
      },
      {
        icon: ShieldCheck,
        title: 'Malware scanning that cannot be skipped',
        body:
          'Every uploaded file is scanned before it is stored. If the scanner is unreachable the upload is rejected.',
        detail:
          'Fails closed by design — an unscanned file is treated as an unsafe file.',
      },
      {
        icon: QrCode,
        title: 'Signed PDF, JSON-LD, and QR',
        body:
          'Download a credential as a signed PDF with an embedded verification QR code, as JSON-LD for machine consumption, or as raw bytes.',
        detail:
          'Carries an RS256 detached proof over the credential payload. Not a PAdES embedded-certificate signature.',
      },
      {
        icon: RefreshCw,
        title: 'Revocation, single or in bulk',
        body:
          'Revoke with a recorded reason. Revocation is immediate and reflected in every verification path from that moment on.',
      },
      {
        icon: Search,
        title: 'Search and filtering',
        body:
          'Filter by schema, status, and issue-date range, sort on any permitted column, and page through results.',
        detail:
          'Sortable columns are allow-listed so encryption material can never be used as an ordering key.',
      },
    ],
  },
  {
    id: 'verify',
    eyebrow: 'Verify',
    heading: 'Consent-scoped verification, no account required',
    intro:
      'A verifier should learn exactly what the holder chose to share and nothing more. Sharing is a deliberate act with an expiry, not a permanent link.',
    features: [
      {
        icon: Share2,
        title: 'Selective disclosure',
        body:
          'The holder picks which fields a verifier may see when they create a share link. Everything unselected stays invisible.',
        detail:
          'The consented field list is bound to the token, not to the account, so it cannot widen after the fact.',
      },
      {
        icon: KeyRound,
        title: 'Single-use, expiring tokens',
        body:
          'Share links live from one hour to seven days and are consumed on first use. Only a SHA-256 hash of the token is ever stored.',
      },
      {
        icon: Fingerprint,
        title: 'Public status check',
        body:
          'Anyone holding a credential ID can confirm whether it is valid or revoked, with no fields disclosed and no login.',
        detail:
          'An invalid or expired token never leaks document data — it returns status only.',
      },
    ],
  },
]

FEATURE_GROUPS.push(
  {
    id: 'trust',
    eyebrow: 'Prove',
    heading: 'Tamper evidence that outlives the platform',
    intro:
      'Credential digests are batched under a Merkle root and published to a ledger. A relying party can then verify a credential using only the proof bundle they were handed — without trusting this platform, or even reaching it.',
    features: [
      {
        icon: Boxes,
        title: 'Merkle batching',
        body:
          'Thousands of credentials are committed under one root, so anchoring costs one ledger write per batch instead of one per credential.',
        detail:
          'RFC 6962 construction with domain-separated leaf and node hashing, so an internal node can never be replayed as a leaf.',
      },
      {
        icon: Link2,
        title: 'Pluggable ledger',
        body:
          'Ships with an append-only hash-chained transparency log that needs no external dependency. Swap in an EVM chain when you want third-party non-repudiation.',
        detail:
          'Signing keys stay outside the application process — transactions are delegated to a configured signer service.',
      },
      {
        icon: Lock,
        title: 'Nothing personal on the ledger',
        body:
          'Anchors commit to a salted, tenant-scoped hash — never a name, an identifier, or a document. What goes on a ledger is permanent, so it must not be personal data.',
        detail:
          'This is what keeps anchoring compatible with an erasure request rather than in conflict with it.',
      },
      {
        icon: ScrollText,
        title: 'Immutable audit trail',
        body:
          'Every read, issue, revoke, and disclosure is recorded. Audit rows cannot be edited or deleted, enforced by the database itself.',
        detail:
          'A trigger rejects UPDATE and DELETE outright; expiry happens by dropping whole monthly partitions.',
      },
    ],
  },
  {
    id: 'privacy',
    eyebrow: 'Protect',
    heading: 'Built for the DPDP Act, not retrofitted',
    intro:
      'Consent is recorded with a purpose and a legal basis, personal data is encrypted at field level, and data principals have working endpoints for the rights the Act gives them.',
    features: [
      {
        icon: UserCheck,
        title: 'Consent with purpose and legal basis',
        body:
          'Each grant records what it covers, why, and which notice version the person was shown. Withdrawal writes a new record rather than erasing the old one.',
        detail:
          'Append-only history, so "was this disclosure authorised when it happened?" stays answerable years later.',
      },
      {
        icon: Database,
        title: 'Field-level data vault',
        body:
          'Personal data is sealed with AES-256-GCM under per-tenant derived keys, with the tenant bound as authenticated data so a value cannot be moved between tenants.',
        detail:
          'A keyed blind index keeps encrypted identifiers searchable without decrypting the table.',
      },
      {
        icon: Trash2,
        title: 'Erasure with honest limits',
        body:
          'Data principals can request access, correction, or erasure — and see in advance exactly what will and will not be removed, and why.',
        detail:
          'Statutory retention and immutable audit are stated up front instead of producing a silent partial erasure.',
      },
      {
        icon: Scale,
        title: 'Retention that actually runs',
        body:
          'Each tenant sets a retention period in years. A scheduled job purges expired documents and drops aged audit partitions.',
      },
    ],
  },
)

FEATURE_GROUPS.push(
  {
    id: 'platform',
    eyebrow: 'Operate',
    heading: 'Multi-tenant from the database up',
    intro:
      'Isolation is enforced by PostgreSQL row-level security, not by remembering to add a WHERE clause. Each tenant gets its own keys, quotas, and rate limits.',
    features: [
      {
        icon: Building2,
        title: 'Tenant lifecycle',
        body:
          'Tenants move through pending, active, suspended, and deactivated. Suspension blocks every request; deactivation blocks writes but still allows reads.',
        detail:
          'Namespace and domain are unique across all lifecycle states, so a deactivated tenant cannot have its identity reused.',
      },
      {
        icon: Lock,
        title: 'Row-level security',
        body:
          'Every tenant-scoped table carries an isolation policy keyed on the session tenant. A query that forgets to set the tenant context returns nothing rather than another tenant\u2019s rows.',
      },
      {
        icon: Gauge,
        title: 'Quotas and rate limits',
        body:
          'Per-tenant storage quotas and hourly request limits, both overridable per tenant, with standard rate-limit headers and Retry-After on rejection.',
      },
      {
        icon: Activity,
        title: 'Anomaly detection',
        body:
          'Unusual document-retrieval volume inside a rolling window raises an alert, so bulk exfiltration looks different from normal use.',
      },
    ],
  },
  {
    id: 'integrate',
    eyebrow: 'Integrate',
    heading: 'Connect it to what you already run',
    intro:
      'A versioned REST API with an OpenAPI document, signed webhooks, and a DigiLocker connector for putting credentials where citizens already look for them.',
    features: [
      {
        icon: Smartphone,
        title: 'DigiLocker publication',
        body:
          'Issued credentials are pushed to the holder\u2019s DigiLocker account, with retry tracking per push and a sweep that picks up anything left outstanding.',
        detail:
          'Attempt counts live in the database rather than the queue, so a broker restart cannot lose them.',
      },
      {
        icon: Webhook,
        title: 'Signed webhooks',
        body:
          'Subscribe to issuance, revocation, and verification events. Each delivery carries an HMAC-SHA256 signature your endpoint can verify.',
        detail:
          'Signed with the secret you hold — so the signature is actually reproducible on your side.',
      },
      {
        icon: BellRing,
        title: 'Notification preferences',
        body:
          'Holders choose which events reach them and whether by email or SMS, and are warned when their chosen channel has no contact detail on file.',
      },
      {
        icon: KeyRound,
        title: 'Layered authentication',
        body:
          'OAuth 2.0 client credentials for systems, one-time passcodes for citizens, and TOTP multi-factor for administrators, with lockout after repeated failures.',
      },
    ],
  },
)

export const ROLES: { role: string; label: string; can: string }[] = [
  {
    role: 'super_admin',
    label: 'Platform administrator',
    can: 'Onboards and suspends tenants, sees platform-wide audit history.',
  },
  {
    role: 'tenant_admin',
    label: 'Authority administrator',
    can: 'Manages schemas, webhooks, users, and audit logs within one tenant.',
  },
  {
    role: 'issuer',
    label: 'Issuing officer',
    can: 'Issues and revokes credentials against approved schemas.',
  },
  {
    role: 'verifier',
    label: 'Relying party',
    can: 'Consumes share tokens and checks credential validity.',
  },
  {
    role: 'beneficiary',
    label: 'Citizen',
    can: 'Views their credentials, shares selected fields, manages consent and notifications.',
  },
]

export const PIPELINE: { step: string; title: string; body: string }[] = [
  {
    step: '01',
    title: 'Validate and scan',
    body: 'The payload is checked against its schema version and the file is malware scanned. Either failure stops the issuance.',
  },
  {
    step: '02',
    title: 'Encrypt and store',
    body: 'A fresh data key encrypts the document, the key is wrapped by the tenant\u2019s master key, and only ciphertext reaches object storage.',
  },
  {
    step: '03',
    title: 'Record and commit',
    body: 'Metadata, an immutable audit entry, and the anchoring commitment are written in the same transaction as the credential.',
  },
  {
    step: '04',
    title: 'Notify and publish',
    body: 'The holder is notified, subscribed webhooks fire, and the credential is pushed to DigiLocker.',
  },
  {
    step: '05',
    title: 'Anchor',
    body: 'A scheduled batch seals the commitment under a Merkle root and publishes it to the configured ledger.',
  },
]
