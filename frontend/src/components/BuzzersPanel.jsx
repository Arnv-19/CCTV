/**
 * BuzzersPanel.jsx
 * ----------------
 * Admin panel for managing buzzer devices.
 * Protocol-aware form validation: USB needs device_id, HTTP/MQTT need ip_address, GPIO needs gpio_pin.
 */

import { useState, useEffect, useCallback } from 'react'
import { Bell, BellOff, Plus, Trash2, Pencil } from 'lucide-react'
import { api } from '../api/client'

const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-sm ' +
  'text-zinc-100 focus:outline-none focus:border-emerald-500'

const PROTOCOLS = ['usb', 'http', 'mqtt', 'gpio']

const EMPTY_FORM = {
  name: '', protocol: 'usb', device_id: '', ip_address: '', port: '', gpio_pin: '', is_active: true,
}

function protocolBadgeColor(p) {
  return {
    usb: 'bg-emerald-900/40 text-emerald-300',
    http: 'bg-green-900/40 text-green-300',
    mqtt: 'bg-orange-900/40 text-orange-300',
    gpio: 'bg-purple-900/40 text-purple-300',
  }[p] ?? 'bg-zinc-700 text-zinc-300'
}

export default function BuzzersPanel() {
  const [buzzers,  setBuzzers]  = useState([])
  const [form,     setForm]     = useState(EMPTY_FORM)
  const [editId,   setEditId]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [showForm, setShowForm] = useState(false)

  const fetchBuzzers = useCallback(async () => {
    try { setBuzzers(await api.getBuzzers()) }
    catch (e) { setError(e.message) }
  }, [])

  useEffect(() => { fetchBuzzers() }, [fetchBuzzers])

  const openCreate = () => { setForm(EMPTY_FORM); setEditId(null); setShowForm(true) }
  const openEdit   = (b) => {
    setForm({
      name: b.name, protocol: b.protocol,
      device_id: b.device_id || '', ip_address: b.ip_address || '',
      port: b.port ?? '', gpio_pin: b.gpio_pin ?? '', is_active: b.is_active,
    })
    setEditId(b.id)
    setShowForm(true)
  }

  const sanitize = (f) => ({
    ...f,
    port:     f.port     !== '' ? parseInt(f.port)     : null,
    gpio_pin: f.gpio_pin !== '' ? parseInt(f.gpio_pin) : null,
    device_id:  f.device_id  || null,
    ip_address: f.ip_address || null,
  })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      if (editId !== null) await api.updateBuzzer(editId, sanitize(form))
      else await api.createBuzzer(sanitize(form))
      setShowForm(false)
      await fetchBuzzers()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this buzzer?')) return
    try { await api.deleteBuzzer(id); await fetchBuzzers() }
    catch (e) { setError(e.message) }
  }

  const handleToggle = async (id) => {
    try { await api.toggleBuzzer(id); await fetchBuzzers() }
    catch (e) { setError(e.message) }
  }

  const f = form

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-zinc-200">Buzzer Devices</h2>
        <button onClick={openCreate}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm
                     font-semibold px-4 py-2 rounded-lg transition-colors">
          <Plus size={14} /> Add Buzzer
        </button>
      </div>

      {/* Buzzer list */}
      <div className="bg-zinc-800 border border-zinc-700 rounded-xl overflow-x-auto">
        {buzzers.length === 0 ? (
          <div className="px-6 py-10 text-center text-zinc-500 text-sm">
            No buzzers configured. Click "Add Buzzer" to create one.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-700/50">
              <tr className="text-left text-xs text-zinc-400 uppercase tracking-wider">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Protocol</th>
                <th className="px-4 py-3">Connection</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-700">
              {buzzers.map(b => (
                <tr key={b.id} className="hover:bg-zinc-700/30 transition-colors">
                  <td className="px-4 py-3 text-zinc-200 font-medium">{b.name}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${protocolBadgeColor(b.protocol)}`}>
                      {b.protocol.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-zinc-400 font-mono text-xs">
                    {b.device_id || b.ip_address || (b.gpio_pin != null ? `GPIO ${b.gpio_pin}` : '—')}
                    {b.port ? `:${b.port}` : ''}
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={() => handleToggle(b.id)}
                      className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full transition-colors
                        ${b.is_active
                          ? 'bg-green-900/40 text-green-400 hover:bg-red-900/40 hover:text-red-400'
                          : 'bg-zinc-700 text-zinc-500 hover:bg-green-900/40 hover:text-green-400'}`}>
                      {b.is_active ? <Bell size={11} /> : <BellOff size={11} />}
                      {b.is_active ? 'Active' : 'Disabled'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => openEdit(b)}
                        className="p-1.5 text-zinc-400 hover:text-emerald-400 hover:bg-emerald-900/30 rounded-lg transition-colors">
                        <Pencil size={14} />
                      </button>
                      <button onClick={() => handleDelete(b.id)}
                        className="p-1.5 text-zinc-400 hover:text-red-400 hover:bg-red-900/30 rounded-lg transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create / Edit modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <form onSubmit={handleSubmit}
            className="bg-zinc-800 border border-zinc-700 rounded-xl p-6 w-full max-w-md space-y-4">
            <h4 className="font-semibold text-zinc-200">
              {editId !== null ? 'Edit Buzzer' : 'New Buzzer'}
            </h4>

            <div className="space-y-3">
              <input className={inputCls} placeholder="Name" required
                value={f.name} onChange={e => setForm({ ...f, name: e.target.value })} />

              <select className={inputCls} value={f.protocol}
                onChange={e => setForm({ ...f, protocol: e.target.value })}>
                {PROTOCOLS.map(p => (
                  <option key={p} value={p}>{p.toUpperCase()}</option>
                ))}
              </select>

              {f.protocol === 'usb' && (
                <input className={inputCls} placeholder="Serial port (e.g. /dev/ttyACM0)" required
                  value={f.device_id} onChange={e => setForm({ ...f, device_id: e.target.value })} />
              )}
              {(f.protocol === 'http' || f.protocol === 'mqtt') && (
                <>
                  <input className={inputCls} placeholder="IP address / broker host" required
                    value={f.ip_address} onChange={e => setForm({ ...f, ip_address: e.target.value })} />
                  <input className={inputCls} placeholder={`Port (default: ${f.protocol === 'mqtt' ? 1883 : 80})`}
                    type="number"
                    value={f.port} onChange={e => setForm({ ...f, port: e.target.value })} />
                </>
              )}
              {f.protocol === 'gpio' && (
                <input className={inputCls} placeholder="GPIO pin number" type="number" required
                  value={f.gpio_pin} onChange={e => setForm({ ...f, gpio_pin: e.target.value })} />
              )}

              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" className="w-4 h-4 accent-emerald-500"
                  checked={f.is_active} onChange={e => setForm({ ...f, is_active: e.target.checked })} />
                <span className="text-sm text-zinc-300">Active</span>
              </label>
            </div>

            <div className="flex gap-3 pt-1">
              <button type="button" onClick={() => setShowForm(false)}
                className="flex-1 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-sm py-2 rounded-lg transition-colors">
                Cancel
              </button>
              <button type="submit" disabled={loading}
                className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold py-2 rounded-lg transition-colors disabled:opacity-50">
                {loading ? 'Saving...' : 'Save'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
