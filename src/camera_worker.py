import cv2
import time
import os
from datetime import datetime
from src.alarm import send_buzzer_command
from src.helmet_detector import run_detection, load_model, load_class_names

RESIZE_DIM = (640, 480)

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def log_violation(cam_id, violation_count):
    ensure_dir("logs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("logs/alerts.log", "a") as f:
        f.write(
            f"[{now}] Camera {cam_id} | Violations in frame: {violation_count}\n")

def save_violation_images(frame, detection, cam_id, frame_count, violation_index):
    try:
        output_dir = "violations"
        ensure_dir(output_dir)
        x1, y1, x2, y2 = map(int, detection['box'])
        cropped_image = frame[y1:y2, x1:x2]
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(output_dir, f"cam{cam_id}_{now}_frame{frame_count}_viol{violation_index}.jpg")
        cv2.imwrite(filename, cropped_image)
    except Exception as e:
        print(f"🔴 [ERROR] Cam {cam_id}: Could not save violation image: {e}")

def camera_loop(cam_id, stream_url, config, frame_dict, lock, stop_event):
    
    # --- Load model and settings inside the thread ---
    print(f"[INFO] Thread {cam_id} started. Loading model...")
    try:
        model = load_model(config['model_path'])
        _, helmet_class, no_helmet_class = load_class_names(config['class_file'])
        threshold = config['confidence_threshold']
        cooldown = config.get('alarm_cooldown_sec', 5)
        use_wifi = config.get('use_wifi', False)
        esp_ip = config.get('esp_ip', None)
        print(f"[INFO] Thread {cam_id}: Model loaded successfully.")
    except Exception as e:
        print(f"🔴 [FATAL] Thread {cam_id} failed to initialize: {e}")
        return # Exit the thread if setup fails

    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        print(f"❌ [ERROR] Cannot open camera {cam_id} at {stream_url}")
        return

    frame_count = 0
    last_image_save_time = 0
    buzzer_is_on = False

    # --- Check stop_event in the main loop ---
    while not stop_event.is_set():
        try:
            ret, frame = cap.read()
            if not ret:
                print(f"⚠ [WARNING] Camera {cam_id} disconnected. Retrying...")
                time.sleep(2)
                cap.release()
                cap = cv2.VideoCapture(stream_url)
                continue

            frame_count += 1
            start_time = time.time()
            resized = cv2.resize(frame, RESIZE_DIM)

            detections = run_detection(model, resized, threshold)

            current_violations = [det for det in detections if det['class'] == no_helmet_class]
            no_of_violations = len(current_violations)
            violation_in_frame = no_of_violations > 0

            if violation_in_frame:
                if not buzzer_is_on:
                    print(f"[ALARM ON] No helmet detected on Camera {cam_id}")
                    send_buzzer_command(True, use_wifi, esp_ip)
                    buzzer_is_on = True

                current_time = time.time()
                if current_time - last_image_save_time > cooldown:
                    log_violation(cam_id, no_of_violations)
                    for index, det in enumerate(current_violations):
                        save_violation_images(resized, det, cam_id, frame_count, index + 1)
                    last_image_save_time = current_time
            else:
                if buzzer_is_on:
                    print(f"[ALARM OFF] Violations cleared on Camera {cam_id}")
                    send_buzzer_command(False, use_wifi, esp_ip)
                    buzzer_is_on = False

            # Draw bounding boxes
            for det in detections:
                x1, y1, x2, y2 = map(int, det['box'])
                class_name = det['class']
                label = f"{class_name.upper()} {det['conf']:.2f}"
                color = (0, 255, 0) if class_name == helmet_class else (0, 0, 255)
                cv2.rectangle(resized, (x1, y1), (x2, y2), color, 2)
                cv2.putText(resized, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            fps = 1 / (time.time() - start_time)
            stat = f"Cam {cam_id} | FPS: {fps:.2f} | Violations: {no_of_violations}"
            cv2.putText(resized, stat, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            
            with lock:
                frame_dict[cam_id] = resized.copy()

        # --- Add exception handling inside the loop ---
        except Exception as e:
            print(f"🔴 [ERROR] An error occurred in camera_loop for Cam {cam_id}: {e}")
            time.sleep(5) # Wait before retrying to avoid spamming errors

    print(f"[INFO] Thread {cam_id} received stop signal. Cleaning up.")
    cap.release()