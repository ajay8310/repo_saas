/** Public directory + sharing API client (U3 — S12/S14). Unauthenticated reads. */

import api from './api'

export interface DirectoryClass {
  badge_class_id: string
  name: string
  description: string | null
  criteria_narrative: string | null
  image_s3_key: string | null
}

export interface PublicEarner {
  display_name: string
  assertion_id: string
  issued_at: string | null
}

export interface DirectoryPage<T> {
  items: T[]
  next_cursor: string | null
}

export interface ShareTarget {
  assertion_id: string
  channel: string
  share_url: string
  linkedin_url: string
  open_graph: Record<string, string>
}

export async function listDirectory(
  tenantId: string,
  cursor?: string | null,
  limit?: number,
): Promise<DirectoryPage<DirectoryClass>> {
  const { data } = await api.get(`/public/badges/directory/${tenantId}`, {
    params: { cursor: cursor ?? undefined, limit },
  })
  return data
}

export async function listClassEarners(
  tenantId: string,
  badgeClassId: string,
  cursor?: string | null,
  limit?: number,
): Promise<DirectoryPage<PublicEarner>> {
  const { data } = await api.get(
    `/public/badges/directory/${tenantId}/classes/${badgeClassId}/earners`,
    { params: { cursor: cursor ?? undefined, limit } },
  )
  return data
}

export async function getShareTarget(assertionId: string, channel: string): Promise<ShareTarget> {
  const { data } = await api.get<ShareTarget>(`/public/badges/assertions/${assertionId}/share`, {
    params: { channel },
  })
  return data
}
