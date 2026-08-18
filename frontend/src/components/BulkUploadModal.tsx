import { useRef, useState } from 'react'
import { Upload, FileText, CheckCircle2, AlertCircle } from 'lucide-react'
import Modal from './Modal'
import {
  BULK_MAX_RECORDS,
  BulkParseError,
  SCHEMA_OPTIONS,
  evaluateBulk,
  parseBulkContent,
  type BulkOutcome,
} from '@/lib/documents'

interface Props {
  onClose: () => void
  onCommit: (schemaName: string, outcome: BulkOutcome) => void
}

const SAMPLE = `beneficiary_id,student_name,grade
amit@example.com,Amit Sharma,A
priya@example.com,Priya Nair,B
,Missing Id,C`

/** Bulk issuance flow (mirrors POST /api/v1/documents/bulk). */
export default function BulkUploadModal({ onClose, onCommit }: Props) {
  const [schemaName, setSchemaName] = useState<string>(SCHEMA_OPTIONS[0])
  const [raw, setRaw] = useState('')
  const [error, setError] = useState('')
  const [outcome, setOutcome] = useState<BulkOutcome | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const name = file.name.toLowerCase()
    if (!name.endsWith('.csv') && !name.endsWith('.json')) {
      setError('Only .csv and .json files are supported (Req 3.9).')
      return
    }
    setError('')
    setOutcome(null)
    setRaw(await file.text())
  }

  const handleValidate = () => {
    setError('')
    try {
      setOutcome(evaluateBulk(parseBulkContent(raw)))
    } catch (err) {
      setOutcome(null)
      setError(err instanceof BulkParseError ? err.message : 'Could not parse content.')
    }
  }

  return (
    <Modal
      title="Bulk Upload"
      subtitle={`CSV or JSON, up to ${BULK_MAX_RECORDS.toLocaleString()} records`}
      onClose={onClose}
      widthClass="max-w-2xl"
    >
      <div className="space-y-4">
        <div>
          <label
            htmlFor="bulk-schema"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Document Schema
          </label>
          <select
            id="bulk-schema"
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

        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.json"
            onChange={handleFile}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="flex items-center gap-2 border border-gray-300 px-4 py-2 rounded-lg text-sm hover:bg-gray-50 transition"
          >
            <FileText size={16} />
            Choose file
          </button>
          <button
            type="button"
            onClick={() => {
              setRaw(SAMPLE)
              setOutcome(null)
              setError('')
            }}
            className="text-sm text-brand-600 hover:text-brand-700"
          >
            Load sample
          </button>
        </div>

        <div>
          <label
            htmlFor="bulk-content"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Records
          </label>
          <textarea
            id="bulk-content"
            value={raw}
            onChange={e => {
              setRaw(e.target.value)
              setOutcome(null)
            }}
            rows={8}
            placeholder={SAMPLE}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg font-mono text-xs focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        {outcome && (
          <div className="border border-gray-200 rounded-xl overflow-hidden">
            <div className="grid grid-cols-3 divide-x divide-gray-200 bg-gray-50 text-center">
              <div className="px-3 py-2.5">
                <p className="text-lg font-bold text-gray-900">{outcome.total}</p>
                <p className="text-xs text-gray-500">Records</p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-lg font-bold text-green-700">
                  {outcome.succeeded.length}
                </p>
                <p className="text-xs text-gray-500">Valid</p>
              </div>
              <div className="px-3 py-2.5">
                <p className="text-lg font-bold text-red-700">
                  {outcome.failed.length}
                </p>
                <p className="text-xs text-gray-500">Failed</p>
              </div>
            </div>

            {outcome.failed.length > 0 && (
              <ul className="divide-y divide-gray-100 max-h-32 overflow-auto">
                {outcome.failed.map(f => (
                  <li
                    key={f.index}
                    className="flex items-start gap-2 px-4 py-2 text-xs text-gray-600"
                  >
                    <AlertCircle size={13} className="text-red-500 mt-0.5 shrink-0" />
                    <span>
                      Row {f.index + 1}: {f.reason}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex gap-3 pt-1">
          {!outcome ? (
            <button
              type="button"
              onClick={handleValidate}
              disabled={!raw.trim()}
              className="flex items-center gap-2 bg-gray-800 text-white px-4 py-2.5 rounded-lg hover:bg-gray-900 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <CheckCircle2 size={16} />
              Validate
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onCommit(schemaName, outcome)}
              disabled={outcome.succeeded.length === 0}
              className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Upload size={16} />
              Issue {outcome.succeeded.length} credential
              {outcome.succeeded.length === 1 ? '' : 's'}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 text-gray-600 hover:text-gray-900 transition"
          >
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  )
}
