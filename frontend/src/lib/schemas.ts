/** Schema types, validation, and breaking-change detection. */

export type FieldType =
  | 'string'
  | 'number'
  | 'date'
  | 'boolean'
  | 'enumeration'
  | 'file_reference'

/** Allowed field types — mirrors _VALID_FIELD_TYPES (Req 2.6). */
export const FIELD_TYPES: FieldType[] = [
  'string',
  'number',
  'date',
  'boolean',
  'enumeration',
  'file_reference',
]

export interface FieldDefinition {
  name: string
  type: FieldType
  required: boolean
  allowed_values?: string[]
}

export interface SchemaRow {
  id: string
  name: string
  version: number
  status: 'active' | 'deactivated'
  documents_count: number
  created_at: string
  field_definitions: FieldDefinition[]
}

export interface BreakingChange {
  field: string
  change:
    | 'field_removed'
    | 'type_changed'
    | 'required_field_added'
    | 'optional_became_required'
    | 'enum_values_removed'
  from?: string
  to?: string
  removed_values?: string[]
}
