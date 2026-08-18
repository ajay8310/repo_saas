import { useState } from 'react'
import { Database, Plus, Edit, Trash2, Download } from 'lucide-react'
import SchemaEditorModal from '@/components/SchemaEditorModal'
import { Toast, useToast } from '@/hooks/useToast'
import { downloadAsJson } from '@/lib/documents'
import type { FieldDefinition, SchemaRow } from '@/lib/schemas'

const INITIAL_SCHEMAS: SchemaRow[] = [
  {
    id: '1', name: 'Degree Certificate', version: 3, status: 'active',
    documents_count: 1240, created_at: '2024-06-15',
    field_definitions: [
      { name: 'student_name', type: 'string', required: true },
      { name: 'graduation_year', type: 'number', required: true },
      { name: 'grade', type: 'enumeration', required: true, allowed_values: ['A', 'B', 'C'] },
      { name: 'honours', type: 'boolean', required: false },
    ],
  },
  {
    id: '2', name: 'Professional License', version: 2, status: 'active',
    documents_count: 532, created_at: '2024-09-01',
    field_definitions: [
      { name: 'licence_no', type: 'string', required: true },
      { name: 'issued_on', type: 'date', required: true },
      { name: 'discipline', type: 'string', required: false },
    ],
  },
  {
    id: '3', name: 'Land Title Deed', version: 1, status: 'active',
    documents_count: 0, created_at: '2025-01-10',
    field_definitions: [
      { name: 'survey_no', type: 'string', required: true },
      { name: 'area_sqm', type: 'number', required: true },
      { name: 'deed_scan', type: 'file_reference', required: false },
    ],
  },
  {
    id: '4', name: 'Legacy Diploma (v1)', version: 1, status: 'deactivated',
    documents_count: 310, created_at: '2023-03-20',
    field_definitions: [
      { name: 'holder_name', type: 'string', required: true },
      { name: 'year', type: 'number', required: false },
    ],
  },
]

export default function SchemasPage() {
  const [schemas, setSchemas] = useState<SchemaRow[]>(INITIAL_SCHEMAS)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<SchemaRow | null>(null)
  const { toast, notify } = useToast()

  const handleCreate = (name: string, fields: FieldDefinition[]) => {
    if (schemas.some(s => s.name.toLowerCase() === name.toLowerCase())) {
      notify(`A schema named "${name}" already exists.`, 'error')
      return
    }
    const row: SchemaRow = {
      id: String(Date.now()),
      name,
      version: 1,
      status: 'active',
      documents_count: 0,
      created_at: new Date().toISOString().slice(0, 10),
      field_definitions: fields,
    }
    setSchemas(prev => [row, ...prev])
    setCreating(false)
    notify(`Created "${name}" v1 with ${fields.length} field(s).`)
  }

  const handleEdit = (name: string, fields: FieldDefinition[]) => {
    if (!editing) return
    // Version increments monotonically on every accepted update (Req 2.4).
    setSchemas(prev =>
      prev.map(s =>
        s.id === editing.id
          ? { ...s, name, field_definitions: fields, version: s.version + 1 }
          : s,
      ),
    )
    notify(`Saved "${name}" as v${editing.version + 1}.`)
    setEditing(null)
  }

  const handleExport = (schema: SchemaRow) => {
    // Matches GET /api/v1/schemas/{id}/export (Req 2.7).
    downloadAsJson(`${schema.name.replace(/\s+/g, '-').toLowerCase()}-v${schema.version}.json`, {
      id: schema.id,
      name: schema.name,
      version: schema.version,
      status: schema.status,
      field_definitions: schema.field_definitions,
      created_at: schema.created_at,
    })
    notify(`Exported "${schema.name}" v${schema.version}.`)
  }

  const handleDeactivate = (schema: SchemaRow) => {
    const ok = window.confirm(
      `Deactivate "${schema.name}"?\n\nExisting documents stay accessible, but no new ones can be issued against it.`,
    )
    if (!ok) return
    setSchemas(prev =>
      prev.map(s => (s.id === schema.id ? { ...s, status: 'deactivated' as const } : s)),
    )
    notify(`Deactivated "${schema.name}".`)
  }

  return (
    <div>
      <Toast toast={toast} />

      {creating && (
        <SchemaEditorModal
          onClose={() => setCreating(false)}
          onSave={handleCreate}
        />
      )}
      {editing && (
        <SchemaEditorModal
          schema={editing}
          onClose={() => setEditing(null)}
          onSave={handleEdit}
        />
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Document Schemas</h1>
          <p className="text-gray-500 mt-1">
            Define and manage credential field structures
          </p>
        </div>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition"
        >
          <Plus size={18} />
          New Schema
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {schemas.map(schema => (
          <div
            key={schema.id}
            className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-md transition"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                  <Database size={18} className="text-green-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{schema.name}</h3>
                  <p className="text-xs text-gray-500">
                    v{schema.version} — {schema.field_definitions.length} fields
                  </p>
                </div>
              </div>
              <span
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                  schema.status === 'active'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-600'
                }`}
              >
                {schema.status}
              </span>
            </div>

            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">
                {schema.documents_count.toLocaleString()} documents issued
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setEditing(schema)}
                  className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                  title="Edit fields"
                >
                  <Edit size={15} />
                </button>
                <button
                  onClick={() => handleExport(schema)}
                  className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                  title="Export JSON"
                >
                  <Download size={15} />
                </button>
                {schema.status === 'active' && (
                  <button
                    onClick={() => handleDeactivate(schema)}
                    className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                    title="Deactivate"
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
