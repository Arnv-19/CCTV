# PPE Violation Tracking System — Technical Documentation

## Overview

The system detects PPE violations (No Hardhat, No Safety Vest, No Gloves) from camera feeds in real time. It uses YOLO for detection and KCF (Kernelized Correlation Filters) for tracking each person, ensuring:

- **One orange tracking box per person** regardless of how many violations they have
- **No duplicate alerts** for the same person within the same visit
- **Identity restoration** if a person briefly leaves and returns to the same area

---

## Architecture

```
Camera Feed
    │
    ▼
ingestion_worker (mp.Process per camera)
    │  sends JPEG frames via mp.Queue
    ▼
inference_server_loop (mp.Process, batch YOLO)
    │  sends detection results via result_queue
    ▼
result_handler_worker (threading.Thread, main process)
    │
    ├── KCF Tracking
    ├── Violation Deduplication
    ├── DB Alert Write
    └── MJPEG Frame Output
```

---

## Detection Sources

| Source | What it detects | How |
|---|---|---|
| YOLO (main model) | NO-Hardhat, NO-Safety Vest, Person | Batch GPU inference |
| YOLO (gloves model) | NO-Gloves, Gloves | Separate model run |
| MediaPipe | Hand landmarks (bare hands) | CPU, in result_handler thread |

MediaPipe hand detections are injected as synthetic `NO-Gloves` detection dicts into the YOLO detection list **before** the tracking loop runs, so they go through the exact same pipeline.

---

## Key Data Structures

### Active Tracker Entry (`_viol_trackers`)

One entry per person currently visible on camera.

```python
{
    "tracker":    cv2.TrackerKCF,             # OpenCV KCF object
    "bbox":       [x1, y1, x2, y2],           # current person position (pixels)
    "alerted":    {"no-hardhat", "no-safety-vest"},  # violations already fired
    "fails":      0,                           # consecutive KCF update failures
    "session_id": "abc-123-uuid"               # unique ID for this visit
}
```

### Cache Entry (`_tracker_cache`)

Saved when a tracker drops (person leaves frame). Used to restore identity if they return.

```python
{
    "bbox":       [x1, y1, x2, y2],           # last known screen position
    "alerted":    {"no-hardhat", "no-safety-vest"},  # violations already fired
    "session_id": "abc-123-uuid",              # same UUID as the live tracker
    "saved_at":   1715430050.0                 # unix timestamp (for TTL)
}
```

### Constants

| Constant | Value | Meaning |
|---|---|---|
| `VIOL_MAX_FAILS` | `8` | KCF failures before tracker drops (~2s at 4fps) |
| `VIOL_IOU_THRESHOLD` | `0.10` | Min IoU to match detection to tracker |
| `TRACKER_CACHE_TTL` | `30.0` s | How long to keep cache after tracker drops |
| `TRACKER_CACHE_IOU` | `0.30` | Min IoU to match returning person to cache |
| `VIOL_ORANGE` | `(0, 165, 255)` | Orange colour for KCF box |

---

## KCF Drift Problem and Fixes

### The Problem

When KCF starts failing (person moves quickly, partial occlusion, or lighting change), the tracker bbox **freezes** at the last good position while the person has physically moved elsewhere on screen.

```
T1 bbox frozen here:        Person actually here now:
┌──────────┐                          ┌──────────┐
│ [75,35,  │                          │ [200,35, │
│  155,380]│          person →→→      │  280,380]│
└──────────┘                          └──────────┘
     ↑                                      ↑
 KCF stuck                           YOLO detects here
```

YOLO then detects the person at `[200,35,280,380]`. `_find_tracker` checks against `[75,35,155,380]` — zero overlap, no match → **creates a second tracker** → two orange boxes on screen.

### Fix 1 — Center-Distance Fallback in `_find_tracker`

Before declaring "no match", we check if the **centres of the two bboxes are close relative to the tracker size**:

```
T1 centre: (115, 207),  T1 width: 80px,  T1 height: 345px
New YOLO centre: (240, 207)

|240 - 115| = 125  <  80 * 0.8 = 64 ?   → moderate drift → match
|240 - 115| = 125  <  80 * 0.8 = 64 ?   → extreme drift  → miss → Fix 2 catches it
```

This handles moderate drift without creating a second tracker.

### Fix 2 — Dedup Pass After Every Frame (Safety Net)

After all violations are processed each frame, all active trackers are scanned and any two that overlap are merged:

```
T1 bbox: [75, 35, 155, 380]
T2 bbox: [80, 38, 158, 375]   ← duplicate from a previous frame
IoU = 0.93  → same person → merge T2 alerted into T1 → delete T2
```

Even if a duplicate slipped through Fix 1, it is removed before the next `cv2.rectangle` draw — so it never appears on screen.

### Fix 3 — Person Class Re-Anchor Every Frame

This is the most important fix. Instead of waiting for a **violation** detection to re-anchor KCF, we use the **Person class** detection to correct KCF **every single frame**.

```
Every frame, after Step 1:
    for each active tracker:
        find YOLO Person bbox that overlaps this tracker
        → re-init KCF with fresh Person bbox
        → tracker never drifts because it is corrected every frame
```

**Why Person class is more reliable than violation class:**

| | Person class | Violation class (NH, NV) |
|---|---|---|
| Size of target | Full body (large) | Head / torso (small) |
| Typical confidence | 0.85–0.95 | 0.25–0.60 |
| Detected when person turns sideways | ✅ usually | ❌ often missed |
| Detected when partially occluded | ✅ usually | ❌ often missed |

**Before this fix:**
```
Frame 10:  violation conf=0.87 → KCF re-anchored ✅
Frame 11:  violation conf=0.22 (below threshold) → not detected → KCF drifts
Frame 12:  violation conf=0.21 → not detected → KCF drifts more
Frame 13:  violation conf=0.79 → detected → KCF re-anchored (already drifted 3 frames)
```

**After this fix:**
```
Frame 10:  Person conf=0.92 → KCF re-anchored ✅
Frame 11:  Person conf=0.91 → KCF re-anchored ✅  (violation not needed)
Frame 12:  Person conf=0.94 → KCF re-anchored ✅
Frame 13:  Person conf=0.90 → KCF re-anchored ✅
           drift = 0 at all times
```

---

## Processing Pipeline — Every Frame

### STEP 1 — KCF Update (no YOLO needed)

KCF tracks each person using pixel pattern matching. It only needs the full frame — no coordinates passed.

```
for each tracker in _viol_trackers:
    ok, rect = tracker.update(full_frame)

    if ok:
        update vt["bbox"] with new position
        reset vt["fails"] = 0

    else:
        vt["fails"] += 1

        if fails >= 8:
            REMOVE from _viol_trackers
            SAVE to _tracker_cache   ← person left frame
```

After Step 1, expired cache entries (older than 30s) are pruned.

### STEP 1b — Re-Anchor Active Trackers from Person Class

YOLO Person detections are available every frame. For each active tracker, find the Person bbox that overlaps it and re-initialize KCF with that fresh bbox:

```
for each tracker in _viol_trackers:
    find Person bbox with IoU > 15% OR tracker centre inside Person bbox
    if found:
        re-init KCF with Person bbox
        update vt["bbox"] = Person bbox
        reset vt["fails"] = 0
```

This keeps the orange box locked to the actual person position every frame, regardless of whether a violation was detected or not.

### STEP 2 — Draw Orange Boxes

```
for each tracker in _viol_trackers:
    draw orange rectangle at vt["bbox"]
```

One box per tracker = one box per person regardless of number of violations.

### STEP 3 — Process YOLO Violations

For each violation detection this frame:

#### 3a — Resolve full-body person bbox

Violation bboxes are small (head, hand). We need the full-body bbox to link all violations to one tracker.

```
Priority:
1. YOLO "Person" class bbox that CONTAINS the violation centre
2. YOLO "Person" class bbox with best IoU > 5%
3. UNION of all violation bboxes with overlapping X range
   (same horizontal column = same person, different body parts)
```

#### 3b — Find existing active tracker

```
_find_tracker(full_body_bbox):
    1. IoU > 10% with any vt["bbox"]
    2. OR violation centre falls INSIDE any vt["bbox"]
```

#### 3c — Decision tree

```
CASE A: tracker found AND violation already in tracker["alerted"]
    → No alert (already fired)
    → Re-anchor KCF with fresh YOLO bbox if drifting (fails>0 or IoU<0.5)

CASE B: tracker found AND new violation class
    → Fire alert with tracker["session_id"]
    → Add violation to tracker["alerted"]
    → Re-anchor KCF with fresh YOLO bbox

CASE C: no tracker found → check _tracker_cache by IoU
    Match found (IoU >= 0.30):
        → Restore session_id from cache
        → Violation already in cached["alerted"]?
              YES → Re-init KCF, restore alerted set, NO alert
              NO  → Fire alert with restored session_id

    No match → brand new person:
        → New session_id = uuid4()
        → Fire alert
        → Init KCF tracker
```

---

## How KCF Tracking Works

KCF is an OpenCV correlation filter tracker. It does **not** use YOLO after initialization.

```
Initialization:
    tracker.init(frame, bbox)
    ↑             ↑      ↑
    full frame    │      (x, y, w, h) — tells KCF "learn these pixels"
                  │
                  KCF builds a filter kernel from the pixel crop

Every subsequent frame:
    tracker.update(full_frame)
    ↑               ↑
    returns new     only the full frame — no bbox needed
    (ok, rect)      KCF searches for the learned pixels
```

KCF returns `ok=False` when it can no longer find the target (person left frame, heavy occlusion, or lighting change). After 8 consecutive failures the tracker is dropped.

**Re-anchoring:** When YOLO detects a violation on an already-tracked person, we optionally re-initialize KCF with the fresh YOLO bbox to prevent drift accumulation.

---

## Person Re-Identification (Cache Lookup)

### Why the cache exists — preventing duplicate DB alerts

The tracker (KCF object) is completely destroyed after 8 consecutive failures. Nothing keeps running. However, just because KCF lost the person does not mean the person left for good — they may have walked behind a pillar, ducked, or been briefly occluded by another worker.

Without the cache, every brief occlusion creates a new session and fires fresh alerts:

```
Second 0:   Worker enters → no-hardhat detected → alert fires (session "abc")
Second 3:   Worker steps behind pillar → KCF fails 8× → tracker destroyed
Second 6:   Worker steps out → YOLO sees no-hardhat again
            No cache → treated as brand new person
            → NEW alert fires (session "xyz")   ← duplicate
Second 9:   Behind pillar again → tracker destroyed
Second 11:  Steps out → THIRD alert (session "pqr") ← duplicate
```

Same person, one visit, three DB records.

With the cache, when the tracker dies its last known position, alerted set, and session_id are saved as a plain dictionary — no CPU, no tracking, just 4 values in a list. When YOLO sees a person at that same location within 30 seconds:

```
Second 0:   Alert fires → session "abc", alerted={"no-hardhat"}
Second 3:   Tracker dies → dict saved to _tracker_cache
Second 6:   YOLO sees person at same spot → IoU matches cache
            → session "abc" restored, alerted={"no-hardhat"} restored
            → "no-hardhat" already in alerted → NO new alert
```

Same person, one visit, one DB record.

The 30-second TTL is "how long to keep the phone number before forgetting the caller." The KCF object itself is gone — the cache is purely a re-identification memory.

---

### How re-identification works

When a person re-enters frame (no active tracker), we check `_tracker_cache` by **screen coordinate proximity**:

```
Saved cache bbox:   [100, 50, 200, 380]   ← where they were last seen
New YOLO bbox:      [110, 55, 205, 375]   ← where they appeared now

IoU = overlap_area / union_area = 0.82   ≥ 0.30 threshold → MATCH
```

**If matched:**
- Same `session_id` is restored — all DB alerts link to the same session
- Already-alerted violations are NOT re-fired
- New KCF object is created at the returning person's current position

**If no match within 30s:**
- Cache entry is deleted — person is forgotten
- Next detection treated as a brand new person
- New `session_id` generated, new alert fires

**Limitation:** This is screen-coordinate based, not biometric. Two different people standing in the same spot may be confused. This is acceptable for factory environments where workers have fixed workstations.

---

## Alert Record (Database)

Each `record_violation()` call writes to the alert queue:

```python
{
    "camera_id":          1,
    "model_name":         "ppe_detection",
    "violation_type":     "NO-Hardhat",
    "confidence_score":   0.87,
    "snapshot_path":      "snapshots/cam_1/...",
    "buzzer_activated":   True,
    "session_tracker_id": "abc-123-uuid"   ← links all violations for same person
}
```

Multiple violations for the same person (NO-Hardhat + NO-Safety Vest + NO-Gloves) all share the same `session_tracker_id`. This allows the frontend to group them as "1 person — 3 violations".

---

## Visual Output on Frame

| Box colour | Meaning |
|---|---|
| **Orange** (thick) | KCF tracker — one per person |
| **Red** (thin, label NH) | YOLO NO-Hardhat detection |
| **Red** (thin, label NV) | YOLO NO-Safety Vest detection |
| **Red** (thin, label NGO) | NO-Gloves (YOLO or MediaPipe) |
| **Green** | PPE compliant detection |

---

## Complete Lifecycle Example

```
t=0s   Worker A enters frame
           YOLO: NO-Hardhat [80,40,140,100], Person [75,35,155,380]
           → full body bbox resolved: [75,35,155,380]
           → no active tracker, no cache match
           → DB alert written (session="abc")
           → KCF initialized at [75,35,155,380]
           → orange box drawn

t=0–9s  Worker A visible
           KCF.update(frame) → bbox follows worker
           YOLO: NO-Hardhat again → found in tracker["alerted"] → skip
           YOLO: NO-Safety Vest  → new violation → DB alert (session="abc")
                                 → added to tracker["alerted"]

t=10s  Worker A steps out of frame
           KCF fails 8 times → tracker dropped
           Cache saved: {bbox:[75,35,155,380], alerted:{NH,NV}, session="abc"}

t=18s  Worker A steps back in
           YOLO: NO-Hardhat [78,38,142,103]
           → no active tracker
           → cache lookup: IoU([78,38,142,103], [75,35,155,380]) = 0.91 → MATCH
           → session restored: "abc"
           → NH already in cached["alerted"] → no duplicate alert
           → KCF re-initialized
           → orange box drawn again

t=50s  Cache entry expires (30s TTL since t=10s when saved... actually t=18 reset it)
       Worker A leaves again at t=45 → cache saved again at t=45
       t=75 → cache pruned

t=80s  Worker A returns
           → no cache match (expired)
           → NEW session_id = "xyz"
           → NEW alert fired
```

---

## File Reference

| File | Role |
|---|---|
| `camera_worker.py` | KCF tracking, violation loop, cache logic (`result_handler_worker`) |
| `app/services/burglar_alarm_service.py` | `init_kcf_tracker()` helper |
| `inference_server.py` | Batch YOLO inference, sends results to result_handler |
| `data/class_names.yaml` | Violation class names, safe class names |
| `config.yaml` | Camera feeds, model paths, thresholds |
