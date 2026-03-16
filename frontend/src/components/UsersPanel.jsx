/**
 * UsersPanel.jsx
 * --------------
 * Admin-only panel for managing application users.
 * Features: list, create, change role/email, deactivate, reset password.
 */

import { useState, useEffect, useCallback } from 'react'
import { UserPlus, Trash2, KeyRound, ShieldCheck, User } from 'lucide-react'
import { api } from '../api/client'

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm ' +
  'text-slate-100 focus:outline-none focus:border-blue-500'

const EMPTY_FORM = { username: '', email: '', password: '', role: 'operator' }

export default function UsersPanel() {
  const [users,   setUsers]   = useState([])
  const [form,    setForm]    = useState(EMPTY_FORM)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const [resetId, setResetId] = useState(null)
  const [newPwd,  setNewPwd]  = useState('')

  const fetchUsers = useCallback(async () => {
    try { setUsers(await api.getUsers()) }
    catch (e) { setError(e.message) }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const handleCreate = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await api.createUser(form)
      setForm(EMPTY_FORM)
      await fetchUsers()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const toggleActive = async (u) => {
    try {
      await api.updateUser(u.id, { is_active: !u.is_active })
      await fetchUsers()
    } catch (e) { setError(e.message) }
  }

  const toggleRole = async (u) => {
    const newRole = u.role === 'admin' ? 'operator' : 'admin'
    try {
      await api.updateUser(u.id, { role: newRole })
      await fetchUsers()
    } catch (e) { setError(e.message) }
  }

  const handleResetPwd = async (e) => {
    e.preventDefault()
    try {
      await api.resetPassword(resetId, newPwd)
      setResetId(null)
      setNewPwd('')
    } catch (e) { setError(e.message) }
  }

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-6">
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Create user form */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <UserPlus size={15} /> Create User
        </h3>
        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input className={inputCls} placeholder="Username" required
            value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
          <input className={inputCls} placeholder="Email" type="email" required
            value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
          <input className={inputCls} placeholder="Password" type="password" required
            value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
          <select className={inputCls} value={form.role}
            onChange={e => setForm({ ...form, role: e.target.value })}>
            <option value="operator">Operator</option>
            <option value="admin">Admin</option>
          </select>
          <button type="submit" disabled={loading}
            className="col-span-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold
                       py-2 rounded-lg transition-colors disabled:opacity-50">
            {loading ? 'Creating...' : 'Create User'}
          </button>
        </form>
      </div>

      {/* User table */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-700/50">
            <tr className="text-left text-xs text-slate-400 uppercase tracking-wider">
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700">
            {users.map(u => (
              <tr key={u.id} className="hover:bg-slate-700/30 transition-colors">
                <td className="px-4 py-3 text-slate-200 font-medium">{u.username}</td>
                <td className="px-4 py-3 text-slate-400">{u.email}</td>
                <td className="px-4 py-3">
                  <button onClick={() => toggleRole(u)}
                    className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full transition-colors
                      ${u.role === 'admin'
                        ? 'bg-purple-900/50 text-purple-300 hover:bg-purple-800/60'
                        : 'bg-slate-700 text-slate-300 hover:bg-slate-600'}`}>
                    {u.role === 'admin' ? <ShieldCheck size={11} /> : <User size={11} />}
                    {u.role}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2.5 py-1 rounded-full font-semibold
                    ${u.is_active ? 'bg-green-900/40 text-green-400' : 'bg-slate-700 text-slate-500'}`}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => { setResetId(u.id); setNewPwd('') }}
                      title="Reset password"
                      className="p-1.5 text-slate-400 hover:text-yellow-400 hover:bg-yellow-900/30 rounded-lg transition-colors">
                      <KeyRound size={14} />
                    </button>
                    <button onClick={() => toggleActive(u)}
                      title={u.is_active ? 'Deactivate' : 'Activate'}
                      className={`p-1.5 rounded-lg transition-colors ${
                        u.is_active
                          ? 'text-slate-400 hover:text-red-400 hover:bg-red-900/30'
                          : 'text-slate-500 hover:text-green-400 hover:bg-green-900/30'
                      }`}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Reset password modal */}
      {resetId !== null && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form onSubmit={handleResetPwd}
            className="bg-slate-800 border border-slate-700 rounded-xl p-6 w-full max-w-sm space-y-4">
            <h4 className="font-semibold text-slate-200">Reset Password</h4>
            <input className={inputCls} type="password" placeholder="New password" required
              value={newPwd} onChange={e => setNewPwd(e.target.value)} autoFocus />
            <div className="flex gap-3">
              <button type="button" onClick={() => setResetId(null)}
                className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm py-2 rounded-lg transition-colors">
                Cancel
              </button>
              <button type="submit"
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2 rounded-lg transition-colors">
                Save
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
