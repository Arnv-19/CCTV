import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Camera, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2.5 text-sm text-slate-100 ' +
  'placeholder-slate-500 focus:outline-none focus:border-blue-500'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.forgotPassword(email)
      const msg = data?.message || 'If an account exists for this email, reset instructions were sent.'
      setMessage(msg)
      toast.success(msg)
    } catch (err) {
      toast.error(err.message || 'Unable to process request')
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
          <h1 className="text-2xl font-bold text-slate-100">Forgot Password</h1>
          <p className="text-sm text-slate-400">Enter your email to request a reset token</p>
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

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <Mail size={15} />
            {loading ? 'Submitting...' : 'Send reset request'}
          </button>

          {message && (
            <p className="text-sm text-green-400 text-center">{message}</p>
          )}

          <p className="text-sm text-center text-slate-400">
            Back to{' '}
            <Link to="/login" className="text-blue-400 hover:text-blue-300">
              Login
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
