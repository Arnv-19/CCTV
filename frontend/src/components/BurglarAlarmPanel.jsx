/**
 * BurglarAlarmPanel.jsx
 * ----------------------
 * Admin panel for configuring per-camera burglar alarms.
 *
 * Features:
 *  - Per-camera enable/disable toggle
 *  - Time window (start/end in HH:MM 24-hour)
 *  - Optional monitored zone selector (from camera's ROI list)
 *  - Cooldown slider
 *  - Live status badge (shows whether the alarm is active right now)
 */

import { useState, useEffect, useCallback } from 'react'
import { ShieldAlert, Clock, Save, Trash2, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm ' +
  'text-slate-100 focus:outline-none focus:border-blue-500'

const DEFAULT_FORM = {
  alarm_enabled:    true,
  alarm_start_time: '20:00',
  alarm_end_time:   '06:00',
  monitored_zone_id: '',
  cooldown_sec:     30,
}

function StatusBadge({ status }) {
  if (!status) return null
  if (!status.configured) {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
        Not configured
      </span>
    )
  }
  if (!status.alarm_enabled) {
    return (
      <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-400">
        Disabled
      </span>
    )
  }
  return status.active_now ? (
    <span className="text-xs px-2 py-0.5 rounded-full bg-red-900/60 text-red-300 font-semibold animate-pulse">
      ALARM ACTIVE ({status.current_time})
    </span>
  ) : (
    <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/50 text-green-400">
      Armed — window inactive ({status.current_time})
    </span>
  )
}

export default function BurglarAlarmPanel() {
  const { isAdmin } = useAuth()

  const [cameras,    setCameras]    = useState([])
  const [selectedCam, setSelectedCam] = useState(null)
  const [form,       setForm]       = useState(DEFAULT_FORM)
  const [rois,       setRois]       = useState([])
  const [status,     setStatus]     = useState(null)
  const [saving,     setSaving]     = useState(false)
  const [deleting,   setDeleting]   = useState(false)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)
  const [success,    setSuccess]    = useState(null)

  // Load camera list once
  useEffect(() => {
    setLoading(true)
    api.getCameras()
      .then(list => {
        setCameras(list)
        if (list.length > 0) setSelectedCam(list[0].id)
      })
      .catch(e => {
        setError(e.message || 'Failed to load cameras')
        setCameras([])
      })
      .finally(() => setLoading(false))
  }, [])

  // Load config + ROIs + status when camera changes
  const loadCamera = useCallback(async (camId) => {
    if (camId === null) return
    setError(null)
    setSuccess(null)
    setRois([])
    setStatus(null)

    try {
      // Load config (may 404 if not yet created — that is fine)
      try {
        const cfg = await api.getBurglarAlarmConfig(camId)
        setForm({
          alarm_enabled:    cfg.alarm_enabled,
          alarm_start_time: cfg.alarm_start_time,
          alarm_end_time:   cfg.alarm_end_time,
          monitored_zone_id: cfg.monitored_zone_id || '',
          cooldown_sec:     cfg.cooldown_sec,
        })
      } catch (e) {
        console.error('Failed to load burglar alarm config:', e)
        setForm({ ...DEFAULT_FORM })
      }

      // Load ROIs for zone selector
      try {
        const zoneList = await api.getRois(camId)
        if (Array.isArray(zoneList)) {
          setRois(zoneList)
        } else {
          console.warn('getRois returned non-array:', zoneList)
          setRois([])
        }
      } catch (e) {
        console.error('Failed to load ROIs:', e)
        setRois([])
      }

      // Load live status
      try {
        const s = await api.getBurglarAlarmStatus(camId)
        setStatus(s)
      } catch (e) {
        console.error('Failed to load burglar alarm status:', e)
        setStatus(null)
      }
    } catch (e) {
      console.error('Unexpected error in loadCamera:', e)
      setError('An unexpected error occurred. Check console for details.')
    }
  }, [])

  useEffect(() => {
    loadCamera(selectedCam)
  }, [selectedCam, loadCamera])

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      await api.upsertBurglarAlarmConfig(selectedCam, {
        ...form,
        monitored_zone_id: form.monitored_zone_id || null,
      })
      setSuccess('Burglar alarm configuration saved.')
      await loadCamera(selectedCam)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Remove burglar alarm configuration for this camera?')) return
    setDeleting(true)
    setError(null)
    try {
      await api.deleteBurglarAlarmConfig(selectedCam)
      setForm({ ...DEFAULT_FORM })
      setSuccess('Configuration removed.')
      await loadCamera(selectedCam)
    } catch (e) {
      setError(e.message)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">
      {(() => {
        try {
          return (
            <>
              {/* Header */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <ShieldAlert size={18} className="text-orange-400" />
                  <h2 className="text-base font-semibold text-slate-200">Burglar Alarm</h2>
                </div>
                <button
                  onClick={() => selectedCam !== null && loadCamera(selectedCam)}
                  disabled={loading || selectedCam === null}
                  className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
                  title="Refresh status"
                >
                  <RefreshCw size={14} />
                </button>
              </div>

              {/* Loading indicator */}
              {loading && (
                <div className="bg-blue-900/40 border border-blue-700 text-blue-300 rounded-lg px-4 py-3 text-sm">
                  Loading cameras...
                </div>
              )}

              {/* Notifications */}
              {error && (
                <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
                  {error}
                </div>
              )}
              {success && (
                <div className="bg-green-900/40 border border-green-700 text-green-300 rounded-lg px-4 py-3 text-sm">
                  {success}
                </div>
              )}

              {/* No cameras message */}
              {!loading && cameras.length === 0 && (
                <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 text-slate-400 text-sm">
                  No cameras configured. Add cameras in the Configuration tab.
                </div>
              )}

              {/* Camera selector */}
              {cameras.length > 0 && (
                <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">Camera</label>
                    <div className="flex items-center gap-3 flex-1">
                      <select
                        className={`${inputCls} flex-1`}
                        value={selectedCam === null ? '' : String(selectedCam)}
                        onChange={e => setSelectedCam(e.target.value === '' ? null : Number(e.target.value))}
                      >
                        <option value="">-- Select camera --</option>
                        {cameras.map(c => (
                          <option key={c.id} value={String(c.id)}>
                            {c.title || `Camera ${c.id}`}
                          </option>
                        ))}
                      </select>
                      <StatusBadge status={status} />
                    </div>
                  </div>
                </div>
              )}

              {/* Configuration form */}
              {cameras.length > 0 && selectedCam !== null && (
                <form onSubmit={handleSave}
                  className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-5">

                  <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                    <Clock size={14} /> Time Window & Zone
                  </h3>

                  {/* Enable toggle */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">Enabled</label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form.alarm_enabled}
                        onChange={e => setForm({ ...form, alarm_enabled: e.target.checked })}
                        className="w-4 h-4 accent-orange-500"
                        disabled={!isAdmin}
                      />
                      <span className="text-sm text-slate-300">
                        {form.alarm_enabled ? 'Burglar alarm is enabled' : 'Burglar alarm is disabled'}
                      </span>
                    </label>
                  </div>

                  {/* Start time */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">Alarm starts</label>
                    <input
                      type="time"
                      className={inputCls}
                      value={form.alarm_start_time}
                      onChange={e => setForm({ ...form, alarm_start_time: e.target.value })}
                      disabled={!isAdmin}
                      required
                    />
                  </div>

                  {/* End time */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">Alarm ends</label>
                    <input
                      type="time"
                      className={inputCls}
                      value={form.alarm_end_time}
                      onChange={e => setForm({ ...form, alarm_end_time: e.target.value })}
                      disabled={!isAdmin}
                      required
                    />
                  </div>

                  <p className="text-xs text-slate-500">
                    Overnight windows are supported — e.g. 20:00 to 06:00 stays active through midnight.
                  </p>

                  {/* Zone selector */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">Monitored zone</label>
                    <select
                      className={inputCls}
                      value={form.monitored_zone_id}
                      onChange={e => setForm({ ...form, monitored_zone_id: e.target.value })}
                      disabled={!isAdmin}
                    >
                      <option value="">All active zones (or full frame if no ROIs)</option>
                      {Array.isArray(rois) && rois.filter(r => r?.is_active).map(r => (
                        <option key={r?.roi_id} value={r?.roi_id}>
                          {r?.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Cooldown */}
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
                    <label className="text-sm text-slate-400 sm:w-32 sm:shrink-0">
                      Cooldown (sec)
                    </label>
                    <div className="flex items-center gap-3 flex-1">
                      <input
                        type="range" min="5" max="300" step="5"
                        value={form.cooldown_sec}
                        onChange={e => setForm({ ...form, cooldown_sec: Number(e.target.value) })}
                        className="flex-1"
                        disabled={!isAdmin}
                      />
                      <span className="w-12 text-sm text-slate-300 text-right shrink-0">
                        {form.cooldown_sec}s
                      </span>
                    </div>
                  </div>

                  {/* Action buttons */}
                  {isAdmin && (
                    <div className="flex flex-col sm:flex-row gap-3 pt-1">
                      <button
                        type="submit"
                        disabled={saving}
                        className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-orange-600 hover:bg-orange-700 text-white px-5 py-2.5 rounded-lg font-semibold text-sm transition-colors disabled:opacity-50"
                      >
                        <Save size={14} />
                        {saving ? 'Saving...' : 'Save Configuration'}
                      </button>
                      <button
                        type="button"
                        onClick={handleDelete}
                        disabled={deleting || !status?.configured}
                        className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-slate-700 hover:bg-red-900/40 text-slate-400 hover:text-red-400 px-5 py-2.5 rounded-lg font-semibold text-sm transition-colors disabled:opacity-40"
                      >
                        <Trash2 size={14} />
                        {deleting ? 'Removing...' : 'Remove Config'}
                      </button>
                    </div>
                  )}
                </form>
              )}

              {/* Info box */}
              <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-4 text-xs text-slate-500 space-y-1.5">
                <p className="font-semibold text-slate-400">How it works</p>
                <p>• The burglar alarm monitors for <span className="text-slate-300">Person</span> detections inside the configured zone during the active time window.</p>
                <p>• When triggered it saves a snapshot, logs the event to the Reports panel, and fires the camera's assigned buzzers.</p>
                <p>• Requires the camera stream to be <span className="text-slate-300">running</span>. Changes take effect on the next camera restart.</p>
                <p>• Configure zones in the <span className="text-slate-300">Live View → ROI Editor</span> per camera.</p>
              </div>
            </>
          )
        } catch (err) {
          console.error('BurglarAlarmPanel render error:', err)
          return (
            <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm m-4">
              <p className="font-semibold mb-2">Error rendering burglar alarm panel</p>
              <p className="text-xs">{String(err?.message || err)}</p>
              <p className="text-xs mt-2 text-red-400">Check browser console for full error details</p>
            </div>
          )
        }
      })()}
    </div>
  )
}
