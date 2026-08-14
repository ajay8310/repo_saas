import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import TenantsPage from './pages/admin/TenantsPage'
import SchemasPage from './pages/tenant/SchemasPage'
import DocumentsPage from './pages/tenant/DocumentsPage'
import AuditLogsPage from './pages/tenant/AuditLogsPage'
import WebhooksPage from './pages/tenant/WebhooksPage'
import MyDocumentsPage from './pages/beneficiary/MyDocumentsPage'
import VerifyPage from './pages/public/VerifyPage'

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={isAuthenticated ? <Navigate to="/dashboard" /> : <LoginPage />} />
      <Route path="/verify/:credentialId" element={<VerifyPage />} />
      <Route path="/verify" element={<VerifyPage />} />

      {/* Authenticated routes */}
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />

        {/* Super Admin */}
        <Route path="tenants" element={<ProtectedRoute requiredRole="super_admin"><TenantsPage /></ProtectedRoute>} />

        {/* Tenant Admin / Issuer */}
        <Route path="schemas" element={<SchemasPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="audit-logs" element={<AuditLogsPage />} />
        <Route path="webhooks" element={<WebhooksPage />} />

        {/* Beneficiary */}
        <Route path="my-documents" element={<MyDocumentsPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
