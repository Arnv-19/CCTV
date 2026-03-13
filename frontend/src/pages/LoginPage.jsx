/**
 * LoginPage.jsx
 * -------------
 * Full-screen login form.  Calls POST /api/auth/login and stores the
 * returned JWT via AuthContext.login(), then navigates to /.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Camera, LogIn } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../api/client'

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-sm text-slate-100 ' +
  'placeholder-slate-500 focus:outline-none focus:border-blue-500'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate  = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const data = await api.login(username, password)
      login(data.access_token)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center">
            <Camera size={24} />
          </div>
          <h1 className="text-2xl font-bold text-slate-100">SkyCCTVAI</h1>
          <p className="text-sm text-slate-400">Sign in to your account</p>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-4"
        >
          {error && (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
              {error}
            </div>
          )}

          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
              Username
            </label>
            <input
              className={inputCls}
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
              Password
            </label>
            <input
              className={inputCls}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <LogIn size={15} />
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
