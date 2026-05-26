"""
app/api/routes/employees.py
----------------------------
Employee face-recognition enrollment endpoints.

All write endpoints require Admin JWT. Read endpoints accept any valid token.

Endpoints
---------
GET    /api/employees/                 List all employees with enrollment status
POST   /api/employees/                 Create employee record (no photo yet)
DELETE /api/employees/{id}             Remove employee and all stored embeddings
POST   /api/employees/{id}/enroll      Upload photo, detect face, store embedding
                                        + 8 augmented embeddings
POST   /api/employees/{id}/enroll/select  Select face from group photo by 0-based index
GET    /api/employees/{id}/photo       Serve the enrolled photo file
POST   /api/employees/bulk-enroll      Bulk import via CSV (name, department, employee_id)
                                        + ZIP of photos named <employee_id>.jpg

Notes
-----
- Photos are stored under  data/employee_photos/<employee_id>/enrolled.jpg
- Embeddings (primary + augmented) are stored as JSON in the employees table.
- The InsightFace model is loaded lazily on first enrollment request.
"""

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Employee, User
from app.dependencies import get_current_user, require_admin
from app.schemas.employee_schemas import (
    BulkEnrollResult,
    EmployeeCreate,
    EmployeeListItem,
    EmployeeOut,
    EnrollmentResult,
    SelectFaceRequest,
    SelectFaceResult,
)
from app.services.face_service import FaceService

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Photo storage root ────────────────────────────────────────────────────────
_PHOTO_ROOT = Path("data") / "employee_photos"


def _photo_dir(employee_id: str) -> Path:
    return _PHOTO_ROOT / employee_id


def _photo_path(employee_id: str) -> Path:
    return _photo_dir(employee_id) / "enrolled.jpg"


def _save_photo(employee_id: str, image_bytes: bytes) -> str:
    """Write photo bytes to disk; return the path string."""
    dest = _photo_path(employee_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image_bytes)
    return str(dest)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/employees/  — list all employees
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[EmployeeListItem])
def list_employees(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return all employee records with their enrollment status."""
    return db.query(Employee).order_by(Employee.id).all()


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/employees/  — create employee record
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Create a new employee record.
    No photo is required at this stage — enrollment is done separately.
    """
    if db.query(Employee).filter(Employee.employee_id == body.employee_id).first():
        raise HTTPException(
            status_code=409,
            detail=f"Employee ID '{body.employee_id}' already exists",
        )
    emp = Employee(
        name=body.name,
        department=body.department,
        employee_id=body.employee_id,
        is_enrolled=False,
    )
    try:
        db.add(emp)
        db.commit()
        db.refresh(emp)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Employee ID '{body.employee_id}' already exists")
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not create employee: {exc}") from exc
    return emp


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/employees/{id}  — remove employee and all embeddings
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{employee_db_id}", status_code=status.HTTP_200_OK)
def delete_employee(
    employee_db_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Remove an employee record together with their stored photo and all embeddings.
    """
    emp = db.get(Employee, employee_db_id)
    if not emp:
        raise HTTPException(404, "Employee not found")

    # Remove photo from disk (best-effort)
    photo = _photo_path(emp.employee_id)
    try:
        if photo.exists():
            photo.unlink()
        if photo.parent.exists() and not any(photo.parent.iterdir()):
            photo.parent.rmdir()
    except Exception as exc:
        logger.warning("[employees] Could not delete photo file: %s", exc)

    try:
        db.delete(emp)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not delete employee: {exc}") from exc

    return {"message": f"Employee '{emp.name}' (ID: {emp.employee_id}) deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/employees/{id}/enroll  — upload photo, store embedding
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{employee_db_id}/enroll", response_model=EnrollmentResult)
async def enroll_employee(
    employee_db_id: int,
    photo: UploadFile = File(..., description="Portrait or close-up face photo (JPEG / PNG)"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Upload a photo for an employee, extract the primary InsightFace embedding,
    generate 8 augmented embeddings via the albumentations pipeline, and
    store everything in the database.

    The largest detected face is used as the primary embedding.
    """
    emp = db.get(Employee, employee_db_id)
    if not emp:
        raise HTTPException(404, "Employee not found")

    img_bytes = await photo.read()
    if not img_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    # Decode image
    try:
        svc = FaceService.get()
        img_bgr = svc.decode_image(img_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, f"Face service unavailable: {exc}") from exc

    # Extract primary embedding
    primary_emb = svc.get_embedding(img_bgr, face_index=0)
    if primary_emb is None:
        raise HTTPException(
            422,
            "No face detected in the uploaded photo. "
            "Please upload a clear portrait image.",
        )

    # Count all detected faces
    all_faces = svc.detect_faces(img_bgr)
    faces_detected = len(all_faces)

    # Generate augmented embeddings
    aug_embeddings = svc.augment_and_embed(img_bgr)

    # Save photo to disk
    photo_path_str = _save_photo(emp.employee_id, img_bytes)

    # Persist to DB
    emp.embedding     = primary_emb.tolist()
    emp.embedding_aug = aug_embeddings
    emp.photo_path    = photo_path_str
    emp.is_enrolled   = True
    emp.enrolled_at   = datetime.now(timezone.utc)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not save enrollment: {exc}") from exc

    return EnrollmentResult(
        message=f"Employee '{emp.name}' enrolled successfully",
        employee_id=emp.employee_id,
        faces_detected=faces_detected,
        aug_embeddings=len(aug_embeddings),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/employees/{id}/enroll/select  — select face from group photo
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{employee_db_id}/enroll/select", response_model=SelectFaceResult)
async def enroll_select_face(
    employee_db_id: int,
    body: SelectFaceRequest,
    photo: UploadFile = File(..., description="Group photo containing multiple faces"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Upload a group photo and select which face (by 0-based left-to-right index)
    belongs to the employee.

    Workflow:
      1. Upload the group photo.
      2. The API returns detected face count in the error if index is out of range.
      3. Re-call with the correct index to enroll.
    """
    emp = db.get(Employee, employee_db_id)
    if not emp:
        raise HTTPException(404, "Employee not found")

    img_bytes = await photo.read()
    if not img_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        svc = FaceService.get()
        img_bgr = svc.decode_image(img_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, f"Face service unavailable: {exc}") from exc

    selected_emb, total_faces = svc.select_face_by_index(img_bgr, body.face_index)

    if total_faces == 0:
        raise HTTPException(422, "No faces detected in the uploaded photo.")

    if selected_emb is None:
        raise HTTPException(
            422,
            f"Face index {body.face_index} is out of range — "
            f"{total_faces} face(s) detected (indices 0–{total_faces - 1}).",
        )

    # Build augmented embeddings on the cropped face region
    aug_embeddings = svc.augment_and_embed(img_bgr)

    # Save the group photo (or just the crop) as the enrollment reference
    photo_path_str = _save_photo(emp.employee_id, img_bytes)

    emp.embedding     = selected_emb.tolist()
    emp.embedding_aug = aug_embeddings
    emp.photo_path    = photo_path_str
    emp.is_enrolled   = True
    emp.enrolled_at   = datetime.now(timezone.utc)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not save enrollment: {exc}") from exc

    return SelectFaceResult(
        message=f"Employee '{emp.name}' enrolled from face index {body.face_index}",
        employee_id=emp.employee_id,
        face_index=body.face_index,
        total_faces=total_faces,
        aug_embeddings=len(aug_embeddings),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/employees/{id}/photo  — serve enrolled photo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{employee_db_id}/photo")
def get_employee_photo(
    employee_db_id: int,
    db: Session = Depends(get_db),
):
    """Serve the enrolled photo for an employee as a JPEG file.

    Note: No auth required — photos are display assets loaded by <img> tags
    in the browser, which cannot send JWT headers.
    """
    emp = db.get(Employee, employee_db_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    if not emp.is_enrolled or not emp.photo_path:
        raise HTTPException(404, "No enrolled photo for this employee")

    photo = Path(emp.photo_path)
    if not photo.exists():
        raise HTTPException(404, "Photo file not found on disk")

    return FileResponse(
        path=str(photo),
        media_type="image/jpeg",
        filename=f"{emp.employee_id}_enrolled.jpg",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/employees/bulk-enroll  — CSV + ZIP bulk import
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/bulk-enroll", response_model=BulkEnrollResult)
async def bulk_enroll(
    csv_file: UploadFile = File(
        ...,
        description="CSV with columns: name, department, employee_id",
    ),
    photos_zip: UploadFile = File(
        ...,
        description="ZIP of face photos named <employee_id>.jpg (or .png / .jpeg)",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Bulk import employees from a CSV file and enroll them from photos in a ZIP.

    CSV format (header row required)::

        name,department,employee_id
        John Smith,Engineering,EMP001
        Jane Doe,HR,EMP002

    ZIP format::

        photos.zip
        ├── EMP001.jpg
        ├── EMP002.jpg
        └── EMP003.png   ← .png and .jpeg extensions also accepted

    Employees in the CSV but without a matching photo are created but not enrolled.
    Employees already in the database are skipped (not updated).
    """
    csv_bytes  = await csv_file.read()
    zip_bytes  = await photos_zip.read()

    errors:  list[str] = []
    success: int = 0
    total:   int = 0

    # ── Parse CSV ──────────────────────────────────────────────────────────
    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        rows   = list(reader)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse CSV: {exc}") from exc

    required_cols = {"name", "employee_id"}
    if rows and not required_cols.issubset(set(rows[0].keys())):
        raise HTTPException(
            400,
            f"CSV must have columns: {sorted(required_cols)}. "
            f"Got: {list(rows[0].keys()) if rows else '(empty)'}",
        )

    # ── Index photos from ZIP ──────────────────────────────────────────────
    photo_map: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                stem = Path(name).stem          # "EMP001"
                ext  = Path(name).suffix.lower()
                if ext in {".jpg", ".jpeg", ".png"}:
                    photo_map[stem] = zf.read(name)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, f"Could not open ZIP: {exc}") from exc

    # ── Load FaceService lazily ────────────────────────────────────────────
    try:
        svc = FaceService.get()
    except RuntimeError as exc:
        raise HTTPException(503, f"Face service unavailable: {exc}") from exc

    # ── Process each CSV row ───────────────────────────────────────────────
    for row in rows:
        total += 1
        emp_id = (row.get("employee_id") or "").strip()
        name   = (row.get("name") or "").strip()
        dept   = (row.get("department") or "").strip() or None

        if not emp_id or not name:
            errors.append(f"Row {total}: 'name' and 'employee_id' are required — skipped")
            continue

        # Create or retrieve employee record
        emp = db.query(Employee).filter(Employee.employee_id == emp_id).first()
        if emp is None:
            emp = Employee(name=name, department=dept, employee_id=emp_id, is_enrolled=False)
            db.add(emp)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                errors.append(f"{emp_id}: duplicate employee_id — skipped")
                continue

        # Enroll from photo if available
        img_bytes = photo_map.get(emp_id)
        if img_bytes is None:
            errors.append(f"{emp_id}: no matching photo in ZIP — record created without enrollment")
            db.commit()
            continue

        try:
            img_bgr     = svc.decode_image(img_bytes)
            primary_emb = svc.get_embedding(img_bgr, face_index=0)

            if primary_emb is None:
                errors.append(f"{emp_id}: no face detected in photo — record created without enrollment")
                db.commit()
                continue

            aug_embeddings = svc.augment_and_embed(img_bgr)
            photo_path_str = _save_photo(emp_id, img_bytes)

            emp.embedding     = primary_emb.tolist()
            emp.embedding_aug = aug_embeddings
            emp.photo_path    = photo_path_str
            emp.is_enrolled   = True
            emp.enrolled_at   = datetime.now(timezone.utc)
            db.commit()
            success += 1

        except Exception as exc:
            db.rollback()
            errors.append(f"{emp_id}: enrollment failed — {exc}")

    return BulkEnrollResult(
        total=total,
        success=success,
        failed=total - success,
        errors=errors,
    )
