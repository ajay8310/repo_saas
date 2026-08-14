import { useAuth } from '@/context/AuthContext'
import { FileText, Users, Database, Shield, Activity, Clock } from 'lucide-react'

export default function DashboardPage() {
  const { user, hasRole } = useAuth()

  const stats = [
    { label: 'Documents', value: '2,451', icon: FileText, color: 'bg-blue-500' },
    { label: 'Active Schemas', value: '12', icon: Database, color: 'bg-green-500' },
    { label: 'Verifications', value: '847', icon: Shield, color: 'bg-purple-500' },
    { label: 'API Calls (24h)', value: '15.2K', icon: Activity, color: 'bg-orange-500' },
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

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {stats.map(stat => (
          <div key={stat.label} className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">{stat.label}</p>
                <p className="text-2xl font-bold mt-1">{stat.value}</p>
              </div>
              <div className={`${stat.color} p-3 rounded-lg`}>
                <stat.icon className="text-white" size={20} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold">Recent Activity</h2>
        </div>
        <div className="divide-y divide-gray-100">
          {[
            { action: 'Document uploaded', resource: 'Certificate #4521', time: '2 min ago', type: 'upload' },
            { action: 'Schema updated', resource: 'Degree Certificate v3', time: '15 min ago', type: 'update' },
            { action: 'Verification completed', resource: 'License #1892', time: '1 hour ago', type: 'verify' },
            { action: 'Document revoked', resource: 'Permit #0034', time: '3 hours ago', type: 'revoke' },
            { action: 'New tenant approved', resource: 'StateGov Education', time: '5 hours ago', type: 'tenant' },
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
