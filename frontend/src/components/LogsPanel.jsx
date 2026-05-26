import { useState, useEffect, useRef } from 'react'
import { RefreshCw, Trash2, User, ShieldAlert, ShieldCheck, ShieldQuestion, EyeOff, ZoomIn, X, Image } from 'lucide-react'
import { api } from '../api/client'

/* ── Snapshot Lightbox ───────────────────────────────────────── */
function SnapshotLightbox({ src, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="relative max-w-3xl w-full rounded-2xl overflow-hidden shadow-2xl border border-zinc-700"
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 p-1.5 bg-zinc-900/80 hover:bg-zinc-700 text-zinc-300 rounded-full transition-colors"
        >
          <X size={16} />
        </button>
        <img src={src} alt="Violation snapshot" className="w-full h-auto max-h-[85vh] object-contain bg-zinc-900" />
        <div className="bg-zinc-900/90 px-4 py-2 text-xs text-zinc-400 text-center">
          Violation Snapshot — Click outside or press Esc to close
        </div>
      </div>
    </div>
  )
}

/* ── Face-status badge ───────────────────────────────────────── */
const FACE_STATUS_META = {
  matched:     { label: 'Matched',     cls: 'bg-emerald-900/50 text-emerald-300 border border-emerald-700', Icon: ShieldCheck },
  unknown:     { label: 'Unknown',     cls: 'bg-red-900/50    text-red-300    border border-red-700',     Icon: ShieldAlert },
  not_visible: { label: 'Not Visible', cls: 'bg-zinc-700      text-zinc-400   border border-zinc-600',   Icon: EyeOff },
  too_small:   { label: 'Too Small',   cls: 'bg-amber-900/50  text-amber-300  border border-amber-700',  Icon: ZoomIn },
  low_quality: { label: 'Low Quality', cls: 'bg-orange-900/50 text-orange-300 border border-orange-700', Icon: ShieldQuestion },
}

function FaceStatusBadge({ status }) {
  if (!status) return <span className="text-zinc-600 text-xs">—</span>
  const meta = FACE_STATUS_META[status] ?? { label: status, cls: 'bg-zinc-700 text-zinc-400', Icon: ShieldQuestion }
  const { label, cls, Icon } = meta
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${cls}`}>
      <Icon size={10} />
      {label}
    </span>
  )
}

/* ── Employee pill shown in each log card ────────────────────── */
function EmployeePill({ alert }) {
  const hasEmployee = alert.face_name || alert.face_employee_id
  if (!hasEmployee && !alert.face_status) return null

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      {hasEmployee && (
        <div className="flex items-center gap-1.5 bg-zinc-800 border border-zinc-600 rounded-lg px-2.5 py-1">
          {alert.face_employee_id ? (
            <img
              src={api.employeePhotoUrl(alert.face_employee_id)}
              alt={alert.face_name ?? 'Employee'}
              className="w-5 h-5 rounded-full object-cover ring-1 ring-zinc-600"
              onError={(e) => { e.target.style.display = 'none' }}
            />
          ) : (
            <User size={12} className="text-zinc-400 shrink-0" />
          )}
          <div className="flex flex-col">
            <span className="text-xs font-semibold text-zinc-200">
              {alert.face_name ?? `Employee #${alert.face_employee_id}`}
            </span>
            {alert.face_employee_id && (
              <span className="text-[10px] text-zinc-500">
                ID: {alert.face_employee_id}
              </span>
            )}
          </div>
          {alert.face_confidence != null && (
            <span className="text-[10px] text-zinc-400 ml-1">
              {(alert.face_confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}
      <FaceStatusBadge status={alert.face_status} />
    </div>
  )
}

/* ── Single log entry card ───────────────────────────────────── */
function LogCard({ alert, onSnapshotClick }) {
  const violationCls =
    alert.face_status === 'matched'
      ? 'border-l-4 border-l-emerald-500 bg-emerald-950/20'
      : alert.face_status === 'unknown'
      ? 'border-l-4 border-l-red-500 bg-red-950/20'
      : 'border-l-4 border-l-zinc-600 bg-zinc-900/60'

  return (
    <div className={`rounded-xl px-4 py-3 ${violationCls} hover:brightness-110 transition-all`}>
      <div className="flex gap-3">
        {/* Snapshot thumbnail */}
        {alert.snapshot_path ? (
          <button
            onClick={() => onSnapshotClick(api.alertSnapshotUrl(alert.id))}
            title="View violation snapshot"
            className="shrink-0 w-16 h-12 rounded overflow-hidden bg-zinc-800 border border-zinc-700 hover:border-red-500 transition-colors group relative"
          >
            <img
              src={api.alertSnapshotUrl(alert.id)}
              alt="snapshot"
              className="w-full h-full object-cover group-hover:opacity-90"
              onError={e => { e.target.style.display = 'none' }}
            />
            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 flex items-center justify-center transition-colors">
              <ZoomIn size={12} className="text-white opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
          </button>
        ) : (
          <div className="shrink-0 w-16 h-12 rounded bg-zinc-800/50 border border-zinc-700 flex items-center justify-center">
            <Image size={14} className="text-zinc-600" />
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            {/* Left: time + camera + violation */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-zinc-500 whitespace-nowrap">
                {new Date(alert.triggered_at).toLocaleString()}
              </span>
              <span className="text-xs text-zinc-400">Cam {alert.camera_id}</span>
              <span className="bg-red-900/40 text-red-300 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide">
                {alert.violation_type}
              </span>
              <span className="text-[10px] text-zinc-500 font-mono">{alert.model_name}</span>
            </div>
            {/* Right: confidence + buzzer */}
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[11px] text-zinc-400">
                {(alert.confidence_score * 100).toFixed(0)}% conf
              </span>
              {alert.buzzer_activated && (
                <span className="bg-orange-900/40 text-orange-300 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border border-orange-700">
                  Buzzer
                </span>
              )}
              {alert.acknowledged && (
                <span className="bg-emerald-900/30 text-emerald-400 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border border-emerald-800">
                  ✓ Ack
                </span>
              )}
            </div>
          </div>

          {/* Employee / face-recognition row */}
          <EmployeePill alert={alert} />
        </div>
      </div>
    </div>
  )
}

/* ── Main panel ──────────────────────────────────────────────── */
export default function LogsPanel() {
  const [alerts, setAlerts]           = useState([])
  const [loading, setLoading]         = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [limit, setLimit]             = useState(100)
  const [lightboxSrc, setLightboxSrc] = useState(null)
  const bottomRef = useRef(null)

  const fetchAlerts = async (scroll = false) => {
    setLoading(true)
    try {
      const data = await api.getAlerts({ limit, page: 1 })
      const items = Array.isArray(data) ? data : (data.items ?? [])
      setAlerts(items)
      if (scroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    } catch (e) {
      console.error('Failed to fetch alerts:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAlerts(true) }, [limit])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => fetchAlerts(false), 5000)
    return () => clearInterval(interval)
  }, [autoRefresh, limit])

  const clearLogs = async () => {
    await api.clearLogs()
    setAlerts([])
  }

  /* quick summary counts */
  const matched  = alerts.filter(a => a.face_status === 'matched').length
  const unknown  = alerts.filter(a => a.face_status === 'unknown').length
  const noFace   = alerts.filter(a => !a.face_status).length

  return (
    <div className="flex flex-col h-full p-3 sm:p-4 gap-3">

      {/* ── Toolbar ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-sm text-zinc-400">{alerts.length} entries</span>

          {/* Quick face-status pills */}
          {alerts.length > 0 && (
            <div className="flex items-center gap-1.5">
              {matched > 0 && (
                <span className="text-[10px] font-semibold bg-emerald-900/50 text-emerald-300 border border-emerald-700 px-1.5 py-0.5 rounded-full">
                  {matched} matched
                </span>
              )}
              {unknown > 0 && (
                <span className="text-[10px] font-semibold bg-red-900/50 text-red-300 border border-red-700 px-1.5 py-0.5 rounded-full">
                  {unknown} unknown
                </span>
              )}
              {noFace > 0 && (
                <span className="text-[10px] font-semibold bg-zinc-700 text-zinc-400 border border-zinc-600 px-1.5 py-0.5 rounded-full">
                  {noFace} no-face
                </span>
              )}
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-zinc-400 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="accent-emerald-500"
            />
            Auto-refresh (5s)
          </label>

          {/* Limit selector */}
          <select
            value={limit}
            onChange={e => setLimit(Number(e.target.value))}
            className="bg-zinc-700 border border-zinc-600 text-zinc-300 text-xs rounded-lg px-2 py-1 focus:outline-none focus:border-emerald-500"
          >
            {[50, 100, 200, 500].map(n => (
              <option key={n} value={n}>Last {n}</option>
            ))}
          </select>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => fetchAlerts(true)}
            className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded-lg transition-colors"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={clearLogs}
            className="flex items-center gap-1.5 text-sm text-red-400 hover:text-red-300 px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded-lg transition-colors"
          >
            <Trash2 size={13} />
            Clear
          </button>
        </div>
      </div>

      {/* ── Alert cards ────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        {alerts.length === 0 ? (
          <p className="text-zinc-600 text-sm p-4">No alerts logged yet.</p>
        ) : (
          alerts.map(alert => (
            <LogCard key={alert.id} alert={alert} onSnapshotClick={setLightboxSrc} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Snapshot lightbox */}
      {lightboxSrc && (
        <SnapshotLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}
    </div>
  )
}
