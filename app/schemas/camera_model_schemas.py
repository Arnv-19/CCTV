from pydantic import BaseModel
from app.db.models.camera_model   import CameraModel


class ModelToggle(BaseModel):
    model_name: str
    is_enabled: bool = True


class ModelPatch(BaseModel):
    is_enabled: bool | None = None


def _row_dict(r: CameraModel) -> dict:
    return {
        "id":         r.id,
        "camera_id":  r.camera_id,
        "model_name": r.model_name,
        "is_enabled": r.is_enabled,
        "updated_at": r.updated_at,
    }
