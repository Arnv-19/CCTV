"""
app/services/face_service.py
-----------------------------
Singleton service wrapping InsightFace for face detection, embedding extraction,
and cosine-similarity identification.

Also provides a data-augmentation pipeline (albumentations) that generates
8 variant embeddings per enrolled photo to improve recognition accuracy under
real-world CCTV conditions (lighting variation, partial occlusion, angle drift).

Model
-----
Uses InsightFace's ``buffalo_l`` analysis pack (ArcFace ResNet-100 backbone,
SCRFD detector). Weights are auto-downloaded to ``~/.insightface/models/``
on first call.

GPU/CPU
-------
Auto-detects CUDA. Set env var ``FACE_CTX_ID=-1`` to force CPU.

Augmentation pipeline (albumentations)
---------------------------------------
For each enrolled photo, 8 augmented variants are generated and embedded:
  1. Horizontal flip
  2. Random brightness/contrast
  3. Gaussian blur
  4. Slight rotation (±10°)
  5. CLAHE histogram equalisation
  6. RGB channel shift
  7. JPEG compression artefact simulation
  8. Combined brightness + rotation
"""

import io
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ─── Lazy imports so the server starts even without the optional packages ────

def _import_insightface():
    try:
        import insightface
        from insightface.app import FaceAnalysis
        return FaceAnalysis
    except ImportError as exc:
        raise RuntimeError(
            "insightface is not installed. Run: pip install insightface onnxruntime"
        ) from exc


def _import_albumentations():
    try:
        import albumentations as A
        return A
    except ImportError as exc:
        raise RuntimeError(
            "albumentations is not installed. Run: pip install albumentations"
        ) from exc


# ─── Constants ───────────────────────────────────────────────────────────────

_FACE_MODEL_NAME  = os.getenv("FACE_MODEL_NAME", "buffalo_l")
_CTX_ID           = int(os.getenv("FACE_CTX_ID", "0"))          # 0 = GPU:0, -1 = CPU
_DET_SIZE         = (640, 640)
_SIMILARITY_THRESH = float(os.getenv("FACE_SIMILARITY_THRESH", "0.45"))  # cosine sim ≥ this → match
_NUM_AUG_VARIANTS = 8   # augmented embeddings stored per enrolment


# ─── Augmentation pipeline ───────────────────────────────────────────────────

def _build_aug_pipeline():
    """Return list of albumentations transforms (one per augmentation variant)."""
    A = _import_albumentations()

    return [
        # 1. Horizontal flip
        A.Compose([A.HorizontalFlip(p=1.0)]),

        # 2. Brightness + contrast
        A.Compose([A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=1.0)]),

        # 3. Gaussian blur
        A.Compose([A.GaussianBlur(blur_limit=(3, 5), p=1.0)]),

        # 4. Rotation ±10°
        A.Compose([A.Rotate(limit=10, border_mode=cv2.BORDER_REFLECT_101, p=1.0)]),

        # 5. CLAHE histogram equalisation
        A.Compose([A.CLAHE(clip_limit=2.0, p=1.0)]),

        # 6. RGB channel shift
        A.Compose([A.RGBShift(r_shift_limit=15, g_shift_limit=15, b_shift_limit=15, p=1.0)]),

        # 7. JPEG compression artefacts
        A.Compose([A.ImageCompression(quality_lower=70, quality_upper=95, p=1.0)]),

        # 8. Combined: brightness + rotation
        A.Compose([
            A.RandomBrightnessContrast(brightness_limit=0.15, contrast_limit=0.1, p=1.0),
            A.Rotate(limit=8, border_mode=cv2.BORDER_REFLECT_101, p=1.0),
        ]),
    ]


# ─── FaceService ─────────────────────────────────────────────────────────────

class FaceService:
    """
    Lazily-initialised singleton for InsightFace operations.

    Call ``FaceService.get()`` to obtain the shared instance.
    The InsightFace model is only downloaded/loaded on the first call.
    """

    _instance: Optional["FaceService"] = None

    def __init__(self):
        FaceAnalysis = _import_insightface()
        ctx = _CTX_ID
        logger.info("[FaceService] Loading InsightFace model '%s' ctx=%d …", _FACE_MODEL_NAME, ctx)
        self._app = FaceAnalysis(name=_FACE_MODEL_NAME, providers=self._providers(ctx))
        self._app.prepare(ctx_id=ctx, det_size=_DET_SIZE)
        self._aug_transforms = _build_aug_pipeline()
        logger.info("[FaceService] Ready.")

    @staticmethod
    def _providers(ctx_id: int) -> list:
        """Return ONNX execution providers based on ctx_id."""
        if ctx_id >= 0:
            try:
                import onnxruntime as ort
                available = ort.get_available_providers()
                if "CUDAExecutionProvider" in available:
                    return ["CUDAExecutionProvider", "CPUExecutionProvider"]
            except Exception:
                pass
        return ["CPUExecutionProvider"]

    @classmethod
    def get(cls) -> "FaceService":
        """Return the shared singleton, initialising on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Face detection ────────────────────────────────────────────────────────

    def detect_faces(self, img_bgr: np.ndarray) -> list:
        """
        Detect all faces in the image.

        Returns a list of InsightFace ``Face`` objects, each with attributes:
          .bbox        — [x1, y1, x2, y2]
          .det_score   — detection confidence
          .embedding   — 512-d ArcFace embedding (numpy float32 array)
          .landmark_2d_106 — facial landmark points
        """
        return self._app.get(img_bgr)

    # ── Embedding extraction ──────────────────────────────────────────────────

    def get_embedding(
        self,
        img_bgr: np.ndarray,
        face_index: int = 0,
    ) -> Optional[np.ndarray]:
        """
        Extract a 512-d embedding for the face at ``face_index`` in the image.
        Faces are sorted by bounding-box area (largest first).

        Returns None if no face is detected.
        """
        faces = self.detect_faces(img_bgr)
        if not faces:
            return None
        # Sort by area descending
        faces_sorted = sorted(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            reverse=True,
        )
        if face_index >= len(faces_sorted):
            return None
        return faces_sorted[face_index].embedding  # shape (512,) float32

    def select_face_by_index(
        self,
        img_bgr: np.ndarray,
        index: int,
    ) -> Tuple[Optional[np.ndarray], int]:
        """
        Return the embedding for the face at ``index`` in a group photo.
        Faces sorted left-to-right by x1 coordinate.

        Returns (embedding, total_face_count).
        If index is out of range, returns (None, total_face_count).
        """
        faces = self.detect_faces(img_bgr)
        if not faces:
            return None, 0
        faces_sorted = sorted(faces, key=lambda f: f.bbox[0])
        if index >= len(faces_sorted):
            return None, len(faces_sorted)
        return faces_sorted[index].embedding, len(faces_sorted)

    # ── Augmentation pipeline ─────────────────────────────────────────────────

    def augment_and_embed(self, img_bgr: np.ndarray) -> List[List[float]]:
        """
        Apply each augmentation transform to ``img_bgr``, detect the face,
        and return the list of 512-d embeddings as plain Python float lists.

        Skips augmentation variants where no face is detected (e.g. extreme crop).
        """
        augmented_embeddings: List[List[float]] = []

        # Convert to RGB for albumentations (it expects RGB)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        for transform in self._aug_transforms:
            try:
                result = transform(image=img_rgb)
                aug_rgb = result["image"]
                aug_bgr = cv2.cvtColor(aug_rgb, cv2.COLOR_RGB2BGR)
                emb = self.get_embedding(aug_bgr, face_index=0)
                if emb is not None:
                    augmented_embeddings.append(emb.tolist())
            except Exception as exc:
                logger.warning("[FaceService] Augmentation variant skipped: %s", exc)

        return augmented_embeddings

    # ── Identification ────────────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity in [-1, 1]. Higher = more similar."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def find_best_match(
        self,
        query_embedding: np.ndarray,
        employees: list,
        threshold: float = _SIMILARITY_THRESH,
    ) -> Tuple[Optional[object], float]:
        """
        Search ``employees`` (list of Employee ORM objects) for the closest
        face match to ``query_embedding``.

        Compares against the primary embedding first, then all augmented
        variants. Uses the maximum score per employee.

        Returns ``(employee, best_score)`` if score >= threshold, else
        ``(None, best_score)``.
        """
        best_emp   = None
        best_score = -1.0

        for emp in employees:
            if not emp.is_enrolled or emp.embedding is None:
                continue

            scores = []

            # Primary embedding
            primary = np.array(emp.embedding, dtype=np.float32)
            scores.append(self.cosine_similarity(query_embedding, primary))

            # Augmented embeddings
            if emp.embedding_aug:
                for aug_vec in emp.embedding_aug:
                    aug = np.array(aug_vec, dtype=np.float32)
                    scores.append(self.cosine_similarity(query_embedding, aug))

            score = max(scores)
            if score > best_score:
                best_score = score
                best_emp   = emp

        if best_score >= threshold:
            return best_emp, best_score
        return None, best_score

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def decode_image(file_bytes: bytes) -> np.ndarray:
        """Decode raw image bytes (any format OpenCV supports) to a BGR ndarray."""
        arr = np.frombuffer(file_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image — unsupported format or corrupt file.")
        return img
