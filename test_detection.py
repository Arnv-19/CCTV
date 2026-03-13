"""
test_detection.py
-----------------
Captures one frame from the webcam and prints all detections with confidence
scores. Useful for diagnosing why a class isn't being detected.

Run:
    .venv/bin/python test_detection.py
"""

import cv2
from ultralytics import YOLO

MODEL_PATH = "weights/ppe_model.pt"
CONFIDENCE = 0.1   # very low threshold to surface weak detections too
SOURCE     = 0     # webcam index

model = YOLO(MODEL_PATH)
cap   = cv2.VideoCapture(SOURCE)

print("Press SPACE to capture a frame, Q to quit.")
while True:
    ret, frame = cap.read()
    if not ret:
        print("Could not read frame.")
        break

    cv2.imshow("Press SPACE to test", frame)
    key = cv2.waitKey(1) & 0xFF

    if key == ord(' '):
        results = model.predict(frame, conf=CONFIDENCE, verbose=False)[0]
        print(f"\n{'─'*50}")
        print(f"{'Class':<25} {'Confidence':>10}")
        print(f"{'─'*50}")
        if len(results.boxes) == 0:
            print("No detections at all (even at conf=0.1)")
        for box in results.boxes.data:
            x1, y1, x2, y2, conf, cls = box.tolist()
            name = results.names[int(cls)]
            print(f"{name:<25} {conf:>10.3f}")
        print(f"{'─'*50}\n")

    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
