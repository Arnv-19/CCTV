/**
 * AuthContext.jsx
 * ---------------
 * Global authentication state.
 *
 * Stores the JWT token in localStorage so sessions survive page reload.
 * Provides:
 *   token      — raw JWT string (or null)
 *   user       — decoded payload: { sub, role, exp }
 *   login(token) — store token and decode payload
 *   logout()     — clear token
 *   isAdmin      — convenience bool
 */

import { createContext, useContext, useState, useCallback, useMemo } from 'react'

const AuthContext = createContext(null)

function decodeJwtPayload(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return null
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('skycctvai_token'))
  const [user, setUser]   = useState(() => {
    const t = localStorage.getItem('skycctvai_token')
    return t ? decodeJwtPayload(t) : null
  })

  const login = useCallback((newToken) => {
    localStorage.setItem('skycctvai_token', newToken)
    setToken(newToken)
    setUser(decodeJwtPayload(newToken))
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('skycctvai_token')
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo(() => ({
    token,
    user,
    login,
    logout,
    isAdmin: user?.role === 'admin',
  }), [token, user, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
