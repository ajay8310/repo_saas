import { useState } from 'react'
import { Smartphone, Upload } from 'lucide-react'
import Modal from './Modal'
import { SCHEMA_OPTIONS } from '@/lib/documents'
import { DOCTYPE_OPTIONS, suggestDoctype } from '@/lib/digilocker'

interface Props {
  onClose: () => void
  onSubmit: (
    schemaName: string,
    beneficiaryId: string,
    options: { publishToDigiLocker: boolean; doctype: string },
  ) => void
}

/** Single-document issuance form (mirrors POST /api/v1/documents). */
export default function UploadDocumentModal({ onClose, onSubmit }: Props) {
  const [schemaName, setSchemaName] = useState<string>(SCHEMA_OPTIONS[0])
  const [beneficiaryId, setBeneficiaryId] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  // On by default: publishing to the citizen's locker at issuance is the
  // expected outcome, and an officer who forgets leaves the certificate
  // stranded in the repository where the citizen will never look for it.
  const [publishToDigiLocker, setPublishToDigiLocker] = useState(true)
  const [doctype, setDoctype] = useState<string | null>(null)

  // Follows the schema unless the officer has explicitly overridden it.
  const effectiveDoctype = doctype ?? suggestDoctype(schemaName)

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
    onSubmit(schemaName, id, {
      publishToDigiLocker,
      doctype: effectiveDoctype,
    })
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

        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={publishToDigiLocker}
              onChange={e => setPublishToDigiLocker(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-2 focus:ring-brand-500"
            />
            <span>
              <span className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
                <Smartphone size={15} className="text-brand-600" />
                Publish to DigiLocker
              </span>
              <span className="mt-0.5 block text-sm text-gray-500">
                Delivers the credential to the beneficiary&rsquo;s DigiLocker
                account as soon as it is issued.
              </span>
            </span>
          </label>

          {publishToDigiLocker && (
            <div className="mt-3 pl-7">
              <label
                htmlFor="doctype"
                className="block text-sm font-medium text-gray-700 mb-1.5"
              >
                DigiLocker document type
              </label>
              <select
                id="doctype"
                value={effectiveDoctype}
                onChange={e => setDoctype(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
              >
                {DOCTYPE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>
                    {o.value} — {o.label}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-xs text-gray-500">
                Suggested from the schema. DigiLocker rejects unknown types, so
                pick the closest match.
              </p>
            </div>
          )}
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
