"""
app/schemas/employee_schemas.py
--------------------------------
Pydantic schemas for the employee face-recognition enrollment subsystem.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Employee creation / update ───────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    name:        str = Field(..., min_length=1, max_length=128, description="Full display name")
    department:  Optional[str] = Field(None, max_length=128, description="Organisational unit")
    employee_id: str = Field(..., min_length=1, max_length=64, description="Unique HR badge / payroll ID")


# ─── Output schemas ───────────────────────────────────────────────────────────

class EmployeeOut(BaseModel):
    id:          int
    name:        str
    department:  Optional[str]
    employee_id: str
    photo_path:  Optional[str]
    is_enrolled: bool
    enrolled_at: Optional[datetime]
    created_at:  datetime
    updated_at:  datetime

    model_config = {"from_attributes": True}


class EmployeeListItem(BaseModel):
    """Lightweight list view — no embeddings, no photo path."""
    id:          int
    name:        str
    department:  Optional[str]
    employee_id: str
    is_enrolled: bool
    enrolled_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ─── Enrollment responses ─────────────────────────────────────────────────────

class EnrollmentResult(BaseModel):
    message:        str
    employee_id:    str
    faces_detected: int
    aug_embeddings: int   # number of augmented variants stored


class SelectFaceRequest(BaseModel):
    face_index: int = Field(..., ge=0, description="0-based index of the face to select (sorted left-to-right)")


class SelectFaceResult(BaseModel):
    message:        str
    employee_id:    str
    face_index:     int
    total_faces:    int
    aug_embeddings: int


# ─── Camera face config (§4.3) ────────────────────────────────────────────────

# Valid values for face_detection_mode
_VALID_FACE_MODES = {"standard", "long_range"}

class FaceConfigPatch(BaseModel):
    face_detection_enabled: Optional[bool] = None
    face_detection_mode:    Optional[str]  = None

    model_config = {"json_schema_extra": {"example": {"face_detection_enabled": True, "face_detection_mode": "standard"}}}

    def model_post_init(self, __context) -> None:
        if self.face_detection_mode is not None and self.face_detection_mode not in _VALID_FACE_MODES:
            raise ValueError(f"face_detection_mode must be one of: {sorted(_VALID_FACE_MODES)}")


class FaceConfigOut(BaseModel):
    camera_id:              int
    face_detection_enabled: bool
    face_detection_mode:    str


# ─── Bulk enroll response ─────────────────────────────────────────────────────

class BulkEnrollResult(BaseModel):
    total:   int
    success: int
    failed:  int
    errors:  List[str]
