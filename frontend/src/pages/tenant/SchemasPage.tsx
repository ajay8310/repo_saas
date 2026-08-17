import { useState } from 'react'
import { Database, Plus, Edit, Trash2, Download } from 'lucide-react'

interface Schema {
  id: string
  name: string
  version: number
  status: 'active' | 'deactivated'
  field_count: number
  documents_count: number
  created_at: string
}

const MOCK_SCHEMAS: Schema[] = [
  { id: '1', name: 'Degree Certificate', version: 3, status: 'active', field_count: 8, documents_count: 1240, created_at: '2024-06-15' },
  { id: '2', name: 'Professional License', version: 2, status: 'active', field_count: 6, documents_count: 532, created_at: '2024-09-01' },
  { id: '3', name: 'Land Title Deed', version: 1, status: 'active', field_count: 12, documents_count: 89, created_at: '2025-01-10' },
  { id: '4', name: 'Legacy Diploma (v1)', version: 1, status: 'deactivated', field_count: 5, documents_count: 310, created_at: '2023-03-20' },
]

export default function SchemasPage() {
  const [schemas] = useState<Schema[]>(MOCK_SCHEMAS)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Document Schemas</h1>
          <p className="text-gray-500 mt-1">Define and manage credential field structures</p>
        </div>
        <button className="flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition">
          <Plus size={18} />
          New Schema
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {schemas.map(schema => (
          <div key={schema.id} className="bg-white rounded-xl border border-gray-200 p-6 hover:shadow-md transition">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                  <Database size={18} className="text-green-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{schema.name}</h3>
                  <p className="text-xs text-gray-500">v{schema.version} — {schema.field_count} fields</p>
                </div>
              </div>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${
                schema.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'
              }`}>
                {schema.status}
              </span>
            </div>

            <div className="mt-4 flex items-center justify-between">
              <p className="text-sm text-gray-500">{schema.documents_count.toLocaleString()} documents issued</p>
              <div className="flex items-center gap-1">
                <button className="p-1.5 text-gray-400 hover:text-brand-600 rounded"><Edit size={15} /></button>
                <button className="p-1.5 text-gray-400 hover:text-brand-600 rounded"><Download size={15} /></button>
                {schema.status === 'active' && (
                  <button className="p-1.5 text-gray-400 hover:text-red-600 rounded"><Trash2 size={15} /></button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
