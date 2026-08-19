import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  RefreshCw,
  Search,
  Send,
  Smartphone,
  XCircle,
} from 'lucide-react'

import { Toast, useToast } from '@/hooks/useToast'
import { type DocumentRow, loadDocuments } from '@/lib/documents'
import {
  DOCTYPE_OPTIONS,
  MAX_ATTEMPTS,
  type PublicationStatus,
  type PushRecord,
  findPush,
  loadPushes,
  publish,
  retry,
  savePushes,
  statusOf,
  suggestDoctype,
  summarise,
  upsert,
} from '@/lib/digilocker'

type StatusFilter = 'all' | 'not_published' | 'success' | 'failed'

const STATUS_STYLES: Record<
  PublicationStatus,
  { label: string; className: string }
> = {
  not_published: { label: 'Not published', className: 'bg-gray-100 text-gray-700' },
  pending: { label: 'Pending', className: 'bg-amber-100 text-amber-800' },
  retrying: { label: 'Retrying', className: 'bg-amber-100 text-amber-800' },
  success: { label: 'In DigiLocker', className: 'bg-green-100 text-green-800' },
  failed: { label: 'Failed', className: 'bg-red-100 text-red-800' },
  permanently_failed: { label: 'Failed', className: 'bg-red-100 text-red-800' },
}


export default function DigiLockerPage() {
  const [docs] = useState<DocumentRow[]>(() => loadDocuments())
  const [pushes, setPushes] = useState<PushRecord[]>(() => loadPushes())
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StatusFilter>('all')
  // Doctype overrides keyed by credential, so an officer can correct the
  // suggestion before sending without it being reset by a re-render.
  const [doctypes, setDoctypes] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const { toast, notify } = useToast()

  const persist = (next: PushRecord[]) => {
    setPushes(next)
    savePushes(next)
  }

  const doctypeFor = (doc: DocumentRow) =>
    doctypes[doc.credential_id] ??
    findPush(pushes, doc.credential_id)?.doctype ??
    suggestDoctype(doc.schema_name)

  const summary = useMemo(
    () => summarise(docs.map(d => d.credential_id), pushes),
    [docs, pushes],
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return docs.filter(doc => {
      const matchesQuery =
        !q ||
        doc.credential_id.toLowerCase().includes(q) ||
        doc.beneficiary_id.toLowerCase().includes(q) ||
        doc.schema_name.toLowerCase().includes(q)
      if (!matchesQuery) return false

      const status = statusOf(pushes, doc.credential_id)
      switch (filter) {
        case 'not_published':
          return status === 'not_published'
        case 'success':
          return status === 'success'
        case 'failed':
          return status === 'failed' || status === 'permanently_failed'
        default:
          return true
      }
    })
  }, [docs, pushes, query, filter])

  const handlePublish = (doc: DocumentRow) => {
    setBusy(doc.credential_id)
    const outcome = publish(pushes, {
      credentialId: doc.credential_id,
      doctype: doctypeFor(doc),
      documentStatus: doc.status,
    })
    setBusy(null)

    if (!outcome.ok || !outcome.record) {
      notify(outcome.error ?? 'Publication failed.', 'error')
      return
    }
    persist(upsert(pushes, outcome.record))
    notify(`${doc.credential_id} published to DigiLocker as ${outcome.record.doctype}`)
  }

  const handleRetry = (doc: DocumentRow) => {
    const record = findPush(pushes, doc.credential_id)
    if (!record) return
    setBusy(doc.credential_id)
    const outcome = retry(record)
    setBusy(null)

    if (!outcome.ok || !outcome.record) {
      notify(outcome.error ?? 'Retry failed.', 'error')
      return
    }
    persist(upsert(pushes, outcome.record))
    notify(`Retry succeeded for ${doc.credential_id}`)
  }

  const handlePublishAll = () => {
    const eligible = docs.filter(
      d => d.status === 'stored' && statusOf(pushes, d.credential_id) !== 'success',
    )
    if (eligible.length === 0) {
      notify('Nothing to publish — every valid credential is already in DigiLocker.')
      return
    }

    // Each credential is published independently so one rejection never blocks
    // the rest, matching how the backend processes a batch.
    let next = pushes
    let ok = 0
    let failed = 0
    eligible.forEach(doc => {
      const outcome = publish(next, {
        credentialId: doc.credential_id,
        doctype: doctypeFor(doc),
        documentStatus: doc.status,
      })
      if (outcome.ok && outcome.record) {
        next = upsert(next, outcome.record)
        ok += 1
      } else {
        failed += 1
      }
    })
    persist(next)
    notify(
      failed === 0
        ? `Published ${ok} credential${ok === 1 ? '' : 's'} to DigiLocker.`
        : `Published ${ok}, skipped ${failed}.`,
    )
  }

  const copyUri = async (uri: string) => {
    try {
      await navigator.clipboard.writeText(uri)
      notify('DigiLocker URI copied.')
    } catch {
      notify('Clipboard blocked by the browser.', 'error')
    }
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">DigiLocker</h1>
          <p className="text-gray-500 mt-1">
            Publish issued credentials to citizens&rsquo; DigiLocker accounts
          </p>
        </div>
        <button
          onClick={handlePublishAll}
          className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
        >
          <Send size={17} />
          Publish all pending
        </button>
      </div>

      {/* Sandbox mode is stated plainly. An officer who believes a certificate
          reached a citizen when it did not will not chase it up. */}
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
        <AlertTriangle size={18} className="text-amber-600 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-amber-900">
            Sandbox mode — publications are simulated
          </p>
          <p className="text-sm text-amber-800 mt-0.5">
            Records here are marked <code className="text-xs">sandbox</code> and
            nothing reaches a real DigiLocker account. Set{' '}
            <code className="text-xs">DIGILOCKER_MODE=live</code> with your
            Meripehchaan client credentials and issuer ID to publish for real.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'In DigiLocker', value: summary.published, icon: CheckCircle2, tone: 'text-green-600 bg-green-100' },
          { label: 'Not published', value: summary.notPublished, icon: Clock, tone: 'text-gray-600 bg-gray-100' },
          { label: 'Outstanding', value: summary.outstanding, icon: RefreshCw, tone: 'text-amber-600 bg-amber-100' },
          { label: 'Failed', value: summary.failed, icon: XCircle, tone: 'text-red-600 bg-red-100' },
        ].map(card => {
          const Icon = card.icon
          return (
            <div
              key={card.label}
              className="bg-white rounded-xl border border-gray-200 p-5 flex items-center justify-between"
            >
              <div>
                <p className="text-sm text-gray-500">{card.label}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1">{card.value}</p>
              </div>
              <span className={`w-10 h-10 rounded-xl flex items-center justify-center ${card.tone}`}>
                <Icon size={19} />
              </span>
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <div className="flex-1 min-w-[240px] relative">
          <Search size={18} className="absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by credential, beneficiary, or schema..."
            aria-label="Search credentials"
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>
        <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
          {([
            ['all', 'All'],
            ['not_published', 'Not published'],
            ['success', 'Published'],
            ['failed', 'Failed'],
          ] as [StatusFilter, string][]).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              aria-pressed={filter === value}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                filter === value
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <caption className="sr-only">
              Issued credentials and their DigiLocker publication status
            </caption>
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th scope="col" className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Credential</th>
                <th scope="col" className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Beneficiary</th>
                <th scope="col" className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Doc type</th>
                <th scope="col" className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">DigiLocker status</th>
                <th scope="col" className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map(doc => {
                const status = statusOf(pushes, doc.credential_id)
                const record = findPush(pushes, doc.credential_id)
                const style = STATUS_STYLES[status]
                const isRevoked = doc.status === 'revoked'
                const isPublished = status === 'success'
                const isFailed =
                  status === 'failed' || status === 'permanently_failed'

                return (
                  <tr key={doc.credential_id} className="hover:bg-gray-50 align-top">
                    <td className="px-6 py-4">
                      <code className="text-sm bg-gray-100 px-2 py-0.5 rounded">
                        {doc.credential_id}
                      </code>
                      <p className="text-xs text-gray-500 mt-1">{doc.schema_name}</p>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {doc.beneficiary_id}
                    </td>
                    <td className="px-6 py-4">
                      <select
                        value={doctypeFor(doc)}
                        onChange={e =>
                          setDoctypes(prev => ({
                            ...prev,
                            [doc.credential_id]: e.target.value,
                          }))
                        }
                        disabled={isPublished}
                        aria-label={`DigiLocker document type for ${doc.credential_id}`}
                        className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:ring-2 focus:ring-brand-500 outline-none disabled:bg-gray-50 disabled:text-gray-500"
                      >
                        {DOCTYPE_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>
                            {o.value} — {o.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style.className}`}
                      >
                        {style.label}
                      </span>
                      {record?.delivery_mode === 'sandbox' && isPublished && (
                        <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                          sandbox
                        </span>
                      )}
                      {record?.digilocker_uri && (
                        <div className="flex items-center gap-1.5 mt-1.5">
                          <code className="text-xs text-gray-500 break-all">
                            {record.digilocker_uri}
                          </code>
                          <button
                            onClick={() => copyUri(record.digilocker_uri!)}
                            title="Copy DigiLocker URI"
                            aria-label={`Copy DigiLocker URI for ${doc.credential_id}`}
                            className="p-1 text-gray-400 hover:text-brand-600 rounded shrink-0"
                          >
                            <Copy size={13} />
                          </button>
                        </div>
                      )}
                      {isFailed && record?.failure_reason && (
                        <p className="text-xs text-red-600 mt-1">
                          {record.failure_reason} (attempt {record.attempt_count}/
                          {MAX_ATTEMPTS})
                        </p>
                      )}
                      {isRevoked && !isPublished && (
                        <p className="text-xs text-gray-500 mt-1">
                          Revoked — not eligible for publication
                        </p>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {isPublished ? (
                        <span className="inline-flex items-center gap-1.5 text-sm text-green-700">
                          <CheckCircle2 size={15} />
                          Delivered
                        </span>
                      ) : isFailed ? (
                        <button
                          onClick={() => handleRetry(doc)}
                          disabled={busy === doc.credential_id}
                          className="inline-flex items-center gap-1.5 border border-gray-300 text-gray-700 px-3 py-1.5 rounded-lg text-sm hover:bg-gray-50 transition disabled:opacity-50"
                        >
                          <RefreshCw size={14} />
                          Retry
                        </button>
                      ) : (
                        <button
                          onClick={() => handlePublish(doc)}
                          disabled={isRevoked || busy === doc.credential_id}
                          title={
                            isRevoked
                              ? 'Revoked credentials cannot be published'
                              : undefined
                          }
                          className="inline-flex items-center gap-1.5 bg-brand-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-brand-700 transition disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <Smartphone size={14} />
                          Publish
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-10 text-center text-sm text-gray-400">
                    No credentials match the current search and filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
