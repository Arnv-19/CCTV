"""
app/api/routes/ai_models.py
----------------------------
CRUD for the AI model registry and per-model class definitions.

Endpoints:
  GET    /api/ai-models/                         List all models
  POST   /api/ai-models/                         Create a model
  GET    /api/ai-models/{id}                     Get model with full class list
  PUT    /api/ai-models/{id}                     Update model fields
  DELETE /api/ai-models/{id}                     Delete model (cascades classes + camera assignments)
  POST   /api/ai-models/{id}/classes             Add a class to a model
  PUT    /api/ai-models/{id}/classes/{class_id}  Update a class
  DELETE /api/ai-models/{id}/classes/{class_id}  Delete a class
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.db.models import AIModel, ModelClass, User
from app.dependencies import get_current_user, require_admin
from app.schemas.ai_models_schemas import (
    AIModelCreate, AIModelUpdate, ModelClassCreate, ModelClassUpdate,_model_dict, _class_dict
)
router = APIRouter()


# # ── Pydantic schemas ──────────────────────────────────────────────────────────

# class AIModelCreate(BaseModel):
#     name: str
#     display_name: str
#     weight_path: str
#     model_type: str = "yolov8"
#     yolo_imgsz: int = 640
#     confidence_threshold: float = 0.25
#     description: Optional[str] = None
#     is_active: bool = True


# class AIModelUpdate(BaseModel):
#     display_name: Optional[str] = None
#     weight_path: Optional[str] = None
#     model_type: Optional[str] = None
#     yolo_imgsz: Optional[int] = None
#     confidence_threshold: Optional[float] = None
#     description: Optional[str] = None
#     is_active: Optional[bool] = None


# class ModelClassCreate(BaseModel):
#     class_index: int
#     class_name: str
#     class_role: str = "neutral"       # "violation" | "safe" | "neutral"
#     display_color: str = "#FFFFFF"
#     trigger_alert: bool = False


# class ModelClassUpdate(BaseModel):
#     class_name: Optional[str] = None
#     class_role: Optional[str] = None
#     display_color: Optional[str] = None
#     trigger_alert: Optional[bool] = None


# # ── Serialisers ───────────────────────────────────────────────────────────────

# def _class_dict(c: ModelClass) -> dict:
#     return {
#         "id":            c.id,
#         "model_id":      c.model_id,
#         "class_index":   c.class_index,
#         "class_name":    c.class_name,
#         "class_role":    c.class_role,
#         "display_color": c.display_color,
#         "trigger_alert": c.trigger_alert,
#     }


# def _model_dict(m: AIModel, include_classes: bool = False) -> dict:
#     d = {
#         "id":                   m.id,
#         "name":                 m.name,
#         "display_name":         m.display_name,
#         "weight_path":          m.weight_path,
#         "model_type":           m.model_type,
#         "yolo_imgsz":           m.yolo_imgsz,
#         "confidence_threshold": m.confidence_threshold,
#         "description":          m.description,
#         "is_active":            m.is_active,
#         "created_at":           m.created_at,
#         "class_count":          len(m.classes),
#     }
#     if include_classes:
#         d["classes"] = [_class_dict(c) for c in m.classes]
#     return d


# ── Model endpoints ───────────────────────────────────────────────────────────

@router.get("/")
def list_models(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List every registered AI model (without class details)."""
    models = db.query(AIModel).order_by(AIModel.id).all()
    return [_model_dict(m) for m in models]


@router.post("/")
def create_model(
    body: AIModelCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Register a new AI model weight file."""
    if db.query(AIModel).filter(AIModel.name == body.name).first():
        raise HTTPException(409, f"Model name '{body.name}' already exists")
    m = AIModel(**body.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return _model_dict(m, include_classes=True)


@router.get("/{model_id}")
def get_model(
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return one model with its full class list."""
    m = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    return _model_dict(m, include_classes=True)


@router.put("/{model_id}")
def update_model(
    model_id: int,
    body: AIModelUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update any field on a model (patch-style — only send fields you want to change)."""
    m = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    db.commit()
    return _model_dict(m, include_classes=True)


@router.delete("/{model_id}")
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Delete a model.
    CASCADE removes: model_classes → camera_class_configs,
                     camera_model_assignments → camera_class_configs.
    """
    m = db.query(AIModel).filter(AIModel.id == model_id).first()
    if not m:
        raise HTTPException(404, "Model not found")
    db.delete(m)
    db.commit()
    return {"message": "Model deleted"}


# ── Class endpoints ───────────────────────────────────────────────────────────

@router.post("/{model_id}/classes")
def add_class(
    model_id: int,
    body: ModelClassCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Add a detectable class to a model."""
    if not db.query(AIModel).filter(AIModel.id == model_id).first():
        raise HTTPException(404, "Model not found")
    c = ModelClass(model_id=model_id, **body.model_dump())
    db.add(c)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "class_index or class_name already exists for this model")
    db.refresh(c)
    return _class_dict(c)


@router.put("/{model_id}/classes/{class_id}")
def update_class(
    model_id: int,
    class_id: int,
    body: ModelClassUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update a class definition (name, role, color, alert flag)."""
    c = db.query(ModelClass).filter(
        ModelClass.id == class_id,
        ModelClass.model_id == model_id,
    ).first()
    if not c:
        raise HTTPException(404, "Class not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    return _class_dict(c)


@router.delete("/{model_id}/classes/{class_id}")
def delete_class(
    model_id: int,
    class_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Delete a class.
    CASCADE removes all camera_class_configs rows that reference this class.
    """
    c = db.query(ModelClass).filter(
        ModelClass.id == class_id,
        ModelClass.model_id == model_id,
    ).first()
    if not c:
        raise HTTPException(404, "Class not found")
    db.delete(c)
    db.commit()
    return {"message": "Class deleted"}
