from flask import Flask, request, jsonify
from flask_cors import CORS
import os, base64, time, cv2, numpy as np
from keras_facenet import FaceNet
from mtcnn import MTCNN

# -------------------------------------------------------------------------
# ⚙️ Setup
# -------------------------------------------------------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

FACE_DB, THRESHOLD_DB = {}, {}

# -------------------------------------------------------------------------
# 🧠 Load Models
# -------------------------------------------------------------------------
print("[BOOT] Starting Enhanced Identity Manager...")
facenet = FaceNet()
detector = MTCNN()
print("[INFO] ✅ FaceNet + MTCNN loaded successfully!")

# -------------------------------------------------------------------------
# ♻️ Reload Stored Data
# -------------------------------------------------------------------------
for f in os.listdir(DATA_DIR):
    if f.startswith("face_") and f.endswith(".npy"):
        name = f.split("face_")[1].split(".npy")[0]
        FACE_DB[name] = np.load(os.path.join(DATA_DIR, f))
    elif f.startswith("thresh_") and f.endswith(".npy"):
        name = f.split("thresh_")[1].split(".npy")[0]
        THRESHOLD_DB[name] = float(np.load(os.path.join(DATA_DIR, f)))

print(f"[INFO] Reloaded {len(FACE_DB)} faces and {len(THRESHOLD_DB)} thresholds.")

# -------------------------------------------------------------------------
# 🔧 Utility Functions
# -------------------------------------------------------------------------
def normalize(v):
    return v / np.linalg.norm(v) if np.linalg.norm(v) != 0 else v

def decode_base64_image(b64data):
    try:
        img_bytes = base64.b64decode(b64data)
        arr = np.frombuffer(img_bytes, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"[ERROR] decode_base64_image failed: {e}")
        return None

def preprocess_image(img):
    try:
        ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
        y, cr, cb = cv2.split(ycrcb)
        y_eq = cv2.equalizeHist(y)
        norm_img = cv2.cvtColor(cv2.merge((y_eq, cr, cb)), cv2.COLOR_YCrCb2BGR)
        return norm_img
    except Exception:
        return img

def align_face(img):
    """Use MTCNN to crop & align the largest face."""
    try:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = detector.detect_faces(rgb)
        if not results:
            return cv2.resize(rgb, (160, 160))
        x, y, w, h = results[0]["box"]
        x, y = max(0, x), max(0, y)
        cropped = rgb[y:y + h, x:x + w]
        return cv2.resize(cropped, (160, 160))
    except Exception as e:
        print(f"[WARN] Face alignment failed: {e}")
        return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (160, 160))

def get_face_embedding(img):
    """Generate normalized FaceNet embedding."""
    try:
        aligned = align_face(preprocess_image(img))
        emb = facenet.embeddings([aligned])[0]
        return normalize(emb)
    except Exception as e:
        print(f"[ERROR] Face embedding failed: {e}")
        return None

def cosine_sim(a, b):
    return float(np.dot(a, b))

# -------------------------------------------------------------------------
# 🧠 Liveness Detection (Sharpness + Motion)
# -------------------------------------------------------------------------
def compute_liveness_score(img):
    """Heuristic liveness score using sharpness and brightness variance."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    roi = gray[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)]

    # Sharpness (focus measure)
    lap_var = cv2.Laplacian(roi, cv2.CV_64F).var()
    sharpness_score = min(lap_var / 1000, 1.0)

    # Brightness variance (motion / dynamic lighting)
    std_intensity = np.std(roi)
    motion_score = min(std_intensity / 50.0, 1.0)

    # Combine
    liveness = (0.6 * motion_score) + (0.4 * sharpness_score)
    return round(min(max(liveness, 0.0), 1.0), 3)

# -------------------------------------------------------------------------
# 📦 Enroll User
# -------------------------------------------------------------------------
@app.route("/enroll", methods=["POST"])
def enroll():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    face_b64 = data.get("face")

    if not name or not face_b64:
        return jsonify({"error": "missing_name_or_face"}), 400

    print(f"[ENROLL] user='{name}' start")
    start = time.time()

    img = decode_base64_image(face_b64)
    if img is None:
        return jsonify({"error": "invalid_face_image"}), 400

    embeddings = []
    for variant in [img, cv2.flip(img, 1)]:
        emb = get_face_embedding(variant)
        if emb is not None:
            embeddings.append(emb)

    if not embeddings:
        return jsonify({"error": "no_face_detected"}), 400

    face_emb = normalize(np.mean(embeddings, axis=0))
    FACE_DB[name] = face_emb
    np.save(os.path.join(DATA_DIR, f"face_{name}.npy"), face_emb)

    THRESHOLD_DB[name] = 0.55
    np.save(os.path.join(DATA_DIR, f"thresh_{name}.npy"), np.array(THRESHOLD_DB[name]))

    print(f"[ENROLL] ✅ user='{name}' completed in {time.time() - start:.2f}s")
    return jsonify({"status": "enrolled", "success": True, "face_ok": True, "voice_enrolled": False})

# -------------------------------------------------------------------------
# 📦 Verify User
# -------------------------------------------------------------------------
@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    face_b64 = data.get("face")

    if not name or not face_b64:
        return jsonify({"error": "missing_name_or_face"}), 400
    if name not in FACE_DB:
        return jsonify({"error": "user_not_enrolled"}), 404

    img = decode_base64_image(face_b64)
    if img is None:
        return jsonify({"error": "invalid_face_image"}), 400

    live_face = get_face_embedding(img)
    if live_face is None:
        return jsonify({"error": "no_face_detected"}), 400

    face_sim = cosine_sim(live_face, FACE_DB[name])
    liveness_score = compute_liveness_score(img)
    final_conf = (face_sim * 0.8) + (liveness_score * 0.2)

    base_thresh = THRESHOLD_DB.get(name, 0.55)
    verdict = "REAL" if final_conf >= base_thresh else "FAKE"

    # Adaptive learning (with floor=0.45 and ceiling=0.75 to prevent drift)
    new_thresh = (base_thresh * 0.9) + (final_conf * 0.1)
    THRESHOLD_DB[name] = float(np.clip(new_thresh, 0.45, 0.75))
    np.save(os.path.join(DATA_DIR, f"thresh_{name}.npy"), np.array(THRESHOLD_DB[name]))

    print(f"[VERIFY] user='{name}' face={face_sim:.3f} live={liveness_score:.3f} "
          f"final={final_conf:.3f} threshold={THRESHOLD_DB[name]:.3f} verdict={verdict}")

    return jsonify({
        "user": name,
        "face_similarity": round(face_sim, 3),
        "liveness_score": round(liveness_score, 3),
        "final_confidence": round(final_conf, 3),
        "threshold": round(THRESHOLD_DB[name], 3),
        "verdict": verdict
    })

# -------------------------------------------------------------------------
# 🔥 Heatmap Visualization Route
# -------------------------------------------------------------------------
@app.route("/heatmap", methods=["POST"])
def generate_heatmap():
    """
    Generate a more detailed heatmap overlay of facial realism zones.
    Uses Laplacian variance + gradient maps to visualize facial texture intensity.
    """
    try:
        data = request.get_json(force=True)
        face_b64 = data.get("face")
        if not face_b64:
            return jsonify({"error": "missing_face"}), 400

        img = decode_base64_image(face_b64)
        if img is None:
            return jsonify({"error": "invalid_image"}), 400

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = detector.detect_faces(rgb)
        if not results:
            return jsonify({"error": "no_face_detected"}), 404

        x, y, w, h = results[0]["box"]
        x, y = max(0, x), max(0, y)
        face_crop = rgb[y:y + h, x:x + w]
        face_crop = cv2.resize(face_crop, (160, 160))

        # Compute edge + gradient intensity
        gray = cv2.cvtColor(face_crop, cv2.COLOR_RGB2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        grad = np.abs(lap)
        norm_grad = cv2.normalize(grad, None, 0, 255, cv2.NORM_MINMAX)

        # Combine gradient + brightness variance for realism mapping
        var_map = cv2.convertScaleAbs(norm_grad)
        heatmap = cv2.applyColorMap(var_map, cv2.COLORMAP_TURBO)
        overlay = cv2.addWeighted(face_crop, 0.6, heatmap, 0.5, 0)

        # Encode output
        _, buf = cv2.imencode(".jpg", cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))
        heatmap_b64 = base64.b64encode(buf).decode("utf-8")

        return jsonify({
            "heatmap": heatmap_b64,
            "heatmap_frame": heatmap_b64,
            "info": "Heatmap highlights high-texture (likely real) regions in red/yellow."
        })

    except Exception as e:
        print(f"[ERROR] Heatmap generation failed: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------------------
# 📦 Status Endpoint
# -------------------------------------------------------------------------
@app.route("/status", methods=["GET"])
def status():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "missing_name"}), 400
    return jsonify({
        "face_enrolled": name in FACE_DB,
        "threshold": THRESHOLD_DB.get(name, 0.55)
    })

# -------------------------------------------------------------------------
# 🚀 Run Server
# -------------------------------------------------------------------------
if __name__ == "__main__":
    print("[READY] 🚀 Enhanced Identity Manager running on http://127.0.0.1:7000")
    app.run(host="0.0.0.0", port=7000, debug=False)
