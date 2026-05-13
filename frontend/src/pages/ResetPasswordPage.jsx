import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Camera, KeyRound } from 'lucide-react'
import toast from 'react-hot-toast'
import { api } from '../api/client'

const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2.5 text-sm text-zinc-100 ' +
  'placeholder-zinc-500 focus:outline-none focus:border-emerald-500'

export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = useMemo(() => searchParams.get('token') || '', [searchParams])

  const [newPassword, setNewPassword] = useState('')
  const [loading, setLoading] = useState(false)

  const hasToken = token.length > 0

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!hasToken) {
      toast.error('Reset token is missing from URL')
      return
    }
    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }

    setLoading(true)
    try {
      await api.resetPasswordWithToken({ token, new_password: newPassword })
      toast.success('Password reset successful. Please sign in.')
      navigate('/login', { replace: true })
    } catch (err) {
      toast.error(err.message || 'Password reset failed')
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
          <h1 className="text-2xl font-bold text-zinc-100">Reset Password</h1>
          <p className="text-sm text-zinc-400">Set a new password for your account</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-zinc-800 border border-zinc-700 rounded-xl p-6 space-y-4"
        >
          {!hasToken && (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
              Reset token is missing. Open the reset link again.
            </div>
          )}

          <div className="space-y-1">
            <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wider">
              New Password
            </label>
            <input
              className={inputCls}
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
            <p className="text-xs text-zinc-500">Minimum 8 characters</p>
          </div>

          <button
            type="submit"
            disabled={loading || !hasToken}
            className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700
                       text-white font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <KeyRound size={15} />
            {loading ? 'Updating password...' : 'Reset password'}
          </button>

          <p className="text-sm text-center text-zinc-400">
            Back to{' '}
            <Link to="/login" className="text-emerald-400 hover:text-emerald-300">
              Login
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
