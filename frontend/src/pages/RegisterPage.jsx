import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Camera, UserPlus } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'

const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2.5 text-sm text-zinc-100 ' +
  'placeholder-zinc-500 focus:outline-none focus:border-emerald-500'

export default function RegisterPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.register({
        email,
        password,
        phone_number: phoneNumber,
      })
      toast.success('Registration successful. Please sign in.')
      navigate('/login', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-900 flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-emerald-600 flex items-center justify-center">
            <Camera size={24} />
          </div>
          <h1 className="text-2xl font-bold text-zinc-100">Create Account</h1>
          <p className="text-sm text-zinc-400">Register with your email and password</p>
        </div>

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
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <p className="text-xs text-zinc-500">Minimum 8 characters</p>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider">
              Phone Number (Optional)
            </label>
            <input
              className={inputCls}
              type="text"
              autoComplete="tel"
              value={phoneNumber}
              onChange={(e) => setPhoneNumber(e.target.value)}
              placeholder="+1 555 123 4567"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <UserPlus size={15} />
            {loading ? 'Creating account...' : 'Register'}
          </button>

          <p className="text-sm text-center text-zinc-400">
            Already have an account?{' '}
            <Link to="/login" className="text-emerald-400 hover:text-emerald-300">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
