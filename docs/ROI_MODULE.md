# ROI Module — Developer Documentation

Region of Interest (ROI) system for the SkyEye CCTV AI monitoring platform.
Fully self-contained drop-in module. Zero changes to existing project files required.

---

## Architecture Summary

```
roi_module/
├── __init__.py            ← Public API + setup_roi_module() one-call integration
├── config.py              ← ROIConfig dataclass + configure_roi()
├── exceptions.py          ← Typed exceptions (NotFound, LimitExceeded, InvalidPolygon)
├── models.py              ← SQLAlchemy ORM: ROI table + init_tables()
├── schemas.py             ← Pydantic v2: ROICreate / ROIUpdate / ROIOut / BulkReplace
├── geometry.py            ← Pure-Python geometry (no external deps)
│                             point_in_polygon · validate_polygon · IoU · S-H clip
├── cache.py               ← Thread-safe in-memory cache (TTL + explicit invalidation)
├── service.py             ← Business logic: CRUD + bulk replace + cache management
├── routes.py              ← FastAPI router (7 endpoints) with swappable dependencies
├── filter.py              ← Detection pipeline hook: filter_detections()
├── seed.py                ← Sample data + example API payloads
├── tests/
│   ├── conftest.py        ← SQLite in-memory fixtures
│   ├── test_geometry.py   ← Unit tests: geometry + IoU + normalization
│   ├── test_filter.py     ← Unit tests: detection filtering edge cases
│   └── test_service.py    ← Integration tests: full CRUD lifecycle
└── frontend/
    ├── roi-api.js         ← Fetch API client (mirrors existing client.js style)
    ├── useROI.js          ← React hook: state machine for draw/edit/view
    ├── ROICanvas.jsx      ← HTML5 Canvas overlay (draw · edit · view)
    ├── ROIPanel.jsx       ← Sidebar list (toggle · rename · color · delete)
    └── ROIEditorPage.jsx  ← Full-page editor combining Canvas + Panel
```

**Separation of concerns:**
- `geometry.py` — zero dependencies, pure math, fully unit-testable
- `service.py` — DB + cache, no HTTP concerns
- `routes.py` — HTTP only, thin wrappers over service
- `filter.py` — pipeline hook, imports only geometry + service

---

## Setup and Integration

### 1 — Backend (FastAPI + SQLAlchemy)

#### Option A: One-call setup (recommended)

```python
# In app/main.py (or wherever you build your FastAPI app)
from roi_module import setup_roi_module
from app.db.database import engine, get_db
from app.dependencies import get_current_user   # your existing JWT dep

setup_roi_module(
    app,
    get_db=get_db,
    get_current_user=get_current_user,
    api_prefix="/api",
    engine=engine,                  # auto-creates the `rois` table
    filter_mode="center",           # or "iou"
    allow_outside_fallback=True,
    max_rois_per_camera=10,
    debug_mode=False,
)
```

#### Option B: Manual wiring

```python
from roi_module.models import init_tables
from roi_module.routes import router as roi_router, set_dependencies
from roi_module.config import configure_roi

configure_roi(filter_mode="iou", iou_threshold=0.25)
init_tables(engine)
set_dependencies(get_db=get_db, get_current_user=get_current_user)
app.include_router(roi_router, prefix="/api")
```

### 2 — Detection Pipeline Integration

Add **two lines** to your `camera_worker.py` `camera_loop()`:

```python
# At the top of the file
from roi_module.filter import make_roi_filter

# Inside camera_loop(), once per camera startup (after DB session is available):
roi_filter = make_roi_filter(camera_id, frame_width, frame_height, db_session)

# After detection, before alert generation:
detections_raw = detector.run_detection(frame, model, threshold)
kept_detections, dropped = roi_filter(detections_raw)

# Use `kept_detections` for buzzer + alert logic
```

For the existing `camera_worker.py` format (list of YOLO result dicts), the filter accepts:
```python
{"x1": 100, "y1": 50, "x2": 200, "y2": 150}          # pixel bbox
{"bbox": [100, 50, 200, 150]}                           # bbox list
{"xmin": 100, "ymin": 50, "xmax": 200, "ymax": 150}   # xmin/xmax style
```

### 3 — Frontend

```jsx
// In your App.jsx, add a route:
import ROIEditorPage from "./roi_module/frontend/ROIEditorPage";

// In your router:
<Route
  path="/roi/:cameraId"
  element={
    <ROIEditorPage
      cameraId={params.cameraId}
      cameraStreamUrl={`/api/stream/${params.cameraId}`}
      token={authToken}
      onClose={() => navigate(-1)}
    />
  }
/>
```

Or embed inline in any component:
```jsx
<ROIEditorPage cameraId="cam_1" cameraStreamUrl="/api/stream/cam_1" token={token} />
```

---

## API Reference

All routes are mounted under `{api_prefix}/rois/`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/rois/camera/{camera_id}` | List ROIs. `?active_only=true` to filter |
| POST | `/rois/camera/{camera_id}` | Create ROI — returns 201 |
| GET | `/rois/{roi_id}` | Get single ROI |
| PUT | `/rois/{roi_id}` | Update ROI (partial) |
| DELETE | `/rois/{roi_id}` | Delete ROI — returns 204 |
| PATCH | `/rois/{roi_id}/toggle` | Toggle active/inactive |
| PUT | `/rois/camera/{camera_id}/bulk` | Atomic replace all ROIs |

### Create ROI — Example Request

```json
POST /api/rois/camera/cam_1
{
  "name": "Entrance Zone",
  "color": "#FF5733",
  "priority": 10,
  "is_active": true,
  "camera_width": 1280,
  "camera_height": 720,
  "points_normalized": [
    {"x": 0.05, "y": 0.05},
    {"x": 0.45, "y": 0.05},
    {"x": 0.45, "y": 0.55},
    {"x": 0.05, "y": 0.55}
  ]
}
```

### Response

```json
{
  "roi_id": "a1b2c3d4-e5f6-...",
  "camera_id": "cam_1",
  "name": "Entrance Zone",
  "color": "#FF5733",
  "priority": 10,
  "is_active": true,
  "camera_width": 1280,
  "camera_height": 720,
  "points_normalized": [
    {"x": 0.05, "y": 0.05},
    {"x": 0.45, "y": 0.05},
    {"x": 0.45, "y": 0.55},
    {"x": 0.05, "y": 0.55}
  ],
  "created_at": "2026-03-11T10:00:00",
  "updated_at": "2026-03-11T10:00:00",
  "created_by": "alice"
}
```

### Error Responses

| Status | When |
|--------|------|
| 404 | ROI not found |
| 409 | Per-camera ROI limit reached |
| 422 | Invalid polygon (self-intersecting, < 3 points, coords out of [0,1]) |

---

## Configuration Reference

```python
from roi_module.config import configure_roi

configure_roi(
    default_enabled=True,        # ROI filtering enabled globally
    max_rois_per_camera=10,      # Hard cap per camera
    max_points_per_roi=50,       # Hard cap per polygon
    allow_outside_fallback=True, # True = allow all when no active ROI exists
    strict_roi_mode=False,       # True = drop all when no active ROI
    filter_mode="center",        # "center" or "iou"
    iou_threshold=0.3,           # Minimum IoU (only in "iou" mode)
    cache_ttl_seconds=60,        # Cache lifetime before DB re-fetch
    debug_mode=False,            # Log kept/dropped counts per detection
)
```

---

## Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-cov

# Run all tests
pytest roi_module/tests/ -v

# With coverage
pytest roi_module/tests/ --cov=roi_module --cov-report=term-missing

# Individual suites
pytest roi_module/tests/test_geometry.py -v
pytest roi_module/tests/test_filter.py -v
pytest roi_module/tests/test_service.py -v
```

Expected output: **~55 tests**, all green.

---

## Seeding Sample Data

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from roi_module.models import init_tables
from roi_module.seed import seed_sample_rois

engine = create_engine("postgresql://user:pass@localhost/skyeye")
init_tables(engine)
Session = sessionmaker(bind=engine)

with Session() as db:
    count = seed_sample_rois(db, skip_if_exists=True)
    print(f"Seeded {count} ROIs")
```

---

## Data Model

```
rois
├── roi_id          TEXT PRIMARY KEY (UUID)
├── camera_id       TEXT NOT NULL  INDEX
├── name            TEXT NOT NULL
├── points_normalized JSON NOT NULL   -- [{x: float, y: float}, ...]
├── is_active       BOOL NOT NULL  INDEX
├── color           TEXT           -- #RRGGBB
├── priority        INT            -- higher = checked first
├── camera_width    INT            -- resolution at draw time
├── camera_height   INT
├── created_at      DATETIME
├── updated_at      DATETIME
└── created_by      TEXT
```

**Invariants enforced by the service layer:**
- `points_normalized[*].x` and `.y` always in [0, 1]
- Minimum 3 vertices
- No self-intersecting edges
- Non-zero area

---

## Filter Modes

### `center` (default)
Checks whether the **center point** of the detection bounding box lies inside the polygon.
Fast O(n) ray casting. Best for rectangular detection boxes with clear centres.

### `iou`
Computes the **Intersection-over-Union** between the detection bbox and the ROI polygon using Sutherland-Hodgman polygon clipping.
More accurate for large or partially-overlapping detections.
Controlled by `iou_threshold` (default 0.3).

---

## Known Limitations & Future Improvements

| Limitation | Suggested Fix |
|-----------|--------------|
| `sutherland_hodgman_clip` assumes convex clip polygon | Use Greiner-Hormann for concave IoU clipping |
| No polygon simplification on save | Add Douglas-Peucker to reduce vertex count |
| Canvas editor has no zoom/pan | Add CSS `transform: scale()` pinch-zoom layer |
| ROI camera resolution mismatch on different streams | Store + validate resolution on every edit |
| No ROI copy/paste between cameras | Add `/rois/{roi_id}/clone?target_camera=...` |
| Bulk replace is non-transactional on Postgres by default | Wrap in explicit `BEGIN`/`COMMIT` or use savepoint |
| Frontend has no undo history for editing mode | Add Redux or Zustand undo middleware |
| No WebSocket push for live ROI updates | Emit on `roi_updated` channel, invalidate frontend cache |

---

## License

MIT — free to use, modify, and integrate into any project.
