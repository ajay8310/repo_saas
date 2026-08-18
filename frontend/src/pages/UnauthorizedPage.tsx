import { Link, useLocation } from 'react-router-dom'
import { ShieldOff, ArrowLeft } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'

/**
 * Shown when an authenticated user reaches a route their role can't access.
 *
 * Previously ProtectedRoute redirected to /unauthorized with no matching route,
 * so the catch-all silently bounced users to the dashboard with no explanation.
 */
export default function UnauthorizedPage() {
  const { user } = useAuth()
  const location = useLocation()
  const attempted = (location.state as { from?: string } | null)?.from

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg border border-gray-200 p-8 text-center">
        <div className="w-16 h-16 bg-red-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <ShieldOff className="text-red-600" size={30} />
        </div>

        <h1 className="text-xl font-bold text-gray-900">Access Denied</h1>
        <p className="text-sm text-gray-500 mt-2">
          Your role does not have permission to view
          {attempted ? (
            <>
              {' '}
              <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">
                {attempted}
              </code>
            </>
          ) : (
            ' this page'
          )}
          .
        </p>

        {user && (
          <div className="mt-4 bg-gray-50 rounded-xl px-4 py-3 text-left text-sm space-y-1.5">
            <div className="flex justify-between">
              <span className="text-gray-500">Signed in as</span>
              <span className="font-medium">{user.sub}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Role</span>
              <span className="font-medium">{user.roles?.join(', ') || 'none'}</span>
            </div>
          </div>
        )}

        <Link
          to="/dashboard"
          className="mt-6 inline-flex items-center gap-2 bg-brand-600 text-white px-4 py-2.5 rounded-lg hover:bg-brand-700 transition text-sm"
        >
          <ArrowLeft size={16} />
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
