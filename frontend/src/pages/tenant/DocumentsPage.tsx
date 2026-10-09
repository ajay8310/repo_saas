import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Search, Ban, FileText, Award, Braces, Award as BadgeIcon, ImagePlus, Check,
  FileArchive, X,
} from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import type { AssertionListItem, BadgeClass } from '@/lib/badges'
import {
  bulkIssueZip,
  bulkPhotosZip,
  downloadBadgeJson,
  downloadBadgePng,
  downloadCertificate,
  listAssertions,
  listBadgeClasses,
  revokeAssertion,
  saveBlob,
  uploadRecipientPhoto,
} from '@/lib/badges'

/** Max ZIP size — mirrors backend bulk_zip_max_bytes (100 MB). */
const MAX_ZIP_BYTES = 100 * 1024 * 1024

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

  // Bulk upload (ZIP of recipients + photos) and bulk photos-only (later upload).
  const [showBulk, setShowBulk] = useState(false)
  const [showPhotos, setShowPhotos] = useState(false)
  const [classes, setClasses] = useState<BadgeClass[]>([])

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

  // Badge classes power the bulk-upload class picker; silent on failure.
  useEffect(() => {
    listBadgeClasses()
      .then(data => setClasses(Array.isArray(data) ? data.filter(c => c.status === 'active') : []))
      .catch(() => setClasses([]))
  }, [])

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

      <div className="flex items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">Issued Credentials</h1>
          <p className="text-gray-500 mt-1">
            Every issued credential has a certificate PDF and a badge (PNG + JSON). Upload a
            student photo to have it printed on the certificate.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            data-testid="docs-bulk-upload"
            onClick={() => setShowBulk(true)}
            className="flex items-center gap-2 whitespace-nowrap bg-brand-600 text-white px-3.5 py-2.5 rounded-lg hover:bg-brand-700 transition"
            title="Issue credentials (and optionally their photos) from one ZIP"
          >
            <FileArchive size={18} className="shrink-0" />
            Bulk upload
          </button>
          <button
            data-testid="docs-bulk-photos"
            onClick={() => setShowPhotos(true)}
            className="flex items-center gap-2 whitespace-nowrap border border-gray-300 text-gray-700 px-3.5 py-2.5 rounded-lg hover:bg-gray-50 transition"
            title="Attach photos to already-issued credentials (upload photos later)"
          >
            <ImagePlus size={18} className="shrink-0" />
            Bulk photos
          </button>
          <Link
            to="/badges"
            className="flex items-center gap-2 whitespace-nowrap border border-gray-300 text-gray-700 px-3.5 py-2.5 rounded-lg hover:bg-gray-50 transition"
            title="Issue a badge to a recipient from the Badges page"
          >
            <BadgeIcon size={18} className="shrink-0" />
            Issue
          </Link>
        </div>
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

      {showBulk && (
        <BulkZipModal
          classes={classes}
          onClose={() => setShowBulk(false)}
          onDone={() => {
            setShowBulk(false)
            load()
          }}
          notify={notify}
        />
      )}

      {showPhotos && (
        <BulkPhotosModal
          classes={classes}
          onClose={() => setShowPhotos(false)}
          onDone={() => {
            setShowPhotos(false)
            load()
          }}
          notify={notify}
        />
      )}
    </div>
  )
}

/**
 * Bulk photos (ZIP) modal — attach photos to already-issued credentials.
 *
 * Decouples photos from issuance: upload a ZIP of images now and they attach to
 * each recipient's existing credential(s), matched by email (filename stem or an
 * optional photos.csv/json map). Optional badge-class scope.
 */
function BulkPhotosModal({
  classes, onClose, onDone, notify,
}: {
  classes: BadgeClass[]
  onClose: () => void
  onDone: () => void
  notify: (msg: string, kind?: 'success' | 'error') => void
}) {
  const [badgeClassId, setBadgeClassId] = useState<string>('') // '' = all classes
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const zipRef = useRef<HTMLInputElement>(null)

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0]
    if (!picked) return
    const isZip = picked.name.toLowerCase().endsWith('.zip') ||
      picked.type === 'application/zip' || picked.type === 'application/x-zip-compressed'
    if (!isZip) {
      notify('Please choose a .zip archive.', 'error')
      return
    }
    if (picked.size > MAX_ZIP_BYTES) {
      notify('ZIP exceeds the 100 MB limit.', 'error')
      return
    }
    setFile(picked)
  }

  const submit = async () => {
    if (!file) {
      notify('Choose a .zip of photos.', 'error')
      return
    }
    setBusy(true)
    setProgress(0)
    try {
      const res = await bulkPhotosZip(file, badgeClassId || undefined, setProgress)
      const unmatched = res.errors.filter(e => /no issued credential/i.test(e.error)).length
      const unmatchedNote = unmatched ? `, ${unmatched} with no credential yet` : ''
      notify(
        `Queued ${res.total} photo(s)${unmatchedNote}. ` +
        'Matching credentials will show the photo shortly.',
      )
      onDone()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail?.message
      notify(msg ? `ZIP rejected: ${msg}` : 'Could not upload the photos ZIP.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-lg font-semibold text-gray-900">Bulk upload photos</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Attach photos to <strong>already-issued</strong> credentials. Upload a <strong>.zip</strong>
          {' '}of images named by recipient email (<code>alice@example.com.png</code>), or include an
          {' '}optional <code>photos.csv</code> mapping <code>filename</code> to <code>beneficiary_id</code>.
          Recipients with no issued credential yet are reported and skipped.
        </p>

        <label className="block text-sm font-medium text-gray-700 mb-1.5">Badge class (optional)</label>
        <select
          data-testid="docs-photos-class"
          value={badgeClassId}
          onChange={e => setBadgeClassId(e.target.value)}
          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg mb-4 focus:ring-2 focus:ring-brand-500 outline-none"
        >
          <option value="">All of each recipient's credentials</option>
          {classes.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <input ref={zipRef} type="file" accept=".zip,application/zip" className="hidden"
          data-testid="docs-photos-zip-input" onChange={onFile} />
        <button
          type="button"
          onClick={() => zipRef.current?.click()}
          data-testid="docs-photos-zip-pick"
          className="flex items-center gap-2 text-sm px-3 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 w-full justify-center"
        >
          <ImagePlus size={16} />
          {file ? `Archive: ${file.name}` : 'Choose ZIP of photos'}
        </button>
        <p className="text-xs text-gray-400 mt-1">
          Photos: PNG or JPEG, up to 5 MB each. Archive up to 100 MB (uploaded directly to storage).
        </p>

        {busy && progress > 0 && progress < 1 && (
          <div className="mt-3">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-brand-600 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <p className="text-xs text-gray-400 mt-1">Uploading… {Math.round(progress * 100)}%</p>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            data-testid="docs-photos-submit"
            onClick={submit}
            disabled={!file || busy}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-40"
          >
            <ImagePlus size={16} />
            {busy ? 'Uploading…' : 'Upload photos'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Bulk upload (ZIP) modal — issue credentials + attach photos in one archive.
 *
 * The ZIP holds a recipients.csv/json manifest plus photo images matched per
 * recipient. Posts to the bulk-issue-zip endpoint; a one-row manifest + one
 * photo is the single-upload case too.
 */
function BulkZipModal({
  classes, onClose, onDone, notify,
}: {
  classes: BadgeClass[]
  onClose: () => void
  onDone: () => void
  notify: (msg: string, kind?: 'success' | 'error') => void
}) {
  const [badgeClassId, setBadgeClassId] = useState<string>(classes[0]?.id ?? '')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const zipRef = useRef<HTMLInputElement>(null)

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0]
    if (!picked) return
    const isZip = picked.name.toLowerCase().endsWith('.zip') ||
      picked.type === 'application/zip' || picked.type === 'application/x-zip-compressed'
    if (!isZip) {
      notify('Please choose a .zip archive.', 'error')
      return
    }
    if (picked.size > MAX_ZIP_BYTES) {
      notify('ZIP exceeds the 100 MB limit.', 'error')
      return
    }
    setFile(picked)
  }

  const submit = async () => {
    if (!badgeClassId) {
      notify('Choose a badge class.', 'error')
      return
    }
    if (!file) {
      notify('Choose a .zip archive.', 'error')
      return
    }
    setBusy(true)
    setProgress(0)
    try {
      const res = await bulkIssueZip(badgeClassId, file, setProgress)
      const errNote = res.errors.length ? `, ${res.errors.length} row error(s)` : ''
      notify(
        `Queued ${res.total} recipient(s) (${res.with_photo} with photo${errNote}). ` +
        'Credentials will appear here shortly.',
      )
      onDone()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail?.message
      notify(msg ? `ZIP rejected: ${msg}` : 'Could not upload the ZIP.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-lg font-semibold text-gray-900">Bulk upload credentials + photos</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Upload one <strong>.zip</strong> containing a <code>recipients.csv</code> (or .json)
          manifest and a <code>photos/</code> folder. Each row needs a <code>beneficiary_id</code>;
          an optional <code>photo</code> column names the image, otherwise
          {' '}<code>photos/&lt;email&gt;.png</code> is matched. One row + one photo also works
          as a single upload.
        </p>

        <label className="block text-sm font-medium text-gray-700 mb-1.5">Badge class</label>
        <select
          data-testid="docs-bulk-class"
          value={badgeClassId}
          onChange={e => setBadgeClassId(e.target.value)}
          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg mb-4 focus:ring-2 focus:ring-brand-500 outline-none"
        >
          {classes.length === 0 && <option value="">No active badge classes</option>}
          {classes.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <input ref={zipRef} type="file" accept=".zip,application/zip" className="hidden"
          data-testid="docs-bulk-zip-input" onChange={onFile} />
        <button
          type="button"
          onClick={() => zipRef.current?.click()}
          data-testid="docs-bulk-zip-pick"
          className="flex items-center gap-2 text-sm px-3 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 w-full justify-center"
        >
          <FileArchive size={16} />
          {file ? `Archive: ${file.name}` : 'Choose ZIP archive'}
        </button>
        <p className="text-xs text-gray-400 mt-1">
          Photos: PNG or JPEG, up to 5 MB each. Archive up to 100 MB (uploaded directly to storage).
        </p>

        {busy && progress > 0 && progress < 1 && (
          <div className="mt-3">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-brand-600 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <p className="text-xs text-gray-400 mt-1">Uploading… {Math.round(progress * 100)}%</p>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            data-testid="docs-bulk-submit"
            onClick={submit}
            disabled={!file || !badgeClassId || busy}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-40"
          >
            <FileArchive size={16} />
            {busy ? 'Uploading…' : 'Upload & issue'}
          </button>
        </div>
      </div>
    </div>
  )
}
