import { useState } from 'react'
import { Upload, Send } from 'lucide-react'
import Modal from './Modal'
import { SCHEMA_OPTIONS } from '@/lib/documents'

interface Props {
  onClose: () => void
  onSubmit: (schemaName: string, beneficiaryId: string, pushToDigiLocker: boolean) => void
}

/** Single-document issuance form (mirrors POST /api/v1/documents). */
export default function UploadDocumentModal({ onClose, onSubmit }: Props) {
  const [schemaName, setSchemaName] = useState<string>(SCHEMA_OPTIONS[0])
  const [beneficiaryId, setBeneficiaryId] = useState('')
  const [content, setContent] = useState('')
  const [pushToDigiLocker, setPushToDigiLocker] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const id = beneficiaryId.trim()

    // Same validation the backend applies (Req 3.4).
    if (!id) {
      setError('Beneficiary ID is required.')
      return
    }
    if (!id.includes('@')) {
      setError('Beneficiary ID should be an email address.')
      return
    }
    if (content.trim()) {
      try {
        JSON.parse(content)
      } catch {
        setError('Field data must be valid JSON (or leave it empty).')
        return
      }
    }
    onSubmit(schemaName, id, pushToDigiLocker)
  }

  return (
    <Modal
      title="Upload Document"
      subtitle="Issue a new credential to a beneficiary"
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="schema"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Document Schema
          </label>
          <select
            id="schema"
            value={schemaName}
            onChange={e => setSchemaName(e.target.value)}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          >
            {SCHEMA_OPTIONS.map(s => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="beneficiary"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Beneficiary ID
          </label>
          <input
            id="beneficiary"
            type="text"
            value={beneficiaryId}
            onChange={e => setBeneficiaryId(e.target.value)}
            placeholder="student@example.com"
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>

        <div>
          <label
            htmlFor="content"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Field Data <span className="text-gray-400 font-normal">(JSON, optional)</span>
          </label>
          <textarea
            id="content"
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={5}
            placeholder={'{\n  "student_name": "John Doe",\n  "grade": "A"\n}'}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg font-mono text-xs focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>

        <div className="flex items-center gap-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <input
            id="digilocker"
            type="checkbox"
            checked={pushToDigiLocker}
            onChange={e => setPushToDigiLocker(e.target.checked)}
            className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
          />
          <label htmlFor="digilocker" className="flex items-center gap-2 text-sm text-blue-900 cursor-pointer select-none">
            <Send size={14} className="text-blue-600" />
            <span>
              <strong>Push to DigiLocker</strong>
              <span className="text-blue-700 ml-1">— auto-deliver to beneficiary's DigiLocker account</span>
            </span>
          </label>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
          >
            <Upload size={16} />
            Issue Credential
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 text-gray-600 hover:text-gray-900 transition"
          >
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}
