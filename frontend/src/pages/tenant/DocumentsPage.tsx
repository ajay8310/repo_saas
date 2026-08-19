import { useState } from 'react'
import { Upload, Search, Ban, Download, Smartphone, CheckCircle2 } from 'lucide-react'
import UploadDocumentModal from '@/components/UploadDocumentModal'
import BulkUploadModal from '@/components/BulkUploadModal'
import { Toast, useToast } from '@/hooks/useToast'
import {
  type BulkOutcome,
  type DocumentRow,
  downloadAsJson,
  generateCredentialId,
  loadDocuments,
  saveDocuments,
  todayIso,
} from '@/lib/documents'
import {
  type PushRecord,
  loadPushes,
  publish,
  savePushes,
  statusOf,
  suggestDoctype,
  upsert,
} from '@/lib/digilocker'

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRow[]>(() => loadDocuments())
  const [pushes, setPushes] = useState<PushRecord[]>(() => loadPushes())
  const [searchQuery, setSearchQuery] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const { toast, notify } = useToast()

  // Both lists are shared with the DigiLocker page through localStorage, so a
  // credential issued here is immediately publishable there.
  const persistDocs = (next: DocumentRow[]) => {
    setDocs(next)
    saveDocuments(next)
  }

  const persistPushes = (next: PushRecord[]) => {
    setPushes(next)
    savePushes(next)
  }

  const handleUpload = (
    schemaName: string,
    beneficiaryId: string,
    options: { publishToDigiLocker: boolean; doctype: string },
  ) => {
    const row: DocumentRow = {
      credential_id: generateCredentialId(docs),
      schema_name: schemaName,
      beneficiary_id: beneficiaryId,
      status: 'stored',
      issued_at: todayIso(),
    }
    persistDocs([row, ...docs])
    setShowUpload(false)

    if (!options.publishToDigiLocker) {
      notify(`Issued ${row.credential_id} to ${beneficiaryId}`)
      return
    }

    const outcome = publish(pushes, {
      credentialId: row.credential_id,
      doctype: options.doctype,
      documentStatus: 'stored',
    })
    if (outcome.ok && outcome.record) {
      persistPushes(upsert(pushes, outcome.record))
      notify(`Issued ${row.credential_id} and published to DigiLocker`)
    } else {
      // Issuance succeeded even though publication did not — say both, so the
      // officer knows the credential exists and needs a retry.
      notify(
        `Issued ${row.credential_id}, but DigiLocker publication failed. Retry from the DigiLocker page.`,
        'error',
      )
    }
  }

  const handlePublish = (doc: DocumentRow) => {
    const outcome = publish(pushes, {
      credentialId: doc.credential_id,
      doctype: suggestDoctype(doc.schema_name),
      documentStatus: doc.status,
    })
    if (!outcome.ok || !outcome.record) {
      notify(outcome.error ?? 'Publication failed.', 'error')
      return
    }
    persistPushes(upsert(pushes, outcome.record))
    notify(`${doc.credential_id} published to DigiLocker`)
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
    persistDocs([...created, ...docs])
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
    persistDocs(
      docs.map(d =>
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
                  {statusOf(pushes, doc.credential_id) === 'success' ? (
                    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-green-700">
                      <CheckCircle2 size={14} />
                      Published
                    </span>
                  ) : (
                    <span className="text-xs text-gray-400">Not published</span>
                  )}
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
                    {doc.status === 'stored' &&
                      statusOf(pushes, doc.credential_id) !== 'success' && (
                        <button
                          onClick={() => handlePublish(doc)}
                          className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                          title="Publish to DigiLocker"
                          aria-label={`Publish ${doc.credential_id} to DigiLocker`}
                        >
                          <Smartphone size={15} />
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
