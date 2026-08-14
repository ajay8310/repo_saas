import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Shield, CheckCircle, XCircle, AlertTriangle, Search } from 'lucide-react'

type VerifyStatus = 'idle' | 'loading' | 'valid' | 'revoked' | 'invalid'

export default function VerifyPage() {
  const { credentialId } = useParams()
  const [inputId, setInputId] = useState(credentialId || '')
  const [status, setStatus] = useState<VerifyStatus>(credentialId ? 'loading' : 'idle')
  const [result, setResult] = useState<any>(null)

  const handleVerify = async () => {
    if (!inputId.trim()) return
    setStatus('loading')

    // Simulated API call
    setTimeout(() => {
      // Mock responses
      if (inputId.includes('001')) {
        setStatus('valid')
        setResult({ status: 'valid', issuer: 'State Education Board', issued_at: '2025-06-01' })
      } else if (inputId.includes('003')) {
        setStatus('revoked')
        setResult({ status: 'revoked', issuer: 'State Education Board', revoked_at: '2025-07-15' })
      } else {
        setStatus('invalid')
        setResult({ status: 'invalid' })
      }
    }, 1000)
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-brand-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <Shield className="text-brand-600" size={32} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Verify Document</h1>
          <p className="text-gray-500 mt-1">Check the authenticity of a credential</p>
        </div>

        {/* Search */}
        <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6 mb-6">
          <div className="flex gap-3">
            <input
              type="text"
              value={inputId}
              onChange={e => setInputId(e.target.value)}
              placeholder="Enter Credential ID or paste verification token"
              className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none text-sm"
            />
            <button
              onClick={handleVerify}
              className="bg-brand-600 text-white px-5 py-3 rounded-xl hover:bg-brand-700 transition flex items-center gap-2"
            >
              <Search size={18} />
              Verify
            </button>
          </div>
        </div>

        {/* Result */}
        {status !== 'idle' && (
          <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-8 text-center">
            {status === 'loading' && (
              <div className="animate-pulse">
                <div className="w-16 h-16 bg-gray-200 rounded-full mx-auto mb-4" />
                <div className="h-4 bg-gray-200 rounded w-48 mx-auto mb-2" />
                <div className="h-3 bg-gray-100 rounded w-32 mx-auto" />
              </div>
            )}

            {status === 'valid' && (
              <>
                <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <CheckCircle className="text-green-600" size={40} />
                </div>
                <h2 className="text-xl font-bold text-green-800 mb-1">Valid Document</h2>
                <p className="text-gray-500 text-sm mb-4">This credential is authentic and current</p>
                <div className="bg-green-50 rounded-xl p-4 text-left text-sm space-y-2">
                  <div className="flex justify-between"><span className="text-gray-500">Issuer</span><span className="font-medium">{result?.issuer}</span></div>
                  <div className="flex justify-between"><span className="text-gray-500">Issued Date</span><span className="font-medium">{result?.issued_at}</span></div>
                  <div className="flex justify-between"><span className="text-gray-500">Status</span><span className="font-medium text-green-700">Active</span></div>
                </div>
              </>
            )}

            {status === 'revoked' && (
              <>
                <div className="w-20 h-20 bg-orange-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <AlertTriangle className="text-orange-600" size={40} />
                </div>
                <h2 className="text-xl font-bold text-orange-800 mb-1">Document Revoked</h2>
                <p className="text-gray-500 text-sm mb-4">This credential has been revoked by the issuer</p>
                <div className="bg-orange-50 rounded-xl p-4 text-left text-sm space-y-2">
                  <div className="flex justify-between"><span className="text-gray-500">Issuer</span><span className="font-medium">{result?.issuer}</span></div>
                  <div className="flex justify-between"><span className="text-gray-500">Revoked On</span><span className="font-medium text-orange-700">{result?.revoked_at}</span></div>
                </div>
              </>
            )}

            {status === 'invalid' && (
              <>
                <div className="w-20 h-20 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <XCircle className="text-red-600" size={40} />
                </div>
                <h2 className="text-xl font-bold text-red-800 mb-1">Invalid Credential</h2>
                <p className="text-gray-500 text-sm">No document found with this identifier</p>
              </>
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
