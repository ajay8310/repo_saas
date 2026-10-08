import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Type, Image as ImageIcon, Award, Building2, QrCode, ShieldCheck,
  Minus, Square, Plus, Trash2, Copy, Eye, Save, Upload, FolderOpen,
} from 'lucide-react'
import { Toast, useToast } from '@/hooks/useToast'
import { listBadgeClasses } from '@/lib/badges'
import type { BadgeClass } from '@/lib/badges'
import {
  BLOCK_TYPES, FONTS, PLACEHOLDERS, assignTemplateToClass, createTemplate,
  deleteTemplate, fileToBase64, listTemplates, previewLayout, starterLayout,
  updateTemplate, uploadTemplateAsset,
} from '@/lib/templates'
import type { Block, BlockType, CertTemplate, Layout } from '@/lib/templates'

/**
 * Certificate Template Designer (U5).
 *
 * A visual, drag-and-drop designer for issuer-owned certificate layouts: place
 * text / recipient photo / badge image / institution logo / QR / signature /
 * line / rect blocks on an A4 canvas, upload a logo + background, live-preview
 * the server-rendered PDF, save, and assign to a badge class. Verification (QR
 * + signature) is always included by the backend even if omitted here.
 */

const BLOCK_META: Record<BlockType, { label: string; icon: typeof Type }> = {
  text: { label: 'Text', icon: Type },
  recipient_photo: { label: 'Recipient photo', icon: ImageIcon },
  badge_image: { label: 'Badge image', icon: Award },
  logo: { label: 'Institution logo', icon: Building2 },
  qr: { label: 'QR (verify)', icon: QrCode },
  signature: { label: 'Signature panel', icon: ShieldCheck },
  line: { label: 'Line', icon: Minus },
  rect: { label: 'Rectangle', icon: Square },
}

const DEFAULT_BLOCK: Record<BlockType, Partial<Block>> = {
  text: { w: 0.4, h: 0.08, style: { text: 'Text', font: 'Helvetica', size: 16, color: '#111827', align: 'center' } },
  recipient_photo: { w: 0.15, h: 0.18 },
  badge_image: { w: 0.15, h: 0.15 },
  logo: { w: 0.16, h: 0.12 },
  qr: { w: 0.14, h: 0.16 },
  signature: { w: 0.5, h: 0.14 },
  line: { w: 0.4, h: 0.01, style: { color: '#111827', line_width: 1 } },
  rect: { w: 0.2, h: 0.1, style: { color: '#1e3a8a', line_width: 1, fill: false } },
}

let _idc = 0
const nextId = (t: string) => `${t}-${Date.now().toString(36)}-${_idc++}`

export default function TemplateDesignerPage() {
  const { toast, notify } = useToast()
  const [templates, setTemplates] = useState<CertTemplate[]>([])
  const [current, setCurrent] = useState<CertTemplate | null>(null)
  const [name, setName] = useState('Untitled template')
  const [layout, setLayout] = useState<Layout>(() => starterLayout('landscape'))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [badges, setBadges] = useState<BadgeClass[]>([])
  const [busy, setBusy] = useState(false)
  const canvasRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: string; mode: 'move' | 'resize'; sx: number; sy: number; ox: number; oy: number; ow: number; oh: number } | null>(null)

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => undefined)
    listBadgeClasses().then(setBadges).catch(() => undefined)
  }, [])

  const selected = layout.blocks.find(b => b.id === selectedId) ?? null

  const patchBlock = useCallback((id: string, patch: Partial<Block>) => {
    setLayout(l => ({ ...l, blocks: l.blocks.map(b => (b.id === id ? { ...b, ...patch } : b)) }))
  }, [])

  const patchStyle = useCallback((id: string, patch: Partial<NonNullable<Block['style']>>) => {
    setLayout(l => ({
      ...l,
      blocks: l.blocks.map(b => (b.id === id ? { ...b, style: { ...b.style, ...patch } } : b)),
    }))
  }, [])

  const addBlock = (type: BlockType) => {
    const d = DEFAULT_BLOCK[type]
    const block: Block = {
      id: nextId(type), type, x: 0.1, y: 0.1,
      w: d.w ?? 0.2, h: d.h ?? 0.1, z: (layout.blocks.length + 1),
      opacity: 1, rotation: 0, style: d.style ? { ...d.style } : {},
    }
    setLayout(l => ({ ...l, blocks: [...l.blocks, block] }))
    setSelectedId(block.id)
  }

  const removeBlock = (id: string) => {
    setLayout(l => ({ ...l, blocks: l.blocks.filter(b => b.id !== id) }))
    if (selectedId === id) setSelectedId(null)
  }

  // --- Drag / resize on the canvas ---
  const onPointerDown = (e: React.PointerEvent, id: string, mode: 'move' | 'resize') => {
    e.stopPropagation()
    const b = layout.blocks.find(x => x.id === id)
    if (!b) return
    setSelectedId(id)
    drag.current = { id, mode, sx: e.clientX, sy: e.clientY, ox: b.x, oy: b.y, ow: b.w, oh: b.h }
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!d || !rect) return
    const dx = (e.clientX - d.sx) / rect.width
    const dy = (e.clientY - d.sy) / rect.height
    if (d.mode === 'move') {
      patchBlock(d.id, {
        x: clamp(d.ox + dx, 0, 1 - d.ow),
        y: clamp(d.oy + dy, 0, 1 - d.oh),
      })
    } else {
      patchBlock(d.id, {
        w: clamp(d.ow + dx, 0.02, 1 - d.ox),
        h: clamp(d.oh + dy, 0.02, 1 - d.oy),
      })
    }
  }

  const onPointerUp = () => { drag.current = null }

  // --- Keyboard nudging for accessibility ---
  const onCanvasKeyDown = (e: React.KeyboardEvent) => {
    if (!selected) return
    const step = e.shiftKey ? 0.05 : 0.01
    let handled = true
    if (e.key === 'ArrowLeft') patchBlock(selected.id, { x: clamp(selected.x - step, 0, 1 - selected.w) })
    else if (e.key === 'ArrowRight') patchBlock(selected.id, { x: clamp(selected.x + step, 0, 1 - selected.w) })
    else if (e.key === 'ArrowUp') patchBlock(selected.id, { y: clamp(selected.y - step, 0, 1 - selected.h) })
    else if (e.key === 'ArrowDown') patchBlock(selected.id, { y: clamp(selected.y + step, 0, 1 - selected.h) })
    else if (e.key === 'Delete' || e.key === 'Backspace') removeBlock(selected.id)
    else handled = false
    if (handled) e.preventDefault()
  }

  // --- Persistence ---
  const save = async () => {
    setBusy(true)
    try {
      if (current) {
        const updated = await updateTemplate(current.id, { name, orientation: layout.page.orientation, layout })
        setCurrent(updated)
        notify(`Saved "${name}" (v${updated.version}).`)
      } else {
        const created = await createTemplate({ name, orientation: layout.page.orientation, layout })
        setCurrent(created)
        notify(`Created "${name}".`)
      }
      setTemplates(await listTemplates())
    } catch {
      notify('Could not save the template.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const openTemplate = (t: CertTemplate) => {
    setCurrent(t)
    setName(t.name)
    setLayout(t.layout?.blocks ? t.layout : starterLayout(t.orientation))
    setSelectedId(null)
  }

  const newTemplate = () => {
    setCurrent(null)
    setName('Untitled template')
    setLayout(starterLayout('landscape'))
    setSelectedId(null)
  }

  const duplicate = () => {
    setCurrent(null)
    setName(`${name} (copy)`)
    notify('Duplicated — save to create a new template.')
  }

  const remove = async (t: CertTemplate) => {
    if (!window.confirm(`Delete "${t.name}"? This is blocked if a badge uses it.`)) return
    try {
      await deleteTemplate(t.id)
      setTemplates(await listTemplates())
      if (current?.id === t.id) newTemplate()
      notify(`Deleted "${t.name}".`)
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status
      notify(status === 409 ? 'Template is assigned to a badge — reassign first.' : 'Could not delete.', 'error')
    }
  }

  const preview = async () => {
    setBusy(true)
    try {
      const blob = await previewLayout(layout, current?.logo_s3_key, current?.background_s3_key)
      const url = URL.createObjectURL(blob)
      window.open(url, '_blank')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch {
      notify('Preview failed.', 'error')
    } finally {
      setBusy(false)
    }
  }

  const uploadAsset = async (kind: 'logo' | 'background', file: File) => {
    if (!current) {
      notify('Save the template first, then upload assets.', 'error')
      return
    }
    const ct = file.type === 'image/png' ? 'image/png' : 'image/jpeg'
    try {
      const b64 = await fileToBase64(file)
      await uploadTemplateAsset(current.id, kind, b64, ct)
      const refreshed = (await listTemplates()).find(t => t.id === current.id)
      if (refreshed) setCurrent(refreshed)
      if (kind === 'background') setLayout(l => ({ ...l, page: { ...l.page, background_image: true } }))
      notify(`${kind === 'logo' ? 'Logo' : 'Background'} uploaded.`)
    } catch {
      notify('Asset upload failed.', 'error')
    }
  }

  const assign = async (badgeClassId: string) => {
    if (!current) {
      notify('Save the template first.', 'error')
      return
    }
    try {
      await assignTemplateToClass(badgeClassId, current.id)
      notify('Template assigned to the badge class.')
    } catch {
      notify('Could not assign the template.', 'error')
    }
  }

  const aspect = layout.page.orientation === 'landscape' ? 297 / 210 : 210 / 297

  return (
    <div>
      <Toast toast={toast} />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Certificate Designer</h1>
          <p className="text-gray-500 mt-1">Design your own certificate template — logo, text, and layout</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={preview} disabled={busy}
            data-testid="designer-preview"
            className="flex items-center gap-2 border border-gray-300 text-gray-700 px-4 py-2.5 rounded-lg hover:bg-gray-50 disabled:opacity-50">
            <Eye size={18} /> Preview
          </button>
          <button onClick={save} disabled={busy}
            data-testid="designer-save"
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 disabled:opacity-50">
            <Save size={18} /> {current ? 'Save' : 'Create'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Palette + template list */}
        <div className="col-span-3 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Add block</h3>
            <div className="grid grid-cols-1 gap-1.5">
              {BLOCK_TYPES.map(t => {
                const Icon = BLOCK_META[t].icon
                return (
                  <button key={t} onClick={() => addBlock(t)}
                    data-testid={`palette-${t}`}
                    className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg border border-gray-200 hover:border-brand-400 hover:bg-brand-50 text-gray-700">
                    <Icon size={15} className="text-gray-500" /> {BLOCK_META[t].label}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Page</h3>
            <label className="text-xs text-gray-500">Orientation</label>
            <select
              data-testid="designer-orientation"
              value={layout.page.orientation}
              onChange={e => setLayout(l => ({ ...l, page: { ...l.page, orientation: e.target.value as 'portrait' | 'landscape' } }))}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm mb-3">
              <option value="landscape">Landscape</option>
              <option value="portrait">Portrait</option>
            </select>
            <label className="text-xs text-gray-500">Background color</label>
            <input type="color" value={layout.page.background_color}
              onChange={e => setLayout(l => ({ ...l, page: { ...l.page, background_color: e.target.value } }))}
              className="w-full h-9 border border-gray-300 rounded-lg mb-3" />
            <AssetButton label="Upload background" onFile={f => uploadAsset('background', f)} />
          </div>

          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">Templates</h3>
              <button onClick={newTemplate} title="New" className="text-gray-400 hover:text-brand-600"><Plus size={16} /></button>
            </div>
            <div className="space-y-1 max-h-48 overflow-auto" data-testid="designer-template-list">
              {templates.map(t => (
                <div key={t.id} className={`flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm ${current?.id === t.id ? 'bg-brand-50' : 'hover:bg-gray-50'}`}>
                  <button onClick={() => openTemplate(t)} className="flex items-center gap-2 flex-1 text-left text-gray-700">
                    <FolderOpen size={14} className="text-gray-400" /> {t.name}
                  </button>
                  <button onClick={() => remove(t)} title="Delete" className="text-gray-300 hover:text-red-600"><Trash2 size={14} /></button>
                </div>
              ))}
              {templates.length === 0 && <p className="text-xs text-gray-400">No saved templates yet.</p>}
            </div>
          </div>
        </div>

        {/* Canvas */}
        <div className="col-span-6">
          <input value={name} onChange={e => setName(e.target.value)}
            data-testid="designer-name"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 mb-3 font-medium" />
          <div
            ref={canvasRef}
            tabIndex={0}
            role="application"
            aria-label="Certificate canvas. Click a block to select, drag to move, arrow keys to nudge, Delete to remove."
            onKeyDown={onCanvasKeyDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onClick={() => setSelectedId(null)}
            className="relative w-full border border-gray-300 rounded-lg shadow-inner focus:outline-none focus:ring-2 focus:ring-brand-400 overflow-hidden"
            style={{ aspectRatio: String(aspect), background: layout.page.background_color }}
            data-testid="designer-canvas"
          >
            {[...layout.blocks].sort((a, b) => a.z - b.z).map(b => (
              <div
                key={b.id}
                data-testid={`block-${b.id}`}
                onPointerDown={e => onPointerDown(e, b.id, 'move')}
                onClick={e => { e.stopPropagation(); setSelectedId(b.id) }}
                className={`absolute cursor-move select-none ${selectedId === b.id ? 'ring-2 ring-brand-500' : 'ring-1 ring-dashed ring-gray-300'}`}
                style={{
                  left: `${b.x * 100}%`, top: `${b.y * 100}%`,
                  width: `${b.w * 100}%`, height: `${b.h * 100}%`,
                  opacity: b.opacity ?? 1,
                  transform: b.rotation ? `rotate(${b.rotation}deg)` : undefined,
                }}
              >
                <BlockPreview block={b} />
                {selectedId === b.id && (
                  <span
                    onPointerDown={e => onPointerDown(e, b.id, 'resize')}
                    className="absolute -bottom-1 -right-1 w-3 h-3 bg-brand-600 rounded-sm cursor-se-resize"
                  />
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-emerald-700 mt-2 flex items-center gap-1">
            <ShieldCheck size={13} /> Verification QR + digital signature are always included on the final certificate.
          </p>
        </div>

        {/* Properties */}
        <div className="col-span-3">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">
              {selected ? `${BLOCK_META[selected.type].label} properties` : 'Properties'}
            </h3>
            {!selected && <p className="text-xs text-gray-400">Select a block to edit it.</p>}
            {selected && (
              <div className="space-y-3 text-sm">
                {selected.type === 'text' && (
                  <>
                    <Field label="Text">
                      <TextWithTokens value={selected.style?.text ?? ''} onChange={v => patchStyle(selected.id, { text: v })} />
                    </Field>
                    <Field label="Font">
                      <select value={selected.style?.font ?? 'Helvetica'} onChange={e => patchStyle(selected.id, { font: e.target.value as never })}
                        className="w-full border border-gray-300 rounded px-2 py-1">
                        {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
                      </select>
                    </Field>
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Size">
                        <input type="number" min={6} max={96} value={selected.style?.size ?? 16}
                          onChange={e => patchStyle(selected.id, { size: Number(e.target.value) })}
                          className="w-full border border-gray-300 rounded px-2 py-1" />
                      </Field>
                      <Field label="Align">
                        <select value={selected.style?.align ?? 'left'} onChange={e => patchStyle(selected.id, { align: e.target.value as never })}
                          className="w-full border border-gray-300 rounded px-2 py-1">
                          <option>left</option><option>center</option><option>right</option>
                        </select>
                      </Field>
                    </div>
                    <Field label="Color">
                      <input type="color" value={selected.style?.color ?? '#111827'} onChange={e => patchStyle(selected.id, { color: e.target.value })}
                        className="w-full h-8 border border-gray-300 rounded" />
                    </Field>
                  </>
                )}

                {selected.type === 'logo' && (
                  <Field label="Logo image">
                    <AssetButton label="Upload logo" onFile={f => uploadAsset('logo', f)} />
                    {current?.logo_s3_key && <p className="text-xs text-emerald-600 mt-1">Logo attached ✓</p>}
                  </Field>
                )}

                {(selected.type === 'line' || selected.type === 'rect') && (
                  <>
                    <Field label="Color">
                      <input type="color" value={selected.style?.color ?? '#111827'} onChange={e => patchStyle(selected.id, { color: e.target.value })}
                        className="w-full h-8 border border-gray-300 rounded" />
                    </Field>
                    <Field label="Line width">
                      <input type="number" min={0.1} max={20} step={0.5} value={selected.style?.line_width ?? 1}
                        onChange={e => patchStyle(selected.id, { line_width: Number(e.target.value) })}
                        className="w-full border border-gray-300 rounded px-2 py-1" />
                    </Field>
                    {selected.type === 'rect' && (
                      <label className="flex items-center gap-2 text-xs text-gray-600">
                        <input type="checkbox" checked={!!selected.style?.fill} onChange={e => patchStyle(selected.id, { fill: e.target.checked })} />
                        Fill
                      </label>
                    )}
                  </>
                )}

                <div className="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3">
                  <Field label="X"><NumBox value={selected.x} onChange={v => patchBlock(selected.id, { x: clamp(v, 0, 1 - selected.w) })} /></Field>
                  <Field label="Y"><NumBox value={selected.y} onChange={v => patchBlock(selected.id, { y: clamp(v, 0, 1 - selected.h) })} /></Field>
                  <Field label="W"><NumBox value={selected.w} onChange={v => patchBlock(selected.id, { w: clamp(v, 0.02, 1 - selected.x) })} /></Field>
                  <Field label="H"><NumBox value={selected.h} onChange={v => patchBlock(selected.id, { h: clamp(v, 0.02, 1 - selected.y) })} /></Field>
                </div>
                <Field label={`Opacity (${Math.round((selected.opacity ?? 1) * 100)}%)`}>
                  <input type="range" min={0} max={1} step={0.05} value={selected.opacity ?? 1}
                    onChange={e => patchBlock(selected.id, { opacity: Number(e.target.value) })} className="w-full" />
                </Field>
                <Field label={`Rotation (${selected.rotation ?? 0}°)`}>
                  <input type="range" min={-180} max={180} step={1} value={selected.rotation ?? 0}
                    onChange={e => patchBlock(selected.id, { rotation: Number(e.target.value) })} className="w-full" />
                </Field>
                <div className="flex gap-2 border-t border-gray-100 pt-3">
                  <button onClick={() => removeBlock(selected.id)}
                    className="flex items-center gap-1 text-sm text-red-600 hover:text-red-700"><Trash2 size={14} /> Remove</button>
                </div>
              </div>
            )}
          </div>

          {/* Assign to a badge class */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 mt-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Assign to badge</h3>
            <p className="text-xs text-gray-500 mb-2">Use this template for a badge class's certificates.</p>
            <select
              data-testid="designer-assign"
              defaultValue=""
              onChange={e => e.target.value && assign(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
              <option value="" disabled>Select a badge…</option>
              {badges.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
            <button onClick={duplicate} className="flex items-center gap-1 text-xs text-gray-500 hover:text-brand-600 mt-3">
              <Copy size={13} /> Duplicate current
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// --- Small helpers / subcomponents ---

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-gray-500">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  )
}

function NumBox({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <input type="number" min={0} max={1} step={0.01} value={Number(value.toFixed(3))}
      onChange={e => onChange(Number(e.target.value))}
      className="w-full border border-gray-300 rounded px-2 py-1" />
  )
}

function TextWithTokens({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <textarea value={value} onChange={e => onChange(e.target.value)} rows={2}
        className="w-full border border-gray-300 rounded px-2 py-1 text-sm" />
      <div className="flex flex-wrap gap-1 mt-1">
        {PLACEHOLDERS.map(p => (
          <button key={p} type="button" onClick={() => onChange(`${value}{{${p}}}`)}
            className="text-[10px] px-1.5 py-0.5 bg-gray-100 rounded hover:bg-brand-100 text-gray-600">
            {`{{${p}}}`}
          </button>
        ))}
      </div>
    </div>
  )
}

function AssetButton({ label, onFile }: { label: string; onFile: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button onClick={() => ref.current?.click()}
        className="flex items-center gap-2 text-sm px-3 py-2 w-full rounded-lg border border-gray-200 hover:border-brand-400 hover:bg-brand-50 text-gray-700">
        <Upload size={15} className="text-gray-500" /> {label}
      </button>
      <input ref={ref} type="file" accept="image/png,image/jpeg" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = '' }} />
    </>
  )
}

function BlockPreview({ block }: { block: Block }) {
  const s = block.style ?? {}
  if (block.type === 'text') {
    return (
      <div className="w-full h-full flex items-center overflow-hidden px-0.5"
        style={{ justifyContent: s.align === 'center' ? 'center' : s.align === 'right' ? 'flex-end' : 'flex-start' }}>
        <span style={{ color: s.color, fontWeight: (s.font ?? '').includes('Bold') ? 700 : 400, fontSize: 11 }}
          className="truncate">{s.text || 'Text'}</span>
      </div>
    )
  }
  if (block.type === 'qr') return <Placeholder label="QR" icon={QrCode} />
  if (block.type === 'signature') return <Placeholder label="Signature" icon={ShieldCheck} />
  if (block.type === 'logo') return <Placeholder label="Logo" icon={Building2} tone="amber" />
  if (block.type === 'recipient_photo') return <Placeholder label="Photo" icon={ImageIcon} />
  if (block.type === 'badge_image') return <Placeholder label="Badge" icon={Award} />
  if (block.type === 'line') return <div className="w-full h-full flex items-center"><div className="w-full" style={{ borderTop: `${s.line_width ?? 1}px solid ${s.color ?? '#111827'}` }} /></div>
  if (block.type === 'rect') return <div className="w-full h-full" style={{ border: `${s.line_width ?? 1}px solid ${s.color ?? '#1e3a8a'}`, background: s.fill ? (s.color ?? '#1e3a8a') : 'transparent' }} />
  return null
}

function Placeholder({ label, icon: Icon, tone }: { label: string; icon: typeof QrCode; tone?: 'amber' }) {
  return (
    <div className={`w-full h-full flex flex-col items-center justify-center gap-0.5 ${tone === 'amber' ? 'bg-amber-50 text-amber-600' : 'bg-slate-50 text-slate-400'}`}>
      <Icon size={14} />
      <span className="text-[9px]">{label}</span>
    </div>
  )
}
