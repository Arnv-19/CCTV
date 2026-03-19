/**
 * ConfigPanel.jsx
 * ---------------
 * System configuration editor.
 *
 * Sections:
 *   1. Camera Streams        — add/edit/remove RTSP URLs + titles
 *   2. Detection Settings    — model path, confidence threshold
 *   3. Alarm Settings        — cooldown, legacy WiFi / ESP32 IP
 *   4. Per-Camera Buzzers    — multi-select buzzer assignment (DB-backed, admin only)
 *   5. Per-Camera AI Models  — enable / disable model flags per camera (DB-backed)
 */

import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Save, Bell, Cpu } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

// Known AI model names — extend as new models are added to the backend
const KNOWN_MODELS = ['helmet_detection', 'gloves_detection', 'vest_detection', 'glasses_detection', 'mask_detection', 'fire_detection']

function Section({ title, children }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-700 p-5 space-y-4">
      <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
      <label className="text-sm text-slate-400 sm:w-40 sm:shrink-0">{label}</label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

const inputCls =
  'w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm ' +
  'text-slate-100 focus:outline-none focus:border-blue-500'


// ── Per-camera buzzer assignment sub-component ─────────────────────────────────
function CameraBuzzers({ camId, allBuzzers }) {
  const [assigned, setAssigned] = useState([])  // list of buzzer_id ints
  const [saving,   setSaving]   = useState(false)

  useEffect(() => {
    api.getCameraBuzzers(camId)
      .then(rows => setAssigned(rows.map(r => r.buzzer_id)))
      .catch(() => {})
  }, [camId])

  const toggle = (buzzerId) => {
    setAssigned(prev =>
      prev.includes(buzzerId) ? prev.filter(id => id !== buzzerId) : [...prev, buzzerId]
    )
  }

  const save = async () => {
    setSaving(true)
    try { await api.setCameraBuzzers(camId, assigned) }
    catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  return (
    <div className="space-y-2">
      {allBuzzers.length === 0 ? (
        <span className="text-slate-500 text-xs">No buzzers configured yet.</span>
      ) : (
        <div className="flex flex-wrap gap-2">
          {allBuzzers.map(b => {
            const active = assigned.includes(b.id)
            return (
              <button key={b.id} onClick={() => toggle(b.id)} type="button"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                  active
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                }`}>
                <Bell size={10} />
                {b.name}
              </button>
            )
          })}
        </div>
      )}
      <button onClick={save} disabled={saving || allBuzzers.length === 0} type="button"
        className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40">
        {saving ? 'Saving...' : 'Save buzzer assignment'}
      </button>
    </div>
  )
}


// ── Per-camera model toggles sub-component ────────────────────────────────────
function CameraModels({ camId, canEdit }) {
  const [models,  setModels]  = useState({})   // { model_name: { id, is_enabled } }
  const [loading, setLoading] = useState(true) // blocks clicks until first fetch completes
  const [saving,  setSaving]  = useState(null)
  const [error,   setError]   = useState(null)

  const fetchModels = useCallback(async () => {
    try {
      const rows = await api.getCameraModels(camId)
      const map = {}
      for (const r of rows) map[r.model_name] = { id: r.id, is_enabled: r.is_enabled }
      setModels(map)
      setError(null)
    } catch (e) {
      setError(e?.message || 'Failed to load model state')
    } finally {
      setLoading(false)
    }
  }, [camId])

  useEffect(() => { fetchModels() }, [fetchModels])

  const handleToggle = async (modelName) => {
    if (!canEdit || loading) return

    setError(null)
    setSaving(modelName)
    try {
      const existing = models[modelName]
      if (existing) {
        // Row exists in DB — flip its current state
        await api.toggleCameraModel(camId, modelName)
      } else {
        // No DB row yet (implicit enabled default) — first click disables it
        await api.upsertCameraModel(camId, modelName, false)
      }
      await fetchModels()
    } catch (e) {
      console.error(e)
      setError(e?.message || 'Failed to update model state')
    }
    finally {
      setSaving(null)
    }
  }

  return (
    <div className="space-y-2">
      {loading && (
        <p className="text-xs text-slate-500 animate-pulse">Loading models…</p>
      )}
      <div className="flex flex-wrap gap-2">
        {KNOWN_MODELS.map(name => {
          const info = models[name]
          const enabled = info ? info.is_enabled : true  // default enabled if not in DB
          const busy = saving === name
          return (
            <button
              key={name}
              onClick={() => handleToggle(name)}
              type="button"
              disabled={busy || !canEdit || loading}
              title={canEdit ? '' : 'Only admin users can change model toggles'}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                enabled
                  ? 'bg-green-900/40 text-green-300 hover:bg-green-800/50'
                  : 'bg-slate-700 text-slate-500 hover:bg-slate-600'
              } ${!canEdit || loading ? 'cursor-not-allowed opacity-60' : ''} disabled:opacity-40`}
            >
              <Cpu size={10} />
              {busy ? '…' : name}
            </button>
          )
        })}
      </div>

      {!canEdit && (
        <p className="text-xs text-amber-400">Only admin users can edit model toggles.</p>
      )}

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}
    </div>
  )
}


// ── Main component ─────────────────────────────────────────────────────────────
export default function ConfigPanel({ onSaved }) {
  const { isAdmin } = useAuth()
  const [cfg,      setCfg]     = useState(null)
  const [buzzers,  setBuzzers] = useState([])
  const [saving,   setSaving]  = useState(false)
  const [error,    setError]   = useState(null)

  useEffect(() => {
    api.getConfig().then(setCfg).catch(e => setError(e.message))
    api.getBuzzers().then(setBuzzers).catch(() => {})
  }, [])

  const updateCamera = (i, field, val) => {
    setCfg(prev => {
      const feeds  = [...(prev.camera_feeds  || [])]
      const titles = [...(prev.camera_titles || [])]
      if (field === 'url') feeds[i] = val
      else titles[i] = val
      return { ...prev, camera_feeds: feeds, camera_titles: titles }
    })
  }

  const addCamera = () => {
    setCfg(prev => ({
      ...prev,
      camera_feeds:  [...(prev.camera_feeds  || []), ''],
      camera_titles: [...(prev.camera_titles || []), `Camera ${(prev.camera_feeds || []).length}`],
    }))
  }

  const removeCamera = (i) => {
    setCfg(prev => ({
      ...prev,
      camera_feeds:  prev.camera_feeds.filter((_,  idx) => idx !== i),
      camera_titles: prev.camera_titles.filter((_, idx) => idx !== i),
    }))
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.updateConfig(cfg)
      onSaved?.()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  if (!cfg) return (
    <div className="flex items-center justify-center h-full text-slate-500">
      {error
        ? <div className="text-red-400 text-sm">{error}</div>
        : 'Loading config...'}
    </div>
  )

  const cameraCount = (cfg.camera_feeds || []).length

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">
      {error && (
        <div className="bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Cameras */}
      <Section title="Camera Streams">
        <div className="space-y-2">
          <div className="hidden sm:grid sm:grid-cols-[1fr_180px_36px] gap-2 text-xs text-slate-500 px-1">
            <span>RTSP / Stream URL</span>
            <span>Title</span>
            <span />
          </div>
          {(cfg.camera_feeds || []).map((url, i) => (
            <div key={i} className="flex flex-col sm:grid sm:grid-cols-[1fr_180px_36px] gap-2 sm:items-center rounded-lg sm:rounded-none bg-slate-700/20 sm:bg-transparent p-2 sm:p-0">
              <input
                className={inputCls}
                value={url}
                onChange={e => updateCamera(i, 'url', e.target.value)}
                placeholder="rtsp://..."
              />
              <div className="flex gap-2 sm:contents">
                <input
                  className={`${inputCls} flex-1`}
                  value={(cfg.camera_titles || [])[i] || ''}
                  onChange={e => updateCamera(i, 'title', e.target.value)}
                  placeholder={`Camera ${i}`}
                />
                <button
                  onClick={() => removeCamera(i)}
                  className="p-2 text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded-lg transition-colors shrink-0"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
          <button
            onClick={addCamera}
            className="flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300 mt-1"
          >
            <Plus size={15} /> Add camera
          </button>
        </div>
      </Section>

      {/* Detection */}
      <Section title="Detection Settings">
        <Field label="Model path">
          <input
            className={inputCls}
            value={cfg.model_path || ''}
            onChange={e => setCfg({ ...cfg, model_path: e.target.value })}
          />
        </Field>
        <Field label="Confidence threshold">
          <div className="flex items-center gap-3">
            <input
              type="range" min="0.05" max="0.95" step="0.05"
              value={cfg.confidence_threshold || 0.25}
              onChange={e => setCfg({ ...cfg, confidence_threshold: parseFloat(e.target.value) })}
              className="flex-1"
            />
            <span className="w-12 text-sm text-slate-300 text-right">
              {(cfg.confidence_threshold || 0.25).toFixed(2)}
            </span>
          </div>
        </Field>
      </Section>

      {/* Alarm */}
      <Section title="Alarm Settings">
        <Field label="Cooldown (sec)">
          <input
            type="number" min="1" max="300"
            className={inputCls}
            value={cfg.alarm_cooldown_sec || 10}
            onChange={e => setCfg({ ...cfg, alarm_cooldown_sec: parseInt(e.target.value) })}
          />
        </Field>
        <Field label="Use WiFi">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={cfg.use_wifi || false}
              onChange={e => setCfg({ ...cfg, use_wifi: e.target.checked })}
              className="w-4 h-4 accent-blue-500"
            />
            <span className="text-sm text-slate-300">Send alarm over WiFi (ESP32)</span>
          </label>
        </Field>
        {cfg.use_wifi && (
          <Field label="ESP32 IP">
            <input
              className={inputCls}
              value={cfg.esp_ip || ''}
              onChange={e => setCfg({ ...cfg, esp_ip: e.target.value })}
              placeholder="192.168.1.100"
            />
          </Field>
        )}
      </Section>

      {/* Per-camera buzzer assignment (admin only) */}
      {isAdmin && cameraCount > 0 && (
        <Section title="Buzzer Assignments">
          <p className="text-xs text-slate-500 -mt-1">
            Select which buzzers fire for each camera. Changes take effect on next camera start.
          </p>
          <div className="space-y-4">
            {(cfg.camera_feeds || []).map((_, i) => (
              <div key={i}>
                <div className="text-xs font-semibold text-slate-400 mb-1.5">
                  {(cfg.camera_titles || [])[i] || `Camera ${i}`}
                </div>
                <CameraBuzzers camId={i} allBuzzers={buzzers} />
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Per-camera AI model toggles */}
      {cameraCount > 0 && (
        <Section title="AI Models per Camera">
          <p className="text-xs text-slate-500 -mt-1">
            Toggle which AI models run on each camera. Changes take effect on next camera start.
          </p>
          <div className="space-y-4">
            {(cfg.camera_feeds || []).map((_, i) => (
              <div key={i}>
                <div className="text-xs font-semibold text-slate-400 mb-1.5">
                  {(cfg.camera_titles || [])[i] || `Camera ${i}`}
                </div>
                <CameraModels camId={i} canEdit={isAdmin} />
              </div>
            ))}
          </div>
        </Section>
      )}

      <div className="flex justify-end">
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg font-semibold text-sm transition-colors disabled:opacity-50"
        >
          <Save size={15} />
          {saving ? 'Saving...' : 'Save All'}
        </button>
      </div>
    </div>
  )
}
