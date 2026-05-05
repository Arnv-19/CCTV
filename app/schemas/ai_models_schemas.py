

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.db.models import AIModel, ModelClass



# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AIModelCreate(BaseModel):
    name: str
    display_name: str
    weight_path: str
    model_type: str = "yolov8"
    yolo_imgsz: int = 640
    confidence_threshold: float = 0.25
    description: Optional[str] = None
    is_active: bool = True


class AIModelUpdate(BaseModel):
    display_name: Optional[str] = None
    weight_path: Optional[str] = None
    model_type: Optional[str] = None
    yolo_imgsz: Optional[int] = None
    confidence_threshold: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ModelClassCreate(BaseModel):
    class_index: int
    class_name: str
    class_role: str = "neutral"       # "violation" | "safe" | "neutral"
    display_color: str = "#FFFFFF"
    trigger_alert: bool = False


class ModelClassUpdate(BaseModel):
    class_name: Optional[str] = None
    class_role: Optional[str] = None
    display_color: Optional[str] = None
    trigger_alert: Optional[bool] = None


# ── Serialisers ───────────────────────────────────────────────────────────────

def _class_dict(c: ModelClass) -> dict:
    return {
        "id":            c.id,
        "model_id":      c.model_id,
        "class_index":   c.class_index,
        "class_name":    c.class_name,
        "class_role":    c.class_role,
        "display_color": c.display_color,
        "trigger_alert": c.trigger_alert,
    }


def _model_dict(m: AIModel, include_classes: bool = False) -> dict:
    d = {
        "id":                   m.id,
        "name":                 m.name,
        "display_name":         m.display_name,
        "weight_path":          m.weight_path,
        "model_type":           m.model_type,
        "yolo_imgsz":           m.yolo_imgsz,
        "confidence_threshold": m.confidence_threshold,
        "description":          m.description,
        "is_active":            m.is_active,
        "created_at":           m.created_at,
        "class_count":          len(m.classes),
    }
    if include_classes:
        d["classes"] = [_class_dict(c) for c in m.classes]
    return d
