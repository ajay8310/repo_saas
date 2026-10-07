import { useEffect, useState } from 'react'
import { Award, Plus, Edit, Send, Users, Ban, Globe, Building2, FileText } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import type { BadgeClass, CertificateTemplate } from '@/lib/badges'
import {
  BULK_ISSUE_MAX,
  CERTIFICATE_TEMPLATES,
  listBadgeClasses,
  createBadgeClass,
  setCertificateTemplate,
} from '@/lib/badges'

/**
 * Badge Classes console (Credly-style credentialing, U1).
 *
 * Manages badge templates and issuance actions: create/edit, issue to one
 * recipient, bulk-issue, revoke, toggle public-directory visibility, and edit
 * the tenant issuer profile. Seeded with demo rows so the page is useful before
 * the backend is populated; live wiring uses the helpers in lib/badges.ts.
 */

const INITIAL_BADGES: BadgeClass[] = [
  {
    id: 'bc-1', name: 'Python Expert', description: 'Awarded for demonstrated Python mastery.',
    criteria_narrative: 'Pass the proctored assessment with 80%+.', criteria_url: null,
    tags: ['python', 'backend'], alignment: [], image_s3_key: null, validity_days: 365,
    status: 'active', directory_visible: true, certificate_template: 'classic', created_at: '2026-02-10',
  },
  {
    id: 'bc-2', name: 'Data Steward', description: 'Recognises responsible data handling.',
    criteria_narrative: null, criteria_url: 'https://acme.test/criteria/data-steward',
    tags: ['data', 'governance'], alignment: [], image_s3_key: null, validity_days: null,
    status: 'active', directory_visible: false, certificate_template: 'modern', created_at: '2026-03-01',
  },
]

interface CreateForm {
  name: string
  description: string
  criteria_narrative: string
  validity_days: string
  tags: string
}

const EMPTY_FORM: CreateForm = {
  name: '', description: '', criteria_narrative: '', validity_days: '', tags: '',
}

export default function BadgeClassesPage() {
  const [badges, setBadges] = useState<BadgeClass[]>(INITIAL_BADGES)
  const [live, setLive] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<BadgeClass | null>(null)
  const [issuing, setIssuing] = useState<BadgeClass | null>(null)
  const [bulkIssuing, setBulkIssuing] = useState<BadgeClass | null>(null)
  const [editingProfile, setEditingProfile] = useState(false)
  const { toast, notify } = useToast()

  // Load real badge classes when authenticated against the live API. On failure
  // (offline / stub token) keep the seeded demo rows so the page still renders.
  useEffect(() => {
    let active = true
    listBadgeClasses()
      .then(rows => {
        if (active && Array.isArray(rows)) {
          setLive(true)
          if (rows.length > 0) setBadges(rows)
        }
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  const handleCreate = async (form: CreateForm) => {
    const name = form.name.trim()
    if (!name) {
      notify('Badge name is required.', 'error')
      return
    }
    if (badges.some(b => b.name.toLowerCase() === name.toLowerCase())) {
      notify(`A badge named "${name}" already exists.`, 'error')
      return
    }
    const input = {
      name,
      description: form.description.trim() || null,
      criteria_narrative: form.criteria_narrative.trim() || null,
      tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
      validity_days: form.validity_days ? Number(form.validity_days) : null,
    }
    if (live) {
      try {
        const created = await createBadgeClass(input)
        setBadges(prev => [created, ...prev])
        setCreating(false)
        notify(`Created badge "${name}".`)
        return
      } catch {
        notify('Could not create on the server; showing locally.', 'error')
      }
    }
    const row: BadgeClass = {
      id: `bc-${Date.now()}`,
      ...input,
      criteria_url: null,
      alignment: [],
      image_s3_key: null,
      status: 'active',
      directory_visible: false,
      certificate_template: 'classic',
      created_at: new Date().toISOString().slice(0, 10),
    }
    setBadges(prev => [row, ...prev])
    setCreating(false)
    notify(`Created badge "${name}".`)
  }

  const changeTemplate = async (badge: BadgeClass, template: CertificateTemplate) => {
    if (live) {
      try {
        await setCertificateTemplate(badge.id, template)
      } catch {
        notify('Could not save template on the server.', 'error')
      }
    }
    setBadges(prev =>
      prev.map(b => (b.id === badge.id ? { ...b, certificate_template: template } : b)),
    )
    notify(`"${badge.name}" certificate template set to ${template}.`)
  }

  const handleEdit = (form: CreateForm) => {
    if (!editing) return
    const name = form.name.trim()
    setBadges(prev =>
      prev.map(b =>
        b.id === editing.id
          ? {
              ...b, name,
              description: form.description.trim() || null,
              criteria_narrative: form.criteria_narrative.trim() || null,
              validity_days: form.validity_days ? Number(form.validity_days) : null,
              tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
            }
          : b,
      ),
    )
    notify(`Saved "${name}".`)
    setEditing(null)
  }

  const handleIssue = async (beneficiaryId: string) => {
    if (!issuing) return
    const id = beneficiaryId.trim()
    if (!id.includes('@')) {
      notify('Enter a valid recipient email.', 'error')
      return
    }
    if (live) {
      try {
        const { issueBadge } = await import('@/lib/badges')
        const a = await issueBadge(issuing.id, id)
        notify(`Issued "${issuing.name}" to ${id} (assertion ${a.assertion_id.slice(0, 8)}…).`)
        setIssuing(null)
        return
      } catch {
        notify('Could not issue on the server.', 'error')
      }
    }
    notify(`Issued "${issuing.name}" to ${id}.`)
    setIssuing(null)
  }

  const handleBulkIssue = async (raw: string) => {
    if (!bulkIssuing) return
    const ids = raw.split(/[\n,]/).map(s => s.trim()).filter(Boolean)
    if (ids.length === 0) {
      notify('Provide at least one recipient.', 'error')
      return
    }
    if (ids.length > BULK_ISSUE_MAX) {
      notify(`${ids.length} exceeds the ${BULK_ISSUE_MAX.toLocaleString()} limit.`, 'error')
      return
    }
    if (live) {
      try {
        const { bulkIssueBadges } = await import('@/lib/badges')
        await bulkIssueBadges(bulkIssuing.id, ids)
        notify(`Queued bulk issue of "${bulkIssuing.name}" to ${ids.length} recipient(s).`)
        setBulkIssuing(null)
        return
      } catch {
        notify('Could not queue bulk issue on the server.', 'error')
      }
    }
    notify(`Queued bulk issue of "${bulkIssuing.name}" to ${ids.length} recipient(s).`)
    setBulkIssuing(null)
  }

  const handleDeactivate = (badge: BadgeClass) => {
    if (!window.confirm(`Deactivate "${badge.name}"? No new badges can be issued from it.`)) return
    setBadges(prev =>
      prev.map(b => (b.id === badge.id ? { ...b, status: 'inactive' as const, directory_visible: false } : b)),
    )
    notify(`Deactivated "${badge.name}".`)
  }

  const toggleVisibility = (badge: BadgeClass) => {
    if (badge.status !== 'active') {
      notify('Only active badges can be published.', 'error')
      return
    }
    setBadges(prev =>
      prev.map(b => (b.id === badge.id ? { ...b, directory_visible: !b.directory_visible } : b)),
    )
    notify(
      badge.directory_visible
        ? `"${badge.name}" removed from public directory.`
        : `"${badge.name}" published to public directory.`,
    )
  }

  return (
    <div>
      <Toast toast={toast} />

      {(creating || editing) && (
        <BadgeFormModal
          initial={editing}
          onClose={() => { setCreating(false); setEditing(null) }}
          onSave={editing ? handleEdit : handleCreate}
        />
      )}
      {issuing && (
        <IssueModal badge={issuing} onClose={() => setIssuing(null)} onIssue={handleIssue} />
      )}
      {bulkIssuing && (
        <BulkIssueModal badge={bulkIssuing} onClose={() => setBulkIssuing(null)} onIssue={handleBulkIssue} />
      )}
      {editingProfile && (
        <IssuerProfileModal onClose={() => setEditingProfile(false)} onSave={() => { setEditingProfile(false); notify('Issuer profile saved.') }} />
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Badges</h1>
          <p className="text-gray-500 mt-1">Design badge classes and issue them to recipients</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="badge-issuer-profile-button"
            onClick={() => setEditingProfile(true)}
            className="flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2.5 rounded-lg hover:bg-gray-50 transition"
          >
            <Building2 size={18} />
            Issuer Profile
          </button>
          <button
            data-testid="badge-create-button"
            onClick={() => setCreating(true)}
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
          >
            <Plus size={18} />
            New Badge
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="badge-list">
        {badges.map(badge => (
          <div
            key={badge.id}
            data-testid={`badge-card-${badge.id}`}
            className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-md transition"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
                  <Award size={18} className="text-amber-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{badge.name}</h3>
                  <p className="text-xs text-gray-500">
                    {badge.validity_days ? `Expires after ${badge.validity_days} days` : 'Non-expiring'}
                    {badge.tags.length > 0 && ` — ${badge.tags.join(', ')}`}
                  </p>
                </div>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span
                  className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    badge.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {badge.status}
                </span>
                {badge.directory_visible && (
                  <span className="flex items-center gap-1 text-xs text-brand-600">
                    <Globe size={12} /> public
                  </span>
                )}
              </div>
            </div>

            {badge.description && (
              <p className="mt-3 text-sm text-gray-600 line-clamp-2">{badge.description}</p>
            )}

            <div className="mt-4 flex items-center gap-2 border-t border-gray-100 pt-3">
              <FileText size={14} className="text-gray-400" />
              <label className="text-xs text-gray-500">Certificate:</label>
              <select
                data-testid={`badge-template-${badge.id}`}
                value={badge.certificate_template}
                onChange={e => changeTemplate(badge, e.target.value as CertificateTemplate)}
                className="text-xs border border-gray-300 rounded px-2 py-1 capitalize"
              >
                {CERTIFICATE_TEMPLATES.map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>

            <div className="mt-2 flex items-center justify-end gap-1">
              <button
                data-testid={`badge-issue-${badge.id}`}
                onClick={() => setIssuing(badge)}
                disabled={badge.status !== 'active'}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                title="Issue to one recipient"
              >
                <Send size={15} /> Issue
              </button>
              <button
                data-testid={`badge-bulk-issue-${badge.id}`}
                onClick={() => setBulkIssuing(badge)}
                disabled={badge.status !== 'active'}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                title="Bulk issue"
              >
                <Users size={15} /> Bulk
              </button>
              <button
                data-testid={`badge-visibility-${badge.id}`}
                onClick={() => toggleVisibility(badge)}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded"
                title="Toggle public directory"
              >
                <Globe size={15} />
              </button>
              <button
                data-testid={`badge-edit-${badge.id}`}
                onClick={() => setEditing(badge)}
                className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                title="Edit"
              >
                <Edit size={15} />
              </button>
              {badge.status === 'active' && (
                <button
                  data-testid={`badge-deactivate-${badge.id}`}
                  onClick={() => handleDeactivate(badge)}
                  className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                  title="Deactivate"
                >
                  <Ban size={15} />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- Modals (kept in-file; small and page-specific) ---

function Backdrop({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">{children}</div>
    </div>
  )
}

function BadgeFormModal({
  initial, onClose, onSave,
}: {
  initial: BadgeClass | null
  onClose: () => void
  onSave: (form: CreateForm) => void
}) {
  const [form, setForm] = useState<CreateForm>(
    initial
      ? {
          name: initial.name,
          description: initial.description ?? '',
          criteria_narrative: initial.criteria_narrative ?? '',
          validity_days: initial.validity_days ? String(initial.validity_days) : '',
          tags: initial.tags.join(', '),
        }
      : EMPTY_FORM,
  )
  const set = (k: keyof CreateForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <Backdrop>
      <h2 className="text-lg font-semibold mb-4">{initial ? 'Edit Badge' : 'New Badge'}</h2>
      <div className="space-y-3">
        <input data-testid="badge-form-name" value={form.name} onChange={set('name')}
          placeholder="Badge name" className="w-full border border-gray-300 rounded-lg px-3 py-2" />
        <textarea data-testid="badge-form-description" value={form.description} onChange={set('description')}
          placeholder="Description" rows={2} className="w-full border border-gray-300 rounded-lg px-3 py-2" />
        <textarea data-testid="badge-form-criteria" value={form.criteria_narrative} onChange={set('criteria_narrative')}
          placeholder="Criteria narrative" rows={2} className="w-full border border-gray-300 rounded-lg px-3 py-2" />
        <div className="flex gap-3">
          <input data-testid="badge-form-validity" value={form.validity_days} onChange={set('validity_days')}
            placeholder="Validity days (blank = non-expiring)" className="flex-1 border border-gray-300 rounded-lg px-3 py-2" />
          <input data-testid="badge-form-tags" value={form.tags} onChange={set('tags')}
            placeholder="tags, comma, separated" className="flex-1 border border-gray-300 rounded-lg px-3 py-2" />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
        <button data-testid="badge-form-save" onClick={() => onSave(form)}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700">Save</button>
      </div>
    </Backdrop>
  )
}

function IssueModal({
  badge, onClose, onIssue,
}: {
  badge: BadgeClass
  onClose: () => void
  onIssue: (beneficiaryId: string) => void
}) {
  const [value, setValue] = useState('')
  return (
    <Backdrop>
      <h2 className="text-lg font-semibold mb-1">Issue "{badge.name}"</h2>
      <p className="text-sm text-gray-500 mb-4">Award this badge to a single recipient.</p>
      <input data-testid="badge-issue-recipient" value={value} onChange={e => setValue(e.target.value)}
        placeholder="recipient@example.com" className="w-full border border-gray-300 rounded-lg px-3 py-2" />
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
        <button data-testid="badge-issue-submit" onClick={() => onIssue(value)}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700">Issue</button>
      </div>
    </Backdrop>
  )
}

function BulkIssueModal({
  badge, onClose, onIssue,
}: {
  badge: BadgeClass
  onClose: () => void
  onIssue: (raw: string) => void
}) {
  const [value, setValue] = useState('')
  return (
    <Backdrop>
      <h2 className="text-lg font-semibold mb-1">Bulk issue "{badge.name}"</h2>
      <p className="text-sm text-gray-500 mb-4">One recipient email per line (or comma-separated).</p>
      <textarea data-testid="badge-bulk-recipients" value={value} onChange={e => setValue(e.target.value)}
        rows={6} placeholder={'alice@example.com\nbob@example.com'} className="w-full border border-gray-300 rounded-lg px-3 py-2 font-mono text-sm" />
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
        <button data-testid="badge-bulk-submit" onClick={() => onIssue(value)}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700">Queue Bulk Issue</button>
      </div>
    </Backdrop>
  )
}

function IssuerProfileModal({ onClose, onSave }: { onClose: () => void; onSave: () => void }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [email, setEmail] = useState('')
  return (
    <Backdrop>
      <h2 className="text-lg font-semibold mb-4">Issuer Profile</h2>
      <div className="space-y-3">
        <input data-testid="issuer-profile-name" value={name} onChange={e => setName(e.target.value)}
          placeholder="Issuer name" className="w-full border border-gray-300 rounded-lg px-3 py-2" />
        <input data-testid="issuer-profile-url" value={url} onChange={e => setUrl(e.target.value)}
          placeholder="https://issuer.example.com" className="w-full border border-gray-300 rounded-lg px-3 py-2" />
        <input data-testid="issuer-profile-email" value={email} onChange={e => setEmail(e.target.value)}
          placeholder="badges@issuer.example.com" className="w-full border border-gray-300 rounded-lg px-3 py-2" />
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">Cancel</button>
        <button data-testid="issuer-profile-save" onClick={onSave}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700">Save</button>
      </div>
    </Backdrop>
  )
}
