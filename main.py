import threading
import atexit
import yaml
import cv2
from src.camera_worker import camera_loop
from src.alarm import init_serial, close_serial, send_buzzer_command

# Shared dictionary to hold latest frames and a global stop event
frame_dict = {}
lock = threading.Lock()
stop_event = threading.Event() # For graceful shutdown

def load_config(path='./config/config.yaml'):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def cleanup_all():
    print("[EXIT] Cleaning up resources...")
    stop_event.set() # Signal all threads to stop

    # --- Turning off the buzzer on exit ---
    print("[EXIT] Sending command to turn off buzzer...")
    try:
        config = load_config()
        use_wifi = config.get('use_wifi', False)
        esp_ip = config.get('esp_ip', None)
        send_buzzer_command(False, use_wifi, esp_ip) # 'False' means turn OFF
        cv2.destroyAllWindows()
    except Exception as e:
        print(f"[EXIT] Could not send buzz_off command or cv2 error: \n{e}")

    close_serial()

def display_frames(camera_titles):
    while not stop_event.is_set():
        with lock:
            # Create a copy of items to avoid issues if dict changes during iteration
            frames_to_show = list(frame_dict.items())

        for cam_id, frame in frames_to_show:
            if frame is not None:
                title = camera_titles[cam_id] if cam_id < len(
                    camera_titles) else f"Camera {cam_id}"
                cv2.imshow(title, frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    # When loop breaks, signal cleanup
    stop_event.set()
    cv2.destroyAllWindows()

def main():
    print("[INFO] Main script started.")
    atexit.register(cleanup_all)

    try:
        config = load_config()
        print("[INFO] Configuration file loaded successfully.")

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
            
            t = threading.Thread(target=camera_loop, args=(
                cam_id, stream_url, config, # Pass the whole config dictionary
                frame_dict, lock, stop_event)) # Pass the stop_event
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
        # Ensure cleanup runs even if display loop exits
        cleanup_all()
        print("[INFO] Main script finished.")


if __name__ == '__main__':
    main()