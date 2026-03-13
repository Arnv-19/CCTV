/**
 * useROI — React hook for ROI state management.
 * Uses the shared `api` client from api/client.js.
 */

import { useCallback, useEffect, useReducer } from 'react'
import { api } from '../api/client'

const INITIAL = {
  rois: [],
  loading: false,
  error: null,
  mode: 'view',          // 'view' | 'draw' | 'edit'
  drawingPoints: [],     // [{x, y}] canvas-pixel coords (normalised on save)
  isClosed: false,
  selectedROIId: null,
  draggingVertexIdx: null,
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_LOADING':  return { ...state, loading: action.value, error: null }
    case 'SET_ERROR':    return { ...state, loading: false, error: action.message }
    case 'SET_ROIS':     return { ...state, rois: action.rois, loading: false }
    case 'ADD_ROI':      return { ...state, rois: [...state.rois, action.roi] }
    case 'UPDATE_ROI':
      return { ...state, rois: state.rois.map(r => r.roi_id === action.roi.roi_id ? action.roi : r) }
    case 'REMOVE_ROI':
      return {
        ...state,
        rois: state.rois.filter(r => r.roi_id !== action.roiId),
        selectedROIId: state.selectedROIId === action.roiId ? null : state.selectedROIId,
      }

    case 'START_DRAWING': return { ...state, mode: 'draw', drawingPoints: [], isClosed: false, selectedROIId: null }
    case 'ADD_DRAW_POINT': return { ...state, drawingPoints: [...state.drawingPoints, action.point] }
    case 'UNDO_DRAW_POINT': return { ...state, drawingPoints: state.drawingPoints.slice(0, -1), isClosed: false }
    case 'CLOSE_POLYGON': return { ...state, isClosed: true }
    case 'RESET_DRAW':    return { ...state, mode: 'view', drawingPoints: [], isClosed: false }

    case 'SELECT_ROI':   return { ...state, selectedROIId: action.roiId, mode: 'edit' }
    case 'DESELECT':     return { ...state, selectedROIId: null, mode: 'view', draggingVertexIdx: null }
    case 'START_DRAG':   return { ...state, draggingVertexIdx: action.idx }
    case 'STOP_DRAG':    return { ...state, draggingVertexIdx: null }
    case 'MOVE_VERTEX':
      return {
        ...state,
        rois: state.rois.map(r =>
          r.roi_id === state.selectedROIId
            ? { ...r, points_normalized: r.points_normalized.map((p, i) =>
                i === action.idx ? { x: action.nx, y: action.ny } : p) }
            : r
        ),
      }

    default: return state
  }
}

export function useROI(cameraId) {
  const [state, dispatch] = useReducer(reducer, INITIAL)

  const fetchROIs = useCallback(async () => {
    if (!cameraId) return
    dispatch({ type: 'SET_LOADING', value: true })
    try {
      const data = await api.getRois(cameraId)
      dispatch({ type: 'SET_ROIS', rois: data.rois ?? [] })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
    }
  }, [cameraId])

  useEffect(() => { fetchROIs() }, [fetchROIs])

  const saveDrawing = useCallback(async ({ name, color, priority, canvasW, canvasH }) => {
    if (state.drawingPoints.length < 3) {
      dispatch({ type: 'SET_ERROR', message: 'Need at least 3 points.' })
      return null
    }
    const points_normalized = state.drawingPoints.map(p => ({
      x: parseFloat((p.x / canvasW).toFixed(6)),
      y: parseFloat((p.y / canvasH).toFixed(6)),
    }))
    dispatch({ type: 'SET_LOADING', value: true })
    try {
      const roi = await api.createRoi(cameraId, { name, color, priority, points_normalized, camera_width: canvasW, camera_height: canvasH })
      dispatch({ type: 'ADD_ROI', roi })
      dispatch({ type: 'RESET_DRAW' })
      return roi
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
      return null
    }
  }, [cameraId, state.drawingPoints])

  const saveEditedROI = useCallback(async () => {
    const roi = state.rois.find(r => r.roi_id === state.selectedROIId)
    if (!roi) return
    dispatch({ type: 'SET_LOADING', value: true })
    try {
      const updated = await api.updateRoi(roi.roi_id, { points_normalized: roi.points_normalized })
      dispatch({ type: 'UPDATE_ROI', roi: updated })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
    }
  }, [state.rois, state.selectedROIId])

  const deleteROI = useCallback(async (roiId) => {
    dispatch({ type: 'SET_LOADING', value: true })
    try {
      await api.deleteRoi(roiId)
      dispatch({ type: 'REMOVE_ROI', roiId })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
    }
  }, [])

  const toggleROI = useCallback(async (roiId) => {
    try {
      const updated = await api.toggleRoi(roiId)
      dispatch({ type: 'UPDATE_ROI', roi: updated })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
    }
  }, [])

  const updateROI = useCallback(async (roiId, patch) => {
    try {
      const updated = await api.updateRoi(roiId, patch)
      dispatch({ type: 'UPDATE_ROI', roi: updated })
      return updated
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err.message })
      return null
    }
  }, [])

  return {
    ...state,
    fetchROIs,
    startDrawing:   () => dispatch({ type: 'START_DRAWING' }),
    addDrawPoint:   (p) => dispatch({ type: 'ADD_DRAW_POINT', point: p }),
    undoDrawPoint:  () => dispatch({ type: 'UNDO_DRAW_POINT' }),
    closePolygon:   () => dispatch({ type: 'CLOSE_POLYGON' }),
    cancelDrawing:  () => dispatch({ type: 'RESET_DRAW' }),
    saveDrawing,
    selectROI:      (id) => dispatch({ type: 'SELECT_ROI', roiId: id }),
    deselectROI:    () => dispatch({ type: 'DESELECT' }),
    startDragVertex:(idx) => dispatch({ type: 'START_DRAG', idx }),
    stopDrag:       () => dispatch({ type: 'STOP_DRAG' }),
    moveVertex:     (idx, nx, ny) => dispatch({ type: 'MOVE_VERTEX', idx, nx, ny }),
    saveEditedROI,
    deleteROI,
    toggleROI,
    updateROI,
  }
}
