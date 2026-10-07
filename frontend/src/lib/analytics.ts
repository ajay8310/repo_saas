/** Issuer analytics API client (U3 — S15). */

import api from './api'

export interface AnalyticsTotals {
  issued_count: number
  accepted_count: number
  published_count: number
  shared_count: number
  verified_count: number
  viewed_count: number
}

export interface AnalyticsOverview {
  from_day: string
  to_day: string
  totals: AnalyticsTotals
  channel_breakdown: Record<string, number>
}

export interface BadgeRank {
  badge_class_id: string
  badge_name: string
  value: number
}

export type RankMetric =
  | 'issued_count'
  | 'accepted_count'
  | 'published_count'
  | 'shared_count'
  | 'verified_count'
  | 'viewed_count'

export async function getOverview(days = 30): Promise<AnalyticsOverview> {
  const { data } = await api.get<AnalyticsOverview>('/badge-analytics/overview', {
    params: { days },
  })
  return data
}

export async function getRanking(metric: RankMetric = 'issued_count', days = 30, limit = 10): Promise<BadgeRank[]> {
  const { data } = await api.get<BadgeRank[]>('/badge-analytics/ranking', {
    params: { metric, days, limit },
  })
  return data
}

export const METRIC_LABELS: Record<keyof AnalyticsTotals, string> = {
  issued_count: 'Issued',
  accepted_count: 'Accepted',
  published_count: 'Published',
  shared_count: 'Shared',
  verified_count: 'Verified',
  viewed_count: 'Viewed',
}
