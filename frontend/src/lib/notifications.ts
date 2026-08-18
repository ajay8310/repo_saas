/**
 * Notification preference types and demo persistence.
 *
 * Shape matches PreferencesResponse in app/routers/notifications.py so this
 * swaps to real API calls without touching the page.
 */

const STORE_KEY = 'reposaas.demo.notification_prefs.v1'

export type Channel = 'email' | 'sms'

export interface Preferences {
  notify_on_issuance: boolean
  notify_on_revocation: boolean
  notify_on_verification: boolean
  preferred_channel: Channel
  contact_email: string
  contact_phone: string
}

export const DEFAULT_PREFERENCES: Preferences = {
  notify_on_issuance: true,
  notify_on_revocation: true,
  notify_on_verification: true,
  preferred_channel: 'email',
  contact_email: '',
  contact_phone: '',
}

/** Event toggles, with copy explaining what each one actually sends. */
export const EVENT_TOGGLES = [
  {
    key: 'notify_on_issuance' as const,
    label: 'Document issued',
    blurb: 'When an issuer adds a new credential to your account.',
  },
  {
    key: 'notify_on_revocation' as const,
    label: 'Document revoked',
    blurb: 'When one of your credentials is withdrawn by its issuer.',
  },
  {
    key: 'notify_on_verification' as const,
    label: 'Credential verified',
    blurb: 'When a third party uses a share link to check a credential.',
  },
]


/** Read stored preferences for a beneficiary, falling back to defaults. */
export function loadPreferences(beneficiaryId: string): Preferences {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    const all = raw ? JSON.parse(raw) : {}
    const stored = all?.[beneficiaryId]
    return stored ? { ...DEFAULT_PREFERENCES, ...stored } : { ...DEFAULT_PREFERENCES }
  } catch {
    return { ...DEFAULT_PREFERENCES }
  }
}

export function savePreferences(beneficiaryId: string, prefs: Preferences): void {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    const all = raw ? JSON.parse(raw) : {}
    all[beneficiaryId] = prefs
    localStorage.setItem(STORE_KEY, JSON.stringify(all))
  } catch {
    // Storage blocked — preferences just won't survive a reload.
  }
}

/**
 * Why delivery would be skipped, or null if it can proceed.
 * Mirrors NotificationService.delivery_blocked_reason.
 */
export function deliveryBlockedReason(prefs: Preferences): string | null {
  if (prefs.preferred_channel === 'email' && !prefs.contact_email.trim()) {
    return 'No contact email saved — email notifications will be skipped.'
  }
  if (prefs.preferred_channel === 'sms' && !prefs.contact_phone.trim()) {
    return 'No contact phone saved — SMS notifications will be skipped.'
  }
  return null
}

const PHONE_RE = /^\+?[0-9]{7,15}$/

/** Field-level validation matching the router's validators. */
export function validatePreferences(prefs: Preferences): Record<string, string> {
  const errors: Record<string, string> = {}

  const email = prefs.contact_email.trim()
  if (email && (!email.includes('@') || email.startsWith('@') || email.endsWith('@'))) {
    errors.contact_email = 'Enter a valid email address.'
  }

  const phone = prefs.contact_phone.trim().replace(/[\s-]/g, '')
  if (phone && !PHONE_RE.test(phone)) {
    errors.contact_phone = 'Use 7-15 digits, optionally starting with +.'
  }

  // The chosen channel needs its contact value to be deliverable.
  if (prefs.preferred_channel === 'email' && !email) {
    errors.contact_email = 'Required while email is the preferred channel.'
  }
  if (prefs.preferred_channel === 'sms' && !phone) {
    errors.contact_phone = 'Required while SMS is the preferred channel.'
  }

  return errors
}

export function anyEventEnabled(prefs: Preferences): boolean {
  return (
    prefs.notify_on_issuance ||
    prefs.notify_on_revocation ||
    prefs.notify_on_verification
  )
}
