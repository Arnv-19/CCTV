"""
train_gloves.py
---------------
Fine-tune YOLOv8n to detect gloves / no_gloves for PPE compliance.

Usage
-----
1. Get a dataset (two options below — pick one):

   Option A — Roboflow public dataset (recommended, free):
       pip install roboflow
       Then fill in RF_API_KEY, RF_WORKSPACE, RF_PROJECT, RF_VERSION below.

   Option B — bring your own dataset:
       Arrange images + YOLO-format labels under data/gloves_dataset/:
           data/gloves_dataset/
               train/images/   train/labels/
               valid/images/   valid/labels/
               data.yaml       ← must list nc, names, train/val paths

2. Run:
       .venv/bin/python train_gloves.py

3. After training, the best weights are saved to:
       weights/gloves_model.pt

4. Update config.yaml:
       model_path: weights/gloves_model.pt

5. Update data/class_names.yaml to match your dataset's class names exactly.
"""

from pathlib import Path
from ultralytics import YOLO
import shutil

# ── Configuration ──────────────────────────────────────────────────────────────

# Base model to fine-tune from (already in the project)
BASE_MODEL = "yolov8n.pt"

# Output path for the trained model
OUTPUT_WEIGHTS = Path("weights/gloves_model.pt")

# Training hyperparameters — keep epochs low for a quick test model
EPOCHS      = 30
IMG_SIZE    = 640
BATCH_SIZE  = 8   # reduce to 4 if you run out of RAM

# ── Option A: Roboflow dataset download ────────────────────────────────────────
USE_ROBOFLOW = False          # set True to download via Roboflow

RF_API_KEY   = "YOUR_API_KEY"   # get free key at roboflow.com
RF_WORKSPACE = "YOUR_WORKSPACE"
RF_PROJECT   = "gloves-detection"   # search roboflow.com/universe for a gloves dataset
RF_VERSION   = 1

# ── Option B: local dataset ────────────────────────────────────────────────────
LOCAL_DATA_YAML = "data/gloves_dataset/data.yaml"   # path to your data.yaml


# ── Download dataset (Option A) ────────────────────────────────────────────────

def download_roboflow_dataset() -> str:
    from roboflow import Roboflow
    rf = Roboflow(api_key=RF_API_KEY)
    project = rf.workspace(RF_WORKSPACE).project(RF_PROJECT)
    dataset = project.version(RF_VERSION).download("yolov8")
    return str(Path(dataset.location) / "data.yaml")


# ── Train ──────────────────────────────────────────────────────────────────────

def train():
    if USE_ROBOFLOW:
        print("[train] Downloading dataset from Roboflow...")
        data_yaml = download_roboflow_dataset()
    else:
        data_yaml = LOCAL_DATA_YAML
        if not Path(data_yaml).exists():
            print(f"[train] ERROR: dataset not found at {data_yaml}")
            print("        Either set USE_ROBOFLOW=True or place your dataset at that path.")
            return

    print(f"[train] Using dataset: {data_yaml}")
    print(f"[train] Fine-tuning {BASE_MODEL} for {EPOCHS} epochs...")

    model = YOLO(BASE_MODEL)
    results = model.train(
        data    = data_yaml,
        epochs  = EPOCHS,
        imgsz   = IMG_SIZE,
        batch   = BATCH_SIZE,
        project = "runs/gloves",
        name    = "train",
        exist_ok= True,
    )

    # Copy best weights to weights/
    best_pt = Path("runs/gloves/train/weights/best.pt")
    if best_pt.exists():
        OUTPUT_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(best_pt, OUTPUT_WEIGHTS)
        print(f"\n[train] Done! Model saved to: {OUTPUT_WEIGHTS}")
        print(f"[train] Update config.yaml → model_path: {OUTPUT_WEIGHTS}")
    else:
        print("[train] Training completed but best.pt not found. Check runs/gloves/train/weights/")


if __name__ == "__main__":
    train()
