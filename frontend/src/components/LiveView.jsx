import CameraCard from './CameraCard'

export default function LiveView({ cameras, running, streamEpoch, systemMetrics, onEditROI }) {
  if (cameras.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        <div className="text-center">
          <p className="text-lg mb-2">No cameras configured</p>
          <p className="text-sm">Go to Configuration to add cameras.</p>
        </div>
      </div>
    )
  }

  // Dynamic grid: 1 cam -> 1 col, 2 -> side by side, 3-4 -> 2x2, 5+ -> scrollable grid.
  const cols =
    cameras.length === 1 ? 'grid-cols-1' :
    cameras.length === 2 ? 'grid-cols-1 sm:grid-cols-2' :
    cameras.length <= 4 ? 'grid-cols-1 sm:grid-cols-2' :
    'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'

  const fitToScreen = cameras.length <= 4
  const rows =
    cameras.length <= 2 ? 'sm:grid-rows-1' :
    cameras.length <= 4 ? 'sm:grid-rows-2' :
    ''

  return (
    <div className={`h-full p-2 sm:p-3 ${fitToScreen ? 'overflow-auto sm:overflow-hidden flex flex-col gap-2' : 'overflow-auto space-y-3'}`}>
      <div className={`grid ${cols} ${rows} gap-2 ${fitToScreen ? 'sm:flex-1 sm:min-h-0' : ''}`}>
        {cameras.map((cam) => (
          <CameraCard
            key={cam.id}
            camera={cam}
            running={running}
            streamEpoch={streamEpoch}
            onEditROI={onEditROI}
            fitToScreen={fitToScreen}
          />
        ))}
      </div>
    </div>
  )
}
