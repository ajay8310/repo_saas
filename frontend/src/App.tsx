import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import UnauthorizedPage from './pages/UnauthorizedPage'
import TenantsPage from './pages/admin/TenantsPage'
import SchemasPage from './pages/tenant/SchemasPage'
import DocumentsPage from './pages/tenant/DocumentsPage'
import AuditLogsPage from './pages/tenant/AuditLogsPage'
import WebhooksPage from './pages/tenant/WebhooksPage'
import MyDocumentsPage from './pages/beneficiary/MyDocumentsPage'
import VerifyPage from './pages/public/VerifyPage'

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
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />}
      />
      <Route path="/verify/:credentialId" element={<VerifyPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />

      {/* Authenticated */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
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
        <Route
          path="my-documents"
          element={
            <ProtectedRoute requiredRoles={['beneficiary']}>
              <MyDocumentsPage />
            </ProtectedRoute>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
