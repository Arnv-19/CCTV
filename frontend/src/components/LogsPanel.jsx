import { useState, useEffect, useRef } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../api/client'

export default function LogsPanel() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const bottomRef = useRef(null)

  const fetchLogs = async (scroll = false) => {
    setLoading(true)
    try {
      const data = await api.getLogs(200)
      setLogs(data.logs || [])
      if (scroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    } catch (e) {
      console.error('Failed to fetch logs:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs(true)
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => fetchLogs(false), 5000)
    return () => clearInterval(interval)
  }, [autoRefresh])

  const clearLogs = async () => {
    await api.clearLogs()
    setLogs([])
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400">{logs.length} entries</span>
          <label className="flex items-center gap-2 text-sm text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="accent-blue-500"
            />
            Auto-refresh (5s)
          </label>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => fetchLogs(true)}
            className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={clearLogs}
            className="flex items-center gap-1.5 text-sm text-red-400 hover:text-red-300 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
          >
            <Trash2 size={13} />
            Clear
          </button>
        </div>
      </div>

      {/* Log output */}
      <div className="flex-1 bg-slate-900 border border-slate-700 rounded-xl overflow-y-auto p-4 font-mono text-xs leading-6">
        {logs.length === 0 ? (
          <p className="text-slate-600">No alerts logged yet.</p>
        ) : (
          logs.map((line, i) => {
            const isViolation = line.toLowerCase().includes('no helmet')
            return (
              <div
                key={i}
                className={`${isViolation ? 'text-red-400' : 'text-slate-400'}`}
              >
                {line}
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
