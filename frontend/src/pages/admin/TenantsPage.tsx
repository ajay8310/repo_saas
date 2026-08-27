import { useState } from 'react'
import { Building2, Plus, Check, Ban, Trash2, RotateCcw, KeyRound } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import { downloadAsJson } from '@/lib/documents'

type TenantStatus = 'pending' | 'active' | 'suspended' | 'deactivated'

interface Tenant {
  id: string
  namespace: string
  name: string
  domain: string
  status: TenantStatus
  storage_quota_bytes: number
  rate_limit_per_hour: number
  created_at: string
  digilocker_enabled: boolean
}

/** Mirrors _VALID_TRANSITIONS in app/services/tenant_service.py. */
const VALID_TRANSITIONS: Record<TenantStatus, TenantStatus[]> = {
  pending: ['active'],
  active: ['suspended', 'deactivated'],
  suspended: ['active', 'deactivated'],
  deactivated: [],
}

const INITIAL_TENANTS: Tenant[] = [
  { id: '1', namespace: 'edu_board', name: 'State Education Board', domain: 'edu.gov.in', status: 'active', storage_quota_bytes: 10737418240, rate_limit_per_hour: 10000, created_at: '2025-01-15T10:00:00Z', digilocker_enabled: true },
  { id: '2', namespace: 'health_dept', name: 'Health Department', domain: 'health.gov.in', status: 'pending', storage_quota_bytes: 5368709120, rate_limit_per_hour: 5000, created_at: '2025-03-20T14:30:00Z', digilocker_enabled: false },
  { id: '3', namespace: 'land_registry', name: 'Land Registry Office', domain: 'land.gov.in', status: 'suspended', storage_quota_bytes: 10737418240, rate_limit_per_hour: 10000, created_at: '2024-11-05T09:00:00Z', digilocker_enabled: true },
  { id: '4', namespace: 'transport', name: 'Transport Authority', domain: 'transport.gov.in', status: 'active', storage_quota_bytes: 21474836480, rate_limit_per_hour: 20000, created_at: '2024-08-12T11:00:00Z', digilocker_enabled: false },
]

const statusColors: Record<TenantStatus, string> = {
  active: 'bg-green-100 text-green-800',
  pending: 'bg-yellow-100 text-yellow-800',
  suspended: 'bg-red-100 text-red-800',
  deactivated: 'bg-gray-100 text-gray-800',
}

const NAMESPACE_RE = /^[a-z][a-z0-9_-]*$/

function randomToken(len: number): string {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
  return Array.from(
    { length: len },
    () => chars[Math.floor(Math.random() * chars.length)],
  ).join('')
}

const EMPTY_FORM = { name: '', namespace: '', domain: '', contact_email: '' }

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>(INITIAL_TENANTS)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const { toast, notify } = useToast()

  const setField = (key: keyof typeof EMPTY_FORM, value: string) =>
    setForm(prev => ({ ...prev, [key]: value }))

  const handleCreate = () => {
    const name = form.name.trim()
    const namespace = form.namespace.trim().toLowerCase()
    const domain = form.domain.trim().toLowerCase()
    const email = form.contact_email.trim()

    if (!name || !namespace || !domain || !email) {
      setFormError('All four fields are required.')
      return
    }
    if (!NAMESPACE_RE.test(namespace) || namespace.length > 63) {
      setFormError('Namespace must start with a letter and use only a-z, 0-9, _ or - (max 63).')
      return
    }
    if (!email.includes('@')) {
      setFormError('Contact email must be a valid email address.')
      return
    }
    // Uniqueness across ALL lifecycle states (Req 1.1, 1.3).
    if (tenants.some(t => t.namespace === namespace)) {
      setFormError(`Namespace "${namespace}" is already in use.`)
      return
    }
    if (tenants.some(t => t.domain === domain)) {
      setFormError(`Domain "${domain}" is already registered.`)
      return
    }

    const tenant: Tenant = {
      id: String(Date.now()),
      namespace,
      name,
      domain,
      status: 'pending', // New tenants always start pending (Req 1.4).
      storage_quota_bytes: 10 * 1024 ** 3,
      rate_limit_per_hour: 10000,
      created_at: new Date().toISOString(),
      digilocker_enabled: false,
    }
    setTenants(prev => [tenant, ...prev])
    setForm(EMPTY_FORM)
    setFormError('')
    setShowCreate(false)
    notify(`Created "${name}" in pending state — approve it to activate.`)
  }

  const transition = (tenant: Tenant, next: TenantStatus, verb: string) => {
    if (!VALID_TRANSITIONS[tenant.status].includes(next)) {
      notify(`Cannot ${verb} a tenant that is ${tenant.status}.`, 'error')
      return
    }
    if (next === 'deactivated') {
      const ok = window.confirm(
        `Deactivate "${tenant.name}"?\n\nThis moves it to a read-only archive and cannot be undone.`,
      )
      if (!ok) return
    }
    setTenants(prev =>
      prev.map(t => (t.id === tenant.id ? { ...t, status: next } : t)),
    )
    notify(`${tenant.name} is now ${next}.`)
  }

  const handleRotateKey = (tenant: Tenant) => {
    if (tenant.status !== 'active') {
      notify('Only active tenants can have keys rotated.', 'error')
      return
    }
    const creds = {
      tenant: tenant.name,
      new_client_id: `${tenant.namespace}_${randomToken(16)}`,
      new_client_secret: randomToken(48),
      grace_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
      note: 'Demo credentials. The old key stays valid until grace_until.',
    }
    downloadAsJson(`${tenant.namespace}-credentials.json`, creds)
    notify(`Rotated key for ${tenant.name} — credentials downloaded.`)
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
          <p className="text-gray-500 mt-1">
            Manage platform tenants and their configurations
          </p>
        </div>
        <button
          onClick={() => {
            setShowCreate(!showCreate)
            setFormError('')
          }}
          className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
        >
          <Plus size={18} />
          New Tenant
        </button>
      </div>

      {showCreate && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h3 className="font-semibold mb-4">Create New Tenant</h3>
          <div className="grid grid-cols-2 gap-4">
            <input
              value={form.name}
              onChange={e => setField('name', e.target.value)}
              placeholder="Organization Name"
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 outline-none"
            />
            <input
              value={form.namespace}
              onChange={e => setField('namespace', e.target.value)}
              placeholder="Namespace (e.g. org_name)"
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 outline-none"
            />
            <input
              value={form.domain}
              onChange={e => setField('domain', e.target.value)}
              placeholder="Domain (e.g. org.example.com)"
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 outline-none"
            />
            <input
              value={form.contact_email}
              onChange={e => setField('contact_email', e.target.value)}
              placeholder="Contact Email"
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 outline-none"
            />
          </div>

          {formError && (
            <div className="mt-4 bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
              {formError}
            </div>
          )}

          <div className="flex gap-3 mt-4">
            <button
              onClick={handleCreate}
              className="bg-brand-600 text-white px-4 py-2 rounded-lg hover:bg-brand-700"
            >
              Create
            </button>
            <button
              onClick={() => {
                setShowCreate(false)
                setFormError('')
              }}
              className="text-gray-600 px-4 py-2 hover:text-gray-900"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Tenant</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">DigiLocker</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Quota</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Rate Limit</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {tenants.map(tenant => (
              <tr key={tenant.id} className="hover:bg-gray-50">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-brand-100 rounded-lg flex items-center justify-center">
                      <Building2 size={18} className="text-brand-600" />
                    </div>
                    <div>
                      <p className="font-medium text-gray-900">{tenant.name}</p>
                      <p className="text-xs text-gray-500">
                        {tenant.namespace} — {tenant.domain}
                      </p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[tenant.status]}`}
                  >
                    {tenant.status}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <button
                    onClick={() => {
                      setTenants(prev =>
                        prev.map(t =>
                          t.id === tenant.id
                            ? { ...t, digilocker_enabled: !t.digilocker_enabled }
                            : t,
                        ),
                      )
                      notify(
                        `DigiLocker ${!tenant.digilocker_enabled ? 'enabled' : 'disabled'} for ${tenant.name}`,
                      )
                    }}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      tenant.digilocker_enabled ? 'bg-blue-600' : 'bg-gray-300'
                    }`}
                    title={tenant.digilocker_enabled ? 'DigiLocker enabled — click to disable' : 'DigiLocker disabled — click to enable'}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                        tenant.digilocker_enabled ? 'translate-x-4.5' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {(tenant.storage_quota_bytes / 1024 ** 3).toFixed(0)} GB
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {tenant.rate_limit_per_hour.toLocaleString()}/hr
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    {tenant.status === 'pending' && (
                      <button
                        onClick={() => transition(tenant, 'active', 'approve')}
                        className="p-1.5 text-green-600 hover:bg-green-50 rounded"
                        title="Approve"
                      >
                        <Check size={16} />
                      </button>
                    )}
                    {tenant.status === 'active' && (
                      <>
                        <button
                          onClick={() => transition(tenant, 'suspended', 'suspend')}
                          className="p-1.5 text-orange-600 hover:bg-orange-50 rounded"
                          title="Suspend"
                        >
                          <Ban size={16} />
                        </button>
                        <button
                          onClick={() => handleRotateKey(tenant)}
                          className="p-1.5 text-brand-600 hover:bg-brand-50 rounded"
                          title="Rotate API key"
                        >
                          <KeyRound size={16} />
                        </button>
                      </>
                    )}
                    {tenant.status === 'suspended' && (
                      <button
                        onClick={() => transition(tenant, 'active', 'reactivate')}
                        className="p-1.5 text-blue-600 hover:bg-blue-50 rounded"
                        title="Reactivate"
                      >
                        <RotateCcw size={16} />
                      </button>
                    )}
                    {tenant.status !== 'deactivated' && (
                      <button
                        onClick={() => transition(tenant, 'deactivated', 'deactivate')}
                        className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                        title="Deactivate"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                    {tenant.status === 'deactivated' && (
                      <span className="text-xs text-gray-400">archived</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
