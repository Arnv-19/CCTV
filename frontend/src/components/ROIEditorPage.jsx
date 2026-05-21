/**
 * ROIEditorPage — Full canvas + sidebar ROI editor for a single camera.
 *
 * Usage in App.jsx:
 *   <ROIEditorPage cameraId={selectedCamId} streamUrl={api.streamUrl(selectedCamId)} />
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import ROICanvas from './ROICanvas'
import ROIPanel  from './ROIPanel'
import { useROI } from '../hooks/useROI'
import { api }   from '../api/client'

// ---------------------------------------------------------------------------
// Save dialog — collect name/colour before persisting
// ---------------------------------------------------------------------------
function SaveDialog({ onSave, onCancel }) {
  const [name,     setName]     = useState('')
  const [color,    setColor]    = useState('#FF5733')
  const [priority, setPriority] = useState(0)
  const nameRef = useRef(null)
  useEffect(() => { nameRef.current?.focus() }, [])

  function submit(e) {
    e.preventDefault()
    if (!name.trim()) return
    onSave({ name: name.trim(), color, priority: Number(priority) })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 w-80 shadow-2xl">
        <h3 className="text-white font-semibold mb-4">Save ROI Zone</h3>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Name *</label>
            <input ref={nameRef}
              className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-600 outline-none focus:border-emerald-500"
              placeholder="e.g. Entrance Zone"
              value={name} onChange={e => setName(e.target.value)} maxLength={100} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Colour</label>
            <input type="color"
              className="h-9 w-full rounded-lg cursor-pointer border border-zinc-600 bg-zinc-800"
              value={color} onChange={e => setColor(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Priority (0–100)</label>
            <input type="number" min={0} max={100}
              className="w-full bg-zinc-800 text-white rounded-lg px-3 py-2 text-sm border border-zinc-600 outline-none focus:border-emerald-500"
              value={priority} onChange={e => setPriority(e.target.value)} />
          </div>
          <div className="flex gap-3 pt-1">
            <button type="submit"
              className="flex-1 py-2 bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg text-sm font-medium transition-colors">
              Save
            </button>
            <button type="button"
              className="flex-1 py-2 bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg text-sm transition-colors"
              onClick={onCancel}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main editor
// ---------------------------------------------------------------------------
export default function ROIEditorPage({ cameraId, streamUrl }) {
  const roi = useROI(cameraId)
  const containerRef  = useRef(null)
  const [cursorPos,       setCursorPos]       = useState(null)
  const [showSaveDialog,  setShowSaveDialog]  = useState(false)
  const [streamNonce,     setStreamNonce]     = useState(Date.now())

  // Force a reconnect when camera source changes.
  useEffect(() => {
    setStreamNonce(Date.now())
  }, [streamUrl])

  // Browsers throttle background tabs; reconnect stream when user returns.
  useEffect(() => {
    function refreshAfterTabSwitch() {
      setStreamNonce(Date.now())
      roi.fetchROIs()
    }

    function onVisibilityChange() {
      if (document.visibilityState === 'visible') {
        refreshAfterTabSwitch()
      }
    }

    window.addEventListener('focus', refreshAfterTabSwitch)
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      window.removeEventListener('focus', refreshAfterTabSwitch)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [roi, streamUrl])

  // Strip any existing query params from streamUrl so we control the nonce exclusively
  const streamBase = streamUrl ? streamUrl.split('?')[0] : null
  const liveBackgroundSrc = streamBase ? `${streamBase}?_=${streamNonce}` : null

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') {
        if (roi.mode === 'draw') roi.cancelDrawing()
        else roi.deselectROI()
      }
      if ((e.key === 'u' || e.key === 'U') && roi.mode === 'draw') roi.undoDrawPoint()
      if (e.key === 'Enter' && roi.mode === 'draw' && roi.drawingPoints.length >= 3) {
        roi.closePolygon(); setShowSaveDialog(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [roi])

  function getCanvasSize() {
    const el = containerRef.current?.querySelector('canvas')
    return el ? { w: el.width, h: el.height } : { w: 1, h: 1 }
  }

  // Drawing
  function handleCanvasClick(x, y) { roi.addDrawPoint({ x, y }) }
  function handleCanvasDblClick() {
    if (roi.drawingPoints.length >= 3) { roi.closePolygon(); setShowSaveDialog(true) }
  }
  async function handleSaveDialog({ name, color, priority }) {
    setShowSaveDialog(false)
    const { w, h } = getCanvasSize()
    await roi.saveDrawing({ name, color, priority, canvasW: w, canvasH: h })
  }

  // Vertex drag
  const dragRef = useRef(null)
  function handleVertexMouseDown(roiId, idx, e) {
    e.preventDefault()
    roi.startDragVertex(idx)
    dragRef.current = { roiId, idx }
    function onMove(me) {
      const canvas = containerRef.current?.querySelector('canvas'); if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const nx = Math.max(0, Math.min(1, (me.clientX - rect.left) / canvas.width))
      const ny = Math.max(0, Math.min(1, (me.clientY - rect.top)  / canvas.height))
      roi.moveVertex(idx, nx, ny)
    }
    function onUp() {
      roi.stopDrag(); dragRef.current = null
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup',   onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup',   onUp)
  }

  function handleROIClick(roiId) {
    if (roi.mode === 'draw') return
    if (!roiId) roi.deselectROI()
    else roi.selectROI(roiId)
  }

  function handleMouseMove(e) {
    if (roi.mode !== 'draw') return
    const canvas = e.currentTarget.querySelector('canvas'); if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    setCursorPos({ x: e.clientX - rect.left, y: e.clientY - rect.top })
  }

  async function handleSaveEdit() {
    if (roi.mode === 'draw') {
      if (roi.drawingPoints.length >= 3) { roi.closePolygon(); setShowSaveDialog(true) }
    } else if (roi.mode === 'edit') {
      await roi.saveEditedROI(); roi.deselectROI()
    }
  }
  function handleCancelEdit() { roi.cancelDrawing(); roi.deselectROI(); roi.fetchROIs() }

  return (
    <div className="flex h-full bg-zinc-950">
      {/* Canvas area */}
      <div className="flex-1 relative flex flex-col" ref={containerRef} onMouseMove={handleMouseMove}>
        {/* Mini toolbar */}
        <div className="flex items-center gap-3 px-4 py-2 bg-zinc-900/80 border-b border-zinc-800 text-xs">
          <span className="text-zinc-400 font-mono">{cameraId}</span>
          {roi.mode === 'draw' && (
            <>
              <span className="text-yellow-400">● Drawing ({roi.drawingPoints.length} pts)</span>
              <button className="ml-auto text-zinc-400 hover:text-white transition-colors"
                onClick={roi.undoDrawPoint} disabled={roi.drawingPoints.length === 0}>↩ Undo (U)</button>
            </>
          )}
          {roi.mode === 'edit' && <span className="text-emerald-400">● Editing</span>}
          {roi.mode === 'view' && streamUrl && (
            <button className="ml-auto text-zinc-400 hover:text-white transition-colors"
              onClick={() => setStreamNonce(Date.now())}>⟳ Refresh stream</button>
          )}
        </div>

        {/* Canvas */}
        <div className="flex-1 relative">
          <ROICanvas
            backgroundSrc={liveBackgroundSrc}
            rois={roi.rois}
            drawingPoints={roi.drawingPoints}
            isClosed={roi.isClosed}
            mode={roi.mode}
            selectedROIId={roi.selectedROIId}
            draggingVertex={roi.draggingVertexIdx}
            cursorPos={cursorPos}
            onCanvasClick={handleCanvasClick}
            onCanvasDblClick={handleCanvasDblClick}
            onVertexMouseDown={handleVertexMouseDown}
            onROIClick={handleROIClick}
            className="absolute inset-0"
          />
          {/* Hint bar */}
          {roi.mode === 'draw' && (
            <div className="absolute bottom-3 left-1/2 -tranzinc-x-1/2 bg-black/70 text-zinc-300 text-xs px-3 py-1.5 rounded-full pointer-events-none">
              Click to add · Dbl-click or Enter to close · U to undo · Esc to cancel
            </div>
          )}
          {roi.mode === 'edit' && (
            <div className="absolute bottom-3 left-1/2 -tranzinc-x-1/2 bg-black/70 text-zinc-300 text-xs px-3 py-1.5 rounded-full pointer-events-none">
              Drag vertices · Save in panel · Esc to cancel
            </div>
          )}
        </div>
      </div>

      {/* Side panel */}
      <div className="w-68 border-l border-zinc-800 flex-shrink-0" style={{ width: 272 }}>
        <ROIPanel
          rois={roi.rois}
          selectedROIId={roi.selectedROIId}
          mode={roi.mode}
          loading={roi.loading}
          error={roi.error}
          onSelect={handleROIClick}
          onToggle={roi.toggleROI}
          onDelete={roi.deleteROI}
          onRename={(id, name) => roi.updateROI(id, { name })}
          onColorChange={(id, color) => roi.updateROI(id, { color })}
          onStartDraw={roi.startDrawing}
          onSaveEdit={handleSaveEdit}
          onCancelEdit={handleCancelEdit}
        />
      </div>

      {showSaveDialog && (
        <SaveDialog
          onSave={handleSaveDialog}
          onCancel={() => { setShowSaveDialog(false); roi.cancelDrawing() }}
        />
      )}
    </div>
  )
}
