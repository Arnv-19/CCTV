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
import { Plus, Trash2, Save, Bell, Cpu, FolderOpen, X, Pencil } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../contexts/AuthContext'


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
    face_detection_enabled: false,
  }
}

function Section({ title, children }) {
  return (
    <div className="bg-zinc-800 rounded-xl border border-zinc-700 p-5 space-y-4">
      <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-4">
      <label className="text-sm text-zinc-400 sm:w-40 sm:shrink-0">{label}</label>
      <div className="flex-1">{children}</div>
    </div>
  )
}

const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-sm ' +
  'text-zinc-100 focus:outline-none focus:border-emerald-500'


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
        <span className="text-zinc-500 text-xs">No buzzers configured yet.</span>
      ) : (
        <div className="flex flex-wrap gap-2">
          {allBuzzers.map(b => {
            const active = assigned.includes(b.id)
            return (
              <button key={b.id} onClick={() => toggle(b.id)} type="button"
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                  active
                    ? 'bg-emerald-600 text-white'
                    : 'bg-zinc-700 text-zinc-400 hover:bg-zinc-600'
                }`}>
                <Bell size={10} />
                {b.name}
              </button>
            )
          })}
        </div>
      )}
      <button onClick={save} disabled={saving || allBuzzers.length === 0} type="button"
        className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-40">
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

  const modelNames = Object.keys(models).sort()

  return (
    <div className="space-y-2">
      {loading && <p className="text-xs text-zinc-500 animate-pulse">Loading models…</p>}
      {!loading && modelNames.length === 0 && (
        <p className="text-xs text-zinc-500">No model types configured for this camera.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {modelNames.map(name => {
          const enabled = models[name].is_enabled
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
                  : 'bg-zinc-700 text-zinc-500 hover:bg-zinc-600'
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
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}


// ── Per-camera missing person override ────────────────────────────────────────
function CameraMissingPerson({ camera, missingCfg, setMissingCfg, canEdit }) {
  const camId    = String(camera.id)
  const override = missingCfg?.per_camera?.[camId]

  const [active,  setActive]  = useState(!!override)
  const [enabled, setEnabled] = useState(override?.enabled ?? missingCfg?.enabled ?? false)
  const [frames,  setFrames]  = useState(override?.missing_frames ?? missingCfg?.missing_frames ?? 3600)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState(null)

  const camFps = camera.ingestion_fps || 4

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const newPerCamera = { ...(missingCfg?.per_camera || {}) }
      if (active) {
        newPerCamera[camId] = { enabled, missing_frames: frames }
      } else {
        delete newPerCamera[camId]
      }
      setMissingCfg(await api.updateMissingPersonConfig({ per_camera: newPerCamera }))
    } catch (e) {
      setError(e?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/40 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-zinc-300">{camera.name || `Camera ${camera.id}`}</span>
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input type="checkbox" className="w-3.5 h-3.5 accent-emerald-500"
            checked={active} disabled={!canEdit} onChange={e => setActive(e.target.checked)} />
          Override
        </label>
      </div>

      {active && (
        <div className="space-y-2 pt-1 border-t border-zinc-700/60">
          <label className="flex items-center justify-between text-xs text-zinc-300">
            <span>Enabled</span>
            <input type="checkbox" className="w-3.5 h-3.5 accent-green-500"
              checked={enabled} disabled={!canEdit} onChange={e => setEnabled(e.target.checked)} />
          </label>
          <Field label="Frames">
            <input className={inputCls} type="number" min="1"
              disabled={!canEdit || !enabled} value={frames}
              onChange={e => setFrames(Number(e.target.value))}
              title="Consecutive frames with no person before alert fires" />
          </Field>
          {enabled && (
            <p className="text-[11px] text-zinc-500">≈ {Math.round(frames / camFps / 60)} min at {camFps} fps</p>
          )}
        </div>
      )}

      {!active && (
        <p className="text-[11px] text-zinc-500">
          Global: {missingCfg?.enabled ? 'enabled' : 'disabled'} — {missingCfg?.missing_frames ?? 3600} frames
        </p>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}
      {canEdit && (
        <button type="button" onClick={save} disabled={saving}
          className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-40">
          {saving ? 'Saving…' : 'Save'}
        </button>
      )}
    </div>
  )
}


// ── Per-camera crowd alert override ──────────────────────────────────────────
function CameraCrowdAlert({ camera, crowdCfg, setCrowdCfg, canEdit }) {
  const camId    = String(camera.id)
  const override = crowdCfg?.per_camera?.[camId]

  const [active,    setActive]    = useState(!!override)
  const [enabled,   setEnabled]   = useState(override?.enabled ?? crowdCfg?.enabled ?? false)
  const [threshold, setThreshold] = useState(override?.person_threshold ?? crowdCfg?.person_threshold ?? 5)
  const [sustained, setSustained] = useState(override?.sustained_seconds ?? crowdCfg?.sustained_seconds ?? 5)
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState(null)

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const newPerCamera = { ...(crowdCfg?.per_camera || {}) }
      if (active) {
        newPerCamera[camId] = { enabled, person_threshold: threshold, sustained_seconds: sustained }
      } else {
        delete newPerCamera[camId]
      }
      setCrowdCfg(await api.updateCrowdAlertConfig({ per_camera: newPerCamera }))
    } catch (e) {
      setError(e?.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900/40 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-zinc-300">{camera.name || `Camera ${camera.id}`}</span>
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <input type="checkbox" className="w-3.5 h-3.5 accent-emerald-500"
            checked={active} disabled={!canEdit} onChange={e => setActive(e.target.checked)} />
          Override
        </label>
      </div>

      {active && (
        <div className="space-y-2 pt-1 border-t border-zinc-700/60">
          <label className="flex items-center justify-between text-xs text-zinc-300">
            <span>Enabled</span>
            <input type="checkbox" className="w-3.5 h-3.5 accent-green-500"
              checked={enabled} disabled={!canEdit} onChange={e => setEnabled(e.target.checked)} />
          </label>
          <Field label="People">
            <input className={inputCls} type="number" min="1"
              disabled={!canEdit || !enabled} value={threshold}
              onChange={e => setThreshold(Number(e.target.value))} />
          </Field>
          <Field label="Sustained (sec)">
            <input className={inputCls} type="number" min="0" step="0.5"
              disabled={!canEdit || !enabled} value={sustained}
              onChange={e => setSustained(Number(e.target.value))} />
          </Field>
        </div>
      )}

      {!active && (
        <p className="text-[11px] text-zinc-500">
          Global: {crowdCfg?.enabled ? 'enabled' : 'disabled'} — {crowdCfg?.person_threshold ?? 5} people / {crowdCfg?.sustained_seconds ?? 5}s
        </p>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}
      {canEdit && (
        <button type="button" onClick={save} disabled={saving}
          className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-40">
          {saving ? 'Saving…' : 'Save'}
        </button>
      )}
    </div>
  )
}


// ── Server file picker modal ──────────────────────────────────────────────────
function FilePicker({ onSelect, onClose }) {
  const [files,   setFiles]   = useState([])
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('')

  useEffect(() => {
    api.browseFiles()
      .then(setFiles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const visible = filter
    ? files.filter(f => f.toLowerCase().includes(filter.toLowerCase()))
    : files

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-zinc-800 rounded-xl border border-zinc-700 w-full max-w-md flex flex-col max-h-[70vh] shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700 shrink-0">
          <span className="text-sm font-semibold text-zinc-200">Select model file</span>
          <button type="button" onClick={onClose} className="text-zinc-400 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="px-3 py-2 border-b border-zinc-700 shrink-0">
          <input
            className="w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-emerald-500"
            placeholder="Filter files…"
            value={filter}
            onChange={e => setFilter(e.target.value)}
            autoFocus
          />
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loading && <p className="text-xs text-zinc-500 px-2 py-3">Scanning for model files…</p>}
          {!loading && visible.length === 0 && (
            <p className="text-xs text-zinc-500 px-2 py-3">No .pt files found.</p>
          )}
          {visible.map(f => (
            <button
              key={f}
              type="button"
              onClick={() => { onSelect(f); onClose() }}
              className="w-full text-left px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-700 rounded-lg font-mono truncate transition-colors"
              title={f}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}


// ── AI model registry manager ─────────────────────────────────────────────────
const EMPTY_FORM = { display_name: '', weight_path: '', confidence_threshold: 0.25, model_type: 'yolov8', yolo_imgsz: 640, is_active: true }

function AIModelsManager({ isAdmin }) {
  const [models,     setModels]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [editingId,  setEditingId]  = useState(null)   // null | 'new' | number
  const [form,       setForm]       = useState(EMPTY_FORM)
  const [saving,     setSaving]     = useState(false)
  const [deleting,   setDeleting]   = useState(null)
  const [error,      setError]      = useState(null)
  const [showPicker, setShowPicker] = useState(false)

  const fetchModels = useCallback(async () => {
    try {
      setModels(await api.getAiModels())
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchModels() }, [fetchModels])

  const openNew = () => {
    setForm({ ...EMPTY_FORM })
    setEditingId('new')
    setError(null)
  }

  const openEdit = (m) => {
    setForm({
      display_name:         m.display_name,
      weight_path:          m.weight_path,
      confidence_threshold: m.confidence_threshold,
      model_type:           m.model_type,
      yolo_imgsz:           m.yolo_imgsz,
      is_active:            m.is_active,
    })
    setEditingId(m.id)
    setError(null)
  }

  const cancelEdit = () => { setEditingId(null); setError(null) }

  const saveModel = async () => {
    if (!form.display_name.trim()) { setError('Display name is required'); return }
    if (!form.weight_path.trim())  { setError('Weight path is required');  return }
    setSaving(true)
    setError(null)
    try {
      if (editingId === 'new') {
        const name = form.display_name.trim().toLowerCase().replace(/\s+/g, '_')
        await api.createAiModel({ ...form, name })
      } else {
        await api.updateAiModel(editingId, form)
      }
      await fetchModels()
      setEditingId(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const deleteModel = async (id) => {
    if (!window.confirm('Delete this model? Camera assignments will also be removed.')) return
    setDeleting(id)
    try {
      await api.deleteAiModel(id)
      await fetchModels()
    } catch (e) {
      setError(e.message)
    } finally {
      setDeleting(null)
    }
  }

  const f = (key) => ({
    value: form[key] ?? '',
    onChange: e => setForm(prev => ({ ...prev, [key]: e.target.value })),
  })

  if (loading) return <p className="text-xs text-zinc-500 animate-pulse">Loading models…</p>

  return (
    <div className="space-y-3">
      {error && <p className="text-xs text-red-400">{error}</p>}

      {/* Model list */}
      {models.length === 0 && editingId === null && (
        <p className="text-xs text-zinc-500">No models registered yet.</p>
      )}
      <div className="space-y-2">
        {models.map(m => (
          editingId === m.id ? (
            // ── Inline edit form ──────────────────────────────────────
            <ModelForm
              key={m.id}
              form={form} setForm={setForm}
              saving={saving}
              onSave={saveModel} onCancel={cancelEdit}
              onBrowse={() => setShowPicker(true)}
              title="Edit model"
            />
          ) : (
            // ── Read-only row ─────────────────────────────────────────
            <div key={m.id} className="flex items-start gap-3 rounded-lg border border-zinc-700 bg-zinc-900/40 px-4 py-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-zinc-200">{m.display_name}</span>
                  <span className="text-xs text-zinc-500">{m.model_type}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${
                    m.is_active ? 'bg-emerald-900/50 text-emerald-400' : 'bg-zinc-700 text-zinc-500'
                  }`}>{m.is_active ? 'Active' : 'Inactive'}</span>
                </div>
                <p className="text-xs text-zinc-400 font-mono truncate mt-0.5" title={m.weight_path}>
                  {m.weight_path}
                </p>
                <p className="text-xs text-zinc-500 mt-0.5">conf {m.confidence_threshold} · imgsz {m.yolo_imgsz}</p>
              </div>
              {isAdmin && (
                <div className="flex items-center gap-1 shrink-0">
                  <button type="button" onClick={() => openEdit(m)}
                    className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 rounded-lg transition-colors">
                    <Pencil size={13} />
                  </button>
                  <button type="button" onClick={() => deleteModel(m.id)} disabled={deleting === m.id}
                    className="p-1.5 text-zinc-400 hover:text-red-400 hover:bg-red-900/30 rounded-lg transition-colors disabled:opacity-40">
                    <Trash2 size={13} />
                  </button>
                </div>
              )}
            </div>
          )
        ))}

        {/* New model form */}
        {editingId === 'new' && (
          <ModelForm
            form={form} setForm={setForm}
            saving={saving}
            onSave={saveModel} onCancel={cancelEdit}
            onBrowse={() => setShowPicker(true)}
            title="Add model"
          />
        )}
      </div>

      {isAdmin && editingId === null && (
        <button type="button" onClick={openNew}
          className="flex items-center gap-2 text-sm text-emerald-400 hover:text-emerald-300 transition-colors">
          <Plus size={14} /> Add model
        </button>
      )}

      {showPicker && (
        <FilePicker
          onSelect={path => setForm(prev => ({ ...prev, weight_path: path }))}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  )
}

function ModelForm({ form, setForm, saving, onSave, onCancel, onBrowse, title }) {
  const cls = 'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:border-emerald-500'
  return (
    <div className="rounded-lg border border-emerald-700/50 bg-zinc-900/60 p-4 space-y-3">
      <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">{title}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">Display name</label>
          <input className={cls} placeholder="Vehicle Model"
            value={form.display_name}
            onChange={e => setForm(p => ({ ...p, display_name: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">Model type</label>
          <select className={cls} value={form.model_type}
            onChange={e => setForm(p => ({ ...p, model_type: e.target.value }))}>
            <option value="yolov8">YOLOv8</option>
            <option value="mediapipe">MediaPipe</option>
            <option value="kcf">KCF</option>
          </select>
        </div>
      </div>
      <div>
        <label className="text-xs text-zinc-400 mb-1 block">Weight path</label>
        <div className="flex gap-2">
          <input className={`${cls} flex-1 font-mono`} placeholder="weights/vehicle_model.pt"
            value={form.weight_path}
            onChange={e => setForm(p => ({ ...p, weight_path: e.target.value }))} />
          <button type="button" onClick={onBrowse}
            className="flex items-center gap-1.5 px-3 py-2 bg-zinc-700 hover:bg-zinc-600 border border-zinc-600 rounded-lg text-xs text-zinc-300 transition-colors shrink-0">
            <FolderOpen size={13} /> Browse
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">Confidence</label>
          <input className={cls} type="number" min="0.05" max="0.95" step="0.05"
            value={form.confidence_threshold}
            onChange={e => setForm(p => ({ ...p, confidence_threshold: parseFloat(e.target.value) || 0.25 }))} />
        </div>
        <div>
          <label className="text-xs text-zinc-400 mb-1 block">Image size</label>
          <input className={cls} type="number" min="320" max="1280" step="32"
            value={form.yolo_imgsz}
            onChange={e => setForm(p => ({ ...p, yolo_imgsz: parseInt(e.target.value) || 640 }))} />
        </div>
      </div>
      <label className="flex items-center gap-2 text-sm text-zinc-300">
        <input type="checkbox" className="w-4 h-4 accent-emerald-500"
          checked={!!form.is_active}
          onChange={e => setForm(p => ({ ...p, is_active: e.target.checked }))} />
        Active (loaded at camera start)
      </label>
      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onSave} disabled={saving}
          className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-50 transition-colors">
          <Save size={13} />{saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel} disabled={saving}
          className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 rounded-lg text-sm transition-colors">
          Cancel
        </button>
      </div>
    </div>
  )
}


const SUB_TABS = [
  { id: 'cameras',    label: 'Cameras'    },
  { id: 'detection',  label: 'Detection'  },
  { id: 'automation', label: 'Automation' },
  { id: 'devices',    label: 'Devices'    },
]

// ── Main component ─────────────────────────────────────────────────────────────
export default function ConfigPanel({ onSaved, systemMetrics }) {
  const { isAdmin } = useAuth()
  const [subTab,   setSubTab]  = useState('cameras')
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
            face_detection_enabled: cam.face_detection_enabled ?? false,
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
            face_detection_enabled: cam.face_detection_enabled,
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

  const saveMissingPersonConfig = async () => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      const updated = await api.updateMissingPersonConfig(missingCfg)
      setMissingCfg(updated)
      setSuccess('Missing person settings saved.')
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  const saveCrowdAlertConfig = async () => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      const updated = await api.updateCrowdAlertConfig(crowdCfg)
      setCrowdCfg(updated)
      setSuccess('Crowd alert settings saved.')
    } catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  if (!cfg) return (
    <div className="flex items-center justify-center h-full text-zinc-500">
      {error
        ? <div className="text-red-400 text-sm">{error}</div>
        : 'Loading config...'}
    </div>
  )

  const cameras = cfg.cameras || []
  const cameraCount = cameras.length
  const system = systemMetrics?.system
  const process = systemMetrics?.process

  const saveBtn = (
    <button
      onClick={save}
      disabled={saving}
      className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-5 py-2.5 rounded-lg font-semibold text-sm transition-colors disabled:opacity-50"
    >
      <Save size={15} />
      {saving ? 'Saving...' : 'Save'}
    </button>
  )

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Sub-tab navigation */}
      <div className="shrink-0 border-b border-zinc-700 px-3 sm:px-6">
        <div className="flex gap-1 pt-3 sm:pt-4">
          {SUB_TABS.map(tab => (
            <button
              key={tab.id}
              type="button"
              onClick={() => { setSubTab(tab.id); setError(null); setSuccess(null) }}
              className={`px-3 sm:px-4 py-2 text-xs sm:text-sm font-medium rounded-t-lg transition-colors ${
                subTab === tab.id
                  ? 'bg-zinc-800 border border-b-zinc-800 border-zinc-700 text-emerald-400 -mb-px'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-3 sm:p-6 space-y-5">
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

        {/* ── Cameras ─────────────────────────────────────────────────── */}
        {subTab === 'cameras' && (
          <>
            {system && process && (
              <Section title="System Resource Overview">
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
                  <div className="rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wide text-zinc-500">Server CPU</p>
                    <p className="mt-1 text-2xl font-semibold text-zinc-100">{system.cpu_percent}%</p>
                    <p className="text-xs text-zinc-400">{system.cpu_logical_cores} logical cores</p>
                  </div>
                  <div className="rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wide text-zinc-500">App CPU</p>
                    <p className="mt-1 text-2xl font-semibold text-zinc-100">{process.cpu_percent_total_machine}%</p>
                    <p className="text-xs text-zinc-400">{process.cpu_percent_single_core}% of one core</p>
                  </div>
                  <div className="rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wide text-zinc-500">Server Memory</p>
                    <p className="mt-1 text-2xl font-semibold text-zinc-100">{system.used_memory_gb} / {system.total_memory_gb} GB</p>
                    <p className="text-xs text-zinc-400">App RSS {process.rss_memory_mb} MB</p>
                  </div>
                  <div className="rounded-xl border border-zinc-700 bg-zinc-900/60 px-4 py-3">
                    <p className="text-[11px] uppercase tracking-wide text-zinc-500">CPU Layout</p>
                    <p className="mt-1 text-2xl font-semibold text-zinc-100">{system.cpu_physical_cores} / {system.cpu_logical_cores}</p>
                    <p className="text-xs text-zinc-400">physical / logical cores</p>
                  </div>
                </div>
              </Section>
            )}

            <Section title="Camera Streams">
              <div className="space-y-2">
                <div className="hidden sm:grid sm:grid-cols-[1fr_160px_80px_48px_36px] gap-2 text-xs text-zinc-500 px-1">
                  <span>RTSP / Stream URL</span>
                  <span>Title</span>
                  <span>FPS</span>
                  <span title="Face Detection & Recognition" className="text-center">Face AI</span>
                  <span />
                </div>
                {cameras.map((camera, i) => (
                  <div key={camera.id ?? `draft-${i}`} className="flex flex-col sm:grid sm:grid-cols-[1fr_160px_80px_48px_36px] gap-2 sm:items-center rounded-lg sm:rounded-none bg-zinc-700/20 sm:bg-transparent p-2 sm:p-0">
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
                      <div className="flex justify-center items-center h-full">
                        <input
                          type="checkbox"
                          className="w-4 h-4 accent-emerald-500 cursor-pointer"
                          checked={camera.face_detection_enabled || false}
                          onChange={e => updateCamera(i, 'face_detection_enabled', e.target.checked)}
                          title="Enable face recognition for this camera"
                        />
                      </div>
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
                  className="flex items-center gap-2 text-sm text-emerald-400 hover:text-emerald-300 mt-1"
                >
                  <Plus size={15} /> Add camera
                </button>
              </div>
            </Section>

            <div className="flex justify-end">{saveBtn}</div>
          </>
        )}

        {/* ── Detection ───────────────────────────────────────────────── */}
        {subTab === 'detection' && (
          <>
            <Section title="AI Model Registry">
              <p className="text-xs text-zinc-500 -mt-1">
                Add and manage model weight files. Each model is automatically assigned to all cameras.
                Browse picks an existing file from the server — no wrong paths.
              </p>
              <AIModelsManager isAdmin={isAdmin} />
            </Section>

            {cameraCount > 0 && (
              <Section title="AI Models per Camera">
                <p className="text-xs text-zinc-500 -mt-1">
                  Toggle which detection types run on each camera. Changes take effect on next camera start.
                </p>
                <div className="space-y-4">
                  {cameras.map((camera, i) => (
                    <div key={camera.id ?? `model-${i}`}>
                      <div className="text-xs font-semibold text-zinc-400 mb-1.5">
                        {camera.name || `Camera ${i + 1}`}
                      </div>
                      {camera.id == null ? (
                        <p className="text-xs text-zinc-500">Save this camera first to configure AI models.</p>
                      ) : (
                        <CameraModels camId={camera.id} canEdit={isAdmin} />
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </>
        )}

        {/* ── Automation ──────────────────────────────────────────────── */}
        {subTab === 'automation' && (
          <>
            {missingCfg && (
              <Section title="Missing Person">
                <div className="space-y-3">
                  <label className="flex items-center justify-between gap-3">
                    <span className="text-sm text-zinc-300">Enabled globally</span>
                    <input type="checkbox" className="w-4 h-4 accent-emerald-500" checked={!!missingCfg.enabled} disabled={!isAdmin}
                      onChange={e => setMissingCfg({ ...missingCfg, enabled: e.target.checked })} />
                  </label>
                  <Field label="Frames">
                    <input className={inputCls} type="number" min="1" disabled={!isAdmin} value={missingCfg.missing_frames ?? 3600}
                      onChange={e => setMissingCfg({ ...missingCfg, missing_frames: Number(e.target.value) })} />
                  </Field>
                  <label className="flex items-center gap-2 text-sm text-zinc-300">
                    <input type="checkbox" className="w-4 h-4 accent-green-500" checked={!!missingCfg.send_whatsapp} disabled={!isAdmin}
                      onChange={e => setMissingCfg({ ...missingCfg, send_whatsapp: e.target.checked })} />
                    WhatsApp snapshot
                  </label>
                  {isAdmin && (
                    <div className="flex justify-end pt-1">
                      <button type="button" onClick={saveMissingPersonConfig} disabled={saving}
                        className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg font-semibold text-sm disabled:opacity-50">
                        <Save size={13} />{saving ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  )}
                </div>

                {cameraCount > 0 && (
                  <div className="mt-4 space-y-2 border-t border-zinc-700 pt-4">
                    <p className="text-xs text-zinc-400 font-semibold uppercase tracking-wide">Per-camera overrides</p>
                    <p className="text-xs text-zinc-500">Leave unchecked to use global settings above.</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 pt-1">
                      {cameras.map(camera =>
                        camera.id == null ? null : (
                          <CameraMissingPerson
                            key={camera.id}
                            camera={camera}
                            missingCfg={missingCfg}
                            setMissingCfg={setMissingCfg}
                            canEdit={isAdmin}
                          />
                        )
                      )}
                    </div>
                  </div>
                )}
              </Section>
            )}

            {crowdCfg && (
              <Section title="Crowd Alert">
                <div className="space-y-3">
                  <label className="flex items-center justify-between gap-3">
                    <span className="text-sm text-zinc-300">Enabled globally</span>
                    <input type="checkbox" className="w-4 h-4 accent-emerald-500" checked={!!crowdCfg.enabled} disabled={!isAdmin}
                      onChange={e => setCrowdCfg({ ...crowdCfg, enabled: e.target.checked })} />
                  </label>
                  <Field label="People threshold">
                    <input className={inputCls} type="number" min="1" disabled={!isAdmin} value={crowdCfg.person_threshold ?? 5}
                      onChange={e => setCrowdCfg({ ...crowdCfg, person_threshold: Number(e.target.value) })} />
                  </Field>
                  <Field label="Sustained (sec)">
                    <input className={inputCls} type="number" min="0" step="0.5" disabled={!isAdmin} value={crowdCfg.sustained_seconds ?? 5}
                      onChange={e => setCrowdCfg({ ...crowdCfg, sustained_seconds: Number(e.target.value) })} />
                  </Field>
                  <label className="flex items-center gap-2 text-sm text-zinc-300">
                    <input type="checkbox" className="w-4 h-4 accent-green-500" checked={!!crowdCfg.send_whatsapp} disabled={!isAdmin}
                      onChange={e => setCrowdCfg({ ...crowdCfg, send_whatsapp: e.target.checked })} />
                    WhatsApp snapshot
                  </label>
                  {isAdmin && (
                    <div className="flex justify-end pt-1">
                      <button type="button" onClick={saveCrowdAlertConfig} disabled={saving}
                        className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg font-semibold text-sm disabled:opacity-50">
                        <Save size={13} />{saving ? 'Saving…' : 'Save'}
                      </button>
                    </div>
                  )}
                </div>

                {cameraCount > 0 && (
                  <div className="mt-4 space-y-2 border-t border-zinc-700 pt-4">
                    <p className="text-xs text-zinc-400 font-semibold uppercase tracking-wide">Per-camera overrides</p>
                    <p className="text-xs text-zinc-500">Leave unchecked to use global settings above.</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 pt-1">
                      {cameras.map(camera =>
                        camera.id == null ? null : (
                          <CameraCrowdAlert
                            key={camera.id}
                            camera={camera}
                            crowdCfg={crowdCfg}
                            setCrowdCfg={setCrowdCfg}
                            canEdit={isAdmin}
                          />
                        )
                      )}
                    </div>
                  </div>
                )}
              </Section>
            )}
          </>
        )}

        {/* ── Devices ─────────────────────────────────────────────────── */}
        {subTab === 'devices' && (
          <>
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
                    className="w-4 h-4 accent-emerald-500"
                  />
                  <span className="text-sm text-zinc-300">Send alarm over WiFi (ESP32)</span>
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

            {isAdmin && cameraCount > 0 && (
              <Section title="Buzzer Assignments">
                <p className="text-xs text-zinc-500 -mt-1">
                  Select which buzzers fire for each camera. Changes take effect on next camera start.
                </p>
                <div className="space-y-4">
                  {cameras.map((camera, i) => (
                    <div key={camera.id ?? `buzzer-${i}`}>
                      <div className="text-xs font-semibold text-zinc-400 mb-1.5">
                        {camera.name || `Camera ${i + 1}`}
                      </div>
                      {camera.id == null ? (
                        <p className="text-xs text-zinc-500">Save this camera first to assign buzzers.</p>
                      ) : (
                        <CameraBuzzers camId={camera.id} allBuzzers={buzzers} />
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            <div className="flex justify-end">{saveBtn}</div>
          </>
        )}
      </div>
    </div>
  )
}
