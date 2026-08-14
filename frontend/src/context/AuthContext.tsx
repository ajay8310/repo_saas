import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

interface User {
  sub: string
  tenant_id: string
  roles: string[]
  exp: number
}

interface AuthContextType {
  user: User | null
  token: string | null
  login: (token: string) => void
  logout: () => void
  isAuthenticated: boolean
  hasRole: (role: string) => boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

function decodeToken(token: string): User | null {
  try {
    const payload = token.split('.')[1]
    const decoded = JSON.parse(atob(payload))
    if (decoded.exp * 1000 < Date.now()) return null
    return decoded as User
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('access_token'))
  const [user, setUser] = useState<User | null>(() => {
    const t = localStorage.getItem('access_token')
    return t ? decodeToken(t) : null
  })

  const login = (newToken: string) => {
    localStorage.setItem('access_token', newToken)
    setToken(newToken)
    setUser(decodeToken(newToken))
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    setToken(null)
    setUser(null)
  }

  const hasRole = (role: string) => user?.roles?.includes(role) ?? false

  useEffect(() => {
    if (token) {
      const decoded = decodeToken(token)
      if (!decoded) logout()
    }
  }, [token])

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated: !!user, hasRole }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
