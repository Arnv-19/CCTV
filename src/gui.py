import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import yaml
import subprocess
import threading
import re, queue
import os

CONFIG_PATH = "config/config.yaml"
if not os.path.exists("ESP"):
    os.makedirs("ESP")
ESP_FILE_PATH = "ESP/ESP.ino"

class HelmetGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Helmet Detection Control Panel")

        # Create a thread-safe queue for log messages
        self.log_queue = queue.Queue()

        self.load_config()
        self.setup_ui()

        # Start the process of checking the queue
        self.process_log_queue()

    def load_config(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                self.config = yaml.safe_load(f)
        except FileNotFoundError:
            messagebox.showerror("Error", f"Config file not found at {CONFIG_PATH}")
            self.root.quit()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load config: {e}")
            self.root.quit()

    def save_config(self):
        with open(CONFIG_PATH, 'w') as f:
            yaml.dump(self.config, f)
        messagebox.showinfo("Success", "Configuration saved!")

    def setup_ui(self):
        top_frame = tk.Frame(self.root)
        top_frame.pack(anchor="nw")

        # ==== Camera Input Fields ====
        self.camera_entries = []
        self.title_entries = []

        cam_frame = tk.LabelFrame(self.root, text="Camera URLs")
        cam_frame.pack(fill="x", padx=10, pady=5)

        for i in range(4):
            frame = tk.Frame(cam_frame)
            frame.pack(fill="x", pady=2)
            tk.Label(frame, text=f"Camera {i+1}:").pack(side="left")

            url_entry = tk.Entry(frame, width=60)
            url_entry.pack(side="left", padx=5)
            if i < len(self.config.get('camera_feeds', [])):
                url_entry.insert(0, self.config['camera_feeds'][i])
            self.camera_entries.append(url_entry)

            title_entry = tk.Entry(frame, width=20)
            title_entry.pack(side="left", padx=5)
            if i < len(self.config.get('camera_titles', [])):
                title_entry.insert(0, self.config['camera_titles'][i])
            self.title_entries.append(title_entry)

        btn_frame = tk.Frame(cam_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Update Cameras",
                  command=self.update_camera_feeds).pack()

        # ==== ESP Settings ====
        esp_frame = tk.LabelFrame(self.root, text="ESP Settings")
        esp_frame.pack(fill="x", padx=10, pady=5)

        tk.Label(esp_frame, text="ESP IP:").pack(side="left", padx=5)
        self.esp_ip_entry = tk.Entry(esp_frame, width=20)
        self.esp_ip_entry.pack(side="left")
        self.esp_ip_entry.insert(0, self.config.get('esp_ip', ''))

        self.use_wifi_var = tk.BooleanVar(
            value=self.config.get('use_wifi', False))
        tk.Checkbutton(esp_frame, text="Use WiFi",
                       variable=self.use_wifi_var).pack(side="left", padx=10)

        tk.Label(esp_frame, text="Serial Port:").pack(side="left", padx=5)
        self.serial_port_entry = tk.Entry(esp_frame, width=20)
        self.serial_port_entry.pack(side="left")

        # Get the serial port from the config dict, providing '' as a default
        self.serial_port_entry.insert(0, self.config.get('serial_port', ''))

        tk.Button(esp_frame, text="WiFi Settings",
                  command=self.open_wifi_settings).pack(side="left", padx=10)
        tk.Button(esp_frame, text="Update ESP Config",
                  command=self.update_esp_config).pack(side="left", padx=10)

        # ==== Run Button ====
        tk.Button(self.root, text="RUN", command=self.run_script,
                  height=2, width=15, bg='green', fg='white').pack(pady=10)

        # ==== Logs ====
        log_frame = tk.LabelFrame(self.root, text="Logs")
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.log_output = ScrolledText(log_frame, height=10)
        self.log_output.pack(fill="both", expand=True)

    def update_camera_feeds(self):
        self.config['camera_feeds'] = [e.get().strip()
                                        for e in self.camera_entries if e.get().strip()]
        self.config['camera_titles'] = [t.get().strip()
                                        for t in self.title_entries][:len(self.config['camera_feeds'])]
        self.save_config()
        messagebox.showinfo(
            "Saved", "Camera feeds and titles updated in config.yaml")

    def update_esp_config(self):
        self.config['esp_ip'] = self.esp_ip_entry.get().strip()
        self.config['use_wifi'] = self.use_wifi_var.get()
        self.config['serial_port'] = self.serial_port_entry.get().strip()
        self.save_config()

        messagebox.showinfo("Saved", "ESP and Serial config updated")

    def open_wifi_settings(self):
        win = tk.Toplevel(self.root)
        win.title("WiFi Settings")

        tk.Label(win, text="SSID:").grid(row=0, column=0, padx=10, pady=5)
        ssid_entry = tk.Entry(win, width=30)
        ssid_entry.grid(row=0, column=1)

        tk.Label(win, text="Password:").grid(row=1, column=0, padx=10, pady=5)
        pass_entry = tk.Entry(win, width=30)
        pass_entry.grid(row=1, column=1)

        def save_wifi():
            ssid = ssid_entry.get().strip()
            pwd = pass_entry.get().strip()
            if ssid and pwd:
                with open(ESP_FILE_PATH, 'r', encoding='utf-8') as f:
                    code = f.read()
                code = re.sub(r'const char\* ssid = ".*?";', f'const char* ssid = "{ssid}";', code)
                code = re.sub(r'const char\* password = ".*?";', f'const char* password = "{pwd}";', code)
                
                with open(ESP_FILE_PATH, 'w', encoding='utf-8') as f:
                    f.write(code)
                messagebox.showinfo("Saved", "WiFi credentials updated in ESP.ino")
                win.destroy()

        tk.Button(win, text="Save", command=save_wifi).grid(
            row=2, column=0, columnspan=2, pady=10)

    def process_log_queue(self):
        """
        Check the queue for new log messages and update the GUI.
        This runs in the main GUI thread.
        """
        try:
            # Get all messages currently in the queue
            while True:
                line = self.log_queue.get_nowait()
                if line:
                    self.log_output.insert(tk.END, line)
                    self.log_output.see(tk.END)
        except queue.Empty:
            # If the queue is empty, do nothing
            pass
        
        # Schedule this method to be called again after 100ms
        self.root.after(100, self.process_log_queue)

    def run_script(self):
        """
        Runs the main detection script in a separate thread and
        sends its output to the log_queue.
        """
        def runner():
            # Check if using 'python' or 'python3' is more appropriate
            # On Windows, it's often 'python'. On Linux/macOS, 'python3'.
            python_executable = "python" if os.name == 'nt' else "python3"
            
            self.log_output.delete(1.0, tk.END) # Clear previous logs
            self.log_output.insert(tk.END, f"--- Starting process: {python_executable} main.py ---\n")

            try:
                process = subprocess.Popen(
                    [python_executable, "./main.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1  # Line-buffered
                )

                # Read output line by line and put it into the queue
                for line in iter(process.stdout.readline, ''):
                    self.log_queue.put(line)
                
                process.stdout.close()
                process.wait()
                self.log_queue.put("--- Process finished ---\n")

            except FileNotFoundError:
                msg = f"Error: '{python_executable}' not found.\n"
                msg += "Please ensure Python is in your system's PATH.\n"
                msg += "You might need to change the 'python_executable' variable in gui.py.\n"
                self.log_queue.put(msg)
            except Exception as e:
                self.log_queue.put(f"--- An unexpected error occurred: {e} ---\n")

        # Start the runner function in a daemon thread
        threading.Thread(target=runner, daemon=True).start()

if __name__ == '__main__':
    root = tk.Tk()
    app = HelmetGUI(root)
    root.mainloop()