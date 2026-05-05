
from typing import Optional

from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import (
    CameraModelAssignment, CameraClassConfig
)



# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    camera_id: int
    model_id: int
    is_enabled: bool = True
    confidence_threshold: Optional[float] = None


class AssignmentPatch(BaseModel):
    is_enabled: Optional[bool] = None
    confidence_threshold: Optional[float] = None


class ClassConfigPatch(BaseModel):
    is_active: bool


class BulkClassConfigItem(BaseModel):
    class_id: int
    is_active: bool


# ── Serialisers ───────────────────────────────────────────────────────────────

def _config_dict(cc: CameraClassConfig) -> dict:
    mc = cc.model_class
    return {
        "id":          cc.id,
        "class_id":    cc.class_id,
        "class_name":  mc.class_name if mc else None,
        "class_role":  mc.class_role if mc else None,
        "class_index": mc.class_index if mc else None,
        "is_active":   cc.is_active,
        "updated_at":  cc.updated_at,
    }


def _assignment_dict(a: CameraModelAssignment, include_classes: bool = False) -> dict:
    d = {
        "id":                   a.id,
        "camera_id":            a.camera_id,
        "model_id":             a.model_id,
        "model_name":           a.model.name if a.model else None,
        "model_display_name":   a.model.display_name if a.model else None,
        "weight_path":          a.model.weight_path if a.model else None,
        "is_enabled":           a.is_enabled,
        "confidence_threshold": a.confidence_threshold,
        "assigned_at":          a.assigned_at,
    }
    if include_classes:
        d["class_configs"] = [_config_dict(cc) for cc in a.class_configs]
    return d

