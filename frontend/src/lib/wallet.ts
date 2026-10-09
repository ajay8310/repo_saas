/** Recipient wallet types and API client (U2) + certificate download (U4). */

import api from './api'

export interface WalletItem {
  assertion_id: string
  badge_class_id: string
  badge_name: string
  badge_description: string | null
  image_s3_key: string | null
  status: 'active' | 'revoked' | 'expired'
  issued_at: string | null
  expires_at: string | null
  accepted: boolean
  hidden: boolean
  public: boolean
  revoked_at: string | null
  public_url: string
}

export async function listWallet(includeHidden = false): Promise<WalletItem[]> {
  const { data } = await api.get<WalletItem[]>('/wallet', {
    params: { include_hidden: includeHidden },
  })
  return data
}

export async function setWalletPublic(assertionId: string, isPublic: boolean): Promise<WalletItem> {
  const { data } = await api.post<WalletItem>(`/wallet/${assertionId}/public`, { public: isPublic })
  return data
}

export async function setWalletHidden(assertionId: string, hidden: boolean): Promise<WalletItem> {
  const { data } = await api.post<WalletItem>(`/wallet/${assertionId}/hide`, { hidden })
  return data
}

export async function deleteFromWallet(assertionId: string): Promise<void> {
  await api.delete(`/wallet/${assertionId}`)
}

/** Download the earner's own certificate PDF (ownership enforced server-side). */
export async function downloadWalletCertificate(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/wallet/${assertionId}/certificate`, { responseType: 'blob' })
  return data as Blob
}

/** Download the earner's own baked Open Badges PNG (ownership enforced). */
export async function downloadWalletBadgePng(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/wallet/${assertionId}/badge.png`, { responseType: 'blob' })
  return data as Blob
}

/** Download the earner's own Open Badges 2.0 assertion JSON (ownership enforced). */
export async function downloadWalletBadgeJson(assertionId: string): Promise<Blob> {
  const { data } = await api.get(`/wallet/${assertionId}/badge.json`, { responseType: 'blob' })
  return data as Blob
}
