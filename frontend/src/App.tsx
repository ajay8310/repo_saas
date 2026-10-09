import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
import TenantsPage from './pages/admin/TenantsPage'
import SchemasPage from './pages/tenant/SchemasPage'
import BadgeClassesPage from './pages/tenant/BadgeClassesPage'
import DocumentsPage from './pages/tenant/DocumentsPage'
import AuditLogsPage from './pages/tenant/AuditLogsPage'
import WebhooksPage from './pages/tenant/WebhooksPage'
import WalletPage from './pages/beneficiary/WalletPage'
import NotificationsPage from './pages/beneficiary/NotificationsPage'
import VerifyPage from './pages/public/VerifyPage'
import LandingPage from './pages/public/LandingPage'
import DirectoryPage from './pages/public/DirectoryPage'
import BadgeAnalyticsPage from './pages/tenant/BadgeAnalyticsPage'
import TemplateDesignerPage from './pages/tenant/TemplateDesignerPage'

/**
 * Role sets per area, mirroring ROLE_PERMISSIONS in app/rbac/permissions.py.
 * Hiding a sidebar link is not access control — every route is guarded so a
 * typed URL can't bypass it.
 */
const ISSUING_ROLES = ['super_admin', 'tenant_admin', 'issuer']
const ADMIN_ROLES = ['super_admin', 'tenant_admin']

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      {/* Public */}
      {/* "/" is the marketing landing page for visitors. Signed-in users are
          sent straight to their console instead. */}
      <Route
        path="/"
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LandingPage />}
      />
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />}
      />
      <Route path="/verify/:credentialId" element={<VerifyPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route path="/directory" element={<DirectoryPage />} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />

      {/* Authenticated. Pathless layout route: the shell wraps these children
          without claiming "/", which the landing page now owns. */}
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="dashboard" element={<DashboardPage />} />

        <Route
          path="tenants"
          element={
            <ProtectedRoute requiredRoles={['super_admin']}>
              <TenantsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="schemas"
          element={
            <ProtectedRoute requiredRoles={ISSUING_ROLES}>
              <SchemasPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="documents"
          element={
            <ProtectedRoute requiredRoles={ISSUING_ROLES}>
              <DocumentsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="badges"
          element={
            <ProtectedRoute requiredRoles={ISSUING_ROLES}>
              <BadgeClassesPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="badge-analytics"
          element={
            <ProtectedRoute requiredRoles={ISSUING_ROLES}>
              <BadgeAnalyticsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="template-designer"
          element={
            <ProtectedRoute requiredRoles={ISSUING_ROLES}>
              <TemplateDesignerPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="audit-logs"
          element={
            <ProtectedRoute requiredRoles={ADMIN_ROLES}>
              <AuditLogsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="webhooks"
          element={
            <ProtectedRoute requiredRoles={ADMIN_ROLES}>
              <WebhooksPage />
            </ProtectedRoute>
          }
        />
        {/* My Documents was consolidated into the single credentials page.
            Keep the old path working by redirecting it to the wallet. */}
        <Route path="my-documents" element={<Navigate to="/wallet" replace />} />
        <Route
          path="wallet"
          element={
            <ProtectedRoute requiredRoles={['beneficiary']}>
              <WalletPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="notifications"
          element={
            <ProtectedRoute requiredRoles={['beneficiary']}>
              <NotificationsPage />
            </ProtectedRoute>
          }
        />
      </Route>

      {/* Unknown paths go to "/", which decides between the landing page and
          the console based on auth state. Sending visitors to /dashboard sent
          them through a pointless bounce to /login. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
