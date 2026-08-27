import { useState } from 'react'
import { Upload, Search, Ban, Download, Send } from 'lucide-react'
import UploadDocumentModal from '@/components/UploadDocumentModal'
import BulkUploadModal from '@/components/BulkUploadModal'
import { Toast, useToast } from '@/hooks/useToast'
import {
  type BulkOutcome,
  type DocumentRow,
  downloadAsJson,
  generateCredentialId,
  todayIso,
} from '@/lib/documents'

interface ExtendedDocRow extends DocumentRow {
  digilocker_status?: 'pending' | 'success' | 'failed' | 'not_pushed'
}

const INITIAL_DOCS: ExtendedDocRow[] = [
  { credential_id: 'cred-001', schema_name: 'Degree Certificate', beneficiary_id: 'john.doe@email.com', status: 'stored', issued_at: '2025-06-01', digilocker_status: 'success' },
  { credential_id: 'cred-002', schema_name: 'Professional License', beneficiary_id: 'jane.smith@email.com', status: 'stored', issued_at: '2025-05-28', digilocker_status: 'pending' },
  { credential_id: 'cred-003', schema_name: 'Degree Certificate', beneficiary_id: 'bob.wilson@email.com', status: 'revoked', issued_at: '2025-04-15', digilocker_status: 'not_pushed' },
  { credential_id: 'cred-004', schema_name: 'Land Title Deed', beneficiary_id: 'alice.brown@email.com', status: 'stored', issued_at: '2025-03-20', digilocker_status: 'success' },
  { credential_id: 'cred-005', schema_name: 'Professional License', beneficiary_id: 'charlie.davis@email.com', status: 'stored', issued_at: '2025-02-10', digilocker_status: 'not_pushed' },
]

const digilockerStatusColors: Record<string, string> = {
  success: 'bg-blue-100 text-blue-800',
  pending: 'bg-yellow-100 text-yellow-800',
  failed: 'bg-red-100 text-red-800',
  not_pushed: 'bg-gray-100 text-gray-500',
}

const digilockerStatusLabels: Record<string, string> = {
  success: 'Pushed',
  pending: 'Pushing...',
  failed: 'Failed',
  not_pushed: '—',
}

export default function DocumentsPage() {
  const [docs, setDocs] = useState<ExtendedDocRow[]>(INITIAL_DOCS)
  const [searchQuery, setSearchQuery] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const { toast, notify } = useToast()

  const handleUpload = (schemaName: string, beneficiaryId: string, pushToDigiLocker: boolean) => {
    const row: ExtendedDocRow = {
      credential_id: generateCredentialId(docs),
      schema_name: schemaName,
      beneficiary_id: beneficiaryId,
      status: 'stored',
      issued_at: todayIso(),
      digilocker_status: pushToDigiLocker ? 'pending' : 'not_pushed',
    }
    setDocs(prev => [row, ...prev])
    setShowUpload(false)
    const msg = pushToDigiLocker
      ? `Issued ${row.credential_id} to ${beneficiaryId} — pushing to DigiLocker...`
      : `Issued ${row.credential_id} to ${beneficiaryId}`
    notify(msg)

    // Simulate async DigiLocker push completion
    if (pushToDigiLocker) {
      setTimeout(() => {
        setDocs(prev =>
          prev.map(d =>
            d.credential_id === row.credential_id
              ? { ...d, digilocker_status: 'success' as const }
              : d,
          ),
        )
      }, 3000)
    }
  }

  const handlePushToDigiLocker = (doc: ExtendedDocRow) => {
    if (doc.status === 'revoked') {
      notify('Cannot push a revoked document to DigiLocker.', 'error')
      return
    }
    setDocs(prev =>
      prev.map(d =>
        d.credential_id === doc.credential_id
          ? { ...d, digilocker_status: 'pending' as const }
          : d,
      ),
    )
    notify(`Pushing ${doc.credential_id} to DigiLocker...`)

    // Simulate async push
    setTimeout(() => {
      setDocs(prev =>
        prev.map(d =>
          d.credential_id === doc.credential_id
            ? { ...d, digilocker_status: 'success' as const }
            : d,
        ),
      )
    }, 2500)
  }

  const handleBulkCommit = (schemaName: string, outcome: BulkOutcome) => {
    // Each record is issued independently — failures don't block the rest
    // (Req 3.2 / 6.7).
    const created: DocumentRow[] = []
    outcome.succeeded.forEach(rec => {
      created.push({
        credential_id: generateCredentialId([...docs, ...created]),
        schema_name: schemaName,
        beneficiary_id: rec.beneficiary_id,
        status: 'stored',
        issued_at: todayIso(),
      })
    })
    setDocs(prev => [...created, ...prev])
    setShowBulk(false)
    notify(
      `Bulk upload: ${created.length} issued, ${outcome.failed.length} failed of ${outcome.total}`,
    )
  }

  const handleRevoke = (doc: DocumentRow) => {
    const reason = window.prompt(
      `Revocation reason for ${doc.credential_id} (1-500 chars):`,
    )
    if (reason === null) return
    if (!reason.trim() || reason.length > 500) {
      notify('Revocation reason must be 1-500 characters.', 'error')
      return
    }
    setDocs(prev =>
      prev.map(d =>
        d.credential_id === doc.credential_id
          ? { ...d, status: 'revoked' as const }
          : d,
      ),
    )
    notify(`Revoked ${doc.credential_id}`)
  }

  const handleDownload = (doc: DocumentRow) => {
    downloadAsJson(`${doc.credential_id}.json`, {
      credential_id: doc.credential_id,
      schema: doc.schema_name,
      beneficiary_id: doc.beneficiary_id,
      status: doc.status,
      issued_at: doc.issued_at,
      verification_url: `${window.location.origin}/verify/${doc.credential_id}`,
      note: 'Demo export. Signed PDF/JSON-LD requires the backend.',
    })
    notify(`Downloaded ${doc.credential_id}.json`)
  }

  const filtered = docs.filter(
    d =>
      d.beneficiary_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.schema_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      d.credential_id.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  return (
    <div>
      {showUpload && (
        <UploadDocumentModal
          onClose={() => setShowUpload(false)}
          onSubmit={handleUpload}
        />
      )}
      {showBulk && (
        <BulkUploadModal
          onClose={() => setShowBulk(false)}
          onCommit={handleBulkCommit}
        />
      )}

      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-gray-500 mt-1">Manage issued credentials and documents</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setShowBulk(true)}
            className="flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2.5 rounded-lg hover:bg-gray-50 transition"
          >
            <Upload size={18} />
            Bulk Upload
          </button>
          <button
            onClick={() => setShowUpload(true)}
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
          >
            <Upload size={18} />
            Upload Document
          </button>
        </div>
      </div>

      <div className="flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search size={18} className="absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by credential, beneficiary, or schema..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Credential</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Schema</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Beneficiary</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">DigiLocker</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Issued</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map(doc => (
              <tr key={doc.credential_id} className="hover:bg-gray-50">
                <td className="px-6 py-4">
                  <code className="text-sm bg-gray-100 px-2 py-0.5 rounded">
                    {doc.credential_id}
                  </code>
                </td>
                <td className="px-6 py-4 text-sm text-gray-700">{doc.schema_name}</td>
                <td className="px-6 py-4 text-sm text-gray-600">{doc.beneficiary_id}</td>
                <td className="px-6 py-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      doc.status === 'stored'
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    {doc.status}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      digilockerStatusColors[doc.digilocker_status || 'not_pushed']
                    }`}
                  >
                    {digilockerStatusLabels[doc.digilocker_status || 'not_pushed']}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-500">{doc.issued_at}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDownload(doc)}
                      className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                      title="Download"
                    >
                      <Download size={15} />
                    </button>
                    {doc.status === 'stored' && doc.digilocker_status !== 'success' && doc.digilocker_status !== 'pending' && (
                      <button
                        onClick={() => handlePushToDigiLocker(doc)}
                        className="p-1.5 text-gray-400 hover:text-blue-600 rounded"
                        title="Push to DigiLocker"
                      >
                        <Send size={15} />
                      </button>
                    )}
                    {doc.status === 'stored' && (
                      <button
                        onClick={() => handleRevoke(doc)}
                        className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                        title="Revoke"
                      >
                        <Ban size={15} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-10 text-center text-sm text-gray-400">
                  No documents match "{searchQuery}".
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
