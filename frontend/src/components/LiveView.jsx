import CameraCard from './CameraCard'

export default function LiveView({ cameras, running, streamEpoch, systemMetrics, onEditROI }) {
  if (cameras.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        <div className="text-center">
          <p className="text-lg mb-2">No cameras configured</p>
          <p className="text-sm">Go to Configuration to add cameras.</p>
        </div>
      </div>
    )
  }

  // Dynamic grid: 1 cam → 1 col, 2 → 1 col on mobile / 2 on sm+, 3-4 → 2×2 on sm+, 5+ → 3 cols on lg+
  const cols =
    cameras.length === 1 ? 'grid-cols-1' :
    cameras.length === 2 ? 'grid-cols-1 sm:grid-cols-2' :
    cameras.length <= 4 ? 'grid-cols-1 sm:grid-cols-2' :
    'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'

  return (
    <div className="h-full overflow-auto p-3 space-y-3">
      {systemMetrics?.notes?.length > 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-800/70 px-4 py-2 text-xs text-slate-400">
          {systemMetrics.notes[1]}
        </div>
      )}

      <div className={`grid ${cols} gap-2`}>
        {cameras.map((cam) => (
          <CameraCard
            key={cam.id}
            camera={cam}
            running={running}
            streamEpoch={streamEpoch}
            onEditROI={onEditROI}
          />
        ))}
      </div>
    </div>
  )
}
