# DeepFakeHybrid 🔍

A **hybrid deepfake detection + identity verification system** for live video meetings.

It monitors Google Meet, Zoom, and Microsoft Teams via a Chrome extension and displays real-time REAL/FAKE verdicts by analyzing both video frames and audio — while also verifying that the face on screen matches the enrolled user.

---

## Architecture

```
Chrome Extension  →  Ingest Server (8765)  →  Flask Analyzer (5000)
                  →  Identity Manager (7000)
```

| Component | Port | Role |
|---|---|---|
| `server/server.py` | 5000 | Deepfake video+audio analysis (ONNX + fallback heuristics) |
| `server/identity_manager.py` | 7000 | Face enrollment + verification (FaceNet + MTCNN) |
| `server/ingest_server.py` | 8765 | CORS relay between extension and Flask |
| `extension/` | — | Chrome extension: captures video, shows verdict overlay |
| `client/client.py` | — | Optional desktop client (webcam-based) |

---

## Setup

### 1. Clone & create virtual environment
```bash
git clone https://github.com/YOUR_USERNAME/DeepFakeHybrid.git
cd DeepFakeHybrid
python -m venv venv
```

### 2. Activate & install dependencies
```bash
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Add ONNX models
Place your trained ONNX models in `server/models/`:
- `server/models/video_model.onnx` — deepfake video detection model
- `server/models/audio_model.onnx` — audio deepfake detection model

> If models are absent, the system automatically falls back to heuristic analyzers (motion + audio energy).

---

## Running

### One-click (Windows)
```bat
run.bat
```
This opens 3 separate server windows and starts all services.

### Manual
```bash
# Terminal 1 — DeepFake Analyzer
cd server && python server.py

# Terminal 2 — Identity Manager
cd server && python identity_manager.py

# Terminal 3 — Ingest Relay
cd server && python ingest_server.py
```

---

## Chrome Extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** → select the `extension/` folder
4. Join a Google Meet / Zoom / Teams meeting
5. The extension overlay will appear automatically in the top-right corner

**Popup features:**
- Enroll your face
- Manual verify
- View face similarity, liveness score, final confidence
- Generate heatmap visualization

---

## How It Works

1. **Frame capture** — The extension captures frames from the meeting video every ~2.5 seconds
2. **Audio capture** — Optional audio is extracted from the video stream
3. **Deepfake analysis** — Frames + audio are sent to the ingest server → Flask analyzer → ONNX models
4. **Identity verification** — Every ~5 ticks, a face frame is sent to identity manager for FaceNet verification
5. **Verdict display** — Results are shown as a colored overlay: 🟢 REAL / 🔴 FAKE

---

## Notes

- Enrolled face data (`.npy` files) is stored locally in `server/data/` — not uploaded
- ONNX model files are excluded from Git (too large) — obtain separately
- The `venv/` folder is excluded from Git — recreate it with `pip install -r requirements.txt`
