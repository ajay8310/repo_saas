import { useState } from 'react'
import { ScrollText, Download, Filter } from 'lucide-react'

interface AuditEntry {
  id: string
  actor_id: string
  operation: string
  resource_type: string
  resource_id: string
  outcome: string
  created_at: string
}

const MOCK_LOGS: AuditEntry[] = [
  { id: '1', actor_id: 'admin@edu.gov.in', operation: 'document:upload', resource_type: 'document', resource_id: 'cred-001', outcome: 'success', created_at: '2025-08-05T10:30:00Z' },
  { id: '2', actor_id: 'admin@edu.gov.in', operation: 'schema:update', resource_type: 'schema', resource_id: 'schema-001', outcome: 'success', created_at: '2025-08-05T09:15:00Z' },
  { id: '3', actor_id: 'john.doe@email.com', operation: 'document:read', resource_type: 'document', resource_id: 'cred-001', outcome: 'success', created_at: '2025-08-05T08:45:00Z' },
  { id: '4', actor_id: 'unknown_client', operation: 'document:read', resource_type: 'document', resource_id: 'cred-002', outcome: 'denied', created_at: '2025-08-05T08:20:00Z' },
  { id: '5', actor_id: 'admin@edu.gov.in', operation: 'document:revoke', resource_type: 'document', resource_id: 'cred-003', outcome: 'success', created_at: '2025-08-04T16:00:00Z' },
]

export default function AuditLogsPage() {
  const [logs] = useState<AuditEntry[]>(MOCK_LOGS)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Logs</h1>
          <p className="text-gray-500 mt-1">Immutable record of all platform operations</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 border border-gray-300 px-4 py-2.5 rounded-lg hover:bg-gray-50">
            <Filter size={18} />
            Filter
          </button>
          <button className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700">
            <Download size={18} />
            Export
          </button>
        </div>
      </div>

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
                <td className="px-6 py-4 text-sm text-gray-500 font-mono">{new Date(log.created_at).toLocaleString()}</td>
                <td className="px-6 py-4 text-sm text-gray-700">{log.actor_id}</td>
                <td className="px-6 py-4"><code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{log.operation}</code></td>
                <td className="px-6 py-4 text-sm text-gray-600">{log.resource_type}/{log.resource_id}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    log.outcome === 'success' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}>
                    {log.outcome}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
