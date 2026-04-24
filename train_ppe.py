"""
train_ppe.py
------------
Train/fine-tune a YOLO model for PPE detection and save weights/ppe_model.pt.

Examples
--------
1) Train from your local PPE dataset:
   .venv/bin/python train_ppe.py --data data/ppe_dataset/data.yaml

2) Train using the helmet dataset path embedded in helmet_model.pt metadata:
   .venv/bin/python train_ppe.py --data /home/skyai/Factory_Automation/no_helmet/data.yaml

Notes
-----
- Default base model is weights/ppe_model.pt to preserve existing PPE knowledge.
- If you train with a helmet-only dataset (e.g. hat/no_hat), the model will only
    strengthen those classes and can forget others unless PPE data is mixed in.
"""

from pathlib import Path
import argparse
import shutil

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train PPE YOLO model")
    parser.add_argument("--data", required=True, help="Path to dataset data.yaml")
    parser.add_argument("--base-model", default="weights/ppe_model.pt", help="Base model to fine-tune")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--project", default="runs/ppe", help="Ultralytics project dir")
    parser.add_argument("--name", default="train", help="Ultralytics run name")
    parser.add_argument(
        "--output",
        default="weights/ppe_model.pt",
        help="Destination path for best model weights",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        raise FileNotFoundError(f"Dataset yaml not found: {data_yaml}")

    print(f"[train] dataset: {data_yaml}")
    print(f"[train] base model: {args.base_model}")

    model = YOLO(args.base_model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=args.project,
        name=args.name,
        exist_ok=True,
    )

    best_pt = Path(args.project) / args.name / "weights" / "best.pt"
    output = Path(args.output)
    if not best_pt.exists():
        raise FileNotFoundError(f"Training ended but best.pt not found at: {best_pt}")

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(best_pt, output)

    print(f"[train] done: {output}")
    print("[train] update config.yaml -> ppe_model_path to this file if needed")


if __name__ == "__main__":
    main()
