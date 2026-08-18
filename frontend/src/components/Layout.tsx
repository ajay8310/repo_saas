import { Outlet, Link, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { clsx } from 'clsx'
import {
  LayoutDashboard, Building2, FileText, Database,
  Webhook, ScrollText, LogOut, FolderOpen, User, ShieldCheck, Bell
} from 'lucide-react'

export default function Layout() {
  const { user, logout, hasRole } = useAuth()
  const location = useLocation()

  const isIssuing =
    hasRole('super_admin') || hasRole('tenant_admin') || hasRole('issuer')
  const isAdmin = hasRole('super_admin') || hasRole('tenant_admin')

  // Keep these conditions aligned with the route guards in App.tsx.
  const navItems = [
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, show: true },
    { to: '/tenants', label: 'Tenants', icon: Building2, show: hasRole('super_admin') },
    { to: '/schemas', label: 'Schemas', icon: Database, show: isIssuing },
    { to: '/documents', label: 'Documents', icon: FileText, show: isIssuing },
    { to: '/my-documents', label: 'My Documents', icon: FolderOpen, show: hasRole('beneficiary') },
    { to: '/notifications', label: 'Notifications', icon: Bell, show: hasRole('beneficiary') },
    { to: '/audit-logs', label: 'Audit Logs', icon: ScrollText, show: isAdmin },
    { to: '/webhooks', label: 'Webhooks', icon: Webhook, show: isAdmin },
    // Public page, but surfaced in-app so verifiers have a destination and
    // other roles can reach it without hand-editing the URL.
    { to: '/verify', label: 'Verify Document', icon: ShieldCheck, show: true },
  ]

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-64 bg-gray-900 text-white flex flex-col">
        <div className="p-6 border-b border-gray-800">
          <h1 className="text-xl font-bold text-brand-400">Repo SaaS</h1>
          <p className="text-xs text-gray-400 mt-1">Document Repository</p>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.filter(i => i.show).map(item => (
            <Link
              key={item.to}
              to={item.to}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
                location.pathname === item.to
                  ? 'bg-brand-600 text-white'
                  : 'text-gray-300 hover:bg-gray-800 hover:text-white'
              )}
            >
              <item.icon size={18} />
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="p-4 border-t border-gray-800">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 bg-brand-600 rounded-full flex items-center justify-center">
              <User size={16} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user?.sub}</p>
              <p className="text-xs text-gray-400">{user?.roles?.[0]}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors w-full"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
