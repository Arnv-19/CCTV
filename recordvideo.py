# #!/usr/bin/env python3
# """
# Download 10 seconds of RTSP video from IP camera and save as MP4.
# """

# import cv2
# import numpy as np
# import time
# import sys
# import argparse

# def download_rtsp_video(rtsp_url, duration=60, filename='rtsp_video.mp4', fps=25):
#     """
#     Record RTSP stream for specified duration.
    
#     Args:
#         rtsp_url: RTSP camera URL
#         duration: seconds to record
#         filename: output MP4 filename
#         fps: target FPS (auto-detect if possible)
#     """
    
#     print(f"🔴 Connecting to: {rtsp_url}")
#     print("⏳ This may take 10-30 seconds to establish connection...")
    
#     # Try multiple backends for RTSP
#     cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    
#     if not cap.isOpened():
#         print("❌ ERROR: Cannot connect to camera")
#         print("\n🔧 Troubleshooting:")
#         print("1. Check IP: ping 192.168.20.103")
#         print("2. Check credentials: admin/admin@123")
#         print("3. Verify RTSP path: /cam/realmonitor?channel=27&subtype=0")
#         print("4. Test with VLC: vlc rtsp://admin:admin@123@192.168.20.103:554/cam/realmonitor?channel=27&subtype=0")
#         return False
    
#     # Get video properties
#     fps_actual = cap.get(cv2.CAP_PROP_FPS)
#     width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
#     height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
#     if fps_actual > 0:
#         fps = fps_actual
#     print(f"📹 Video info: {fps:.1f} FPS, {width}x{height}")
    
#     # Video writer (MP4)
#     fourcc = cv2.VideoWriter_fourcc(*'mp4v')
#     out = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    
#     if not out.isOpened():
#         print("❌ ERROR: Cannot create output video file")
#         cap.release()
#         return False
    
#     print(f"🎥 Recording {duration}s to '{filename}'...")
    
#     start_time = time.time()
#     frames = 0
    
#     while True:
#         ret, frame = cap.read()
#         if not ret:
#             print("⚠️  Warning: Lost frames, continuing...")
#             continue
        
#         out.write(frame)
#         frames += 1
        
#         elapsed = time.time() - start_time
#         if elapsed >= duration:
#             break
    
#     # Cleanup
#     cap.release()
#     out.release()
#     cv2.destroyAllWindows()
    
#     print(f"✅ SUCCESS!")
#     print(f"📊 Recorded: {frames} frames, {elapsed:.1f}s, {filename}")
#     print(f"\n🎬 Test playback:")
#     print(f"ffplay {filename}")
#     print(f"vlc {filename}")
    
#     return True

# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Download RTSP video")
#     parser.add_argument("--url", default="rtsp://admin:admin@123@192.168.20.103:554/cam/realmonitor?channel=27&subtype=0")
#     parser.add_argument("--duration", type=int, default=10, help="seconds to record")
#     parser.add_argument("--output", default="camera_10sec.mp4", help="output filename")
    
#     args = parser.parse_args()
    
#     success = download_rtsp_video(
#         rtsp_url=args.url,
#         duration=args.duration,
#         filename=args.output
#     )
    
#     sys.exit(0 if success else 1)


#!/usr/bin/env python3

#-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
#for 1 minute video recording and saving frames
# import cv2
# import time
# import os
# import sys
# import argparse

# def download_rtsp_video(rtsp_url, duration=60, filename='rtsp_video.mp4', fps=25, frame_skip=5):
#     print(f"🔴 Connecting to: {rtsp_url}")
    
#     cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

#     if not cap.isOpened():
#         print("❌ ERROR: Cannot connect to camera")
#         return False

#     # Get properties
#     fps_actual = cap.get(cv2.CAP_PROP_FPS)
#     width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
#     height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

#     if fps_actual > 0:
#         fps = fps_actual

#     print(f"📹 Video info: {fps:.1f} FPS, {width}x{height}")

#     # Create output video writer
#     fourcc = cv2.VideoWriter_fourcc(*'mp4v')
#     out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

#     # Create folder for frames
#     frame_folder = "saved_frames"
#     os.makedirs(frame_folder, exist_ok=True)

#     print(f"📁 Frames will be saved in: {frame_folder}")
#     print(f"🎥 Recording {duration}s video + saving frames...")

#     start_time = time.time()
#     frame_count = 0
#     saved_count = 0

#     while True:
#         ret, frame = cap.read()
#         if not ret:
#             print("⚠️ Frame not received, retrying...")
#             continue

#         # Save video
#         out.write(frame)

#         # Save image every N frames (skip 4-5 frames)
#         if frame_count % frame_skip == 0:
#             img_name = os.path.join(frame_folder, f"frame_{saved_count}.jpg")
#             cv2.imwrite(img_name, frame)
#             saved_count += 1

#         frame_count += 1

#         # Stop after duration
#         if time.time() - start_time >= duration:
#             break

#     # Cleanup
#     cap.release()
#     out.release()
#     cv2.destroyAllWindows()

#     print("\n✅ DONE!")
#     print(f"🎥 Video saved: {filename}")
#     print(f"🖼️ Total frames saved: {saved_count}")

#     return True


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Download RTSP video + save frames")
#     parser.add_argument("--url", default="rtsp://admin:admin%40123@192.168.20.103:554/cam/realmonitor?channel=29&subtype=0")
#     parser.add_argument("--duration", type=int, default=60)  # ✅ 1 minute
#     parser.add_argument("--output", default="camera_1min.mp4")
#     parser.add_argument("--skip", type=int, default=5, help="save every Nth frame")

#     args = parser.parse_args()

#     success = download_rtsp_video(
#         rtsp_url=args.url,
#         duration=args.duration,
#         filename=args.output,
#         frame_skip=args.skip
#     )

#     sys.exit(0 if success else 1)


#-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------  
#for 10 min video recording and saving frames
#!/usr/bin/env python3

import cv2
import time
import os

def download_rtsp_video(rtsp_url, duration=600, filename='camera_10min2.mp4', fps=25, frame_skip=10):

    print(f"🔴 Connecting to: {rtsp_url}")
    
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    

    if not cap.isOpened():
        print("❌ ERROR: Cannot connect to camera")
        return False

    # Get properties
    fps_actual = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps_actual > 0:
        fps = fps_actual

    print(f"📹 Video info: {fps:.1f} FPS, {width}x{height}")

    # Video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))

    # Create folder for frames
    frame_folder = "saved_frames_10min2"
    os.makedirs(frame_folder, exist_ok=True)

    print(f"📁 Frames folder: {frame_folder}")
    print(f"🎥 Recording 10 minutes video...")

    start_time = time.time()
    frame_count = 0
    saved_count = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            print("⚠️ Frame not received, retrying...")
            continue

        # Save video
        out.write(frame)

        # Save image every N frames
        if frame_count % frame_skip == 0:
            img_path = os.path.join(frame_folder, f"frame_{saved_count}.jpg")
            cv2.imwrite(img_path, frame)
            saved_count += 1

        frame_count += 1

        # Stop after 10 minutes (600 sec)
        if time.time() - start_time >= duration:
            break

    # Cleanup
    cap.release()
    out.release()
    cv2.destroyAllWindows()

    print("\n✅ DONE!")
    print(f"🎥 Video saved: {filename}")
    print(f"🖼️ Frames saved: {saved_count}")

    return True


# 🔽 MAIN
if __name__ == "__main__":

    rtsp_url = "rtsp://admin:admin%40123@192.168.20.103:554/cam/realmonitor?channel=28&subtype=0"

    download_rtsp_video(
        rtsp_url=rtsp_url,
        duration=600,          # ✅ 10 minutes
        filename="camera_10min2.mp4",
        frame_skip=10          # ✅ skip frames (reduce load)
    )