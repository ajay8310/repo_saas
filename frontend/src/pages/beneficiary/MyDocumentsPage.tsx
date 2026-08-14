import { useState } from 'react'
import { FileText, Download, Share2, Shield, QrCode } from 'lucide-react'

interface MyDocument {
  credential_id: string
  schema_name: string
  issuer_name: string
  status: 'stored' | 'revoked'
  issued_at: string
}

const MOCK_MY_DOCS: MyDocument[] = [
  { credential_id: 'cred-001', schema_name: 'B.Tech Degree Certificate', issuer_name: 'State University', status: 'stored', issued_at: '2025-06-01' },
  { credential_id: 'cred-007', schema_name: 'Professional Engineering License', issuer_name: 'Engineering Council', status: 'stored', issued_at: '2025-03-15' },
  { credential_id: 'cred-012', schema_name: 'Diploma in Computer Science', issuer_name: 'State Polytechnic', status: 'revoked', issued_at: '2024-12-20' },
]

export default function MyDocumentsPage() {
  const [docs] = useState<MyDocument[]>(MOCK_MY_DOCS)
  const [showShare, setShowShare] = useState<string | null>(null)

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">My Documents</h1>
        <p className="text-gray-500 mt-1">View, download, and share your credentials</p>
      </div>

      <div className="space-y-4">
        {docs.map(doc => (
          <div key={doc.credential_id} className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                  doc.status === 'stored' ? 'bg-blue-100' : 'bg-red-100'
                }`}>
                  <FileText size={22} className={doc.status === 'stored' ? 'text-blue-600' : 'text-red-600'} />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{doc.schema_name}</h3>
                  <p className="text-sm text-gray-500">Issued by {doc.issuer_name} on {doc.issued_at}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{doc.credential_id}</code>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      doc.status === 'stored' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                    }`}>
                      {doc.status === 'stored' ? 'Valid' : 'Revoked'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button className="flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">
                  <Download size={15} />
                  Download
                </button>
                {doc.status === 'stored' && (
                  <button
                    onClick={() => setShowShare(showShare === doc.credential_id ? null : doc.credential_id)}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700"
                  >
                    <Share2 size={15} />
                    Share
                  </button>
                )}
              </div>
            </div>

            {/* Share/Verification Token Panel */}
            {showShare === doc.credential_id && (
              <div className="mt-4 pt-4 border-t border-gray-200">
                <h4 className="text-sm font-medium text-gray-700 mb-3">Generate Verification Token</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="text-xs text-gray-500">Expiry (hours)</label>
                    <select className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm">
                      <option value="24">24 hours</option>
                      <option value="48">48 hours</option>
                      <option value="72">72 hours (default)</option>
                      <option value="168">7 days</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500">Fields to share</label>
                    <select className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" multiple>
                      <option>student_name</option>
                      <option>degree</option>
                      <option>graduation_year</option>
                      <option>institution</option>
                    </select>
                  </div>
                  <div className="flex items-end">
                    <button className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700 text-sm">
                      <QrCode size={16} />
                      Generate Token
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
