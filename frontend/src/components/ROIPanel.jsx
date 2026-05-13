/**
 * ROIPanel — Sidebar listing saved ROIs with toggle, rename, colour, delete.
 */

import { useState } from 'react'

const PRESET_COLORS = ['#FF5733','#33FF57','#3357FF','#FF33A1','#FFCC00','#00CCFF','#FF8800','#AA00FF']

function ROIItem({ roi, isSelected, onSelect, onToggle, onDelete, onRename, onColorChange }) {
  const [editing, setEditing]         = useState(false)
  const [nameInput, setNameInput]     = useState(roi.name)
  const [showColors, setShowColors]   = useState(false)

  function commitRename() {
    const v = nameInput.trim()
    if (v && v !== roi.name) onRename(roi.roi_id, v)
    setEditing(false)
  }

  return (
    <div
      onClick={() => onSelect(roi.roi_id)}
      className={`rounded-lg border p-3 mb-2 cursor-pointer transition-colors ${
        isSelected ? 'border-emerald-500 bg-emerald-950/40' : 'border-zinc-700 bg-zinc-800/50 hover:border-zinc-500'
      }`}
    >
      <div className="flex items-center gap-2">
        {/* Colour swatch */}
        <div className="relative">
          <button
            className="w-4 h-4 rounded-full border border-white/20 flex-shrink-0"
            style={{ backgroundColor: roi.color }}
            onClick={e => { e.stopPropagation(); setShowColors(!showColors) }}
          />
          {showColors && (
            <div
              className="absolute z-10 top-6 left-0 bg-zinc-900 border border-zinc-600 rounded-lg p-2 shadow-xl"
              onClick={e => e.stopPropagation()}
            >
              <div className="grid grid-cols-4 gap-1 mb-2">
                {PRESET_COLORS.map(c => (
                  <button key={c} className="w-6 h-6 rounded-full border border-white/20 hover:scale-110 transition-transform"
                    style={{ backgroundColor: c }}
                    onClick={() => { onColorChange(roi.roi_id, c); setShowColors(false) }} />
                ))}
              </div>
              <input type="color" className="w-full h-7 rounded cursor-pointer border border-zinc-600"
                value={roi.color} onChange={e => onColorChange(roi.roi_id, e.target.value)} />
            </div>
          )}
        </div>

        {/* Name */}
        {editing ? (
          <input autoFocus
            className="flex-1 bg-zinc-700 text-white text-sm rounded px-2 py-0.5 border border-emerald-500 outline-none"
            value={nameInput}
            onChange={e => setNameInput(e.target.value)}
            onBlur={commitRename}
            onKeyDown={e => { if (e.key==='Enter') commitRename(); if (e.key==='Escape') setEditing(false) }}
            onClick={e => e.stopPropagation()}
          />
        ) : (
          <span
            className={`flex-1 text-sm font-medium truncate ${roi.is_active ? 'text-white' : 'text-zinc-400 line-through'}`}
            onDoubleClick={e => { e.stopPropagation(); setEditing(true); setNameInput(roi.name) }}
            title="Double-click to rename"
          >{roi.name}</span>
        )}

        {roi.priority > 0 && (
          <span className="text-xs bg-zinc-700 text-zinc-300 px-1.5 py-0.5 rounded">P{roi.priority}</span>
        )}
      </div>

      <div className="flex items-center gap-2 mt-2" onClick={e => e.stopPropagation()}>
        <button
          className={`text-xs px-2 py-0.5 rounded transition-colors ${
            roi.is_active ? 'bg-green-800/60 text-green-300 hover:bg-green-700' : 'bg-zinc-700 text-zinc-400 hover:bg-zinc-600'
          }`}
          onClick={() => onToggle(roi.roi_id)}
        >{roi.is_active ? 'Active' : 'Disabled'}</button>
        <button className="text-xs text-zinc-400 hover:text-white ml-auto transition-colors"
          onClick={() => { setEditing(true); setNameInput(roi.name) }}>✏</button>
        <button className="text-xs text-zinc-500 hover:text-red-400 transition-colors"
          onClick={() => { if (window.confirm(`Delete "${roi.name}"?`)) onDelete(roi.roi_id) }}>🗑</button>
      </div>
      <div className="mt-1 text-xs text-zinc-500">
        {roi.points_normalized?.length ?? 0} pts
        {roi.camera_width ? ` · ${roi.camera_width}×${roi.camera_height}` : ''}
      </div>
    </div>
  )
}

export default function ROIPanel({
  rois = [], selectedROIId, onSelect, onToggle, onDelete, onRename, onColorChange,
  onStartDraw, onSaveEdit, onCancelEdit, mode = 'view', loading = false, error = null,
}) {
  return (
    <div className="flex flex-col h-full bg-zinc-900 text-white select-none">
      <div className="px-4 py-3 border-b border-zinc-700">
        <h2 className="font-semibold text-sm text-zinc-200">
          ROI Zones {rois.length > 0 && <span className="ml-1 text-xs text-zinc-400">({rois.length})</span>}
        </h2>
      </div>

      {error && (
        <div className="mx-3 mt-3 p-2 bg-red-900/40 border border-red-700 rounded text-xs text-red-300">{error}</div>
      )}

      <div className="px-3 py-3 border-b border-zinc-800">
        {mode === 'draw' ? (
          <div className="space-y-2">
            <p className="text-xs text-yellow-400 font-medium">Drawing — click to add points, dbl-click to close</p>
            <div className="flex gap-2">
              <button className="flex-1 py-1.5 bg-yellow-700 hover:bg-yellow-600 text-white text-xs rounded transition-colors" onClick={onSaveEdit}>✓ Close</button>
              <button className="flex-1 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-xs rounded transition-colors" onClick={onCancelEdit}>✕ Cancel</button>
            </div>
          </div>
        ) : mode === 'edit' ? (
          <div className="space-y-2">
            <p className="text-xs text-emerald-400 font-medium">Edit mode — drag vertices to reshape</p>
            <div className="flex gap-2">
              <button className="flex-1 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-xs rounded transition-colors" onClick={onSaveEdit}>💾 Save</button>
              <button className="flex-1 py-1.5 bg-zinc-700 hover:bg-zinc-600 text-xs rounded transition-colors" onClick={onCancelEdit}>✕ Cancel</button>
            </div>
          </div>
        ) : (
          <button className="w-full py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition-colors font-medium" onClick={onStartDraw} disabled={loading}>
            + Draw new ROI
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {loading && <div className="text-center text-xs text-zinc-500 py-4">Loading…</div>}
        {!loading && rois.length === 0 && (
          <div className="text-center text-xs text-zinc-500 py-8">
            <p>No ROIs defined.</p>
            <p className="mt-1">Click "Draw new ROI" to start.</p>
          </div>
        )}
        {rois.map(roi => (
          <ROIItem key={roi.roi_id} roi={roi} isSelected={roi.roi_id === selectedROIId}
            onSelect={onSelect} onToggle={onToggle} onDelete={onDelete}
            onRename={onRename} onColorChange={onColorChange} />
        ))}
      </div>

      <div className="px-3 py-2 border-t border-zinc-800 text-xs text-zinc-600 space-y-0.5">
        <p>Double-click name to rename · Click zone to select</p>
      </div>
    </div>
  )
}
