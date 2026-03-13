import CameraCard from './CameraCard'

export default function LiveView({ cameras, running, streamEpoch, onEditROI }) {
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

  // Dynamic grid: 1 cam → 1 col, 2 → 2, 3-4 → 2×2, 5+ → 3 cols
  const cols =
    cameras.length === 1 ? 'grid-cols-1' :
    cameras.length === 2 ? 'grid-cols-2' :
    cameras.length <= 4 ? 'grid-cols-2' :
    'grid-cols-3'

  return (
    <div className={`grid ${cols} gap-2 p-3 h-full`}>
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
  )
}
