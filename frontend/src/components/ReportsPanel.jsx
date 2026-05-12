/**
 * ReportsPanel.jsx
 * ----------------
 * Filterable alert history with pagination, CSV export, and acknowledge button.
 * Also shows summary cards: today's total, unacknowledged, top camera, top model.
 */

import { useState, useEffect, useCallback } from 'react'
import { Download, CheckCheck, AlertTriangle, Camera, Cpu, BellRing, FileText, FileSpreadsheet, MessageCircle } from 'lucide-react'
import { api } from '../api/client'

const inputCls =
  'bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm ' +
  'text-slate-100 focus:outline-none focus:border-blue-500'

function SummaryCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
        <Icon size={18} />
      </div>
      <div>
        <div className="text-xl font-bold text-slate-100">{value ?? '—'}</div>
        <div className="text-xs text-slate-400">{label}</div>
      </div>
    </div>
  )
}

export default function ReportsPanel() {
  const [alerts,  setAlerts]  = useState([])
  const [summary, setSummary] = useState(null)
  const [filters, setFilters] = useState({
    camera_id: '', date_from: '', date_to: '',
  })
  const [appliedFilters, setAppliedFilters] = useState({
    camera_id: '', date_from: '', date_to: '',
  })
  const [page,    setPage]    = useState(1)
  const [total,   setTotal]   = useState(0)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)
  const [success, setSuccess] = useState('')
  const PAGE_SIZE = 10
  const reportDate = appliedFilters.date_to || appliedFilters.date_from || new Date().toISOString().slice(0, 10)
  const reportParams = {
    report_date: reportDate,
    camera_id: appliedFilters.camera_id ? Number(appliedFilters.camera_id) : undefined,
    date_from: appliedFilters.date_from || undefined,
    date_to: appliedFilters.date_to || undefined,
    use_dummy_data: false,
  }
  const reportFileLabel = appliedFilters.date_from && appliedFilters.date_to
    ? (appliedFilters.date_from === appliedFilters.date_to
        ? appliedFilters.date_from
        : `${appliedFilters.date_from}_to_${appliedFilters.date_to}`)
    : (appliedFilters.date_to || appliedFilters.date_from || reportDate)

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        ...Object.fromEntries(Object.entries(appliedFilters).filter(([, v]) => v !== '')),
        page,
        limit: PAGE_SIZE,
      }
      const data = await api.getAlerts(params)
      // Backend returns { items, total } or plain array depending on version
      if (Array.isArray(data)) {
        setAlerts(data)
        setTotal(data.length)
      } else {
        setAlerts(data.items ?? [])
        setTotal(data.total ?? 0)
      }
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [appliedFilters, page])

  const fetchSummary = useCallback(async () => {
    try { setSummary(await api.getAlertSummary()) }
    catch {}
  }, [])

  useEffect(() => { fetchAlerts(); fetchSummary() }, [fetchAlerts, fetchSummary])

  useEffect(() => {
    if (!success) return undefined
    const timer = window.setTimeout(() => setSuccess(''), 3000)
    return () => window.clearTimeout(timer)
  }, [success])

  const handleFilter = (e) => {
    e.preventDefault()
    setSuccess('')
    setPage(1)
    const normalized = { ...filters }
    if (normalized.date_from && !normalized.date_to) normalized.date_to = normalized.date_from
    if (normalized.date_to && !normalized.date_from) normalized.date_from = normalized.date_to
    setFilters(normalized)
    setAppliedFilters(normalized)
  }

  const handleAck = async (id) => {
    try { await api.acknowledgeAlert(id); fetchAlerts(); fetchSummary() }
    catch (e) { setError(e.message) }
  }

  const handleExport = async () => {
    try {
      const params = Object.fromEntries(Object.entries(appliedFilters).filter(([, v]) => v !== ''))
      const res = await api.exportAlertsCsv(params)
      const blob = res.data
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `alerts_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setError(e.message) }
  }

  const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleDailyPdf = async () => {
    try {
      const res = await api.exportDailyReportPdf(reportParams)
      downloadBlob(res.data, `daily_alert_report_${reportFileLabel}.pdf`)
    } catch (e) { setError(e.message) }
  }

  const handleDailyExcel = async () => {
    try {
      const res = await api.exportDailyReportExcel(reportParams)
      downloadBlob(res.data, `daily_alert_report_${reportFileLabel}.xlsx`)
    } catch (e) { setError(e.message) }
  }

  const handleWhatsAppReport = async () => {
    try {
      setLoading(true)
      setError(null)
      setSuccess('')
      await api.sendDailyReportWhatsApp({
        ...reportParams,
        include_pdf: true,
        include_excel: true,
      })
      await fetchAlerts()
      await fetchSummary()
      setSuccess('Report sent to WhatsApp successfully.')
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleSnapshotWhatsApp = async (alert) => {
    try {
      setError(null)
      setSuccess('')
      await api.sendSnapshotWhatsApp({
        snapshot_path: alert.snapshot_path,
        caption: `AXIS CCTV SNAPSHOT | Cam ${alert.camera_id} | ${alert.violation_type}`,
      })
      setSuccess('Snapshot sent to WhatsApp successfully.')
    } catch (e) { setError(e.message) }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-emerald-900/30 border border-emerald-700 text-emerald-300 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
          <CheckCheck size={16} className="shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SummaryCard icon={AlertTriangle} label="Today's alerts" value={summary.today_count}   color="bg-yellow-900/40 text-yellow-400" />
          <SummaryCard icon={BellRing}      label="Unacknowledged" value={summary.unacknowledged} color="bg-red-900/40 text-red-400" />
          <SummaryCard icon={Camera}        label="Top camera"     value={summary.top_camera != null ? `Cam ${summary.top_camera}` : '—'} color="bg-blue-900/40 text-blue-400" />
          <SummaryCard icon={Cpu}           label="Top model"      value={summary.top_model}      color="bg-purple-900/40 text-purple-400" />
        </div>
      )}

      {/* Filters */}
      <form onSubmit={handleFilter}
        className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">Filter Alerts</h3>
            <p className="text-xs text-slate-400">Camera aur date range ke hisaab se alerts dekhein.</p>
          </div>
          <div className="text-xs text-slate-400">
            Showing {alerts.length} of {total} alerts
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-slate-400">Camera ID</label>
            <input className={`${inputCls} w-full`} type="number" placeholder="All cameras"
              value={filters.camera_id} onChange={e => setFilters({ ...filters, camera_id: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-slate-400">Date From</label>
            <input className={`${inputCls} w-full color-scheme-dark`} type="date"
              value={filters.date_from} onChange={e => setFilters({ ...filters, date_from: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-slate-400">Date To</label>
            <input className={`${inputCls} w-full color-scheme-dark`} type="date"
              value={filters.date_to} onChange={e => setFilters({ ...filters, date_to: e.target.value })} />
          </div>
          <div className="flex items-end gap-2">
            <button type="submit"
              className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
              Apply Filter
            </button>
            <button
              type="button"
              onClick={() => {
                setSuccess('')
                setFilters({ camera_id: '', date_from: '', date_to: '' })
                setAppliedFilters({ camera_id: '', date_from: '', date_to: '' })
                setPage(1)
              }}
              className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button type="button" onClick={handleDailyPdf}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-rose-700 hover:bg-rose-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
            <FileText size={14} /> Daily PDF
          </button>
          <button type="button" onClick={handleDailyExcel}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
            <FileSpreadsheet size={14} /> Daily Excel
          </button>
          <button type="button" onClick={handleWhatsAppReport}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-green-600 hover:bg-green-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors">
            <MessageCircle size={14} /> WhatsApp Report
          </button>
          <button type="button" onClick={handleExport}
            className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm font-semibold px-4 py-2 rounded-lg transition-colors sm:ml-auto">
            <Download size={14} /> Export CSV
          </button>
        </div>
      </form>

      {/* Table */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-x-auto">
        {loading ? (
          <div className="px-6 py-10 text-center text-slate-500 text-sm">Loading...</div>
        ) : alerts.length === 0 ? (
          <div className="px-6 py-10 text-center text-slate-500 text-sm">No alerts found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-700/50">
              <tr className="text-left text-xs text-slate-400 uppercase tracking-wider">
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Camera</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">Violation</th>
                <th className="px-4 py-3">Conf</th>
                <th className="px-4 py-3">Buzzer</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {alerts.map(a => (
                <tr key={a.id}
                  className={`hover:bg-slate-700/30 transition-colors ${a.acknowledged ? 'opacity-60' : ''}`}>
                  <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                    {new Date(a.triggered_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-slate-300">Cam {a.camera_id}</td>
                  <td className="px-4 py-3 text-slate-300 font-mono text-xs">{a.model_name}</td>
                  <td className="px-4 py-3">
                    <span className="bg-red-900/40 text-red-300 text-xs font-semibold px-2 py-0.5 rounded-full">
                      {a.violation_type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    {(a.confidence_score * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      a.buzzer_activated
                        ? 'bg-orange-900/40 text-orange-300'
                        : 'bg-slate-700 text-slate-500'
                    }`}>
                      {a.buzzer_activated ? 'Fired' : 'No'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                    {a.snapshot_path && (
                      <button onClick={() => handleSnapshotWhatsApp(a)}
                        className="text-xs text-green-400 hover:text-green-300 hover:underline">
                        WhatsApp
                      </button>
                    )}
                    {a.acknowledged ? (
                      <span className="text-xs text-green-500 flex items-center justify-end gap-1">
                        <CheckCheck size={12} /> Done
                      </span>
                    ) : (
                      <button onClick={() => handleAck(a.id)}
                        className="text-xs text-blue-400 hover:text-blue-300 hover:underline">
                        Acknowledge
                      </button>
                    )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between gap-3 text-sm bg-slate-800 border border-slate-700 rounded-xl px-4 py-3">
          <span className="text-slate-400">
            Page {page} of {totalPages}
          </span>
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
            className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors disabled:opacity-40">
            Prev
          </button>
          <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
            className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors disabled:opacity-40">
            Next
          </button>
        </div>
      )}
    </div>
  )
}
