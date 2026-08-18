import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

interface Props {
  children: React.ReactNode
  /**
   * Roles permitted to view this route. The user needs any one of them.
   * Omit to require authentication only.
   */
  requiredRoles?: string[]
}

export default function ProtectedRoute({ children, requiredRoles }: Props) {
  const { isAuthenticated, user } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (requiredRoles?.length) {
    const roles = user?.roles ?? []
    const permitted = requiredRoles.some(r => roles.includes(r))
    if (!permitted) {
      // Carry the attempted path so the page can name it.
      return (
        <Navigate to="/unauthorized" replace state={{ from: location.pathname }} />
      )
    }
  }

  return <>{children}</>
}
