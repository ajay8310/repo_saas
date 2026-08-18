import { useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import Modal from './Modal'

/** Event types the backend dispatches (see webhook_service.dispatch_event). */
export const WEBHOOK_EVENT_TYPES = [
  'document.uploaded',
  'document.revoked',
  'document.verified',
] as const

/** Minimum secret length enforced by the API (routers/webhooks.py). */
const MIN_SECRET_LEN = 16

interface Props {
  onClose: () => void
  onSubmit: (url: string, eventTypes: string[]) => void
}

function randomSecret(len = 40): string {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
  return Array.from(
    { length: len },
    () => chars[Math.floor(Math.random() * chars.length)],
  ).join('')
}

export default function AddWebhookModal({ onClose, onSubmit }: Props) {
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState(randomSecret())
  const [selected, setSelected] = useState<string[]>([...WEBHOOK_EVENT_TYPES])
  const [error, setError] = useState('')

  const toggle = (evt: string) =>
    setSelected(prev =>
      prev.includes(evt) ? prev.filter(e => e !== evt) : [...prev, evt],
    )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = url.trim()

    if (!trimmed) {
      setError('Endpoint URL is required.')
      return
    }
    let parsed: URL
    try {
      parsed = new URL(trimmed)
    } catch {
      setError('Enter a valid absolute URL, e.g. https://example.com/hooks.')
      return
    }
    if (parsed.protocol !== 'https:') {
      setError('Endpoint must use HTTPS — payloads carry credential data.')
      return
    }
    if (trimmed.length > 2048) {
      setError('URL exceeds the 2048 character limit.')
      return
    }
    if (secret.trim().length < MIN_SECRET_LEN) {
      setError(`Signing secret must be at least ${MIN_SECRET_LEN} characters.`)
      return
    }
    if (selected.length === 0) {
      setError('Select at least one event type.')
      return
    }
    onSubmit(trimmed, selected)
  }

  return (
    <Modal
      title="Add Webhook"
      subtitle="Receive signed HTTP callbacks for platform events"
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="wh-url"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Endpoint URL
          </label>
          <input
            id="wh-url"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://api.example.com/hooks/documents"
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-brand-500 outline-none"
          />
        </div>

        <div>
          <label
            htmlFor="wh-secret"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Signing Secret
          </label>
          <div className="flex gap-2">
            <input
              id="wh-secret"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              className="flex-1 px-3 py-2.5 border border-gray-300 rounded-lg font-mono text-xs focus:ring-2 focus:ring-brand-500 outline-none"
            />
            <button
              type="button"
              onClick={() => setSecret(randomSecret())}
              title="Generate a new secret"
              className="px-3 border border-gray-300 rounded-lg text-gray-500 hover:bg-gray-50"
            >
              <RefreshCw size={15} />
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Used to compute the HMAC-SHA256 <code>X-Webhook-Signature</code> header.
          </p>
        </div>

        <div>
          <span className="block text-sm font-medium text-gray-700 mb-2">
            Event Types
          </span>
          <div className="space-y-2">
            {WEBHOOK_EVENT_TYPES.map(evt => (
              <label
                key={evt}
                className="flex items-center gap-2.5 text-sm text-gray-700 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(evt)}
                  onChange={() => toggle(evt)}
                  className="rounded border-gray-300"
                />
                <code className="text-xs bg-gray-100 px-2 py-0.5 rounded">{evt}</code>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
            {error}
          </div>
        )}

        <div className="flex gap-3 pt-1">
          <button
            type="submit"
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
          >
            <Plus size={16} />
            Register Webhook
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
