/**
 * ROICanvas — HTML5 Canvas overlay for drawing and editing ROI polygons.
 */

import { useEffect, useRef } from 'react'

const V_RADIUS = 6
const V_HOVER  = 9

export default function ROICanvas({
  backgroundSrc,
  rois = [],
  drawingPoints = [],
  isClosed = false,
  mode = 'view',
  selectedROIId = null,
  draggingVertex = null,
  cursorPos = null,
  onCanvasClick,
  onCanvasDblClick,
  onVertexMouseDown,
  onROIClick,
  className = '',
}) {
  const canvasRef = useRef(null)
  const imgRef    = useRef(null)  // DOM <img> for MJPEG — browser cleans up connection on unmount
  const redrawRef = useRef(() => {})

  function hexRGBA(hex, a) {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16)
    return `rgba(${r},${g},${b},${a})`
  }

  function drawPoly(ctx, pts, color, selected, active, label) {
    if (pts.length < 2) return
    ctx.beginPath()
    ctx.moveTo(pts[0].x, pts[0].y)
    pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y))
    ctx.closePath()
    ctx.fillStyle   = hexRGBA(color, active ? 0.2 : 0.08)
    ctx.fill()
    ctx.strokeStyle = hexRGBA(color, active ? 1 : 0.4)
    ctx.lineWidth   = selected ? 2.5 : 1.5
    if (!active) ctx.setLineDash([5,4])
    ctx.stroke()
    ctx.setLineDash([])
    if (label) {
      const cx = pts.reduce((s,p) => s+p.x, 0) / pts.length
      const cy = pts.reduce((s,p) => s+p.y, 0) / pts.length
      ctx.font = '11px sans-serif'
      ctx.fillStyle = 'rgba(255,255,255,0.85)'
      ctx.textAlign = 'center'
      ctx.fillText(label, cx, cy)
    }
  }

  function drawHandles(ctx, pts, color, highlight) {
    pts.forEach((p, i) => {
      const r = i === highlight ? V_HOVER : V_RADIUS
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI*2)
      ctx.fillStyle   = i === highlight ? '#fff' : hexRGBA(color, 0.9)
      ctx.fill()
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke()
    })
  }

  function drawInProgress(ctx, pts, cursor) {
    if (!pts.length) return
    ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y)
    pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y))
    if (cursor && !isClosed) ctx.lineTo(cursor.x, cursor.y)
    if (isClosed) ctx.closePath()
    ctx.strokeStyle = 'rgba(255,200,0,0.9)'; ctx.lineWidth = 2
    ctx.setLineDash([6,3]); ctx.stroke(); ctx.setLineDash([])
    if (isClosed) { ctx.fillStyle = 'rgba(255,200,0,0.15)'; ctx.fill() }
    pts.forEach((p, i) => {
      ctx.beginPath(); ctx.arc(p.x, p.y, i === 0 ? 8 : 5, 0, Math.PI*2)
      ctx.fillStyle = i === 0 ? 'rgba(255,200,0,0.9)' : 'rgba(255,255,255,0.8)'
      ctx.fill(); ctx.strokeStyle = '#FFCC00'; ctx.lineWidth = 2; ctx.stroke()
    })
  }

  function norm2px(nx, ny, w, h) { return { x: nx*w, y: ny*h } }

  function redraw() {
    const canvas = canvasRef.current; if (!canvas) return
    const ctx = canvas.getContext('2d')
    const { width: w, height: h } = canvas
    ctx.clearRect(0, 0, w, h)
    const img = imgRef.current
    if (img && img.naturalWidth > 0) ctx.drawImage(img, 0, 0, w, h)
    else { ctx.fillStyle = '#111827'; ctx.fillRect(0,0,w,h) }

    for (const roi of rois) {
      const selected = roi.roi_id === selectedROIId
      const px = roi.points_normalized.map(({x,y}) => norm2px(x,y,w,h))
      drawPoly(ctx, px, roi.color, selected, roi.is_active, roi.name)
      if (selected) drawHandles(ctx, px, roi.color, draggingVertex)
    }
    if (mode === 'draw' && drawingPoints.length) drawInProgress(ctx, drawingPoints, cursorPos)
  }

  redrawRef.current = redraw

  useEffect(() => { redraw() }) // re-draw every render

  // MJPEG images keep updating internally; redraw on a timer so the canvas tracks new frames.
  useEffect(() => {
    if (!backgroundSrc) return
    const timer = window.setInterval(() => {
      redrawRef.current()
    }, 33) // ~30 FPS draw loop
    return () => window.clearInterval(timer)
  }, [backgroundSrc])

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return
    const ro = new ResizeObserver(() => {
      const r = canvas.getBoundingClientRect()
      canvas.width = r.width; canvas.height = r.height; redraw()
    })
    ro.observe(canvas)
    return () => ro.disconnect()
  }, []) // eslint-disable-line

  function xy(e) {
    const r = canvasRef.current.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }

  function hitVertex(pts, px, py, r = V_HOVER) {
    for (let i = 0; i < pts.length; i++) {
      const dx = pts[i].x - px, dy = pts[i].y - py
      if (Math.sqrt(dx*dx + dy*dy) <= r) return i
    }
    return -1
  }

  function pipCanvas(px, py, pts) {
    let inside = false, j = pts.length - 1
    for (let i = 0; i < pts.length; i++) {
      const xi=pts[i].x, yi=pts[i].y, xj=pts[j].x, yj=pts[j].y
      if ((yi>py) !== (yj>py) && px < (xj-xi)*(py-yi)/(yj-yi)+xi) inside = !inside
      j = i
    }
    return inside
  }

  function handleClick(e) {
    if (e.detail > 1) return
    const { x, y } = xy(e)
    if (mode === 'draw') {
      if (drawingPoints.length >= 3) {
        const dx = drawingPoints[0].x - x, dy = drawingPoints[0].y - y
        if (Math.sqrt(dx*dx+dy*dy) < 12) { onCanvasDblClick?.(); return }
      }
      onCanvasClick?.(x, y); return
    }
    const canvas = canvasRef.current
    const { width: w, height: h } = canvas
    for (const roi of [...rois].reverse()) {
      const px = roi.points_normalized.map(({x:nx,y:ny}) => norm2px(nx,ny,w,h))
      if (hitVertex(px,x,y) >= 0 || pipCanvas(x,y,px)) { onROIClick?.(roi.roi_id); return }
    }
    onROIClick?.(null)
  }

  function handleDblClick(e) {
    if (mode === 'draw') { e.preventDefault(); onCanvasDblClick?.() }
  }

  function handleMouseDown(e) {
    if (mode !== 'edit') return
    const { x, y } = xy(e)
    const roi = rois.find(r => r.roi_id === selectedROIId); if (!roi) return
    const canvas = canvasRef.current
    const px = roi.points_normalized.map(({x:nx,y:ny}) => norm2px(nx,ny,canvas.width,canvas.height))
    const vIdx = hitVertex(px, x, y)
    if (vIdx >= 0) onVertexMouseDown?.(roi.roi_id, vIdx, e)
  }

  const cursor = mode === 'draw' ? 'crosshair' : mode === 'edit' ? 'pointer' : 'default'

  return (
    <div className={`relative ${className}`}>
      {/* Hidden <img> keeps the MJPEG connection alive and always has the latest frame.
          React removes it from the DOM on unmount, which aborts the HTTP connection immediately. */}
      {backgroundSrc && (
        <img
          ref={imgRef}
          src={backgroundSrc}
          crossOrigin="anonymous"
          onLoad={() => redrawRef.current()}
          alt=""
          className="hidden"
        />
      )}
      <canvas
        ref={canvasRef}
        className="block w-full h-full"
        style={{ cursor }}
        onClick={handleClick}
        onDoubleClick={handleDblClick}
        onMouseDown={handleMouseDown}
      />
    </div>
  )
}
