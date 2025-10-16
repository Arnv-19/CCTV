import time
import threading
import serial
import yaml

CONFIG_PATH = "config/config.yaml"

def load_config():
    """Loads the configuration from the YAML file."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ERROR: Configuration file not found at {CONFIG_PATH}")
        return None
    except Exception as e:
        print(f"ERROR: Failed to load or parse config file: {e}")
        return None

config = load_config()
# Cooldown to avoid repeated buzz
last_sent_time = {}
COOLDOWN = config['alarm_cooldown_sec']  # seconds

# Serial configuration
SERIAL_PORT = config['serial_port']
BAUDRATE = 115200
serial_lock = threading.Lock()

# Global serial object
ser = None

def init_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        print(f"[USB] Serial connected on {SERIAL_PORT}")
    except Exception as e:
        ser = None
        print(f"[USB] Failed to open serial port {SERIAL_PORT}: {e}")

def reconnect_serial():
    global ser
    try:
        if ser:
            ser.close()
            time.sleep(0.5)
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        print("[USB] Serial reconnected.")
    except Exception as e:
        ser = None
        print(f"[USB] Reconnection failed: {e}")

def send_buzzer_command(state, use_wifi, esp_ip=None):
    if use_wifi and esp_ip:
        import requests
        try:
            url = f"http://{esp_ip}/buzz_{'on' if state else 'off'}"
            print(f"[WiFi] Sending request to {url}")
            requests.get(url, timeout=1)
        except Exception as e:
            print(f"[WiFi] Error sending buzzer request: {e}")
    else:
        if ser and ser.is_open:
            cmd = "buzz_on\n" if state else "buzz_off\n"
            try:
                with serial_lock:
                    ser.write(cmd.encode())
                print(f"[USB] Sent: {cmd.strip()}")
            except Exception as e:
                print(f"[USB] Error sending serial command: {e}")
                reconnect_serial()
        else:
            print("[USB] Serial port not open, can't send command")

# def trigger_alarm(camera_id, cooldown, use_wifi=False, esp_ip=None):
#     now = time.time()

#     if camera_id not in last_sent_time:
#         last_sent_time[camera_id] = 0

#     if now - last_sent_time[camera_id] > COOLDOWN:
#         print(f"[ALARM] No helmet detected on Camera {camera_id}")
#         threading.Thread(
#             target=send_buzzer_command,
#             args=(True, use_wifi, esp_ip),
#             daemon=True
#             ).start()
        
#         last_sent_time[camera_id] = now

def close_serial():
    global ser
    if ser and ser.is_open:
        print("[USB] Closing serial port...")
        ser.close()
        time.sleep(0.5)