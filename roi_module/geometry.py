"""
ROI Geometry Utilities
======================
Pure-Python geometry algorithms — no third-party dependencies.

Public API
----------
  point_in_polygon(point, polygon) -> bool
  validate_polygon(points) -> (bool, str)
  normalize_points(points_px, width, height) -> list[dict]
  denormalize_points(points_norm, width, height) -> list[dict]
  detection_center(detection) -> (float, float)
  detection_bbox_normalized(detection, frame_w, frame_h) -> (x1, y1, x2, y2)
  compute_iou_with_polygon(bbox_norm, polygon_points) -> float
  polygon_bounding_box(points) -> (x1, y1, x2, y2)
"""

from __future__ import annotations

from typing import List, Optional, Tuple


# Type aliases
Point = Tuple[float, float]
Polygon = List[Point]


# ---------------------------------------------------------------------------
# Core: point-in-polygon  (ray casting)
# ---------------------------------------------------------------------------

def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    """
    Determine whether *point* lies inside *polygon* using the ray-casting rule.
    Works for both CW and CCW vertex ordering.
    Points exactly on an edge may return True or False (boundary ambiguity).
    """
    x, y = point
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Ray crosses edge i→j?
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Polygon validation
# ---------------------------------------------------------------------------

def _cross(o: Point, a: Point, b: Point) -> float:
    """Signed 2-D cross product of vectors OA × OB."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_intersect_proper(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """
    Return True only for *proper* (non-endpoint) intersection.
    Adjacent edges sharing a vertex are always excluded.
    """
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return (
        ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and
        ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0))
    )


def is_self_intersecting(polygon: Polygon) -> bool:
    """Return True if any two non-adjacent edges of *polygon* cross."""
    n = len(polygon)
    for i in range(n):
        for j in range(i + 2, n):
            # Skip the wrap-around adjacent pair (last edge → first edge)
            if i == 0 and j == n - 1:
                continue
            p1, p2 = polygon[i], polygon[(i + 1) % n]
            p3, p4 = polygon[j], polygon[(j + 1) % n]
            if _segments_intersect_proper(p1, p2, p3, p4):
                return True
    return False


def polygon_area(polygon: Polygon) -> float:
    """Compute polygon area via the shoelace formula (always positive)."""
    n = len(polygon)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2.0


def validate_polygon(points: List[dict]) -> Tuple[bool, str]:
    """
    Validate a polygon expressed as a list of ``{x, y}`` dicts with normalized
    coordinates in **[0, 1]**.

    Returns ``(True, "")`` on success, or ``(False, reason)`` on failure.
    """
    if len(points) < 3:
        return False, "Polygon must have at least 3 points"
    if len(points) > 200:
        return False, "Polygon exceeds 200-point limit"

    for i, pt in enumerate(points):
        try:
            x = float(pt["x"] if isinstance(pt, dict) else pt[0])
            y = float(pt["y"] if isinstance(pt, dict) else pt[1])
        except (KeyError, TypeError, IndexError):
            return False, f"Point {i} is malformed (missing x or y)"

        if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
            return False, f"Point {i} ({x:.4f}, {y:.4f}) is outside [0, 1] range"

    tuples = points_to_tuples(points)

    if is_self_intersecting(tuples):
        return False, "Polygon edges self-intersect"

    if polygon_area(tuples) < 1e-8:
        return False, "Polygon has near-zero area (degenerate)"

    return True, ""


# ---------------------------------------------------------------------------
# Coordinate conversion helpers
# ---------------------------------------------------------------------------

def points_to_tuples(points: List[dict]) -> Polygon:
    """Convert ``[{x, y}, …]`` dicts to ``[(x, y), …]`` tuples."""
    result: Polygon = []
    for pt in points:
        if isinstance(pt, dict):
            result.append((float(pt["x"]), float(pt["y"])))
        else:
            result.append((float(pt[0]), float(pt[1])))
    return result


def tuples_to_dicts(polygon: Polygon) -> List[dict]:
    return [{"x": float(x), "y": float(y)} for x, y in polygon]


def normalize_points(points_px: List[dict], width: int, height: int) -> List[dict]:
    """Pixel ``{x, y}`` → normalized ``{x, y}`` in [0, 1]."""
    return [{"x": pt["x"] / width, "y": pt["y"] / height} for pt in points_px]


def denormalize_points(points_norm: List[dict], width: int, height: int) -> List[dict]:
    """Normalized ``{x, y}`` → pixel ``{x, y}``."""
    return [{"x": pt["x"] * width, "y": pt["y"] * height} for pt in points_norm]


def polygon_bounding_box(points: List[dict]) -> Tuple[float, float, float, float]:
    """Return ``(x1, y1, x2, y2)`` bounding box of a normalized polygon."""
    xs = [pt["x"] if isinstance(pt, dict) else pt[0] for pt in points]
    ys = [pt["y"] if isinstance(pt, dict) else pt[1] for pt in points]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def detection_center(detection: dict) -> Point:
    """
    Extract the center point of a detection bounding box.

    Accepts formats:
    - ``{x1, y1, x2, y2}``
    - ``{xmin, ymin, xmax, ymax}``
    - ``{bbox: [x1, y1, x2, y2]}``
    """
    if "bbox" in detection:
        x1, y1, x2, y2 = detection["bbox"]
    else:
        x1 = detection.get("x1", detection.get("xmin", 0))
        y1 = detection.get("y1", detection.get("ymin", 0))
        x2 = detection.get("x2", detection.get("xmax", 0))
        y2 = detection.get("y2", detection.get("ymax", 0))
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def detection_bbox_normalized(
    detection: dict, frame_w: int, frame_h: int
) -> Tuple[float, float, float, float]:
    """Return the detection bbox as normalized ``(x1, y1, x2, y2)`` in [0, 1]."""
    if "bbox" in detection:
        x1, y1, x2, y2 = detection["bbox"]
    else:
        x1 = detection.get("x1", detection.get("xmin", 0))
        y1 = detection.get("y1", detection.get("ymin", 0))
        x2 = detection.get("x2", detection.get("xmax", 0))
        y2 = detection.get("y2", detection.get("ymax", 0))

    # If coords already look normalized, skip division
    if max(x1, y1, x2, y2) <= 1.0 and frame_w > 1:
        return (float(x1), float(y1), float(x2), float(y2))

    return (x1 / frame_w, y1 / frame_h, x2 / frame_w, y2 / frame_h)


# ---------------------------------------------------------------------------
# IoU via Sutherland-Hodgman polygon clipping
# ---------------------------------------------------------------------------

def _ensure_ccw(polygon: Polygon) -> Polygon:
    """Reverse vertex order if polygon is CW (needed for S-H clipping)."""
    n = len(polygon)
    signed = sum(
        polygon[i][0] * polygon[(i + 1) % n][1] - polygon[(i + 1) % n][0] * polygon[i][1]
        for i in range(n)
    )
    return polygon[::-1] if signed < 0 else polygon


def _inside_edge(p: Point, edge_a: Point, edge_b: Point) -> bool:
    """Is *p* on the 'inside' (left) side of directed edge a→b?"""
    return _cross(edge_a, edge_b, p) >= 0


def _line_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> Optional[Point]:
    """Intersection of infinite lines through p1-p2 and p3-p4."""
    denom = (
        (p4[1] - p3[1]) * (p2[0] - p1[0]) -
        (p4[0] - p3[0]) * (p2[1] - p1[1])
    )
    if abs(denom) < 1e-12:
        return None  # parallel
    t = (
        (p4[0] - p3[0]) * (p1[1] - p3[1]) -
        (p4[1] - p3[1]) * (p1[0] - p3[0])
    ) / denom
    return (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))


def sutherland_hodgman_clip(subject: Polygon, clip: Polygon) -> Polygon:
    """
    Clip *subject* polygon against convex *clip* polygon.
    Returns the clipped polygon (may be empty if no overlap).
    """
    output = list(subject)
    n_clip = len(clip)
    for i in range(n_clip):
        if not output:
            return []
        edge_a, edge_b = clip[i], clip[(i + 1) % n_clip]
        input_list = output
        output = []
        for j in range(len(input_list)):
            cur = input_list[j]
            prev = input_list[j - 1]
            cur_inside = _inside_edge(cur, edge_a, edge_b)
            prev_inside = _inside_edge(prev, edge_a, edge_b)
            if cur_inside:
                if not prev_inside:
                    pt = _line_intersect(prev, cur, edge_a, edge_b)
                    if pt:
                        output.append(pt)
                output.append(cur)
            elif prev_inside:
                pt = _line_intersect(prev, cur, edge_a, edge_b)
                if pt:
                    output.append(pt)
    return output


def compute_iou_with_polygon(
    bbox_norm: Tuple[float, float, float, float],
    polygon_points: List[dict],
) -> float:
    """
    Compute IoU between a normalized axis-aligned bounding box and an ROI polygon.

    Args:
        bbox_norm: ``(x1, y1, x2, y2)`` in [0, 1]
        polygon_points: list of ``{x, y}`` dicts in [0, 1]

    Returns:
        IoU in [0, 1]
    """
    x1, y1, x2, y2 = bbox_norm
    box_as_poly: Polygon = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    roi_poly = _ensure_ccw(points_to_tuples(polygon_points))

    clipped = sutherland_hodgman_clip(box_as_poly, roi_poly)
    if len(clipped) < 3:
        return 0.0

    intersection = polygon_area(clipped)
    box_area = (x2 - x1) * (y2 - y1)
    roi_area = polygon_area(roi_poly)
    union = box_area + roi_area - intersection

    return intersection / union if union > 0 else 0.0
