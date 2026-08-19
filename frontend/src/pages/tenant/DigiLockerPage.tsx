import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  RefreshCw,
  Search,
  Send,
  Smartphone,
  XCircle,
} from 'lucide-react'

import { Toast, useToast } from '@/hooks/useToast'
import { type DocumentRow, loadDocuments } from '@/lib/documents'
import {
  DOCTYPE_OPTIONS,
  MAX_ATTEMPTS,
  type PublicationStatus,
  type PushRecord,
  findPush,
  loadPushes,
  publish,
  retry,
  savePushes,
  statusOf,
  suggestDoctype,
  summarise,
  upsert,
} from '@/lib/digilocker'

type StatusFilter = 'all' | 'not_published' | 'success' | 'failed'

const STATUS_STYLES: Record<
  PublicationStatus,
  { label: string; className: string }
> = {
  not_published: { label: 'Not published', className: 'bg-gray-100 text-gray-700' },
  pending: { label: 'Pending', className: 'bg-amber-100 text-amber-800' },
  retrying: { label: 'Retrying', className: 'bg-amber-100 text-amber-800' },
  success: { label: 'In DigiLocker', className: 'bg-green-100 text-green-800' },
  failed: { label: 'Failed', className: 'bg-red-100 text-red-800' },
  permanently_failed: { label: 'Failed', className: 'bg-red-100 text-red-800' },
}
