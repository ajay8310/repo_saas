import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import {
  FileText, Database, Shield, Activity, Clock, Building2,
  Upload, ScrollText, FolderOpen, ArrowRight,
} from 'lucide-react'

interface QuickAction {
  label: string
  to: string
  icon: typeof FileText
  show: boolean
}

export default function DashboardPage() {
  const { user, hasRole } = useAuth()
  const navigate = useNavigate()

  const isIssuing =
    hasRole('super_admin') || hasRole('tenant_admin') || hasRole('issuer')
  const isAdmin = hasRole('super_admin') || hasRole('tenant_admin')

  /** Each card links somewhere the role can actually go. */
  const stats = [
    { label: 'Documents', value: '2,451', icon: FileText, color: 'bg-blue-500', to: isIssuing ? '/documents' : '/my-documents' },
    { label: 'Active Schemas', value: '12', icon: Database, color: 'bg-green-500', to: isIssuing ? '/schemas' : null },
    { label: 'Verifications', value: '847', icon: Shield, color: 'bg-purple-500', to: '/verify' },
    { label: 'API Calls (24h)', value: '15.2K', icon: Activity, color: 'bg-orange-500', to: isAdmin ? '/audit-logs' : null },
  ]

  const quickActions: QuickAction[] = [
    { label: 'Upload a document', to: '/documents', icon: Upload, show: isIssuing },
    { label: 'Onboard a tenant', to: '/tenants', icon: Building2, show: hasRole('super_admin') },
    { label: 'Review audit trail', to: '/audit-logs', icon: ScrollText, show: isAdmin },
    { label: 'View my credentials', to: '/my-documents', icon: FolderOpen, show: hasRole('beneficiary') },
    { label: 'Verify a credential', to: '/verify', icon: Shield, show: true },
  ]
