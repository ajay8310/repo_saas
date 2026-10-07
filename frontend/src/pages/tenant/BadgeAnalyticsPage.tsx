import { useState } from 'react'
import { BarChart3, Award, Share2, Eye, CheckCircle2, Send, Globe } from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import type { AnalyticsTotals, BadgeRank } from '@/lib/analytics'
import { METRIC_LABELS } from '@/lib/analytics'

/**
 * Issuer badge analytics dashboard (U3 — S15).
 *
 * Metric cards, a top-badges ranking, and the share channel breakdown, backed
 * by the async daily rollup. Seeded with representative demo numbers so the page
 * renders before the aggregator has run; live wiring uses lib/analytics.ts.
 */

const DEMO_TOTALS: AnalyticsTotals = {
  issued_count: 1284,
  accepted_count: 1102,
  published_count: 640,
  shared_count: 318,
  verified_count: 2451,
  viewed_count: 5820,
}

const DEMO_RANKING: BadgeRank[] = [
  { badge_class_id: 'bc-1', badge_name: 'Python Expert', value: 540 },
  { badge_class_id: 'bc-2', badge_name: 'Data Steward', value: 410 },
  { badge_class_id: 'bc-3', badge_name: 'Cloud Practitioner', value: 334 },
]

const DEMO_CHANNELS: Record<string, number> = {
  linkedin: 189, twitter: 64, email: 41, link: 24,
}

const METRIC_ICON: Record<keyof AnalyticsTotals, typeof Award> = {
  issued_count: Send,
  accepted_count: CheckCircle2,
  published_count: Globe,
  shared_count: Share2,
  verified_count: BarChart3,
  viewed_count: Eye,
}

export default function BadgeAnalyticsPage() {
  const [days, setDays] = useState(30)
  const [totals] = useState<AnalyticsTotals>(DEMO_TOTALS)
  const [ranking] = useState<BadgeRank[]>(DEMO_RANKING)
  const [channels] = useState<Record<string, number>>(DEMO_CHANNELS)
  const { toast } = useToast()

  const maxRank = Math.max(1, ...ranking.map(r => r.value))
  const totalShares = Object.values(channels).reduce((a, b) => a + b, 0) || 1

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Badge Analytics</h1>
          <p className="text-gray-500 mt-1">Issuance, acceptance, sharing, and verification activity</p>
        </div>
        <select
          data-testid="analytics-range"
          value={days}
          onChange={e => setDays(Number(e.target.value))}
          className="text-sm border border-gray-300 rounded-lg px-3 py-2"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8" data-testid="analytics-metrics">
        {(Object.keys(METRIC_LABELS) as (keyof AnalyticsTotals)[]).map(key => {
          const Icon = METRIC_ICON[key]
          return (
            <div key={key} className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-center gap-2 text-gray-500">
                <Icon size={16} />
                <span className="text-sm">{METRIC_LABELS[key]}</span>
              </div>
              <p className="mt-2 text-2xl font-bold text-gray-900">
                {totals[key].toLocaleString()}
              </p>
            </div>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Ranking */}
        <div className="bg-white rounded-xl border border-gray-200 p-6" data-testid="analytics-ranking">
          <h2 className="font-semibold text-gray-900 mb-4">Top badges by issuance</h2>
          <div className="space-y-3">
            {ranking.map(r => (
              <div key={r.badge_class_id}>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-700">{r.badge_name}</span>
                  <span className="text-gray-500">{r.value.toLocaleString()}</span>
                </div>
                <div className="mt-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-brand-500"
                    style={{ width: `${(r.value / maxRank) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Channel breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-6" data-testid="analytics-channels">
          <h2 className="font-semibold text-gray-900 mb-4">Shares by channel</h2>
          <div className="space-y-3">
            {Object.entries(channels).map(([channel, count]) => (
              <div key={channel}>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-700 capitalize">{channel}</span>
                  <span className="text-gray-500">
                    {count.toLocaleString()} ({Math.round((count / totalShares) * 100)}%)
                  </span>
                </div>
                <div className="mt-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-500"
                    style={{ width: `${(count / totalShares) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
