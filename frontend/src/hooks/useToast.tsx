import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, AlertCircle } from 'lucide-react'

type ToastKind = 'success' | 'error'

interface ToastState {
  msg: string
  kind: ToastKind
}

/** Transient feedback banner shared across pages. */
export function useToast(durationMs = 4000) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const notify = useCallback(
    (msg: string, kind: ToastKind = 'success') => {
      window.clearTimeout(timer.current)
      setToast({ msg, kind })
      timer.current = window.setTimeout(() => setToast(null), durationMs)
    },
    [durationMs],
  )

  // Avoid a setState-after-unmount if the page changes while a toast is up.
  useEffect(() => () => window.clearTimeout(timer.current), [])

  return { toast, notify }
}

export function Toast({ toast }: { toast: ToastState | null }) {
  if (!toast) return null
  const isError = toast.kind === 'error'
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-6 right-6 z-[60] flex items-center gap-2 bg-gray-900 text-white text-sm px-4 py-3 rounded-lg shadow-lg max-w-sm"
    >
      {isError ? (
        <AlertCircle size={16} className="text-red-400 shrink-0" />
      ) : (
        <CheckCircle2 size={16} className="text-green-400 shrink-0" />
      )}
      {toast.msg}
    </div>
  )
}
