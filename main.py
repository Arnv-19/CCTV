import threading
import atexit
import yaml
import cv2
import numpy as np
from src.camera_worker import camera_loop
from src.alarm import init_serial, close_serial, send_buzzer_command
from src.roi_manager import load_rois, save_rois
from src.helmet_detector import load_model, load_class_names 

# Shared dictionary to hold latest frames
frame_dict = {}
lock = threading.Lock()

thread_stop_events = {} 

# Shared state for ROIs
rois_state = {}
roi_lock = threading.Lock()
roi_setup_points = {} 

def load_config(path='./config/config.yaml'):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def cleanup_all():
    print("[EXIT] Cleaning up resources...")
    # Signal all running threads to stop
    for cam_id, event in thread_stop_events.items():
        if not event.is_set():
            print(f"[EXIT] Sending stop signal to thread {cam_id}...")
            event.set()

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

def mouse_callback(event, x, y, flags, param):
    """
    Handles mouse clicks on the cv2 windows for ROI selection.
    
    CONTROLS:
    - Left-Click:       Add a point.
    - Double-Click:     Save the current polygon (min 3 points).
    - Right-Click:      Remove the last added point (undo).
                        If no points, clear saved ROI.
    - Middle-Click:     Save the current polygon (min 3 points).
    """
    cam_id = param
    cam_id_str = str(cam_id)

    if event == cv2.EVENT_LBUTTONDOWN:
        # Add a point
        if cam_id_str not in roi_setup_points:
            roi_setup_points[cam_id_str] = []
        roi_setup_points[cam_id_str].append([x, y])
        print(f"[ROI] Cam {cam_id_str}: Added point {len(roi_setup_points[cam_id_str])} at ({x},{y})")

    elif event == cv2.EVENT_LBUTTONDBLCLK:
        # --- Double left-click saves the polygon ---
        if cam_id_str in roi_setup_points and len(roi_setup_points[cam_id_str]) >= 3:
            points = roi_setup_points.pop(cam_id_str)
            roi_np = np.array(points, dtype=np.int32)
            with roi_lock:
                rois_state[cam_id_str] = roi_np
            save_rois(rois_state)
            print(f"✅ [ROI] Cam {cam_id_str}: SAVED with {len(points)} points (Double-Click).")
        else:
            print(f"[ROI] Cam {cam_id_str}: Cannot save (Double-Click). Need at least 3 points.")

    elif event == cv2.EVENT_RBUTTONDOWN:
        # Undo last point, or clear saved ROI
        if cam_id_str in roi_setup_points and roi_setup_points[cam_id_str]:
            removed_point = roi_setup_points[cam_id_str].pop()
            print(f"[ROI] Cam {cam_id_str}: Removed last point {removed_point}")
        else:
            # If no setup points exist, clear the *saved* ROI
            with roi_lock:
                rois_state.pop(cam_id_str, None) # Remove from live state
            save_rois(rois_state)  # Save the cleared state
            print(f"❌ [ROI] Cam {cam_id_str}: ROI CLEARED.")
    
    elif event == cv2.EVENT_MBUTTONDOWN: # Middle mouse click
        # Save the current polygon
        if cam_id_str in roi_setup_points and len(roi_setup_points[cam_id_str]) >= 3:
            points = roi_setup_points.pop(cam_id_str)
            roi_np = np.array(points, dtype=np.int32)
            with roi_lock:
                rois_state[cam_id_str] = roi_np
            save_rois(rois_state)
            print(f"✅ [ROI] Cam {cam_id_str}: SAVED with {len(points)} points (Middle-Click).")
        else:
            print(f"[ROI] Cam {cam_id_str}: Cannot save (Middle-Click). Need at least 3 points.")


# --- MODIFIED: display_frames with all UI fixes ---
def display_frames(camera_titles):
    print("\n[INFO] Display started. Press 'q' to quit all.")
    print("--- ROI CONTROLS (on any camera window) ---")
    print(" Left-Click:       Add point")
    print(" Double-Click:     Save polygon (min 3 points)")
    print(" Middle-Click:     Save polygon (min 3 points)")
    print(" Right-Click:      Remove last point (or clear saved ROI)")
    print(" Click 'x' on a window to close just that stream.")
    
    window_titles = {}
    for cam_id in range(len(camera_titles)):
        title = camera_titles[cam_id] if cam_id < len(
            camera_titles) else f"Camera {cam_id}"
        window_titles[cam_id] = title
        cv2.namedWindow(title)
        cv2.setMouseCallback(title, mouse_callback, cam_id) 

    running = True
    while running:
        with lock:
            frames_to_show = list(frame_dict.items())

        # --- Iterate over a copy of keys, as we may modify the dict ---
        for cam_id in list(window_titles.keys()):
            title = window_titles[cam_id]
            
            # --- Check if window was closed by user ---
            try:
                if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                    print(f"[INFO] Window '{title}' (Cam {cam_id}) closed by user.")
                    thread_stop_events[cam_id].set() # Signal thread to stop
                    cv2.destroyWindow(title)
                    del window_titles[cam_id] # Remove from display loop
                    continue # Move to next window
            except cv2.error:
                # Window was already destroyed, just clean up
                if cam_id in window_titles:
                    del window_titles[cam_id]
                continue

            # Get the frame for this cam_id
            frame = frame_dict.get(cam_id)

            if frame is not None:
                # Always draw on a fresh copy of the frame
                display_frame = frame.copy() 
                
                # Draw in-progress ROI points
                setup_pts = roi_setup_points.get(str(cam_id), [])
                for i in range(len(setup_pts)):
                    cv2.circle(display_frame, tuple(setup_pts[i]), 5, (0, 255, 255), -1) 
                    if i > 0:
                        cv2.line(display_frame, tuple(setup_pts[i-1]), tuple(setup_pts[i]), (0, 255, 255), 2)
                
                if len(setup_pts) > 2:
                    cv2.line(display_frame, tuple(setup_pts[-1]), tuple(setup_pts[0]), (0, 255, 255), 2)
                
                # Show the modified copy
                cv2.imshow(title, display_frame) 

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("[INFO] 'q' pressed. Shutting down all streams.")
            running = False # Break the display loop
        
        # If all windows are closed, exit the display loop
        if not window_titles:
            print("[INFO] All camera windows are closed. Exiting.")
            running = False

    # After loop breaks, let atexit handle the full cleanup
    cv2.destroyAllWindows()

def main():
    global rois_state, thread_stop_events
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

        print("[INFO] Loading shared YOLO model...")
        try:
            model = load_model(config['model_path'])
            _, helmet_class, no_helmet_class = load_class_names(config['class_file'])
            print("[INFO] Model and class names loaded successfully.")
        except Exception as e:
            print(f"🔴 [FATAL] Could not load model or class file: {e}")
            return

        feeds = config['camera_feeds']
        titles = config.get(
            'camera_titles', [f"Camera {i}" for i in range(len(feeds))])
        threads = []
        
        print(f"[INFO] Found {len(feeds)} camera feeds. Starting threads...")

        for cam_id, stream_url in enumerate(feeds):
            print(f"[INFO] Starting thread for Camera {cam_id} with URL: {stream_url}")
            
            # --- Create stop event and pass the dict ---
            thread_stop_events[cam_id] = threading.Event() # Create event for this thread
            
            t = threading.Thread(target=camera_loop, args=(
                cam_id, stream_url, config,
                frame_dict, lock, 
                thread_stop_events, # Pass the whole dict
                rois_state, roi_lock,
                model, helmet_class, no_helmet_class
            ))
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
        print("[INFO] Main script finished.")


if __name__ == '__main__':
    main()