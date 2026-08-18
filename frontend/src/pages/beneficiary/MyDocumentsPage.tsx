import { useState } from 'react'
import { FileText, Download, Share2, QrCode, Copy, Clock } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import { downloadAsJson } from '@/lib/download'

interface MyDocument {
  credential_id: string
  schema_name: string
  issuer_name: string
  status: 'stored' | 'revoked'
  issued_at: string
  /** Fields the beneficiary may choose to disclose. */
  available_fields: string[]
}

interface TokenResult {
  token: string
  expires_at: string
  consented_fields: string[]
}

const INITIAL_DOCS: MyDocument[] = [
  {
    credential_id: 'cred-001', schema_name: 'B.Tech Degree Certificate',
    issuer_name: 'State University', status: 'stored', issued_at: '2025-06-01',
    available_fields: ['student_name', 'degree', 'graduation_year', 'grade', 'institution'],
  },
  {
    credential_id: 'cred-007', schema_name: 'Professional Engineering License',
    issuer_name: 'Engineering Council', status: 'stored', issued_at: '2025-03-15',
    available_fields: ['holder_name', 'licence_no', 'discipline', 'valid_until'],
  },
  {
    credential_id: 'cred-012', schema_name: 'Diploma in Computer Science',
    issuer_name: 'State Polytechnic', status: 'revoked', issued_at: '2024-12-20',
    available_fields: ['holder_name', 'year'],
  },
]

/** Expiry choices — backend bounds this to 1..168 hours (Req 5.1). */
const EXPIRY_OPTIONS = [
  { hours: 24, label: '24 hours' },
  { hours: 48, label: '48 hours' },
  { hours: 72, label: '72 hours (default)' },
  { hours: 168, label: '7 days (max)' },
]

/** URL-safe random token, mirroring the backend's 32-byte token. */
function generateToken(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

export default function MyDocumentsPage() {
  const [docs] = useState<MyDocument[]>(INITIAL_DOCS)
  const [openShare, setOpenShare] = useState<string | null>(null)
  const [expiry, setExpiry] = useState(72)
  const [consented, setConsented] = useState<string[]>([])
  const [result, setResult] = useState<TokenResult | null>(null)
  const { toast, notify } = useToast()

  const openSharePanel = (doc: MyDocument) => {
    if (openShare === doc.credential_id) {
      setOpenShare(null)
      return
    }
    // Reset the form each time a different document is opened.
    setOpenShare(doc.credential_id)
    setExpiry(72)
    setConsented([])
    setResult(null)
  }

  const toggleField = (field: string) =>
    setConsented(prev =>
      prev.includes(field) ? prev.filter(f => f !== field) : [...prev, field],
    )

  const handleDownload = (doc: MyDocument) => {
    downloadAsJson(`${doc.credential_id}.json`, {
      credential_id: doc.credential_id,
      schema: doc.schema_name,
      issuer: doc.issuer_name,
      status: doc.status,
      issued_at: doc.issued_at,
      verification_url: `${window.location.origin}/verify/${doc.credential_id}`,
      note: 'Demo export. Signed PDF/JSON-LD with QR requires the backend.',
    })
    notify(`Downloaded ${doc.credential_id}.json`)
  }

  const handleGenerateToken = (doc: MyDocument) => {
    if (doc.status !== 'stored') {
      notify('Revoked documents cannot be shared.', 'error')
      return
    }
    const token = generateToken()
    const expiresAt = new Date(Date.now() + expiry * 3600 * 1000)
    setResult({
      token,
      expires_at: expiresAt.toISOString(),
      consented_fields: [...consented],
    })
    notify(
      consented.length
        ? `Token created disclosing ${consented.length} field(s).`
        : 'Token created — validity status only, no fields disclosed.',
    )
  }

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      notify(`${label} copied to clipboard.`)
    } catch {
      notify('Clipboard blocked by the browser.', 'error')
    }
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">My Documents</h1>
        <p className="text-gray-500 mt-1">
          View, download, and share your credentials
        </p>
      </div>

      <div className="space-y-4">
        {docs.map(doc => (
          <div
            key={doc.credential_id}
            className="bg-white rounded-xl border border-gray-200 p-6"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div
                  className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                    doc.status === 'stored' ? 'bg-blue-100' : 'bg-red-100'
                  }`}
                >
                  <FileText
                    size={22}
                    className={
                      doc.status === 'stored' ? 'text-blue-600' : 'text-red-600'
                    }
                  />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{doc.schema_name}</h3>
                  <p className="text-sm text-gray-500">
                    Issued by {doc.issuer_name} on {doc.issued_at}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">
                      {doc.credential_id}
                    </code>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        doc.status === 'stored'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {doc.status === 'stored' ? 'Valid' : 'Revoked'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleDownload(doc)}
                  className="flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  <Download size={15} />
                  Download
                </button>
                {doc.status === 'stored' && (
                  <button
                    onClick={() => openSharePanel(doc)}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700"
                  >
                    <Share2 size={15} />
                    Share
                  </button>
                )}
              </div>
            </div>

            {openShare === doc.credential_id && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <h4 className="text-sm font-medium text-gray-700 mb-3">
                  Generate Verification Token
                </h4>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div>
                    <label
                      htmlFor={`exp-${doc.credential_id}`}
                      className="text-xs text-gray-500"
                    >
                      Expires after
                    </label>
                    <select
                      id={`exp-${doc.credential_id}`}
                      value={expiry}
                      onChange={e => setExpiry(Number(e.target.value))}
                      className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
                    >
                      {EXPIRY_OPTIONS.map(o => (
                        <option key={o.hours} value={o.hours}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-gray-400 mt-1.5">
                      Single-use. The link stops working once opened.
                    </p>
                  </div>

                  <div>
                    <span className="text-xs text-gray-500">Fields to disclose</span>
                    <div className="mt-1.5 space-y-1.5">
                      {doc.available_fields.map(f => (
                        <label
                          key={f}
                          className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={consented.includes(f)}
                            onChange={() => toggleField(f)}
                            className="rounded border-gray-300"
                          />
                          <code className="text-xs">{f}</code>
                        </label>
                      ))}
                    </div>
                    <p className="text-xs text-gray-400 mt-1.5">
                      Leave all unchecked to share validity only.
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => handleGenerateToken(doc)}
                  className="mt-4 flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 text-sm"
                >
                  <QrCode size={16} />
                  Generate Token
                </button>

                {result && (
                  <div className="mt-4 bg-green-50 border border-green-200 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Clock size={14} className="text-green-700" />
                      <span className="text-xs font-semibold text-green-800">
                        Token created — expires{' '}
                        {new Date(result.expires_at).toLocaleString()}
                      </span>
                    </div>

                    <div className="space-y-2">
                      <div>
                        <span className="text-xs text-gray-500">Token</span>
                        <div className="flex gap-2 mt-1">
                          <code className="flex-1 bg-white border border-green-200 rounded px-2 py-1.5 text-xs break-all">
                            {result.token}
                          </code>
                          <button
                            onClick={() => copy(result.token, 'Token')}
                            title="Copy token"
                            className="px-2 border border-green-200 bg-white rounded text-green-700 hover:bg-green-100"
                          >
                            <Copy size={14} />
                          </button>
                        </div>
                      </div>

                      <div>
                        <span className="text-xs text-gray-500">Verification link</span>
                        <div className="flex gap-2 mt-1">
                          <code className="flex-1 bg-white border border-green-200 rounded px-2 py-1.5 text-xs break-all">
                            {window.location.origin}/verify/{doc.credential_id}
                          </code>
                          <button
                            onClick={() =>
                              copy(
                                `${window.location.origin}/verify/${doc.credential_id}`,
                                'Link',
                              )
                            }
                            title="Copy link"
                            className="px-2 border border-green-200 bg-white rounded text-green-700 hover:bg-green-100"
                          >
                            <Copy size={14} />
                          </button>
                        </div>
                      </div>

                      <p className="text-xs text-green-800 pt-1">
                        Disclosing:{' '}
                        {result.consented_fields.length
                          ? result.consented_fields.join(', ')
                          : 'validity status only'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
