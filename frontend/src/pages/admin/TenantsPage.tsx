import { useState } from 'react'
import { Building2, Plus, Check, Ban, Trash2, RotateCcw } from 'lucide-react'

interface Tenant {
  id: string
  namespace: string
  name: string
  domain: string
  status: 'pending' | 'active' | 'suspended' | 'deactivated'
  storage_quota_bytes: number
  rate_limit_per_hour: number
  created_at: string
}

const MOCK_TENANTS: Tenant[] = [
  { id: '1', namespace: 'edu_board', name: 'State Education Board', domain: 'edu.gov.in', status: 'active', storage_quota_bytes: 10737418240, rate_limit_per_hour: 10000, created_at: '2025-01-15T10:00:00Z' },
  { id: '2', namespace: 'health_dept', name: 'Health Department', domain: 'health.gov.in', status: 'pending', storage_quota_bytes: 5368709120, rate_limit_per_hour: 5000, created_at: '2025-03-20T14:30:00Z' },
  { id: '3', namespace: 'land_registry', name: 'Land Registry Office', domain: 'land.gov.in', status: 'suspended', storage_quota_bytes: 10737418240, rate_limit_per_hour: 10000, created_at: '2024-11-05T09:00:00Z' },
  { id: '4', namespace: 'transport', name: 'Transport Authority', domain: 'transport.gov.in', status: 'active', storage_quota_bytes: 21474836480, rate_limit_per_hour: 20000, created_at: '2024-08-12T11:00:00Z' },
]

const statusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  pending: 'bg-yellow-100 text-yellow-800',
  suspended: 'bg-red-100 text-red-800',
  deactivated: 'bg-gray-100 text-gray-800',
}

export default function TenantsPage() {
  const [tenants] = useState<Tenant[]>(MOCK_TENANTS)
  const [showCreate, setShowCreate] = useState(false)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
          <p className="text-gray-500 mt-1">Manage platform tenants and their configurations</p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
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
            <input placeholder="Organization Name" className="px-3 py-2 border border-gray-300 rounded-lg" />
            <input placeholder="Namespace (e.g. org_name)" className="px-3 py-2 border border-gray-300 rounded-lg" />
            <input placeholder="Domain (e.g. org.example.com)" className="px-3 py-2 border border-gray-300 rounded-lg" />
            <input placeholder="Contact Email" className="px-3 py-2 border border-gray-300 rounded-lg" />
          </div>
          <div className="flex gap-3 mt-4">
            <button className="bg-brand-600 text-white px-4 py-2 rounded-lg hover:bg-brand-700">Create</button>
            <button onClick={() => setShowCreate(false)} className="text-gray-600 px-4 py-2 hover:text-gray-900">Cancel</button>
          </div>
        </div>
      )}

      {/* Tenant Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Tenant</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
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
                      <p className="text-xs text-gray-500">{tenant.namespace} — {tenant.domain}</p>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[tenant.status]}`}>
                    {tenant.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {(tenant.storage_quota_bytes / (1024 ** 3)).toFixed(0)} GB
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {tenant.rate_limit_per_hour.toLocaleString()}/hr
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    {tenant.status === 'pending' && (
                      <button className="p-1.5 text-green-600 hover:bg-green-50 rounded" title="Approve">
                        <Check size={16} />
                      </button>
                    )}
                    {tenant.status === 'active' && (
                      <button className="p-1.5 text-orange-600 hover:bg-orange-50 rounded" title="Suspend">
                        <Ban size={16} />
                      </button>
                    )}
                    {tenant.status === 'suspended' && (
                      <button className="p-1.5 text-blue-600 hover:bg-blue-50 rounded" title="Reactivate">
                        <RotateCcw size={16} />
                      </button>
                    )}
                    {tenant.status !== 'deactivated' && (
                      <button className="p-1.5 text-red-600 hover:bg-red-50 rounded" title="Deactivate">
                        <Trash2 size={16} />
                      </button>
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
