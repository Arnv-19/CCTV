import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Camera, UserPlus } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-sm text-slate-100 ' +
  'placeholder-slate-500 focus:outline-none focus:border-blue-500'

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
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-blue-600 flex items-center justify-center">
            <Camera size={24} />
          </div>
          <h1 className="text-2xl font-bold text-slate-100">Create Account</h1>
          <p className="text-sm text-slate-400">Register with your email and password</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-4"
        >
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
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
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
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
            <p className="text-xs text-slate-500">Minimum 8 characters</p>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
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
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <UserPlus size={15} />
            {loading ? 'Creating account...' : 'Register'}
          </button>

          <p className="text-sm text-center text-slate-400">
            Already have an account?{' '}
            <Link to="/login" className="text-blue-400 hover:text-blue-300">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
