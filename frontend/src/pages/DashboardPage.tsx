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

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">
          Welcome back, <span className="font-medium">{user?.sub}</span>
          <span className="ml-2 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-800">
            {user?.roles?.[0]}
          </span>
        </p>
      </div>

      {/* Stats — clickable when the role has somewhere to go. */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {stats.map(stat => {
          const interactive = Boolean(stat.to)
          return (
            <button
              key={stat.label}
              type="button"
              disabled={!interactive}
              onClick={() => stat.to && navigate(stat.to)}
              className={`bg-white rounded-xl border border-gray-200 p-6 text-left w-full transition ${
                interactive
                  ? 'hover:shadow-md hover:border-brand-300 cursor-pointer'
                  : 'cursor-default'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500">{stat.label}</p>
                  <p className="text-2xl font-bold mt-1">{stat.value}</p>
                </div>
                <div className={`${stat.color} p-3 rounded-lg`}>
                  <stat.icon className="text-white" size={20} />
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {/* Quick actions — the dashboard previously had no CTAs at all. */}
      <div className="bg-white rounded-xl border border-gray-200 mb-8">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">Quick Actions</h2>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {quickActions.filter(a => a.show).map(action => (
            <Link
              key={action.to + action.label}
              to={action.to}
              className="flex items-center justify-between gap-3 px-4 py-3 border border-gray-200 rounded-lg hover:border-brand-300 hover:bg-brand-50 transition group"
            >
              <span className="flex items-center gap-3 text-sm text-gray-700">
                <action.icon size={17} className="text-brand-600" />
                {action.label}
              </span>
              <ArrowRight
                size={15}
                className="text-gray-300 group-hover:text-brand-600"
              />
            </Link>
          ))}
        </div>
      </div>

      {/* Recent activity */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent Activity</h2>
          {isAdmin && (
            <Link
              to="/audit-logs"
              className="text-xs text-brand-600 hover:text-brand-700 flex items-center gap-1"
            >
              View full audit log
              <ArrowRight size={13} />
            </Link>
          )}
        </div>
        <div className="divide-y divide-gray-100">
          {[
            { action: 'Document uploaded', resource: 'Certificate #4521', time: '2 min ago' },
            { action: 'Schema updated', resource: 'Degree Certificate v3', time: '15 min ago' },
            { action: 'Verification completed', resource: 'License #1892', time: '1 hour ago' },
            { action: 'Document revoked', resource: 'Permit #0034', time: '3 hours ago' },
            { action: 'New tenant approved', resource: 'StateGov Education', time: '5 hours ago' },
          ].map((item, i) => (
            <div key={i} className="px-6 py-4 flex items-center gap-4">
              <div className="w-2 h-2 rounded-full bg-brand-500" />
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-900">{item.action}</p>
                <p className="text-xs text-gray-500">{item.resource}</p>
              </div>
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <Clock size={12} />
                {item.time}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
