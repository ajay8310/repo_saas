import { useMemo, useState } from 'react'
import { Download, Filter, X } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import { downloadAsCsv, downloadAsJson } from '@/lib/download'

interface AuditEntry {
  id: string
  actor_id: string
  operation: string
  resource_type: string
  resource_id: string
  outcome: string
  created_at: string
}

const ALL_LOGS: AuditEntry[] = [
  { id: '1', actor_id: 'admin@edu.gov.in', operation: 'document:upload', resource_type: 'document', resource_id: 'cred-001', outcome: 'success', created_at: '2025-08-05T10:30:00Z' },
  { id: '2', actor_id: 'admin@edu.gov.in', operation: 'schema:update', resource_type: 'schema', resource_id: 'schema-001', outcome: 'success', created_at: '2025-08-05T09:15:00Z' },
  { id: '3', actor_id: 'john.doe@email.com', operation: 'document:read', resource_type: 'document', resource_id: 'cred-001', outcome: 'success', created_at: '2025-08-05T08:45:00Z' },
  { id: '4', actor_id: 'unknown_client', operation: 'document:read', resource_type: 'document', resource_id: 'cred-002', outcome: 'denied', created_at: '2025-08-05T08:20:00Z' },
  { id: '5', actor_id: 'admin@edu.gov.in', operation: 'document:revoke', resource_type: 'document', resource_id: 'cred-003', outcome: 'success', created_at: '2025-08-04T16:00:00Z' },
  { id: '6', actor_id: 'registrar@edu.gov.in', operation: 'document:download', resource_type: 'document', resource_id: 'cred-004', outcome: 'success', created_at: '2025-08-04T14:05:00Z' },
  { id: '7', actor_id: 'hr@employer.com', operation: 'verification:read', resource_type: 'verification', resource_id: 'tok-9f21', outcome: 'success', created_at: '2025-08-04T11:40:00Z' },
  { id: '8', actor_id: 'unknown_client', operation: 'tenant:create', resource_type: 'tenant', resource_id: 'health_dept', outcome: 'denied', created_at: '2025-08-03T19:10:00Z' },
]

const EXPORT_COLUMNS = [
  'created_at',
  'actor_id',
  'operation',
  'resource_type',
  'resource_id',
  'outcome',
] as const

const BLANK_FILTERS = { actor: '', operation: '', resource_type: '', outcome: '' }

/** Distinct values for a column, for populating the filter dropdowns. */
function distinct(key: keyof AuditEntry): string[] {
  return Array.from(new Set(ALL_LOGS.map(l => String(l[key])))).sort()
}

export default function AuditLogsPage() {
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState(BLANK_FILTERS)
  const { toast, notify } = useToast()

  const setFilter = (key: keyof typeof BLANK_FILTERS, value: string) =>
    setFilters(prev => ({ ...prev, [key]: value }))

  const activeCount = Object.values(filters).filter(v => v).length

  const logs = useMemo(() => {
    const actor = filters.actor.trim().toLowerCase()
    return ALL_LOGS.filter(l => {
      if (actor && !l.actor_id.toLowerCase().includes(actor)) return false
      if (filters.operation && l.operation !== filters.operation) return false
      if (filters.resource_type && l.resource_type !== filters.resource_type)
        return false
      if (filters.outcome && l.outcome !== filters.outcome) return false
      return true
    })
  }, [filters])

  const handleExport = (format: 'json' | 'csv') => {
    if (logs.length === 0) {
      notify('Nothing to export with the current filters.', 'error')
      return
    }
    const stamp = new Date().toISOString().slice(0, 10)
    if (format === 'csv') {
      downloadAsCsv(`audit-logs-${stamp}.csv`, [...EXPORT_COLUMNS], logs)
    } else {
      downloadAsJson(`audit-logs-${stamp}.json`, logs)
    }
    notify(`Exported ${logs.length} entr${logs.length === 1 ? 'y' : 'ies'} as ${format.toUpperCase()}.`)
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Logs</h1>
          <p className="text-gray-500 mt-1">
            Immutable record of all platform operations
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`flex items-center gap-2 border px-4 py-2.5 rounded-lg transition ${
              activeCount
                ? 'border-brand-300 bg-brand-50 text-brand-700'
                : 'border-gray-300 hover:bg-gray-50'
            }`}
          >
            <Filter size={18} />
            Filter{activeCount ? ` (${activeCount})` : ''}
          </button>
          <button
            onClick={() => handleExport('json')}
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700"
          >
            <Download size={18} />
            Export JSON
          </button>
          <button
            onClick={() => handleExport('csv')}
            className="flex items-center gap-2 border border-gray-300 px-4 py-2.5 rounded-lg hover:bg-gray-50"
          >
            <Download size={18} />
            CSV
          </button>
        </div>
      </div>

      {showFilters && (
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label htmlFor="f-actor" className="block text-xs font-medium text-gray-600 mb-1.5">
                Actor
              </label>
              <input
                id="f-actor"
                value={filters.actor}
                onChange={e => setFilter('actor', e.target.value)}
                placeholder="Search actor..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
              />
            </div>
            <div>
              <label htmlFor="f-op" className="block text-xs font-medium text-gray-600 mb-1.5">
                Operation
              </label>
              <select
                id="f-op"
                value={filters.operation}
                onChange={e => setFilter('operation', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
              >
                <option value="">All</option>
                {distinct('operation').map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="f-res" className="block text-xs font-medium text-gray-600 mb-1.5">
                Resource Type
              </label>
              <select
                id="f-res"
                value={filters.resource_type}
                onChange={e => setFilter('resource_type', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
              >
                <option value="">All</option>
                {distinct('resource_type').map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="f-out" className="block text-xs font-medium text-gray-600 mb-1.5">
                Outcome
              </label>
              <select
                id="f-out"
                value={filters.outcome}
                onChange={e => setFilter('outcome', e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 outline-none"
              >
                <option value="">All</option>
                {distinct('outcome').map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between mt-4">
            <p className="text-xs text-gray-500">
              Showing {logs.length} of {ALL_LOGS.length} entries
            </p>
            {activeCount > 0 && (
              <button
                onClick={() => setFilters(BLANK_FILTERS)}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800"
              >
                <X size={13} />
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Timestamp</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Actor</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Operation</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Resource</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Outcome</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {logs.map(log => (
              <tr key={log.id} className="hover:bg-gray-50">
                <td className="px-6 py-4 text-sm text-gray-500 font-mono">
                  {new Date(log.created_at).toLocaleString()}
                </td>
                <td className="px-6 py-4 text-sm text-gray-700">{log.actor_id}</td>
                <td className="px-6 py-4">
                  <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">
                    {log.operation}
                  </code>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600">
                  {log.resource_type}/{log.resource_id}
                </td>
                <td className="px-6 py-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      log.outcome === 'success'
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    {log.outcome}
                  </span>
                </td>
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-10 text-center text-sm text-gray-400">
                  No entries match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-400 mt-3">
        Audit entries are append-only — the database rejects updates and deletes.
      </p>
    </div>
  )
}
