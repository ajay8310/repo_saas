import { useState } from 'react'
import { Plus, Trash2, Save, AlertTriangle } from 'lucide-react'
import Modal from './Modal'
import {
  FIELD_TYPES,
  type BreakingChange,
  type FieldDefinition,
  type SchemaRow,
  describeBreakingChange,
  detectBreakingChanges,
  validateFieldDefinitions,
} from '@/lib/schemas'

interface Props {
  /** Existing schema when editing; omitted when creating. */
  schema?: SchemaRow
  onClose: () => void
  onSave: (name: string, fields: FieldDefinition[]) => void
}

const BLANK_FIELD: FieldDefinition = {
  name: '',
  type: 'string',
  required: false,
}

export default function SchemaEditorModal({ schema, onClose, onSave }: Props) {
  const isEdit = Boolean(schema)
  const [name, setName] = useState(schema?.name ?? '')
  const [fields, setFields] = useState<FieldDefinition[]>(
    schema ? schema.field_definitions.map(f => ({ ...f })) : [{ ...BLANK_FIELD }],
  )
  const [errors, setErrors] = useState<string[]>([])
  const [breaking, setBreaking] = useState<BreakingChange[] | null>(null)

  const patchField = (i: number, patch: Partial<FieldDefinition>) =>
    setFields(prev => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)))

  const addField = () => setFields(prev => [...prev, { ...BLANK_FIELD }])

  const removeField = (i: number) =>
    setFields(prev => prev.filter((_, idx) => idx !== i))

  const handleSave = () => {
    setBreaking(null)
    const cleaned = fields.map(f => ({
      ...f,
      name: f.name.trim(),
      allowed_values:
        f.type === 'enumeration'
          ? (f.allowed_values ?? []).filter(v => v.trim())
          : undefined,
    }))

    const validationErrors = validateFieldDefinitions(cleaned)
    if (!name.trim()) validationErrors.unshift('Schema name is required.')
    if (validationErrors.length) {
      setErrors(validationErrors)
      return
    }
    setErrors([])

    // On edit, block changes that would invalidate issued documents (Req 2.3),
    // but only when documents actually exist at the current version.
    if (isEdit && schema && schema.documents_count > 0) {
      const changes = detectBreakingChanges(schema.field_definitions, cleaned)
      if (changes.length) {
        setBreaking(changes)
        return
      }
    }

    onSave(name.trim(), cleaned)
  }

  return (
    <Modal
      title={isEdit ? `Edit "${schema!.name}"` : 'New Schema'}
      subtitle={
        isEdit
          ? `v${schema!.version} — ${schema!.documents_count.toLocaleString()} documents issued`
          : 'Define the fields this credential type will carry'
      }
      onClose={onClose}
      widthClass="max-w-2xl"
    >
      <div className="space-y-4">
        <div>
          <label
            htmlFor="schema-name"
            className="block text-sm font-medium text-gray-700 mb-1.5"
          >
            Schema Name
          </label>
          <input
            id="schema-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. Degree Certificate"
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-brand-500 outline-none"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Fields</span>
            <button
              type="button"
              onClick={addField}
              className="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-700"
            >
              <Plus size={14} />
              Add field
            </button>
          </div>

          <div className="space-y-2 max-h-72 overflow-auto pr-1">
            {fields.map((f, i) => (
              <div
                key={i}
                className="border border-gray-200 rounded-lg p-3 space-y-2"
              >
                <div className="flex items-center gap-2">
                  <input
                    value={f.name}
                    onChange={e => patchField(i, { name: e.target.value })}
                    placeholder="field_name"
                    aria-label={`Field ${i + 1} name`}
                    className="flex-1 px-2.5 py-1.5 border border-gray-300 rounded text-sm font-mono focus:ring-2 focus:ring-brand-500 outline-none"
                  />
                  <select
                    value={f.type}
                    onChange={e =>
                      patchField(i, {
                        type: e.target.value as FieldDefinition['type'],
                        allowed_values:
                          e.target.value === 'enumeration'
                            ? (f.allowed_values ?? [])
                            : undefined,
                      })
                    }
                    aria-label={`Field ${i + 1} type`}
                    className="px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-brand-500 outline-none"
                  >
                    {FIELD_TYPES.map(t => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1.5 text-xs text-gray-600 whitespace-nowrap">
                    <input
                      type="checkbox"
                      checked={f.required}
                      onChange={e => patchField(i, { required: e.target.checked })}
                      className="rounded border-gray-300"
                    />
                    required
                  </label>
                  <button
                    type="button"
                    onClick={() => removeField(i)}
                    aria-label={`Remove field ${i + 1}`}
                    className="p-1 text-gray-400 hover:text-red-600 rounded"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                {f.type === 'enumeration' && (
                  <input
                    value={(f.allowed_values ?? []).join(', ')}
                    onChange={e =>
                      patchField(i, {
                        allowed_values: e.target.value.split(',').map(v => v.trim()),
                      })
                    }
                    placeholder="Allowed values, comma separated (e.g. A, B, C)"
                    aria-label={`Field ${i + 1} allowed values`}
                    className="w-full px-2.5 py-1.5 border border-gray-300 rounded text-xs focus:ring-2 focus:ring-brand-500 outline-none"
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {errors.length > 0 && (
          <ul className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm space-y-1">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}

        {breaking && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={15} className="text-amber-600" />
              <span className="text-sm font-semibold text-amber-800">
                Breaking change — update rejected
              </span>
            </div>
            <p className="text-xs text-amber-700 mb-2">
              These changes would invalidate{' '}
              {schema!.documents_count.toLocaleString()} already-issued document
              {schema!.documents_count === 1 ? '' : 's'}. The backend returns 409
              SCHEMA_BREAKING_CHANGE for this.
            </p>
            <ul className="text-xs text-amber-800 space-y-1 list-disc list-inside">
              {breaking.map((c, i) => (
                <li key={i}>{describeBreakingChange(c)}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex gap-3 pt-1">
          <button
            type="button"
            onClick={handleSave}
            className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
          >
            <Save size={16} />
            {isEdit ? 'Save as new version' : 'Create Schema'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2.5 text-gray-600 hover:text-gray-900 transition"
          >
            Cancel
          </button>
        </div>
      </div>
    </Modal>
  )
}
