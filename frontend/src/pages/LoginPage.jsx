import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Camera, LogIn } from 'lucide-react'
import toast from 'react-hot-toast'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../api/client'

const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2.5 text-sm text-zinc-100 ' +
  'placeholder-zinc-500 focus:outline-none focus:border-emerald-500'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate  = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.login({ email, password })
      login(data.access_token)
      toast.success('Welcome back')
      navigate('/', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-900 flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-emerald-600 flex items-center justify-center">
            <Camera size={24} />
          </div>
          <h1 className="text-2xl font-bold text-zinc-100">Axis CCTV</h1>
          <p className="text-sm text-zinc-400">Sign in to your account</p>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="bg-zinc-800 border border-zinc-700 rounded-xl p-6 space-y-4"
        >
          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider">
              Email
            </label>
            <input
              className={inputCls}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider">
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
            className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <LogIn size={15} />
            {loading ? 'Signing in...' : 'Sign In'}
          </button>

          <div className="flex items-center justify-between text-sm">
            <Link to="/register" className="text-emerald-400 hover:text-emerald-300">
              Create account
            </Link>
            <Link to="/forgot-password" className="text-zinc-300 hover:text-zinc-100">
              Forgot password?
            </Link>
          </div>
        </form>
      </div>
    </div>
  )
}
