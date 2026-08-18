import { useEffect } from 'react'
import { X } from 'lucide-react'

interface Props {
  title: string
  subtitle?: string
  onClose: () => void
  children: React.ReactNode
  widthClass?: string
}

/** Centred modal with backdrop, Escape-to-close, and a header. */
export default function Modal({
  title,
  subtitle,
  onClose,
  children,
  widthClass = 'max-w-lg',
}: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-gray-900/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`relative bg-white rounded-2xl shadow-2xl w-full ${widthClass} max-h-[90vh] overflow-auto`}
      >
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="p-1 text-gray-400 hover:text-gray-700 rounded"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  )
}
