import { useState } from 'react'
import { Upload, Search, Filter, Ban, Download } from 'lucide-react'

interface Document {
  credential_id: string
  schema_name: string
  beneficiary_id: string
  status: 'stored' | 'revoked'
  issued_at: string
}

const MOCK_DOCS: Document[] = [
  { credential_id: 'cred-001', schema_name: 'Degree Certificate', beneficiary_id: 'john.doe@email.com', status: 'stored', issued_at: '2025-06-01' },
  { credential_id: 'cred-002', schema_name: 'Professional License', beneficiary_id: 'jane.smith@email.com', status: 'stored', issued_at: '2025-05-28' },
  { credential_id: 'cred-003', schema_name: 'Degree Certificate', beneficiary_id: 'bob.wilson@email.com', status: 'revoked', issued_at: '2025-04-15' },
  { credential_id: 'cred-004', schema_name: 'Land Title Deed', beneficiary_id: 'alice.brown@email.com', status: 'stored', issued_at: '2025-03-20' },
  { credential_id: 'cred-005', schema_name: 'Professional License', beneficiary_id: 'charlie.davis@email.com', status: 'stored', issued_at: '2025-02-10' },
]

export default function DocumentsPage() {
  const [docs] = useState<Document[]>(MOCK_DOCS)
  const [searchQuery, setSearchQuery] = useState('')

  const filtered = docs.filter(d =>
    d.beneficiary_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    d.schema_name.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-gray-500 mt-1">Manage issued credentials and documents</p>
        </div>
        <div className="flex gap-3">
          <button className="flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2.5 rounded-lg hover:bg-gray-50 transition">
            <Upload size={18} />
            Bulk Upload
          </button>
          <button className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition">
            <Upload size={18} />
            Upload Document
          </button>
        </div>
      </div>

      {/* Search and Filter */}
      <div className="flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search size={18} className="absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by beneficiary or schema..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>
        <button className="flex items-center gap-2 border border-gray-300 px-4 py-2.5 rounded-lg hover:bg-gray-50">
          <Filter size={18} />
          Filter
        </button>
      </div>

      {/* Document Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Credential</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Schema</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Beneficiary</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Issued</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map(doc => (
              <tr key={doc.credential_id} className="hover:bg-gray-50">
                <td className="px-6 py-4">
                  <code className="text-sm bg-gray-100 px-2 py-0.5 rounded">{doc.credential_id}</code>
                </td>
                <td className="px-6 py-4 text-sm text-gray-700">{doc.schema_name}</td>
                <td className="px-6 py-4 text-sm text-gray-600">{doc.beneficiary_id}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    doc.status === 'stored' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}>
                    {doc.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-500">{doc.issued_at}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-1">
                    <button className="p-1.5 text-gray-400 hover:text-brand-600 rounded" title="Download"><Download size={15} /></button>
                    {doc.status === 'stored' && (
                      <button className="p-1.5 text-gray-400 hover:text-red-600 rounded" title="Revoke"><Ban size={15} /></button>
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
