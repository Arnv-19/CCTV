/**
 * App.jsx
 * -------
 * Root component. Wraps the authenticated shell or redirects to /login.
 * Role-based tab visibility: Reports/Buzzers/Users shown to admins only.
 */

import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import {
  Camera, Settings, FileText, Bell, Play, Square,
  Wifi, WifiOff, BarChart2, BellRing, Users, LogOut, X,ShieldAlert
} from 'lucide-react'
import { useAuth } from './contexts/AuthContext'
import { api } from './api/client'
import LiveView      from './components/LiveView'
import ConfigPanel   from './components/ConfigPanel'
import LogsPanel     from './components/LogsPanel'
import AlarmPanel    from './components/AlarmPanel'
import ReportsPanel  from './components/ReportsPanel'
import BuzzersPanel  from './components/BuzzersPanel'
import UsersPanel    from './components/UsersPanel'
import ROIEditorPage from './components/ROIEditorPage'
import BurglarAlarmPanel  from './components/BurglarAlarmPanel'


function buildTabs(isAdmin) {
  const tabs = [
    { id: 'live',    label: 'Live View',     Icon: Camera    },
    { id: 'config',  label: 'Configuration', Icon: Settings  },
    { id: 'reports', label: 'Reports',        Icon: BarChart2 },
    { id: 'logs',    label: 'Logs',           Icon: FileText  },
    { id: 'alarm',   label: 'Alarm',          Icon: Bell      },
    { id: 'burglar', label: 'Burglar Alarm',  Icon: ShieldAlert  },

  ]
  if (isAdmin) {
    tabs.push(
      { id: 'buzzers', label: 'Buzzers', Icon: BellRing },
      { id: 'users',   label: 'Users',   Icon: Users    },
    )
  }
  return tabs
}

export default function App() {
  const { token, user, isAdmin, logout } = useAuth()

  // Redirect to login if not authenticated
  if (!token) return <Navigate to="/login" replace />

  const [tab,         setTab]         = useState('live')
  const [cameras,     setCameras]     = useState([])
  const [running,     setRunning]     = useState(false)
  const [loading,     setLoading]     = useState(false)
  const [toast,       setToast]       = useState(null)
  const [streamEpoch, setStreamEpoch] = useState(0)
  const [roiCameraId, setRoiCameraId] = useState(null)  // null = ROI modal closed
  const [resourceMetrics, setResourceMetrics] = useState(null)

  const TABS = buildTabs(isAdmin)

  // Reset tab if it is no longer visible (e.g. after role change)
  useEffect(() => {
    if (!TABS.find(t => t.id === tab)) setTab('live')
  }, [isAdmin])

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  // Listen for 401 events emitted by client.js
  useEffect(() => {
    const handler = () => { showToast('Session expired', 'error'); logout() }
    window.addEventListener('skycctvai:unauthorized', handler)
    return () => window.removeEventListener('skycctvai:unauthorized', handler)
  }, [logout, showToast])

  // Reconnect streams when returning from a background browser tab or window blur.
  // Browsers throttle/kill background MJPEG connections; bumping streamEpoch forces a fresh reconnect.
  useEffect(() => {
    const bump = () => setStreamEpoch(n => n + 1)
    const onVisible = () => { if (document.visibilityState === 'visible') bump() }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', bump)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', bump)
    }
  }, [])

  const fetchCameras = useCallback(async () => {
    try {
      const [cameraData, metricsData] = await Promise.all([
        api.getCameras(),
        api.getCameraMetrics(),
      ])
      const resourceByCameraId = new Map((metricsData?.cameras || []).map((cam) => [cam.id, cam]))
      const mergedCameras = cameraData.map((cam) => ({
        ...cam,
        resources: resourceByCameraId.get(cam.id) || null,
      }))
      setCameras(mergedCameras)
      setResourceMetrics(metricsData)
      setRunning(mergedCameras.some(c => c.active))
    } catch {
      try {
        const data = await api.getCameras()
        setCameras(data)
        setRunning(data.some(c => c.active))
      } catch {}
      setResourceMetrics(null)
    }
  }, [])

  useEffect(() => {
    fetchCameras()
    const id = setInterval(fetchCameras, 3000)
    return () => clearInterval(id)
  }, [fetchCameras])

  const handleTabChange = (newTab) => {
    // Force stream reconnect when returning to live tab so streams aren't stale
    if (newTab === 'live' && tab !== 'live') {
      setStreamEpoch((n) => n + 1)
    }
    setTab(newTab)
  }

  const handleStartStop = async () => {
    setLoading(true)
    try {
      if (running) {
        await api.stopAll()
        showToast('Detection stopped')
        setRunning(false)
        setStreamEpoch((n) => n + 1)
        await fetchCameras()
      } else {
        await api.startAll()
        showToast('Detection started')
        // Optimistically show streams immediately — don't wait for fetchCameras()
        // which can race against thread startup and return running=false even
        // when the backend is healthy (confirmed by hard-refresh working).
        setRunning(true)
        setStreamEpoch((n) => n + 1)
        // Non-blocking background fetch to sync actual camera data
        fetchCameras()
      }
    } catch (e) { showToast(e.message, 'error') }
    finally { setLoading(false) }
  }

  const activeViolations = cameras.reduce((s, c) => s + (c.violations || 0), 0)
  const roiCamera = roiCameraId !== null ? cameras.find(c => c.id === roiCameraId) : null

  return (
    <div className="flex flex-col h-screen bg-zinc-900 text-zinc-100">
      {/* Header */}
      <header className="flex items-center justify-between px-3 sm:px-6 py-3 bg-zinc-800 border-b border-zinc-700 shrink-0 gap-2">
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <div className="w-8 h-8 rounded-lg bg-emerald-600 flex items-center justify-center shrink-0">
            <Camera size={18} />
          </div>
          <span className="text-base sm:text-lg font-bold tracking-wide">Axis CCTV</span>
        </div>

        {/* Desktop stats — hidden on mobile */}
        <div className="hidden md:flex items-center gap-6 text-sm text-zinc-400">
          <span>{cameras.length} camera{cameras.length !== 1 ? 's' : ''}</span>
          {activeViolations > 0 && (
            <span className="text-red-400 font-semibold">
              {activeViolations} violation{activeViolations !== 1 ? 's' : ''}
            </span>
          )}
          <div className="flex items-center gap-1.5">
            {running
              ? <Wifi size={14} className="text-green-400" />
              : <WifiOff size={14} className="text-zinc-500" />}
            <span className={running ? 'text-green-400' : 'text-zinc-500'}>
              {running ? 'Running' : 'Stopped'}
            </span>
          </div>
          {/* Logged-in user + role badge */}
          <div className="flex items-center gap-2 text-xs text-zinc-500 border-l border-zinc-700 pl-4">
            <span className="text-zinc-300">{user?.sub}</span>
            <span className={`px-1.5 py-0.5 rounded font-semibold ${
              isAdmin ? 'bg-purple-900/50 text-purple-300' : 'bg-zinc-700 text-zinc-400'
            }`}>{user?.role}</span>
          </div>
        </div>

        {/* Mobile compact status — visible only on mobile */}
        <div className="flex md:hidden items-center gap-2 text-xs text-zinc-400 min-w-0">
          {running
            ? <Wifi size={13} className="text-green-400 shrink-0" />
            : <WifiOff size={13} className="text-zinc-500 shrink-0" />}
          {activeViolations > 0 && (
            <span className="text-red-400 font-semibold shrink-0">{activeViolations}!</span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {tab === 'live' && (
            <button
              onClick={handleStartStop}
              disabled={loading}
              className={`flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2 rounded-lg font-semibold text-sm transition-colors ${
                running
                  ? 'bg-red-600 hover:bg-red-700 text-white'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              } disabled:opacity-50`}
            >
              {running ? <Square size={14} /> : <Play size={14} />}
              {loading ? '...' : running ? 'Stop' : 'Start'}
            </button>
          )}
          <button onClick={logout} title="Sign out"
            className="p-2 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 rounded-lg transition-colors">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* Tabs — horizontally scrollable on mobile */}
      <nav className="flex gap-1 px-2 sm:px-6 pt-3 bg-zinc-800 border-b border-zinc-700 shrink-0 overflow-x-auto">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => handleTabChange(id)}
            className={`flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2 text-sm font-medium rounded-t-lg transition-colors whitespace-nowrap shrink-0 ${
              tab === id
                ? 'bg-zinc-900 text-emerald-400 border-b-2 border-emerald-400'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-hidden">
        {/* LiveView is always mounted so MJPEG connections survive tab switches. */}
        <div className={tab === 'live' ? 'h-full' : 'hidden'}>
          <LiveView
            cameras={cameras}
            running={running}
            streamEpoch={streamEpoch}
            systemMetrics={resourceMetrics}
            onEditROI={setRoiCameraId}
          />
        </div>
        {tab === 'config'  && (
          <ConfigPanel
            onSaved={() => { showToast('Config saved'); fetchCameras() }}
            systemMetrics={resourceMetrics}
          />
        )}
        {tab === 'reports' && <ReportsPanel />}
        {tab === 'logs'    && <LogsPanel />}
        {tab === 'alarm'   && <AlarmPanel onTest={() => showToast('Alarm triggered')} />}
        {tab === 'burglar' && <BurglarAlarmPanel />}
        {tab === 'buzzers' && isAdmin && <BuzzersPanel />}
        {tab === 'users'   && isAdmin && <UsersPanel />}
      </main>

      {/* ROI Editor modal — fullscreen overlay on top of live view */}
      {roiCameraId !== null && (
        <div className="fixed inset-0 z-50 flex flex-col bg-zinc-950">
          {/* Modal header */}
          <div className="flex items-center justify-between px-4 py-2 bg-zinc-800 border-b border-zinc-700 shrink-0">
            <span className="text-sm font-semibold text-zinc-200">
              ROI Zones — {roiCamera?.title || `Camera ${roiCameraId}`}
            </span>
            <button
              onClick={() => setRoiCameraId(null)}
              className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              title="Close ROI editor"
            >
              <X size={16} />
            </button>
          </div>
          {/* Editor */}
          <div className="flex-1 overflow-hidden">
            <ROIEditorPage
              key={roiCameraId}
              cameraId={String(roiCameraId)}
              streamUrl={api.streamUrl(roiCameraId)}
            />
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 px-4 py-3 rounded-lg text-sm font-medium shadow-lg transition-all ${
          toast.type === 'error' ? 'bg-red-600' : 'bg-green-600'
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
