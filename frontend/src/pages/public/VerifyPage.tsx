import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Shield, CheckCircle, XCircle, AlertTriangle, Search, Clock, RotateCcw,
} from 'lucide-react'
import { type VerificationResult, verifyInput } from '@/lib/verificationStore'

type UiState = 'idle' | 'loading' | 'done'

/** Presentation for each backend status. */
const PRESENTATION = {
  valid: {
    icon: CheckCircle, tone: 'green',
    title: 'Valid Document',
    blurb: 'This credential is authentic and current.',
  },
  revoked: {
    icon: AlertTriangle, tone: 'orange',
    title: 'Document Revoked',
    blurb: 'This credential was revoked by the issuer.',
  },
  expired: {
    icon: Clock, tone: 'orange',
    title: 'Link Expired',
    blurb: 'This verification link has passed its expiry time.',
  },
  used: {
    icon: RotateCcw, tone: 'orange',
    title: 'Link Already Used',
    blurb: 'Verification links are single-use. Ask for a fresh one.',
  },
  invalid: {
    icon: XCircle, tone: 'red',
    title: 'Invalid Credential',
    blurb: 'No document found with this identifier.',
  },
} as const

const TONES = {
  green: { bg: 'bg-green-100', fg: 'text-green-600', head: 'text-green-800', panel: 'bg-green-50' },
  orange: { bg: 'bg-orange-100', fg: 'text-orange-600', head: 'text-orange-800', panel: 'bg-orange-50' },
  red: { bg: 'bg-red-100', fg: 'text-red-600', head: 'text-red-800', panel: 'bg-red-50' },
} as const

export default function VerifyPage() {
  const { credentialId } = useParams()
  const [input, setInput] = useState(credentialId ?? '')
  const [ui, setUi] = useState<UiState>('idle')
  const [result, setResult] = useState<VerificationResult | null>(null)

  const timer = useRef<number | undefined>(undefined)
  // Tracks what we've already auto-verified. Consuming a token is single-use,
  // and StrictMode double-invokes effects in dev — without this guard the
  // second run would burn the token and report "already used".
  const autoVerified = useRef<string | null>(null)

  const runVerify = useCallback((value: string) => {
    if (!value.trim()) return
    setUi('loading')
    window.clearTimeout(timer.current)
    // Brief delay so the transition reads as a lookup rather than a flicker.
    timer.current = window.setTimeout(() => {
      setResult(verifyInput(value))
      setUi('done')
    }, 450)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  // Auto-verify when arriving via /verify/:idOrToken. Without this the page
  // used to sit on the loading skeleton forever.
  useEffect(() => {
    if (!credentialId || autoVerified.current === credentialId) return
    autoVerified.current = credentialId
    runVerify(credentialId)
  }, [credentialId, runVerify])

  const presentation = result ? PRESENTATION[result.status] : null
  const tone = presentation ? TONES[presentation.tone] : null
  const Icon = presentation?.icon

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white flex flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-brand-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <Shield className="text-brand-600" size={32} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Verify Document</h1>
          <p className="text-gray-500 mt-1">Check the authenticity of a credential</p>
        </div>

        <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6 mb-6">
          <form
            onSubmit={e => {
              e.preventDefault()
              runVerify(input)
            }}
            className="flex gap-3"
          >
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Credential ID or verification token"
              aria-label="Credential ID or verification token"
              className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm"
            />
            <button
              type="submit"
              className="bg-brand-600 text-white px-5 py-3 rounded-xl hover:bg-brand-700 transition flex items-center gap-2 disabled:opacity-50"
              disabled={!input.trim()}
            >
              <Search size={18} />
              Verify
            </button>
          </form>
          <p className="text-xs text-gray-400 mt-3">
            A credential ID (e.g. <code>cred-001</code>) returns validity only. A
            verification token also reveals the fields its holder chose to share.
          </p>
        </div>

        {ui === 'loading' && (
          <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-8 text-center animate-pulse">
            <div className="w-20 h-20 bg-gray-200 rounded-full mx-auto mb-4" />
            <div className="h-4 bg-gray-200 rounded w-44 mx-auto mb-2" />
            <div className="h-3 bg-gray-100 rounded w-32 mx-auto" />
          </div>
        )}

        {ui === 'done' && result && presentation && tone && Icon && (
          <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-8 text-center">
            <div
              className={`w-20 h-20 ${tone.bg} rounded-full flex items-center justify-center mx-auto mb-4`}
            >
              <Icon className={tone.fg} size={40} />
            </div>
            <h2 className={`text-xl font-bold ${tone.head} mb-1`}>
              {presentation.title}
            </h2>
            <p className="text-gray-500 text-sm mb-4">{presentation.blurb}</p>

            {result.issuer_name && (
              <div className={`${tone.panel} rounded-xl p-4 text-left text-sm space-y-2`}>
                <div className="flex justify-between">
                  <span className="text-gray-500">Issuer</span>
                  <span className="font-medium">{result.issuer_name}</span>
                </div>
                {result.schema_name && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Credential</span>
                    <span className="font-medium">{result.schema_name}</span>
                  </div>
                )}
                {result.issued_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Issued</span>
                    <span className="font-medium">{result.issued_at}</span>
                  </div>
                )}
                {result.revoked_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">Revoked</span>
                    <span className="font-medium text-orange-700">
                      {result.revoked_at}
                    </span>
                  </div>
                )}
              </div>
            )}

            {result.fields && Object.keys(result.fields).length > 0 && (
              <div className="mt-3 border border-gray-200 rounded-xl overflow-hidden text-left">
                <p className="px-4 py-2 bg-gray-50 text-xs font-semibold text-gray-600 border-b border-gray-200">
                  Disclosed by the holder
                </p>
                <dl className="divide-y divide-gray-100">
                  {Object.entries(result.fields).map(([k, v]) => (
                    <div key={k} className="flex justify-between px-4 py-2 text-sm">
                      <dt className="text-gray-500">{k.replace(/_/g, ' ')}</dt>
                      <dd className="font-medium text-gray-900">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            {result.via_token && result.valid && (
              <p className="text-xs text-gray-400 mt-3">
                This token has now been consumed and cannot be reused.
              </p>
            )}
          </div>
        )}

        <p className="text-center text-xs text-gray-400 mt-8">
          Powered by Repo SaaS — Secure Document Verification
        </p>
      </div>
    </div>
  )
}
