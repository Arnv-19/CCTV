# Multi-Camera AI Detection System

A flexible, multi-threaded video analysis platform that leverages YOLOv8 to perform real-time object detection across multiple camera streams. This system is designed to be modular, allowing users to switch between different detection models (e.g., Person, Vehicle, Face) and includes a specialized Helmet Safety Compliance mode with an integrated alarm system.

---

## Key Features

- **Multi-Camera Support:** Concurrently process and display video feeds from multiple sources (IP cameras, local video files, webcams).

- **Pluggable AI Models:** Easily switch between different YOLOv8 models for various detection tasks like Helmet, Person, Vehicle, or Face detection via a simple configuration change.

- **Specialized Helmet Safety Mode:** When "Helmet Detection" is active, the system specifically monitors for safety violations (i.e., persons without helmets).

- **Centralized Alarm System:** A smart alarm triggers only when a safety violation is detected. It remains active as long as a violation exists on any camera feed and only turns off when all streams are clear. Supports both Wi-Fi (ESP8266/ESP32) and Serial-based buzzers.

- **Dynamic Region of Interest (ROI):** Interactively draw a rectangle on any video feed to focus the AI's detection resources exclusively on that area, creating a separate window for the focused view. Closing the ROI window seamlessly reverts detection to the full frame.

- **User-Friendly GUI:** A Tkinter-based control panel (gui.py) allows for easy configuration of camera URLs, AI models, and alarm settings without editing code.

- **Violation Logging & Evidence:** Automatically saves cropped images of detected violations to a violations/ directory and logs event details to logs/alerts.log.

- **Robust & Resilient:** The multi-threaded architecture ensures that the UI remains responsive and that an issue with one camera feed does not crash the entire application.

---

## System Architecture

The application operates on a multi-threaded model to ensure high performance and a non-blocking user interface:

* **Main Thread:** Handles user input (keyboard, mouse clicks for ROI) and renders all video windows using OpenCV.

* **Camera Worker Threads:** One dedicated thread per camera feed. Each thread is responsible for grabbing frames, performing AI inference (on the full frame or ROI), and updating shared data structures with the latest frame and detection results.

* **Alarm Thread:** A separate thread that runs only in "Helmet Detection" mode. It continuously monitors the violation status of all camera threads to manage the central alarm state.

---

## Setup and Installation

**Prerequisites:**

Python 3.9+
An NVIDIA GPU is recommended for optimal performance with CUDA.

### Steps

1. **Clone the repository:**
```bash
git clone https://github.com/skyai-dev/skyai_factory_cctv_AI
cd skyai_factory_cctv_AI
```

2. **Create a virtual environment (recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

### How to Run

The application is designed to be run in two steps: configuration followed by execution.

**Step 1: Configure the System**

First, run the GUI to set up your camera feeds, select the desired AI model, and configure your alarm hardware.
```bash
python3 src/gui.py 
```

Make your changes in the GUI and click the "Update" buttons to save them to `config/config.yaml`.

**Step 2: Run the Detection**

From the GUI, simply click the RUN button. This will launch the main detection application (main.py) in a new process, which will read your saved configuration and start the camera feeds.

## Usage

- **Select ROI:** Left-click and drag your mouse over a camera feed to draw a Region of Interest. A new window will pop up showing detections only within that ROI.

- **Close Windows:** You can close any camera window or ROI window individually by clicking the 'x' button.

- **Quit Application:** Press the `q` key on your keyboard while any of the OpenCV windows are in focus to gracefully shut down the entire application.