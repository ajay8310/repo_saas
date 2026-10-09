import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, Ban, FileText, Award, Braces, Award as BadgeIcon, ImagePlus, Check } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import type { AssertionListItem } from '@/lib/badges'
import {
  downloadBadgeJson,
  downloadBadgePng,
  downloadCertificate,
  listAssertions,
  revokeAssertion,
  saveBlob,
  uploadRecipientPhoto,
} from '@/lib/badges'

/** Max student-photo size — mirrors backend certificate_photo_max_bytes (5 MB). */
const MAX_PHOTO_BYTES = 5 * 1024 * 1024
const ALLOWED_PHOTO_TYPES = ['image/png', 'image/jpeg'] as const

/** Read a File as base64 (without the data: URL prefix) for the JSON upload API. */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Could not read file'))
    reader.onload = () => {
      const result = String(reader.result)
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.readAsDataURL(file)
  })
}

/**
 * Issued Credentials (Documents) — live view of real badge assertions (U6).
 *
 * Each issued credential offers two downloadable credentials: the issuer-signed
 * certificate PDF (QR + digital signature) and the badge — in its two Open
 * Badges forms (a baked PNG and the raw OB2.0 JSON). Issuance itself lives on
 * the Badges page; this page lists what has been issued and lets you download,
 * verify, and revoke.
 */

const statusColors: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  revoked: 'bg-red-100 text-red-700',
  expired: 'bg-gray-100 text-gray-500',
}

export default function DocumentsPage() {
  const [rows, setRows] = useState<AssertionListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const { toast, notify } = useToast()

  // Student-photo upload: a single hidden file input, retargeted per row.
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [photoTargetId, setPhotoTargetId] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    listAssertions()
      .then(data => {
        setRows(Array.isArray(data) ? data : [])
        setError(false)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const shortId = (id: string) => id.slice(0, 8)

  const getCertificate = async (r: AssertionListItem) => {
    setBusyId(r.assertion_id)
    try {
      const blob = await downloadCertificate(r.assertion_id)
      saveBlob(blob, `certificate-${r.assertion_id}.pdf`)
      notify('Certificate (PDF) downloaded.')
    } catch {
      notify('Could not download the certificate.', 'error')
    } finally {
      setBusyId(null)
    }
  }

  const getBadgePng = async (r: AssertionListItem) => {
    setBusyId(r.assertion_id)
    try {
      const blob = await downloadBadgePng(r.assertion_id)
      saveBlob(blob, `badge-${r.assertion_id}.png`)
      notify('Badge (PNG) downloaded.')
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      notify(
        status === 422
          ? 'This badge has no PNG image to bake. Add a PNG badge image on the Badges page.'
          : 'Could not download the badge PNG.',
        'error',
      )
    } finally {
      setBusyId(null)
    }
  }

  const getBadgeJson = async (r: AssertionListItem) => {
    setBusyId(r.assertion_id)
    try {
      const blob = await downloadBadgeJson(r.assertion_id)
      saveBlob(blob, `badge-${r.assertion_id}.json`)
      notify('Badge (JSON) downloaded.')
    } catch {
      notify('Could not download the badge JSON.', 'error')
    } finally {
      setBusyId(null)
    }
  }

  /** Open the OS file picker for a specific credential's student photo. */
  const pickPhoto = (r: AssertionListItem) => {
    setPhotoTargetId(r.assertion_id)
    // Reset so re-selecting the same file still fires onChange.
    if (fileInputRef.current) fileInputRef.current.value = ''
    fileInputRef.current?.click()
  }

  /** Validate, encode, and upload the chosen student photo for the target row. */
  const onPhotoSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    const assertionId = photoTargetId
    setPhotoTargetId(null)
    if (!file || !assertionId) return

    if (!ALLOWED_PHOTO_TYPES.includes(file.type as (typeof ALLOWED_PHOTO_TYPES)[number])) {
      notify('Photo must be a PNG or JPEG image.', 'error')
      return
    }
    if (file.size > MAX_PHOTO_BYTES) {
      notify('Photo exceeds the 5 MB limit.', 'error')
      return
    }

    setBusyId(assertionId)
    try {
      const base64 = await fileToBase64(file)
      const contentType = file.type === 'image/png' ? 'image/png' : 'image/jpeg'
      await uploadRecipientPhoto(assertionId, base64, contentType)
      notify('Student photo uploaded. It will appear on the certificate.')
      load()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      notify(
        status === 503
          ? 'Photo could not be scanned right now. Try again shortly.'
          : 'Could not upload the student photo.',
        'error',
      )
    } finally {
      setBusyId(null)
    }
  }

  const revoke = async (r: AssertionListItem) => {
    const reason = window.prompt(`Revocation reason for ${shortId(r.assertion_id)} (1-500 chars):`)
    if (reason === null) return
    if (!reason.trim() || reason.length > 500) {
      notify('Revocation reason must be 1-500 characters.', 'error')
      return
    }
    try {
      await revokeAssertion(r.assertion_id, reason.trim())
      notify(`Revoked ${shortId(r.assertion_id)}.`)
      load()
    } catch {
      notify('Could not revoke on the server.', 'error')
    }
  }

  const filtered = rows.filter(
    r =>
      r.beneficiary_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.badge_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.assertion_id.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  return (
    <div>
      <Toast toast={toast} />

      {/* Single hidden file input, retargeted per row for student-photo upload. */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={onPhotoSelected}
        data-testid="photo-file-input"
      />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Issued Credentials</h1>
          <p className="text-gray-500 mt-1">
            Every issued credential has a certificate PDF and a badge (PNG + JSON). Upload a
            student photo to have it printed on the certificate.
          </p>
        </div>
        <Link
          to="/badges"
          className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
        >
          <BadgeIcon size={18} />
          Issue from Badges
        </Link>
      </div>

      <div className="flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search size={18} className="absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search by credential id, beneficiary, or badge..."
            className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Credential</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Badge</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Beneficiary</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Issued</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Downloads</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100" data-testid="documents-list">
            {filtered.map(r => (
              <tr key={r.assertion_id} className="hover:bg-gray-50" data-testid={`doc-row-${r.assertion_id}`}>
                <td className="px-6 py-4">
                  <code className="text-sm bg-gray-100 px-2 py-0.5 rounded">{shortId(r.assertion_id)}</code>
                </td>
                <td className="px-6 py-4 text-sm text-gray-700">{r.badge_name}</td>
                <td className="px-6 py-4 text-sm text-gray-600">{r.beneficiary_id}</td>
                <td className="px-6 py-4">
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[r.status] || statusColors.expired}`}>
                    {r.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-500">{r.issued_at?.slice(0, 10)}</td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-1">
                    <button
                      data-testid={`doc-cert-${r.assertion_id}`}
                      onClick={() => getCertificate(r)}
                      disabled={busyId === r.assertion_id}
                      className="flex items-center gap-1 text-xs px-2 py-1 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                      title="Download certificate (PDF)"
                    >
                      <FileText size={14} /> PDF
                    </button>
                    <button
                      data-testid={`doc-badge-png-${r.assertion_id}`}
                      onClick={() => getBadgePng(r)}
                      disabled={busyId === r.assertion_id}
                      className="flex items-center gap-1 text-xs px-2 py-1 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                      title="Download badge (PNG)"
                    >
                      <Award size={14} /> Badge
                    </button>
                    <button
                      data-testid={`doc-badge-json-${r.assertion_id}`}
                      onClick={() => getBadgeJson(r)}
                      disabled={busyId === r.assertion_id}
                      className="flex items-center gap-1 text-xs px-2 py-1 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                      title="Download badge (Open Badges JSON)"
                    >
                      <Braces size={14} /> JSON
                    </button>
                    <button
                      data-testid={`doc-photo-${r.assertion_id}`}
                      onClick={() => pickPhoto(r)}
                      disabled={busyId === r.assertion_id}
                      className={`flex items-center gap-1 text-xs px-2 py-1 rounded disabled:opacity-40 ${
                        r.has_photo
                          ? 'text-green-700 hover:text-green-800'
                          : 'text-gray-600 hover:text-brand-600'
                      }`}
                      title={
                        r.has_photo
                          ? 'Student photo attached — click to replace'
                          : 'Upload student photo (PNG/JPEG) for the certificate'
                      }
                    >
                      {r.has_photo ? <Check size={14} /> : <ImagePlus size={14} />} Photo
                    </button>
                    {r.status === 'active' && (
                      <button
                        data-testid={`doc-revoke-${r.assertion_id}`}
                        onClick={() => revoke(r)}
                        className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                        title="Revoke"
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-6 py-10 text-center text-sm text-gray-400">
                  {error
                    ? 'Could not load issued credentials.'
                    : rows.length === 0
                      ? 'No credentials issued yet. Issue badges from the Badges page.'
                      : `No credentials match "${searchQuery}".`}
                </td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={6} className="px-6 py-10 text-center text-sm text-gray-400">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
