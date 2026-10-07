import { useState } from 'react'
import { Award, Globe, Lock, EyeOff, Eye, Trash2, Share2, Download, Ban } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import { savePdfBlob } from '@/lib/badges'
import type { WalletItem } from '@/lib/wallet'

/**
 * Recipient wallet (U2 S7/S9/S10/S11/S12 + U4 certificate download).
 *
 * The earner's own badges: toggle public/private, hide, remove-from-wallet
 * (soft delist — stays verifiable), copy the public share link, and download
 * the issuer-signed certificate PDF. Revoked badges cannot be made public.
 *
 * Seeded with demo rows so the page is useful before issuance; live wiring uses
 * the helpers in lib/wallet.ts.
 */

const INITIAL_WALLET: WalletItem[] = [
  {
    assertion_id: 'as-1001', badge_class_id: 'bc-1', badge_name: 'Python Expert',
    badge_description: 'Awarded for demonstrated Python mastery.', image_s3_key: null,
    status: 'active', issued_at: '2026-02-12T10:00:00Z', expires_at: '2027-02-12T10:00:00Z',
    accepted: true, hidden: false, public: true, revoked_at: null,
    public_url: '/api/v1/public/badges/assertions/as-1001',
  },
  {
    assertion_id: 'as-1002', badge_class_id: 'bc-2', badge_name: 'Data Steward',
    badge_description: 'Recognises responsible data handling.', image_s3_key: null,
    status: 'active', issued_at: '2026-03-05T09:30:00Z', expires_at: null,
    accepted: true, hidden: false, public: false, revoked_at: null,
    public_url: '/api/v1/public/badges/assertions/as-1002',
  },
  {
    assertion_id: 'as-1003', badge_class_id: 'bc-3', badge_name: 'Cloud Practitioner',
    badge_description: 'Foundational cloud competency.', image_s3_key: null,
    status: 'revoked', issued_at: '2025-11-01T09:30:00Z', expires_at: null,
    accepted: true, hidden: false, public: false, revoked_at: '2026-01-10T00:00:00Z',
    public_url: '/api/v1/public/badges/assertions/as-1003',
  },
]

export default function WalletPage() {
  const [items, setItems] = useState<WalletItem[]>(INITIAL_WALLET)
  const [showHidden, setShowHidden] = useState(false)
  const { toast, notify } = useToast()

  const visible = showHidden ? items : items.filter(i => !i.hidden)

  const togglePublic = (item: WalletItem) => {
    if (item.status === 'revoked' && !item.public) {
      notify('A revoked badge cannot be made public.', 'error')
      return
    }
    setItems(prev =>
      prev.map(i => (i.assertion_id === item.assertion_id ? { ...i, public: !i.public } : i)),
    )
    notify(item.public ? `"${item.badge_name}" is now private.` : `"${item.badge_name}" is now public.`)
  }

  const toggleHidden = (item: WalletItem) => {
    setItems(prev =>
      prev.map(i => (i.assertion_id === item.assertion_id ? { ...i, hidden: !i.hidden } : i)),
    )
    notify(item.hidden ? `"${item.badge_name}" restored.` : `"${item.badge_name}" hidden.`)
  }

  const removeFromWallet = (item: WalletItem) => {
    if (!window.confirm(
      `Remove "${item.badge_name}" from your wallet?\n\nIt stays verifiable via its link but leaves your active wallet and the public directory.`,
    )) return
    setItems(prev =>
      prev.map(i =>
        i.assertion_id === item.assertion_id ? { ...i, hidden: true, public: false } : i,
      ),
    )
    notify(`"${item.badge_name}" removed from wallet.`)
  }

  const copyShareLink = async (item: WalletItem) => {
    const url = `${window.location.origin}${item.public_url}`
    try {
      await navigator.clipboard.writeText(url)
      notify('Public verification link copied to clipboard.')
    } catch {
      notify(`Public link: ${url}`)
    }
  }

  const downloadCertificate = async (item: WalletItem) => {
    try {
      const { downloadWalletCertificate } = await import('@/lib/wallet')
      const blob = await downloadWalletCertificate(item.assertion_id)
      savePdfBlob(blob, `certificate-${item.assertion_id}.pdf`)
      notify('Certificate downloaded.')
    } catch {
      notify('Certificate download is available once the badge is issued live.', 'error')
    }
  }

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">My Wallet</h1>
          <p className="text-gray-500 mt-1">Your earned badges — share, manage, and download certificates</p>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            data-testid="wallet-show-hidden"
            checked={showHidden}
            onChange={e => setShowHidden(e.target.checked)}
          />
          Show hidden
        </label>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="wallet-list">
        {visible.map(item => (
          <div
            key={item.assertion_id}
            data-testid={`wallet-card-${item.assertion_id}`}
            className={`bg-white rounded-xl border p-6 transition ${
              item.hidden ? 'border-dashed border-gray-300 opacity-70' : 'border-gray-200 hover:shadow-md'
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
                  <Award size={18} className="text-amber-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{item.badge_name}</h3>
                  <p className="text-xs text-gray-500">
                    Issued {item.issued_at?.slice(0, 10)}
                    {item.expires_at ? ` · Expires ${item.expires_at.slice(0, 10)}` : ' · Non-expiring'}
                  </p>
                </div>
              </div>
              <div className="flex flex-col items-end gap-1">
                {item.status === 'revoked' ? (
                  <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
                    <Ban size={11} /> revoked
                  </span>
                ) : item.public ? (
                  <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-700">
                    <Globe size={11} /> public
                  </span>
                ) : (
                  <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                    <Lock size={11} /> private
                  </span>
                )}
              </div>
            </div>

            {item.badge_description && (
              <p className="mt-3 text-sm text-gray-600 line-clamp-2">{item.badge_description}</p>
            )}

            <div className="mt-4 flex flex-wrap items-center justify-end gap-1 border-t border-gray-100 pt-3">
              <button
                data-testid={`wallet-certificate-${item.assertion_id}`}
                onClick={() => downloadCertificate(item)}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded"
                title="Download certificate (PDF)"
              >
                <Download size={15} /> Certificate
              </button>
              <button
                data-testid={`wallet-public-${item.assertion_id}`}
                onClick={() => togglePublic(item)}
                disabled={item.status === 'revoked' && !item.public}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded disabled:opacity-40"
                title={item.public ? 'Make private' : 'Make public'}
              >
                {item.public ? <Lock size={15} /> : <Globe size={15} />}
                {item.public ? 'Make Private' : 'Make Public'}
              </button>
              <button
                data-testid={`wallet-share-${item.assertion_id}`}
                onClick={() => copyShareLink(item)}
                className="flex items-center gap-1.5 text-sm px-2.5 py-1.5 text-gray-600 hover:text-brand-600 rounded"
                title="Copy public verification link"
              >
                <Share2 size={15} />
              </button>
              <button
                data-testid={`wallet-hide-${item.assertion_id}`}
                onClick={() => toggleHidden(item)}
                className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                title={item.hidden ? 'Unhide' : 'Hide'}
              >
                {item.hidden ? <Eye size={15} /> : <EyeOff size={15} />}
              </button>
              <button
                data-testid={`wallet-delete-${item.assertion_id}`}
                onClick={() => removeFromWallet(item)}
                className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                title="Remove from wallet"
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {visible.length === 0 && (
        <div className="text-center text-gray-500 py-16" data-testid="wallet-empty">
          No badges to show.
        </div>
      )}
    </div>
  )
}
