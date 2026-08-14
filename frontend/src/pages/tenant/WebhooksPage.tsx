import { useState } from 'react'
import { Webhook, Plus, Trash2, CheckCircle, XCircle } from 'lucide-react'

interface WebhookEntry {
  id: string
  url: string
  event_types: string[]
  status: 'active' | 'disabled'
  created_at: string
}

const MOCK_WEBHOOKS: WebhookEntry[] = [
  { id: '1', url: 'https://api.example.com/hooks/documents', event_types: ['document.uploaded', 'document.revoked'], status: 'active', created_at: '2025-05-10' },
  { id: '2', url: 'https://internal.corp.com/notifications', event_types: ['document.uploaded'], status: 'active', created_at: '2025-06-22' },
  { id: '3', url: 'https://old-system.example.com/webhook', event_types: [], status: 'disabled', created_at: '2024-12-01' },
]

export default function WebhooksPage() {
  const [webhooks] = useState<WebhookEntry[]>(MOCK_WEBHOOKS)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Webhooks</h1>
          <p className="text-gray-500 mt-1">Receive real-time notifications for platform events</p>
        </div>
        <button className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition">
          <Plus size={18} />
          Add Webhook
        </button>
      </div>

      <div className="space-y-4">
        {webhooks.map(wh => (
          <div key={wh.id} className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                  wh.status === 'active' ? 'bg-green-100' : 'bg-gray-100'
                }`}>
                  <Webhook size={18} className={wh.status === 'active' ? 'text-green-600' : 'text-gray-400'} />
                </div>
                <div>
                  <p className="font-medium text-gray-900 font-mono text-sm">{wh.url}</p>
                  <div className="flex items-center gap-2 mt-1">
                    {wh.status === 'active' ? (
                      <span className="flex items-center gap-1 text-xs text-green-600"><CheckCircle size={12} /> Active</span>
                    ) : (
                      <span className="flex items-center gap-1 text-xs text-gray-400"><XCircle size={12} /> Disabled</span>
                    )}
                    <span className="text-xs text-gray-400">Created {wh.created_at}</span>
                  </div>
                </div>
              </div>
              <button className="p-2 text-gray-400 hover:text-red-600 rounded-lg hover:bg-red-50">
                <Trash2 size={16} />
              </button>
            </div>
            {wh.event_types.length > 0 && (
              <div className="mt-3 flex gap-2">
                {wh.event_types.map(et => (
                  <span key={et} className="px-2 py-0.5 bg-brand-50 text-brand-700 text-xs rounded-full">{et}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
