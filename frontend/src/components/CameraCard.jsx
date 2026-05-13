import { useEffect, useState } from 'react'
import { AlertTriangle, Activity, Tv, Crop } from 'lucide-react'
import { api } from '../api/client'

export default function CameraCard({ camera, running, streamEpoch, onEditROI, fitToScreen = false }) {
  const [imgError, setImgError] = useState(false)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [streamAttempt, setStreamAttempt] = useState(0)
  const fallbacks = camera.runtime_fallbacks || {}
  const resources = camera.resources || null
  // Key forces img reload when detection state or explicit epoch changes.
  const streamKey = `cam-${camera.id}-${running ? 'on' : 'off'}-${streamEpoch}`

  useEffect(() => {
    // Clear stale error when stream lifecycle changes.
    setImgError(false)
    setImgLoaded(false)
    setStreamAttempt(0)
  }, [streamEpoch, running, camera.id, camera.status])

  useEffect(() => {
    if (!running || !imgError) return
    const id = setTimeout(() => setImgError(false), 800)
    return () => clearTimeout(id)
  }, [imgError, running, streamEpoch, camera.id])

  const statusColor =
    camera.status === 'running' ? 'bg-green-500' :
    camera.status === 'error'   ? 'bg-red-500' :
    'bg-zinc-500'

  const cameraReady = camera.status === 'running'
  const shouldMountStream = running && cameraReady && !imgError
  const streamClass = fitToScreen
    ? 'relative bg-black aspect-video sm:aspect-auto sm:flex-1 sm:min-h-0 overflow-hidden'
    : 'relative bg-black aspect-video overflow-hidden'

  return (
    <div className="relative min-h-0 bg-zinc-800 rounded-lg overflow-hidden border border-zinc-700 flex flex-col">
      {/* Stream */}
      <div className={streamClass}>
        {shouldMountStream ? (
          <>
            <img
              key={streamKey}
              src={api.streamUrl(camera.id, streamEpoch, streamAttempt)}
              alt={camera.title}
              className="camera-stream absolute inset-0"
              onLoad={() => setImgLoaded(true)}
              onError={() => {
                setImgLoaded(false)
                setImgError(true)
                setStreamAttempt((n) => n + 1)
              }}
            />
            {!imgLoaded && (
              <div className="absolute inset-0 flex items-center justify-center text-zinc-500">
                <div className="text-center">
                  <Tv size={36} className="mx-auto mb-2 opacity-30" />
                  <p className="text-xs">Connecting stream...</p>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-600">
            <div className="text-center">
              <Tv size={36} className="mx-auto mb-2 opacity-30" />
              <p className="text-xs">
                {imgError ? 'Stream unavailable' : (running ? 'Starting camera...' : 'Not running')}
              </p>
            </div>
          </div>
        )}

        {/* Violation badge */}
        {camera.violations > 0 && (
          <div className="absolute top-2 right-2 flex items-center gap-1 bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded-full">
            <AlertTriangle size={11} />
            {camera.violations}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 px-3 py-1.5 bg-zinc-800 border-t border-zinc-700 text-xs">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2 h-2 rounded-full shrink-0 ${statusColor}`} />
            <span className="font-semibold text-zinc-200 truncate">{camera.title}</span>
          </div>
          <div className="flex items-center gap-3 text-zinc-400 shrink-0">
            {fallbacks.model_fallback && (
              <span className="px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-300 text-[10px] font-semibold">
                model fallback
              </span>
            )}
            {fallbacks.source_fallback && (
              <span className="px-1.5 py-0.5 rounded bg-sky-900/50 text-sky-300 text-[10px] font-semibold">
                webcam fallback
              </span>
            )}
            {camera.fps > 0 && (
              <span className="flex items-center gap-1">
                <Activity size={11} />
                {camera.fps} fps
              </span>
            )}
            <span>Cam {camera.id}</span>
            <button
              onClick={() => onEditROI?.(camera.id)}
              title="Edit ROI zones"
              className="p-1 text-zinc-500 hover:text-emerald-400 hover:bg-zinc-700 rounded transition-colors"
            >
              <Crop size={13} />
            </button>
          </div>
        </div>

        {resources && (
          <div className="mt-1 flex items-center gap-3 text-[11px] text-zinc-400">
            <span>CPU {resources.thread_cpu_percent_single_core}% of one core</span>
          </div>
        )}
      </div>
    </div>
  )
}
