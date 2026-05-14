# server/server.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import base64, cv2, numpy as np, onnxruntime as ort, os, time, io, requests
from fusion import fuse_scores
from PIL import Image

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ==========================================================
# 🔧 Model setup
# ==========================================================
VIDEO_MODEL_PATH = os.path.join("models", "video_model.onnx")
AUDIO_MODEL_PATH = os.path.join("models", "audio_model.onnx")

video_sess = None
audio_sess = None
USE_VIDEO_MODEL = True
USE_AUDIO_MODEL = True

IDENTITY_HEATMAP_URL = "http://127.0.0.1:7000/heatmap"  # Identity Manager endpoint

def try_load_model(path):
    """Attempt to load ONNX model safely."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
            print(f"[INFO] Loaded ONNX model: {path}")
            return sess
        except Exception as e:
            print(f"[WARNING] Failed to load ONNX model {path}: {e}")
            return None
    else:
        print(f"[WARNING] Model file not found or empty: {path}")
        return None

video_sess = try_load_model(VIDEO_MODEL_PATH)
audio_sess = try_load_model(AUDIO_MODEL_PATH)
USE_VIDEO_MODEL = video_sess is not None
USE_AUDIO_MODEL = audio_sess is not None

# ==========================================================
# 🧩 Utility functions
# ==========================================================
def decode_frame_b64(b64str):
    """Decode base64 → BGR numpy array."""
    arr = np.frombuffer(base64.b64decode(b64str), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img

# Mock analyzers (fallbacks)
def mock_video_analyze(frames_np):
    """Heuristic fake-probability based on motion intensity."""
    try:
        gray_seq = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames_np]
        diffs = [
            np.mean(np.abs(gray_seq[i].astype(float) - gray_seq[i - 1].astype(float)))
            for i in range(1, len(gray_seq))
        ] or [0.0]
        motion = float(np.mean(diffs))
        vprob = max(0.0, min(1.0, 0.6 - (motion / 50.0)))  # less motion → more fake
    except Exception:
        vprob = 0.5
    return vprob

def mock_audio_analyze(audio_bytes):
    """Heuristic fake-probability based on audio energy."""
    try:
        arr = np.frombuffer(audio_bytes, dtype=np.float32)
        energy = float(np.mean(np.square(arr))) if arr.size else 0.0
        aprob = max(0.0, min(1.0, 0.4 + (0.05 if energy < 0.001 else -0.05)))
    except Exception:
        aprob = 0.5
    return aprob

# ==========================================================
# 🧠 Model inference
# ==========================================================
def run_video_model(frames_np):
    """Run video ONNX model or fallback mock."""
    if not USE_VIDEO_MODEL:
        return mock_video_analyze(frames_np)
    try:
        mean_frame = np.mean(frames_np.astype(np.float32), axis=0) / 255.0
        input_tensor = mean_frame.transpose(2, 0, 1)[None, ...].astype(np.float32)
        input_name = video_sess.get_inputs()[0].name
        out = video_sess.run(None, {input_name: input_tensor})
        vprob = float(np.asarray(out[0]).ravel()[0])
        return max(0.0, min(1.0, vprob))
    except Exception as e:
        print(f"[WARNING] Video model inference failed: {e}")
        return mock_video_analyze(frames_np)

def run_audio_model(audio_bytes):
    """Run audio ONNX model or fallback mock."""
    if not USE_AUDIO_MODEL:
        return mock_audio_analyze(audio_bytes)
    try:
        arr = np.frombuffer(audio_bytes, dtype=np.float32)
        input_tensor = arr.astype(np.float32)[None, :]
        input_name = audio_sess.get_inputs()[0].name
        out = audio_sess.run(None, {input_name: input_tensor})
        aprob = float(np.asarray(out[0]).ravel()[0])
        return max(0.0, min(1.0, aprob))
    except Exception as e:
        print(f"[WARNING] Audio model inference failed: {e}")
        return mock_audio_analyze(audio_bytes)

# ==========================================================
# 📦 Routes
# ==========================================================

@app.route("/analyze", methods=["POST"])
def analyze():
    """Analyze frames + audio and return verdict with breakdown."""
    start_time = time.time()
    data = request.get_json(force=True)

    frames_b64 = data.get("frames", [])
    audio_b64 = data.get("audio", "")
    motion_flag = data.get("motion_flag", True)

    # Decode frames
    frames_np = []
    for b64 in frames_b64:
        try:
            img = decode_frame_b64(b64)
            if img is None:
                continue
            img = cv2.resize(img, (224, 224))
            frames_np.append(img)
        except Exception as e:
            print(f"[WARNING] Failed to decode frame: {e}")

    if len(frames_np) == 0:
        return jsonify({"verdict": "ERROR", "reason": "no_frames_received"}), 400

    # Decode audio
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        audio_bytes = b""

    # Run inference
    vscore = run_video_model(np.array(frames_np))
    ascore = run_audio_model(audio_bytes)
    final_score = float(fuse_scores(vscore, ascore, motion_flag))
    verdict = "FAKE" if final_score > 0.6 else "REAL"

    resp = {
        "verdict": verdict,
        "confidence": round(final_score, 3),
        "video_score": round(vscore, 3),
        "audio_score": round(ascore, 3),
        "motion_flag": bool(motion_flag),
        "time_ms": int((time.time() - start_time) * 1000)
    }
    return jsonify(resp)

# ==========================================================
# 🌈 Heatmap Visualization (Forward or Fallback)
# ==========================================================
@app.route("/heatmap", methods=["POST"])
def heatmap():
    """
    Forward heatmap generation to Identity Manager (port 7000).
    If unavailable, generate a local texture-based heatmap as fallback.
    """
    try:
        data = request.get_json(force=True)
        face_b64 = data.get("face") or data.get("frame")
        if not face_b64:
            return jsonify({"error": "missing_face"}), 400

        # --- Try forwarding to Identity Manager first ---
        try:
            resp = requests.post(IDENTITY_HEATMAP_URL, json={"face": face_b64}, timeout=10)
            if resp.status_code == 200:
                return jsonify(resp.json())
            else:
                print(f"[WARN] Heatmap forward failed ({resp.status_code}), using fallback.")
        except Exception as e:
            print(f"[WARN] Could not reach Identity Manager: {e}")

        # --- Local fallback (gradient/texture-based heatmap) ---
        img_data = base64.b64decode(face_b64)
        img = np.array(Image.open(io.BytesIO(img_data)).convert("RGB"))
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        grad = np.abs(lap)
        norm_grad = cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX)
        heatmap = cv2.applyColorMap(norm_grad.astype(np.uint8), cv2.COLORMAP_TURBO)
        overlay = cv2.addWeighted(img, 0.7, heatmap, 0.4, 0)
        _, buf = cv2.imencode(".jpg", cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
        heatmap_b64 = base64.b64encode(buf).decode("utf-8")

        return jsonify({
            "heatmap": heatmap_b64,
            "heatmap_frame": heatmap_b64,
            "source": "fallback",
            "info": "Local gradient-based heatmap used (Identity Manager offline)."
        })

    except Exception as e:
        print(f"[ERROR] Heatmap generation failed: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================================
# 🏁 Index + Run
# ==========================================================
@app.route("/")
def index():
    return jsonify({
        "status": "DeepFakeHybrid API Running",
        "video_model_loaded": USE_VIDEO_MODEL,
        "audio_model_loaded": USE_AUDIO_MODEL,
        "heatmap_forward_enabled": True
    })

if __name__ == "__main__":
    print("[INFO] DeepFakeHybrid Flask server starting...")
    print(f"[INFO] Video model loaded: {USE_VIDEO_MODEL}")
    print(f"[INFO] Audio model loaded: {USE_AUDIO_MODEL}")
    app.run(host="0.0.0.0", port=5000, debug=False)
