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


/** Validate field definitions the way the backend does (Req 2.2). */
export function validateFieldDefinitions(fields: FieldDefinition[]): string[] {
  const errors: string[] = []

  if (fields.length === 0) {
    errors.push('At least one field is required.')
  }

  const seen = new Set<string>()
  fields.forEach((f, i) => {
    const name = (f.name ?? '').trim()
    if (!name) {
      errors.push(`Field ${i + 1}: name must be a non-empty string.`)
    } else if (seen.has(name)) {
      errors.push(`Field ${i + 1}: duplicate field name "${name}".`)
    } else {
      seen.add(name)
    }

    if (!FIELD_TYPES.includes(f.type)) {
      errors.push(`Field ${i + 1}: invalid type "${f.type}".`)
    }
    if (typeof f.required !== 'boolean') {
      errors.push(`Field ${i + 1}: required must be a boolean.`)
    }
    if (f.type === 'enumeration' && !(f.allowed_values ?? []).length) {
      errors.push(
        `Field ${i + 1} ("${name || '?'}"): enumeration needs at least one allowed value.`,
      )
    }
  })

  return errors
}

/**
 * Detect changes that would invalidate already-issued documents (Req 2.3).
 *
 * Port of detect_breaking_changes() in app/services/schema_service.py — kept
 * in sync so the UI can warn before the backend returns 409.
 */
export function detectBreakingChanges(
  oldFields: FieldDefinition[],
  newFields: FieldDefinition[],
): BreakingChange[] {
  const oldBy = new Map(oldFields.filter(f => f.name).map(f => [f.name, f]))
  const newBy = new Map(newFields.filter(f => f.name).map(f => [f.name, f]))
  const breaking: BreakingChange[] = []

  // Removed fields (a rename shows up as a removal plus an addition).
  for (const name of oldBy.keys()) {
    if (!newBy.has(name)) {
      breaking.push({ field: name, change: 'field_removed' })
    }
  }

  for (const [name, next] of newBy.entries()) {
    const prev = oldBy.get(name)

    if (!prev) {
      if (next.required) {
        breaking.push({ field: name, change: 'required_field_added' })
      }
      continue
    }

    if (next.type !== prev.type) {
      breaking.push({
        field: name,
        change: 'type_changed',
        from: prev.type,
        to: next.type,
      })
    }

    if (next.required && !prev.required) {
      breaking.push({ field: name, change: 'optional_became_required' })
    }

    if (prev.type === 'enumeration' && next.type === 'enumeration') {
      const nextVals = new Set(next.allowed_values ?? [])
      const removed = (prev.allowed_values ?? []).filter(v => !nextVals.has(v))
      if (removed.length) {
        breaking.push({
          field: name,
          change: 'enum_values_removed',
          removed_values: removed.sort(),
        })
      }
    }
  }

  return breaking
}

export function describeBreakingChange(c: BreakingChange): string {
  switch (c.change) {
    case 'field_removed':
      return `"${c.field}" was removed`
    case 'type_changed':
      return `"${c.field}" type changed from ${c.from} to ${c.to}`
    case 'required_field_added':
      return `"${c.field}" added as a required field`
    case 'optional_became_required':
      return `"${c.field}" changed from optional to required`
    case 'enum_values_removed':
      return `"${c.field}" no longer allows: ${(c.removed_values ?? []).join(', ')}`
  }
}
