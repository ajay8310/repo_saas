import { useEffect, useMemo, useState } from 'react'
import { Bell, BellOff, Mail, MessageSquare, Save, RotateCcw, AlertTriangle } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { Toast, useToast } from '@/hooks/useToast'
import {
  type Channel,
  type Preferences,
  DEFAULT_PREFERENCES,
  EVENT_TOGGLES,
  anyEventEnabled,
  deliveryBlockedReason,
  loadPreferences,
  savePreferences,
  validatePreferences,
} from '@/lib/notifications'

const CHANNELS: { value: Channel; label: string; icon: typeof Mail; hint: string }[] = [
  { value: 'email', label: 'Email', icon: Mail, hint: 'Delivered via SES' },
  { value: 'sms', label: 'SMS', icon: MessageSquare, hint: 'Delivered via SNS' },
]

export default function NotificationsPage() {
  const { user } = useAuth()
  const beneficiaryId = user?.sub ?? 'unknown'
  const { toast, notify } = useToast()

  const [saved, setSaved] = useState<Preferences>(DEFAULT_PREFERENCES)
  const [draft, setDraft] = useState<Preferences>(DEFAULT_PREFERENCES)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Seed the form from storage, defaulting the contact email to the signed-in
  // identity since beneficiary IDs are email addresses.
  useEffect(() => {
    const loaded = loadPreferences(beneficiaryId)
    if (!loaded.contact_email && beneficiaryId.includes('@')) {
      loaded.contact_email = beneficiaryId
    }
    setSaved(loaded)
    setDraft(loaded)
  }, [beneficiaryId])

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(saved),
    [draft, saved],
  )
  const blocked = deliveryBlockedReason(draft)
  const allOff = !anyEventEnabled(draft)

  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }))
    setErrors(prev => ({ ...prev, [key]: '' }))
  }
  const handleSave = () => {
    const found = validatePreferences(draft)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      notify('Fix the highlighted fields before saving.', 'error')
      return
    }
    // Persist the same normalised form the router would store.
    const normalized: Preferences = {
      ...draft,
      contact_email: draft.contact_email.trim(),
      contact_phone: draft.contact_phone.trim().replace(/[\s-]/g, ''),
    }
    savePreferences(beneficiaryId, normalized)
    setSaved(normalized)
    setDraft(normalized)
    setErrors({})
    notify(
      anyEventEnabled(normalized)
        ? 'Notification preferences saved.'
        : 'Saved — every event notification is now switched off.',
    )
  }

  const handleReset = () => {
    setDraft(saved)
    setErrors({})
    notify('Reverted to your last saved preferences.')
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Notifications</h1>
        <p className="text-gray-500 mt-1">
          Choose which events reach you, and how they get delivered
        </p>
      </div>

      <div className="space-y-4 max-w-3xl">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center">
              <Bell size={20} className="text-blue-600" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Events</h2>
              <p className="text-sm text-gray-500">
                Pick the moments you want to hear about.
              </p>
            </div>
          </div>

          <div className="divide-y divide-gray-100">
            {EVENT_TOGGLES.map(ev => (
              <div
                key={ev.key}
                className="flex items-start justify-between gap-4 py-3"
              >
                <div>
                  <p className="font-medium text-gray-900 text-sm">{ev.label}</p>
                  <p className="text-sm text-gray-500 mt-0.5">{ev.blurb}</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={draft[ev.key]}
                  aria-label={ev.label}
                  onClick={() => set(ev.key, !draft[ev.key])}
                  className={`relative shrink-0 w-11 h-6 rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
                    draft[ev.key] ? 'bg-blue-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                      draft[ev.key] ? 'translate-x-5' : ''
                    }`}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-900">Delivery channel</h2>
          <p className="text-sm text-gray-500 mt-0.5 mb-4">
            Only the selected channel is used — the other contact detail is kept
            on file but stays idle.
          </p>

          <div className="grid sm:grid-cols-2 gap-3">
            {CHANNELS.map(ch => {
              const Icon = ch.icon
              const active = draft.preferred_channel === ch.value
              return (
                <button
                  key={ch.value}
                  type="button"
                  onClick={() => set('preferred_channel', ch.value)}
                  aria-pressed={active}
                  className={`flex items-center gap-3 p-4 rounded-xl border-2 text-left transition-colors ${
                    active
                      ? 'border-blue-600 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <Icon
                    size={20}
                    className={active ? 'text-blue-600' : 'text-gray-400'}
                  />
                  <div>
                    <p className="font-medium text-gray-900 text-sm">{ch.label}</p>
                    <p className="text-xs text-gray-500">{ch.hint}</p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-900">Contact details</h2>
          <p className="text-sm text-gray-500 mt-0.5 mb-4">
            Where notifications are sent. Clearing the field for your selected
            channel stops delivery.
          </p>

          <div className="space-y-4">
            <div>
              <label
                htmlFor="contact_email"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Contact email
              </label>
              <input
                id="contact_email"
                type="email"
                value={draft.contact_email}
                onChange={e => set('contact_email', e.target.value)}
                placeholder="you@example.com"
                maxLength={255}
                aria-invalid={Boolean(errors.contact_email)}
                aria-describedby={
                  errors.contact_email ? 'contact_email_error' : undefined
                }
                className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 ${
                  errors.contact_email
                    ? 'border-red-400 focus:ring-red-500'
                    : 'border-gray-300 focus:ring-blue-500'
                }`}
              />
              {errors.contact_email && (
                <p id="contact_email_error" className="text-sm text-red-600 mt-1">
                  {errors.contact_email}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="contact_phone"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Contact phone
              </label>
              <input
                id="contact_phone"
                type="tel"
                value={draft.contact_phone}
                onChange={e => set('contact_phone', e.target.value)}
                placeholder="+919876543210"
                maxLength={32}
                aria-invalid={Boolean(errors.contact_phone)}
                aria-describedby={
                  errors.contact_phone ? 'contact_phone_error' : undefined
                }
                className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 ${
                  errors.contact_phone
                    ? 'border-red-400 focus:ring-red-500'
                    : 'border-gray-300 focus:ring-blue-500'
                }`}
              />
              {errors.contact_phone ? (
                <p id="contact_phone_error" className="text-sm text-red-600 mt-1">
                  {errors.contact_phone}
                </p>
              ) : (
                <p className="text-xs text-gray-500 mt-1">
                  7-15 digits, optionally starting with +.
                </p>
              )}
            </div>
          </div>
        </div>

        {blocked && (
          <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl p-4">
            <AlertTriangle size={18} className="text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-900">
                Notifications would not be delivered
              </p>
              <p className="text-sm text-amber-800 mt-0.5">{blocked}</p>
            </div>
          </div>
        )}

        {allOff && (
          <div className="flex items-start gap-3 bg-gray-50 border border-gray-200 rounded-xl p-4">
            <BellOff size={18} className="text-gray-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-gray-900">
                All notifications are off
              </p>
              <p className="text-sm text-gray-600 mt-0.5">
                You will not hear about issuance, revocation, or verification
                activity on your credentials.
              </p>
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 pb-2">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save size={16} />
            Save preferences
          </button>
          <button
            type="button"
            onClick={handleReset}
            disabled={!dirty}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RotateCcw size={16} />
            Reset
          </button>
          {dirty && (
            <span className="text-sm text-gray-500">Unsaved changes</span>
          )}
        </div>
      </div>
    </div>
  )
}
