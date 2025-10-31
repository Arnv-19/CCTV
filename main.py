import threading
import atexit
import yaml
import cv2
import numpy as np  
from src.camera_worker import camera_loop
from src.alarm import init_serial, close_serial, send_buzzer_command
from src.roi_manager import load_rois, save_rois 

# Shared dictionary to hold latest frames and a global stop event
frame_dict = {}
lock = threading.Lock()
stop_event = threading.Event()  # For graceful shutdown

rois_state = {} # Jo ROI ban chuki h, video stream me chal rahi h
roi_lock = threading.Lock()
roi_setup_points = {}  # Temp Coordinates store

def load_config(path='./config/config.yaml'):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def cleanup_all():
    print("[EXIT] Cleaning up resources...")
    stop_event.set()  # Signal all threads to stop

    print("[EXIT] Sending command to turn off buzzer...")
    try:
        config = load_config()
        use_wifi = config.get('use_wifi', False)
        esp_ip = config.get('esp_ip', None)
        send_buzzer_command(False, use_wifi, esp_ip) 
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"[EXIT] Could not send buzz_off command or cv2 error: \n{e}")

    close_serial()

# --- Mouse Callback Function ---
def mouse_callback(event, x, y, flags, param):
    """
    Handles mouse clicks on the cv2 windows for ROI selection.
    'param' is the camera_id.
    """
    cam_id = param
    cam_id_str = str(cam_id)

    if event == cv2.EVENT_LBUTTONDOWN:
        # Initialize list for this camera if it doesn't exist
        if cam_id_str not in roi_setup_points:
            roi_setup_points[cam_id_str] = []
        
        # Add the new point
        roi_setup_points[cam_id_str].append([x, y])
        print(f"[ROI] Cam {cam_id_str}: Added point {len(roi_setup_points[cam_id_str])}/4 at ({x},{y})")

        # If 4 points are clicked, save it as the new ROI
        if len(roi_setup_points[cam_id_str]) == 4:
            points = roi_setup_points.pop(cam_id_str)  # Get points and clear setup
            roi_np = np.array(points, dtype=np.int32)
            
            # Update the live state for the camera_worker thread
            with roi_lock:
                rois_state[cam_id_str] = roi_np
            
            save_rois(rois_state)  # Save for persistence
            print(f"✅ [ROI] Cam {cam_id_str}: ROI SAVED.")
    
    elif event == cv2.EVENT_RBUTTONDOWN:
        # Right-click clears the ROI
        with roi_lock:
            rois_state.pop(cam_id_str, None) # Remove from live state
        
        roi_setup_points.pop(cam_id_str, None) # Clear any in-progress clicks
        
        save_rois(rois_state)  # Save the cleared state
        print(f"❌ [ROI] Cam {cam_id_str}: ROI CLEARED.")


# --- display_frames Function ---
def display_frames(camera_titles):
    print("\n[INFO] Display started. Press 'q' to quit.")
    print(" Left-click 4 points on a window to set ROI.")
    print(" Right-click on a window to clear its ROI.")
    
    window_titles = {}
    # --- Create windows and set callbacks *before* the loop ---
    for cam_id in range(len(camera_titles)):
        title = camera_titles[cam_id] if cam_id < len(
            camera_titles) else f"Camera {cam_id}"
        window_titles[cam_id] = title
        cv2.namedWindow(title)
        cv2.setMouseCallback(title, mouse_callback, cam_id) # Pass cam_id as parameter

    while not stop_event.is_set():
        with lock:
            frames_to_show = list(frame_dict.items())

        for cam_id, frame in frames_to_show:
            if frame is not None:
                title = window_titles.get(cam_id)
                if title:
                    # --- Draw in-progress ROI points (Temp Coords) ---
                    setup_pts = roi_setup_points.get(str(cam_id), [])
                    for i in range(len(setup_pts)):
                        cv2.circle(frame, tuple(setup_pts[i]), 5, (0, 255, 255), -1) # Yellow dot
                        if i > 0:
                            # Draw line from previous point to current point
                            cv2.line(frame, tuple(setup_pts[i-1]), tuple(setup_pts[i]), (0, 255, 255), 2)
                    
                    cv2.imshow(title, frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    # When loop breaks, signal cleanup
    stop_event.set()
    cv2.destroyAllWindows()

def main():
    global rois_state
    print("[INFO] Main script started.")
    atexit.register(cleanup_all)

    try:
        config = load_config()
        print("[INFO] Configuration file loaded successfully.")
        
        # --- Load persistent ROIs into the shared state ---
        rois_state = load_rois()
        print(f"[INFO] Loaded {len(rois_state)} saved ROIs.")

        if not config.get('use_wifi', False):
            init_serial()
        else:
            print("[INFO] WiFi mode is enabled. Skipping serial initialization.")

        use_wifi = config.get('use_wifi', False)
        esp_ip = config.get('esp_ip', None)
        cooldown = config.get('alarm_cooldown_sec', 5)

        feeds = config['camera_feeds']
        titles = config.get(
            'camera_titles', [f"Camera {i}" for i in range(len(feeds))])
        threads = []
        
        print(f"[INFO] Found {len(feeds)} camera feeds. Starting threads...")

        for cam_id, stream_url in enumerate(feeds):
            print(f"[INFO] Starting thread for Camera {cam_id} with URL: {stream_url}")
            
            # --- Pass the shared ROI state and lock to the thread ---
            t = threading.Thread(target=camera_loop, args=(
                cam_id, stream_url, config,
                frame_dict, lock, stop_event,
                rois_state, roi_lock))
            t.daemon = True
            t.start()
            threads.append(t)

        if not feeds:
            print("[WARNING] No camera feeds are defined in config.yaml. Nothing to display.")
            return

        print("[INFO] All threads started. Starting frame display loop.")
        display_frames(titles)

    except FileNotFoundError as e:
        print(f"[ERROR] A required file was not found: {e}")
    except KeyError as e:
        print(f"[ERROR] Missing a required key in config.yaml: {e}")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred in main: {e}")
    finally:
        cleanup_all()
        print("[INFO] Main script finished.")


if __name__ == '__main__':
    main()