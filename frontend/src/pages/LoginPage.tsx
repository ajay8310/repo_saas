import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import api from '@/lib/api'
import {
  DEMO_ROLES,
  DEMO_ROLE_LABELS,
  mintDemoToken,
  type DemoRole,
} from '@/lib/devAuth'
import { Shield, FlaskConical } from 'lucide-react'

export default function LoginPage() {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  // Dev-only shortcut so the UI can be explored without a running backend.
  // `import.meta.env.DEV` is statically false in production builds, so this
  // block and its devAuth import are tree-shaken out entirely.
  const showDemoLogin = import.meta.env.DEV

  const handleDemoLogin = (role: DemoRole) => {
    login(mintDemoToken(role))
    navigate('/dashboard')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await api.post('/auth/token', {
        grant_type: 'client_credentials',
        client_id: clientId,
        client_secret: clientSecret,
      })
      login(res.data.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.message || 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-brand-900">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-2xl shadow-2xl p-8">
          <div className="text-center mb-8">
            <div className="w-16 h-16 bg-brand-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
              <Shield className="text-brand-600" size={32} />
            </div>
            <h2 className="text-2xl font-bold text-gray-900">Repo SaaS</h2>
            <p className="text-gray-500 mt-1">Sign in to your account</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Client ID</label>
              <input
                type="text"
                value={clientId}
                onChange={e => setClientId(e.target.value)}
                className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none transition"
                placeholder="your_namespace_xxxxxxxx"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Client Secret</label>
              <input
                type="password"
                value={clientSecret}
                onChange={e => setClientSecret(e.target.value)}
                className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none transition"
                placeholder="Enter your client secret"
                required
              />
            </div>

            {error && (
              <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-brand-600 text-white py-2.5 rounded-lg font-medium hover:bg-brand-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>

          {showDemoLogin && (
            <div className="mt-6 pt-6 border-t border-dashed border-amber-300">
              <div className="flex items-center gap-2 mb-1">
                <FlaskConical size={14} className="text-amber-600" />
                <span className="text-xs font-semibold text-amber-700">
                  Dev preview
                </span>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                Browse the UI without a backend. Pages show sample data; API
                calls will still fail.
              </p>
              <div className="grid grid-cols-2 gap-2">
                {DEMO_ROLES.map(role => (
                  <button
                    key={role}
                    type="button"
                    onClick={() => handleDemoLogin(role)}
                    className="px-3 py-2 text-xs font-medium text-amber-800 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 transition"
                  >
                    {DEMO_ROLE_LABELS[role]}
                  </button>
                ))}
              </div>
            </div>
          )}

          <p className="text-center text-xs text-gray-400 mt-6">
            Secure multi-tenant document repository
          </p>
        </div>
      </div>
    </div>
  )
}
