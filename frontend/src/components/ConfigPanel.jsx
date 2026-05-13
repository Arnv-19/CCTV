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
const KNOWN_MODELS = ['helmet_detection', 'gloves_detection', 'vest_detection', 'glasses_detection', 'mask_detection']

function makeDraftCamera(index = 0) {
  return {
    id: null,
    name: `Camera ${index + 1}`,
    stream_url: '',
    location: '',
    is_active: true,
    ingestion_fps: 4,
    detection_width: 960,
    detection_height: 720,
  }
}

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
export default function ConfigPanel({ onSaved, systemMetrics }) {
  const { isAdmin } = useAuth()
  const [cfg,      setCfg]     = useState(null)
  const [missingCfg, setMissingCfg] = useState(null)
  const [crowdCfg, setCrowdCfg] = useState(null)
  const [dynamicFpsCfg, setDynamicFpsCfg] = useState(null)
  const [fpsRecommendations, setFpsRecommendations] = useState([])
  const [buzzers,  setBuzzers] = useState([])
  const [saving,   setSaving]  = useState(false)
  const [error,    setError]   = useState(null)
  const [success,  setSuccess] = useState(null)

  useEffect(() => {
    api.getConfig().then(setCfg).catch(e => setError(e.message))
    api.getMissingPersonConfig().then(setMissingCfg).catch(() => {})
    api.getCrowdAlertConfig().then(setCrowdCfg).catch(() => {})
    api.getDynamicFpsConfig().then(setDynamicFpsCfg).catch(() => {})
    api.getBuzzers().then(setBuzzers).catch(() => {})
  }, [])

  const updateCamera = (i, field, val) => {
    setCfg(prev => {
      const cameras = [...(prev.cameras || [])]
      cameras[i] = { ...cameras[i], [field]: val }
      return { ...prev, cameras }
    })
  }

  const addCamera = () => {
    setCfg(prev => ({
      ...prev,
      cameras: [...(prev.cameras || []), makeDraftCamera((prev.cameras || []).length)],
    }))
  }

  const removeCamera = async (i) => {
    const cam = (cfg.cameras || [])[i]
    if (cam.id != null) {
      try {
        await api.deleteCamera(cam.id)
      } catch (e) {
        setError(`Failed to delete camera: ${e.message}`)
        return
      }
    }
    setCfg(prev => ({
      ...prev,
      cameras: (prev.cameras || []).filter((_, idx) => idx !== i),
    }))
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      // Save non-camera settings first so model rows exist in DB before assignment creation
      const { cameras: _c, camera_feeds: _f, camera_titles: _t, ...settingsOnly } = cfg
      await api.updateConfig(settingsOnly)

      // Save each camera via its dedicated endpoint (assignments are created server-side)
      for (const cam of (cfg.cameras || [])) {
        if (cam.id == null) {
          await api.addCamera({
            name: cam.name,
            stream_url: cam.stream_url,
            location: cam.location,
            is_active: cam.is_active ?? true,
            ingestion_fps: cam.ingestion_fps ?? 4,
            detection_width: cam.detection_width ?? 960,
            detection_height: cam.detection_height ?? 720,
          })
        } else {
          await api.updateCamera(cam.id, {
            name: cam.name,
            stream_url: cam.stream_url,
            location: cam.location,
            is_active: cam.is_active,
            ingestion_fps: cam.ingestion_fps,
            detection_width: cam.detection_width,
            detection_height: cam.detection_height,
          })
        }
      }

      // Reload config to get fresh camera list with correct IDs for new cameras
      const freshCfg = await api.getConfig()
      setCfg(freshCfg)
      onSaved?.()
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const loadFpsRecommendations = async () => {
    try {
      setFpsRecommendations(await api.getDynamicFpsRecommendations(systemMetrics?.system?.cpu_percent))
    } catch (e) { setError(e.message) }
  }

  const applyFpsRecommendations = async () => {
    try {
      setFpsRecommendations(await api.applyDynamicFps(systemMetrics?.system?.cpu_percent))
      setSuccess('Dynamic FPS applied. Restart detection to use new FPS.')
    } catch (e) { setError(e.message) }
  }

  if (!cfg) return (
    <div className="flex items-center justify-center h-full text-slate-500">
      {error
        ? <div className="text-red-400 text-sm">{error}</div>
        : 'Loading config...'}
    </div>
  )

  const cameras = cfg.cameras || []
  const cameraCount = cameras.length
  const system = systemMetrics?.system
  const process = systemMetrics?.process

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">
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

      {system && process && (
        <Section title="System Resource Overview">
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
            <div className="rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Server CPU</p>
              <p className="mt-1 text-2xl font-semibold text-slate-100">{system.cpu_percent}%</p>
              <p className="text-xs text-slate-400">{system.cpu_logical_cores} logical cores</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">App CPU</p>
              <p className="mt-1 text-2xl font-semibold text-slate-100">{process.cpu_percent_total_machine}%</p>
              <p className="text-xs text-slate-400">{process.cpu_percent_single_core}% of one core</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Server Memory</p>
              <p className="mt-1 text-2xl font-semibold text-slate-100">{system.used_memory_gb} / {system.total_memory_gb} GB</p>
              <p className="text-xs text-slate-400">App RSS {process.rss_memory_mb} MB</p>
            </div>
            <div className="rounded-xl border border-slate-700 bg-slate-900/60 px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">CPU Layout</p>
              <p className="mt-1 text-2xl font-semibold text-slate-100">{system.cpu_physical_cores} / {system.cpu_logical_cores}</p>
              <p className="text-xs text-slate-400">physical / logical cores</p>
            </div>
          </div>
        </Section>
      )}

      {/* Cameras */}
      <Section title="Camera Streams">
        <div className="space-y-2">
          <div className="hidden sm:grid sm:grid-cols-[1fr_160px_80px_36px] gap-2 text-xs text-slate-500 px-1">
            <span>RTSP / Stream URL</span>
            <span>Title</span>
            <span>FPS</span>
            <span />
          </div>
          {cameras.map((camera, i) => (
            <div key={camera.id ?? `draft-${i}`} className="flex flex-col sm:grid sm:grid-cols-[1fr_160px_80px_36px] gap-2 sm:items-center rounded-lg sm:rounded-none bg-slate-700/20 sm:bg-transparent p-2 sm:p-0">
              <input
                className={inputCls}
                value={camera.stream_url || ''}
                onChange={e => updateCamera(i, 'stream_url', e.target.value)}
                placeholder="rtsp://..."
              />
              <input
                className={inputCls}
                value={camera.name || ''}
                onChange={e => updateCamera(i, 'name', e.target.value)}
                placeholder={`Camera ${i + 1}`}
              />
              <div className="flex gap-2 sm:contents">
                <input
                  type="number"
                  min="1"
                  max="30"
                  className={`${inputCls} flex-1`}
                  value={camera.ingestion_fps ?? 4}
                  onChange={e => updateCamera(i, 'ingestion_fps', parseInt(e.target.value) || 1)}
                  title="Frames per second ingested from stream"
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
        <Field label="Person model path">
          <input
            className={inputCls}
            value={cfg.person_model_path || ''}
            onChange={e => setCfg({ ...cfg, person_model_path: e.target.value })}
          />
        </Field>
        <Field label="Gloves model path">
          <input
            className={inputCls}
            value={cfg.gloves_model_path || ''}
            onChange={e => setCfg({ ...cfg, gloves_model_path: e.target.value })}
          />
        </Field>
        <Field label="PPE model path">
          <input
            className={inputCls}
            value={cfg.ppe_model_path || ''}
            onChange={e => setCfg({ ...cfg, ppe_model_path: e.target.value })}
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
            {cameras.map((camera, i) => (
              <div key={camera.id ?? `buzzer-${i}`}>
                <div className="text-xs font-semibold text-slate-400 mb-1.5">
                  {camera.name || `Camera ${i + 1}`}
                </div>
                {camera.id == null ? (
                  <p className="text-xs text-slate-500">Save this camera first to assign buzzers.</p>
                ) : (
                  <CameraBuzzers camId={camera.id} allBuzzers={buzzers} />
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {(missingCfg || crowdCfg || dynamicFpsCfg) && (
        <Section title="Safety Automation">
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            {missingCfg && (
              <div className="rounded-xl border border-slate-700 bg-slate-900/40 p-4 space-y-3">
                <label className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-200">Missing person</span>
                  <input type="checkbox" className="w-4 h-4 accent-blue-500" checked={!!missingCfg.enabled} disabled={!isAdmin}
                    onChange={e => setMissingCfg({ ...missingCfg, enabled: e.target.checked })} />
                </label>
                <Field label="Frames"><input className={inputCls} type="number" min="1" disabled={!isAdmin} value={missingCfg.missing_frames ?? 3600}
                  onChange={e => setMissingCfg({ ...missingCfg, missing_frames: Number(e.target.value) })} /></Field>
                <Field label="Cooldown"><input className={inputCls} type="number" min="0" disabled={!isAdmin} value={missingCfg.cooldown_sec ?? 300}
                  onChange={e => setMissingCfg({ ...missingCfg, cooldown_sec: Number(e.target.value) })} /></Field>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" className="w-4 h-4 accent-green-500" checked={!!missingCfg.send_whatsapp} disabled={!isAdmin}
                    onChange={e => setMissingCfg({ ...missingCfg, send_whatsapp: e.target.checked })} />
                  WhatsApp snapshot
                </label>
              </div>
            )}

            {crowdCfg && (
              <div className="rounded-xl border border-slate-700 bg-slate-900/40 p-4 space-y-3">
                <label className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-200">Crowd alert</span>
                  <input type="checkbox" className="w-4 h-4 accent-blue-500" checked={!!crowdCfg.enabled} disabled={!isAdmin}
                    onChange={e => setCrowdCfg({ ...crowdCfg, enabled: e.target.checked })} />
                </label>
                <Field label="People"><input className={inputCls} type="number" min="1" disabled={!isAdmin} value={crowdCfg.person_threshold ?? 5}
                  onChange={e => setCrowdCfg({ ...crowdCfg, person_threshold: Number(e.target.value) })} /></Field>
                <Field label="Seconds"><input className={inputCls} type="number" min="0" step="0.5" disabled={!isAdmin} value={crowdCfg.sustained_seconds ?? 5}
                  onChange={e => setCrowdCfg({ ...crowdCfg, sustained_seconds: Number(e.target.value) })} /></Field>
                <Field label="Cooldown"><input className={inputCls} type="number" min="0" disabled={!isAdmin} value={crowdCfg.cooldown_sec ?? 300}
                  onChange={e => setCrowdCfg({ ...crowdCfg, cooldown_sec: Number(e.target.value) })} /></Field>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" className="w-4 h-4 accent-green-500" checked={!!crowdCfg.send_whatsapp} disabled={!isAdmin}
                    onChange={e => setCrowdCfg({ ...crowdCfg, send_whatsapp: e.target.checked })} />
                  WhatsApp snapshot
                </label>
              </div>
            )}

            {/* Dynamic FPS — uncomment when required
            {dynamicFpsCfg && (
              <div className="rounded-xl border border-slate-700 bg-slate-900/40 p-4 space-y-3">
                <label className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-slate-200">Dynamic FPS</span>
                  <input type="checkbox" className="w-4 h-4 accent-blue-500" checked={!!dynamicFpsCfg.enabled} disabled={!isAdmin}
                    onChange={e => setDynamicFpsCfg({ ...dynamicFpsCfg, enabled: e.target.checked })} />
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {['min_fps', 'max_fps', 'default_fps'].map(key => (
                    <label key={key} className="space-y-1">
                      <span className="text-xs text-slate-400">{key.replace('_fps', '')}</span>
                      <input className={inputCls} type="number" min="1" disabled={!isAdmin} value={dynamicFpsCfg[key] ?? 4}
                        onChange={e => setDynamicFpsCfg({ ...dynamicFpsCfg, [key]: Number(e.target.value) })} />
                    </label>
                  ))}
                </div>
                <Field label="CPU target"><input className={inputCls} type="number" min="1" max="100" disabled={!isAdmin}
                  value={dynamicFpsCfg.target_cpu_percent ?? 70}
                  onChange={e => setDynamicFpsCfg({ ...dynamicFpsCfg, target_cpu_percent: Number(e.target.value) })} /></Field>
                <div className="flex gap-2">
                  <button type="button" onClick={loadFpsRecommendations}
                    className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold px-3 py-2 rounded-lg">Recommend</button>
                  <button type="button" onClick={applyFpsRecommendations} disabled={!isAdmin}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3 py-2 rounded-lg disabled:opacity-50">Apply</button>
                </div>
                {fpsRecommendations.length > 0 && (
                  <div className="text-xs text-slate-400 space-y-1">
                    {fpsRecommendations.map(r => <div key={r.camera_id} className="flex justify-between"><span>Cam {r.camera_id}</span><span>{r.current_fps ?? '-'} → {r.recommended_fps} fps</span></div>)}
                  </div>
                )}
              </div>
            )}
            */}
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
            {cameras.map((camera, i) => (
              <div key={camera.id ?? `model-${i}`}>
                <div className="text-xs font-semibold text-slate-400 mb-1.5">
                  {camera.name || `Camera ${i + 1}`}
                </div>
                {camera.id == null ? (
                  <p className="text-xs text-slate-500">Save this camera first to configure AI models.</p>
                ) : (
                  <CameraModels camId={camera.id} canEdit={isAdmin} />
                )}
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
