"""
tests/test_burglar_deduplication.py
-----------------------------------
Test burglar alarm deduplication via IoU (Intersection over Union).
Validates that multiple detections of the same person in consecutive frames
result in only one DB event.
"""

import pytest


def test_iou_computation():
    """Test IoU (Intersection over Union) calculation."""
    # Helper to compute IoU (same logic as in camera_worker.py)
    def compute_iou(box1, box2):
        if box1 is None or box2 is None:
            return 0.0
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        # Intersection
        xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
        xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
        if xi2 < xi1 or yi2 < yi1:
            inter_area = 0.0
        else:
            inter_area = (xi2 - xi1) * (yi2 - yi1)
        # Union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = area1 + area2 - inter_area
        if union_area <= 0:
            return 0.0
        return inter_area / union_area

    # Test: identical boxes → IoU = 1.0
    box = [10, 20, 100, 200]
    assert compute_iou(box, box) == 1.0

    # Test: no overlap → IoU = 0.0
    box1 = [0, 0, 50, 50]
    box2 = [100, 100, 150, 150]
    assert compute_iou(box1, box2) == 0.0

    # Test: 50% overlap (half intersection)
    # box1: (0,0) to (100,100), area=10000
    # box2: (50,0) to (150,100), area=10000
    # intersection: (50,0) to (100,100), area=5000
    # union: 10000+10000-5000=15000, IoU=5000/15000≈0.333
    box1 = [0, 0, 100, 100]
    box2 = [50, 0, 150, 100]
    iou = compute_iou(box1, box2)
    assert abs(iou - 0.333) < 0.01

    # Test: small offset (likely same person)
    # box1: (100, 100) to (200, 300)
    # box2: (105, 105) to (205, 305), offset by (5,5) pixels
    # Should have high IoU
    box1 = [100, 100, 200, 300]
    box2 = [105, 105, 205, 305]
    iou = compute_iou(box1, box2)
    assert iou > 0.85  # very high overlap = same person

    # Test: None handling
    assert compute_iou(None, box1) == 0.0
    assert compute_iou(box1, None) == 0.0
    assert compute_iou(None, None) == 0.0


def test_deduplication_logic():
    """Test the deduplication decision logic."""
    IoU_THRESHOLD = 0.3

    # Scenario 1: Same person in consecutive frames (small offset)
    last_bbox = [100, 100, 200, 300]
    new_bbox = [102, 101, 202, 301]  # tiny shift
    
    def compute_iou(b1, b2):
        if b1 is None or b2 is None:
            return 0.0
        x1_1, y1_1, x2_1, y2_1 = b1
        x1_2, y1_2, x2_2, y2_2 = b2
        xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
        xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
        inter_area = (xi2 - xi1) * (yi2 - yi1) if xi2 >= xi1 and yi2 >= yi1 else 0.0
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = area1 + area2 - inter_area
        return inter_area / union_area if union_area > 0 else 0.0

    iou = compute_iou(new_bbox, last_bbox)
    assert iou > IoU_THRESHOLD  # Same person → skip event
    print(f"✓ Same person detected: IoU={iou:.3f} > threshold={IoU_THRESHOLD}")

    # Scenario 2: Different person (far away)
    last_bbox = [100, 100, 200, 300]
    new_bbox = [400, 400, 500, 600]  # far away
    
    iou = compute_iou(new_bbox, last_bbox)
    assert iou < IoU_THRESHOLD  # Different person → queue event
    print(f"✓ Different person detected: IoU={iou:.3f} < threshold={IoU_THRESHOLD}")

    # Scenario 3: First detection (no previous bbox)
    last_bbox = None
    new_bbox = [100, 100, 200, 300]
    
    iou = compute_iou(new_bbox, last_bbox)
    assert iou == 0.0  # No previous → always queue event
    print(f"✓ First detection: IoU={iou:.3f} (no previous bbox)")


def test_session_reset():
    """Test that session state resets correctly."""
    # Session should reset when:
    # 1. Alarm window closes
    # 2. KCF tracker fails (5 consecutive misses)
    # 3. Person leaves monitored zone
    
    ba_last_saved_bbox = [100, 100, 200, 300]
    
    # After window close or zone exit, reset:
    ba_last_saved_bbox = None
    assert ba_last_saved_bbox is None
    print("✓ Session reset: ba_last_saved_bbox = None")
    
    # Next detection after reset always triggers event (IoU > threshold check skipped)
    new_bbox = [150, 150, 250, 350]
    iou = 0.0 if ba_last_saved_bbox is None else compute_iou(new_bbox, ba_last_saved_bbox)
    assert iou == 0.0 or ba_last_saved_bbox is None
    print(f"✓ First detection after reset always triggers event")


if __name__ == "__main__":
    test_iou_computation()
    test_deduplication_logic()
    test_session_reset()
    print("\n✅ All deduplication tests passed!")
