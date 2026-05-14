# client/client.py
import cv2, requests, base64, time
import numpy as np
import sounddevice as sd
import os
import onnxruntime as ort

SERVER_URL = "http://127.0.0.1:5000/analyze"

# ───────────────────────────────────────────────
# Try to load lightweight ONNX models (optional)
# ───────────────────────────────────────────────
# Model paths are relative to the server/models directory
face_model_path = os.path.join(os.path.dirname(__file__), "..", "server", "models", "video_model.onnx")
lipsync_model_path = os.path.join(os.path.dirname(__file__), "..", "server", "models", "audio_model.onnx")

face_detector = None
lipsync_model = None

if os.path.exists(face_model_path):
    try:
        face_detector = ort.InferenceSession(face_model_path, providers=['CPUExecutionProvider'])
        print("[INFO] Face detector model loaded.")
    except Exception as e:
        print(f"[WARNING] Failed to load face detector: {e}")
else:
    print("[WARNING] face_detector.onnx not found — using mock motion check.")

if os.path.exists(lipsync_model_path):
    try:
        lipsync_model = ort.InferenceSession(lipsync_model_path, providers=['CPUExecutionProvider'])
        print("[INFO] Lip-sync model loaded.")
    except Exception as e:
        print(f"[WARNING] Failed to load lipsync model: {e}")
else:
    print("[WARNING] lipsync_light.onnx not found — using mock motion check.")

# ───────────────────────────────────────────────
# Helper functions
# ───────────────────────────────────────────────
def capture_video_chunk(duration=3):
    """Capture frames from webcam for a given duration (seconds)."""
    cap = cv2.VideoCapture(0)
    frames = []
    start = time.time()
    while time.time() - start < duration:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.resize(frame, (224, 224))
        _, buffer = cv2.imencode(".jpg", frame)
        frames.append(base64.b64encode(buffer).decode("utf-8"))
    cap.release()
    return frames

def capture_audio_chunk(duration=3, fs=16000):
    """Record audio chunk using microphone."""
    print("[INFO] Recording audio chunk...")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float32')
    sd.wait()
    return base64.b64encode(audio.tobytes()).decode("utf-8")

def quick_motion_check(frames):
    """Simple mock motion/lip-sync check using frame differences."""
    try:
        arr = np.array([
            cv2.cvtColor(cv2.imdecode(np.frombuffer(base64.b64decode(f), np.uint8), 1), cv2.COLOR_BGR2GRAY)
            for f in frames
        ])
        diff = np.mean(np.abs(np.diff(arr, axis=0)))
        return diff > 8.0
    except Exception as e:
        print(f"[WARNING] quick_motion_check failed: {e}")
        return True  # assume motion if check fails

# ───────────────────────────────────────────────
# Main routine
# ───────────────────────────────────────────────
def main():
    frames = capture_video_chunk()
    audio = capture_audio_chunk()
    motion_flag = quick_motion_check(frames)

    payload = {
        "frames": frames,
        "audio": audio,
        "motion_flag": bool(motion_flag)  # explicitly cast to bool
    }

    print("[INFO] Sending data to server...")
    try:
        import json
        res = requests.post(SERVER_URL, data=json.dumps(payload),
                            headers={"Content-Type": "application/json"},
                            timeout=30)
        print("Server result:", res.json())
    except Exception as e:
        print(f"[ERROR] Failed to connect to server: {e}")


if __name__ == "__main__":
    main()
