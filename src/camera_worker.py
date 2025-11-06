import cv2
import time
import os
import numpy as np
from datetime import datetime
from src.alarm import send_buzzer_command
from src.helmet_detector import run_detection

RESIZE_DIM = (640, 480)

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def log_violation(cam_id, violation_count):
    ensure_dir("logs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("logs/alerts.log", "a") as f:
        f.write(f"[{now}] Camera {cam_id} | HELMET VIOLATIONS: {violation_count}\n")

def log_person_entry(cam_id, person_id):
    ensure_dir("logs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("logs/person_alerts.log", "a") as f:
        f.write(f"[{now}] Camera {cam_id} | PERSON DETECTED IN ROI | ID: {person_id}\n")

def save_violation_images(frame, detection, cam_id, frame_count, violation_index):
    try:
        output_dir = "violations/helmet_violations"
        ensure_dir(output_dir)
        x1, y1, x2, y2 = map(int, detection['box'])
        # Ensure coordinates are within frame bounds
        h, w, _ = frame.shape
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        cropped_image = frame[y1:y2, x1:x2]
        if cropped_image.size > 0:
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = os.path.join(output_dir, f"cam{cam_id}_{now}_frame{frame_count}_viol{violation_index}.jpg")
            cv2.imwrite(filename, cropped_image)
    except Exception as e:
        print(f"🔴 [ERROR] Cam {cam_id}: Could not save helmet violation image: {e}")

def save_person_image(frame, box, track_id, cam_id, frame_count, person_index):
    """Saves a cropped image of a person detected in the ROI."""
    try:
        output_dir = "violations/person_violations"
        ensure_dir(output_dir)
        x1, y1, x2, y2 = map(int, box)

        # Ensure coordinates are within frame bounds
        h, w, _ = frame.shape
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        cropped_image = frame[y1:y2, x1:x2]
        if cropped_image.size > 0:
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = os.path.join(output_dir, f"cam{cam_id}_{now}_frame{frame_count}_person{track_id}_idx{person_index}.jpg")
            cv2.imwrite(filename, cropped_image)
    except Exception as e:
        print(f"🔴 [ERROR] Cam {cam_id}: Could not save person violation image: {e}")

def camera_loop(cam_id, stream_url, config, frame_dict, lock, thread_stop_events, 
                rois_state, roi_lock, helmet_model, person_model, 
                helmet_class, no_helmet_class):
    
    print(f"[INFO] Thread {cam_id} started.")
    try:
        threshold = config['confidence_threshold']
        cooldown = config.get('alarm_cooldown_sec', 5)
        person_image_cooldown = config.get('person_image_cooldown_sec', 30)
        use_wifi = config.get('use_wifi', False)
        esp_ip = config.get('esp_ip', None)
        print(f"[INFO] Thread {cam_id}: Configuration loaded.")
    except Exception as e:
        print(f"🔴 [FATAL] Thread {cam_id} configuration failed: {e}")
        return

    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        print(f"❌ [ERROR] Cannot open camera {cam_id} at {stream_url}")
        return

    frame_count = 0
    last_image_save_time = 0
    last_person_save_time = 0
    buzzer_is_on = False
    
    # Keep track of person IDs already logged for this session to avoid spamming
    logged_person_ids = set()

    while not thread_stop_events[cam_id].is_set():
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

            # --- Get the latest ROI for this camera ---
            with roi_lock:
                roi_np = rois_state.get(str(cam_id))

            helmet_detections = run_detection(helmet_model, resized, threshold)
            
            # Filter for violations (no_helmet) - No longer filtered by ROI
            current_violations = [det for det in helmet_detections if det['class'] == no_helmet_class]
            helmet_violation_active = len(current_violations) > 0

            person_in_roi_active = False
            current_person_ids_in_roi = set()
            person_boxes_in_roi = [] # --- To store boxes for saving images ---

            if roi_np is not None:
                # Run tracking. Class 0 is standard for 'person' in COCO models.
                # persist=True is crucial for keeping IDs consistent across frames.
                p_results = person_model.track(resized, persist=True, classes=[0], verbose=False, stream=False)[0]
                
                if p_results.boxes and p_results.boxes.id is not None:
                    # Extract boxes and IDs. Ensure they are on CPU and numpy format.
                    boxes = p_results.boxes.xyxy.cpu().numpy()
                    track_ids = p_results.boxes.id.int().cpu().tolist()

                    for box, track_id in zip(boxes, track_ids):
                        x1, y1, x2, y2 = box
                        # Check the feet (bottom center) for ROI inclusion for better accuracy
                        feet_point = (int((x1 + x2) / 2), int(y2))
                        
                        if cv2.pointPolygonTest(roi_np, feet_point, False) >= 0:
                            person_in_roi_active = True
                            current_person_ids_in_roi.add(track_id)
                            person_boxes_in_roi.append((box, track_id)) # --- Store box and ID ---

                            # Draw person box specifically if in ROI
                            cv2.rectangle(resized, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 255), 2)
                            cv2.putText(resized, f"ID: {track_id}", (int(x1), int(y1)-10), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

                            # Log if this is a new person entering the ROI
                            if track_id not in logged_person_ids:
                                print(f"[ALERT] New Person (ID {track_id}) entered ROI on Camera {cam_id}")
                                log_person_entry(cam_id, track_id)
                                logged_person_ids.add(track_id)

            alarm_needed = helmet_violation_active or person_in_roi_active
            current_time = time.time() # --- current_time idhar initilize krdiya dono checks ke liye ---

            if alarm_needed:
                if not buzzer_is_on:
                    reason = []
                    if helmet_violation_active: reason.append("NO HELMET")
                    if person_in_roi_active: reason.append("PERSON IN ROI")
                    print(f"[ALARM ON] Cam {cam_id} triggered by: {', '.join(reason)}")
                    send_buzzer_command(True, use_wifi, esp_ip)
                    buzzer_is_on = True

                # Handle Helmet Image Saving (Cooldown applies to saving images, not the buzzer)
                if helmet_violation_active and (current_time - last_image_save_time > cooldown):
                    log_violation(cam_id, len(current_violations))
                    for index, det in enumerate(current_violations):
                        save_violation_images(resized, det, cam_id, frame_count, index + 1)
                    last_image_save_time = current_time
                
                # --- Handle Person Image Saving ---
                if person_in_roi_active and (current_time - last_person_save_time > person_image_cooldown):
                    print(f"[INFO] Saving person violation images for Cam {cam_id}")
                    for index, (box, track_id) in enumerate(person_boxes_in_roi):
                        save_person_image(resized, box, track_id, cam_id, frame_count, index + 1)
                    last_person_save_time = current_time

            else:
                if buzzer_is_on:
                    print(f"[ALARM OFF] All cleared on Camera {cam_id}")
                    send_buzzer_command(False, use_wifi, esp_ip)
                    buzzer_is_on = False

            if roi_np is not None:
                color = (255, 0, 0) if not person_in_roi_active else (0, 0, 255) # Turn ROI red if person inside
                cv2.polylines(resized, [roi_np], isClosed=True, color=color, thickness=2)

            # Draw Helmet detections 
            for det in helmet_detections:
                class_name = det['class']
                
                # --- Only draw "no_helmet_class" ---
                if class_name == no_helmet_class:
                    x1, y1, x2, y2 = map(int, det['box'])
                    label = f"{class_name.upper()} {det['conf']:.2f}"
                    cv2.rectangle(resized, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    cv2.putText(resized, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

            fps = 1 / (time.time() - start_time)
            stat = f"Cam {cam_id} | FPS: {fps:.1f} | No_Helmet: {len(current_violations)} | Person: {len(current_person_ids_in_roi)}"
            cv2.putText(resized, stat, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            with lock:
                frame_dict[cam_id] = resized.copy()

        except Exception as e:
            print(f"🔴 [ERROR] Cam {cam_id} loop error: {e}")
            time.sleep(1) 

    print(f"[INFO] Thread {cam_id} stopping.")
    cap.release()