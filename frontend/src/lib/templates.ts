/** Certificate template designer types and API client (U5). Mirrors
 * app/routers/certificate_templates.py and app/services/certificate_layout.py. */

import api from './api'

export const BLOCK_TYPES = [
  'text',
  'recipient_photo',
  'badge_image',
  'logo',
  'qr',
  'signature',
  'line',
  'rect',
] as const
export type BlockType = (typeof BLOCK_TYPES)[number]

export const FONTS = [
  'Helvetica',
  'Helvetica-Bold',
  'Helvetica-Oblique',
  'Times-Roman',
  'Times-Bold',
  'Times-Italic',
  'Courier',
  'Courier-Bold',
] as const
export type FontName = (typeof FONTS)[number]

/** Tokens the backend resolves at render time (see PLACEHOLDER_WHITELIST). */
export const PLACEHOLDERS = [
  'recipient',
  'badge_name',
  'issuer_name',
  'issued_at',
  'expires_at',
  'criteria',
  'verify_url',
  'assertion_id',
] as const

export interface BlockStyle {
  text?: string
  font?: FontName
  size?: number
  color?: string
  align?: 'left' | 'center' | 'right'
  caption?: string
  border?: boolean
  border_color?: string
  line_width?: number
  fill?: boolean
}

export interface Block {
  id: string
  type: BlockType
  x: number
  y: number
  w: number
  h: number
  z: number
  rotation?: number
  opacity?: number
  style?: BlockStyle
}

export interface PageSettings {
  orientation: 'portrait' | 'landscape'
  background_color: string
  background_image?: boolean
}

export interface Layout {
  page: PageSettings
  blocks: Block[]
}

export interface CertTemplate {
  id: string
  name: string
  orientation: 'portrait' | 'landscape'
  layout: Layout
  logo_s3_key: string | null
  background_s3_key: string | null
  version: number
  status: 'active' | 'archived'
  created_at: string | null
}

const BASE = '/certificate-templates'

export async function listTemplates(): Promise<CertTemplate[]> {
  const { data } = await api.get<CertTemplate[]>(BASE)
  return data
}

export async function getTemplate(id: string): Promise<CertTemplate> {
  const { data } = await api.get<CertTemplate>(`${BASE}/${id}`)
  return data
}

export async function createTemplate(input: {
  name: string
  orientation: 'portrait' | 'landscape'
  layout: Layout
}): Promise<CertTemplate> {
  const { data } = await api.post<CertTemplate>(BASE, input)
  return data
}

export async function updateTemplate(
  id: string,
  input: { name?: string; orientation?: 'portrait' | 'landscape'; layout?: Layout },
): Promise<CertTemplate> {
  const { data } = await api.put<CertTemplate>(`${BASE}/${id}`, input)
  return data
}

export async function deleteTemplate(id: string): Promise<void> {
  await api.delete(`${BASE}/${id}`)
}

export async function uploadTemplateAsset(
  id: string,
  kind: 'logo' | 'background',
  contentBase64: string,
  contentType: 'image/png' | 'image/jpeg',
): Promise<{ status: string; kind: string; s3_key: string }> {
  const { data } = await api.post(`${BASE}/${id}/assets`, {
    kind,
    content_base64: contentBase64,
    content_type: contentType,
  })
  return data
}

/** Render an unsaved layout to a PDF blob for the live preview. */
export async function previewLayout(
  layout: Layout,
  logoS3Key?: string | null,
  backgroundS3Key?: string | null,
): Promise<Blob> {
  const { data } = await api.post(
    `${BASE}/preview`,
    { layout, logo_s3_key: logoS3Key ?? null, background_s3_key: backgroundS3Key ?? null },
    { responseType: 'blob' },
  )
  return data as Blob
}

/** Render a saved template to a PDF blob. */
export async function previewSavedTemplate(id: string): Promise<Blob> {
  const { data } = await api.post(`${BASE}/${id}/preview`, {}, { responseType: 'blob' })
  return data as Blob
}

export async function assignTemplateToClass(
  badgeClassId: string,
  customTemplateId: string | null,
): Promise<{ status: string; badge_class_id: string; custom_template_id: string | null }> {
  const { data } = await api.post(`${BASE}/assign`, {
    badge_class_id: badgeClassId,
    custom_template_id: customTemplateId,
  })
  return data
}

/** Read a File as a base64 string (no data: prefix) for asset upload. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

/** A sensible starter layout so a new template is not blank. */
export function starterLayout(orientation: 'portrait' | 'landscape'): Layout {
  return {
    page: { orientation, background_color: '#ffffff' },
    blocks: [
      {
        id: 'logo', type: 'logo', x: 0.08, y: 0.07, w: 0.16, h: 0.12, z: 1,
      },
      {
        id: 'title', type: 'text', x: 0.1, y: 0.28, w: 0.8, h: 0.1, z: 2,
        style: { text: 'Certificate of Achievement', font: 'Helvetica-Bold', size: 26, color: '#1e3a8a', align: 'center' },
      },
      {
        id: 'presented', type: 'text', x: 0.1, y: 0.42, w: 0.8, h: 0.06, z: 2,
        style: { text: 'This is proudly presented to', font: 'Helvetica', size: 12, color: '#374151', align: 'center' },
      },
      {
        id: 'recipient', type: 'text', x: 0.1, y: 0.5, w: 0.8, h: 0.09, z: 2,
        style: { text: '{{recipient}}', font: 'Helvetica-Bold', size: 22, color: '#111827', align: 'center' },
      },
      {
        id: 'badge', type: 'text', x: 0.1, y: 0.62, w: 0.8, h: 0.07, z: 2,
        style: { text: 'for earning {{badge_name}}', font: 'Helvetica', size: 14, color: '#374151', align: 'center' },
      },
      {
        id: 'qr', type: 'qr', x: 0.8, y: 0.78, w: 0.14, h: 0.16, z: 3,
      },
    ],
  }
}
