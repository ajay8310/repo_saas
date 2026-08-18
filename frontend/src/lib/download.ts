/** Generic browser-download helpers shared across pages. */

function triggerDownload(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function downloadAsJson(filename: string, data: unknown): void {
  triggerDownload(
    filename,
    new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
  )
}

/** Escape a value for CSV: quote it and double any embedded quotes. */
function csvCell(value: unknown): string {
  const s = value == null ? '' : String(value)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/**
 * Write `rows` as CSV using `columns` for both header order and cell lookup.
 */
export function downloadAsCsv<T extends object>(
  filename: string,
  columns: (keyof T & string)[],
  rows: T[],
): void {
  const lines = [
    columns.join(','),
    ...rows.map(r => columns.map(c => csvCell(r[c])).join(',')),
  ]
  triggerDownload(
    filename,
    new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }),
  )
}
