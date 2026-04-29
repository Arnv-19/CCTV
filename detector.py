"""
detector.py
-----------
YOLOv8 model loader and inference wrapper.

All camera threads share a single loaded model instance to avoid duplicating
GPU/CPU memory. Call load_model() once at startup, then pass the model object
to run_detection() from any thread (ultralytics YOLO is thread-safe for inference).
"""

from ultralytics import YOLO
import yaml
import threading


# Shared YOLO instances are used across camera threads.
# Guard predict() to avoid internal race conditions in model warmup/fusion.
_PREDICT_LOCK = threading.Lock()


def load_model(model_path: str) -> YOLO:
    """Load a YOLOv8 model from the given .pt weights file."""
    model = YOLO(model_path)
    # Uncomment the line below to force GPU inference:
    # model.to('cuda')
    return model


def load_class_names(path: str) -> tuple[list, str, str, list, list]:
    """
    Read class names and PPE label keys from a YAML file.

    Expected YAML format:
        names: {0: hats, 1: no_hats, 2: gloves, 3: no_gloves}
        helmet_class: hats
        no_helmet_class: no_hats
        violation_classes: [no_hats, no_gloves]
        safe_classes: [hats, gloves]
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    names = data.get("names", {})
    if isinstance(names, dict):
        names = list(names.values())
    helmet_class    = data.get("helmet_class", "")
    no_helmet_class = data.get("no_helmet_class", "")
    violation_classes = data.get(
        "violation_classes", [no_helmet_class] if no_helmet_class else []
    )
    safe_classes = data.get(
        "safe_classes", [helmet_class] if helmet_class else []
    )
    return names, helmet_class, no_helmet_class, violation_classes, safe_classes


def run_detection(model: YOLO, frame, confidence: float, imgsz: int | None = None) -> list[dict]:
    """
    Run YOLOv8 inference on a single BGR frame (numpy array).

    Returns a list of detection dicts:
        {id, box: [x1,y1,x2,y2], conf: float, class: str}

    Detections with class name 'ignore' are filtered out.
    """
    # stream=False: process a single frame, not a generator
    # verbose=False: suppress per-frame console output from ultralytics
    try:
        with _PREDICT_LOCK:
            kwargs = {
                "source": frame,
                "conf": confidence,
                "stream": False,
                "verbose": False,
            }
            if imgsz:
                kwargs["imgsz"] = int(imgsz)
            results = model.predict(**kwargs)[0]
    except AttributeError as e:
        # Ultralytics internals can throw AttributeError("bn") if predict is
        # called concurrently while layers are being fused/warmed.
        print(f"[detector] Inference AttributeError: {e}")
        return []
    except Exception as e:
        print(f"[detector] Inference error: {e}")
        return []

    detections = []
    for i, box in enumerate(results.boxes.data):
        x1, y1, x2, y2, conf, cls = box.tolist()
        class_name = results.names[int(cls)]

        # Skip the 'ignore' class (used for ambiguous or partial detections)
        if class_name == "ignore":
            continue

        detections.append({
            "id": i,
            "box": [x1, y1, x2, y2],
            "conf": conf,
            "class": class_name,
        })

    return detections
