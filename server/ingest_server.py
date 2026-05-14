# server/ingest_server.py
import json
from aiohttp import web, ClientSession

# -----------------------------
# 🔗 Target backend endpoints
# -----------------------------
FLASK_ANALYZE_URL = "http://127.0.0.1:5000/analyze"       # DeepFake Analyzer
IDENTITY_HEATMAP_URL = "http://127.0.0.1:7000/heatmap"    # Identity Manager heatmap

# --------------------------------------------------------------------
# 🧩 CORS Middleware
# --------------------------------------------------------------------
@web.middleware
async def cors_middleware(request, handler):
    """Allow cross-origin requests from extension."""
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

# --------------------------------------------------------------------
# 📡 Route Table
# --------------------------------------------------------------------
routes = web.RouteTableDef()

@routes.get("/")
async def health_check(request):
    """Simple health check."""
    return web.Response(text="Ingest server is running!", content_type="text/plain")

# --------------------------------------------------------------------
# 🎥 /receive_chunk — Forwards video/audio data to analyzer
# --------------------------------------------------------------------
@routes.post("/receive_chunk")
async def receive_chunk(request: web.Request):
    """Receive captured meeting frames + optional audio, forward to analyzer."""
    try:
        body = await request.json()
    except Exception as e:
        return web.json_response({"error": f"invalid_json: {e}"}, status=400)

    frames = body.get("frames") or []
    audio_b64 = body.get("audio")
    motion_flag = bool(body.get("motion_flag", True))

    if not isinstance(frames, list) or len(frames) == 0:
        return web.json_response({"error": "no_frames"}, status=400)

    payload = {"frames": frames, "audio": audio_b64, "motion_flag": motion_flag}

    async with ClientSession() as sess:
        try:
            async with sess.post(FLASK_ANALYZE_URL, json=payload, timeout=60) as resp:
                text = await resp.text()
                status = resp.status
                r = web.Response(text=text, status=status, content_type="application/json")
                r.headers["Access-Control-Allow-Origin"] = "*"
                r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
                return r
        except Exception as e:
            return web.json_response({"error": f"forward_failed: {e}"}, status=502)

# --------------------------------------------------------------------
# 🌈 /heatmap — Forward base64 image to identity manager for heatmap
# --------------------------------------------------------------------
@routes.post("/heatmap")
async def forward_heatmap(request: web.Request):
    """
    Accepts:
      {
        "face": "<base64_jpeg>"
      }

    Forwards to Identity Manager’s /heatmap endpoint and returns heatmap result.
    """
    try:
        data = await request.json()
    except Exception as e:
        return web.json_response({"error": f"invalid_json: {e}"}, status=400)

    if "face" not in data:
        return web.json_response({"error": "missing_face"}, status=400)

    async with ClientSession() as sess:
        try:
            async with sess.post(IDENTITY_HEATMAP_URL, json=data, timeout=30) as resp:
                text = await resp.text()
                status = resp.status
                r = web.Response(text=text, status=status, content_type="application/json")
                r.headers["Access-Control-Allow-Origin"] = "*"
                r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
                return r
        except Exception as e:
            return web.json_response({"error": f"heatmap_forward_failed: {e}"}, status=502)

# --------------------------------------------------------------------
# ⚙️ Main App Entrypoint
# --------------------------------------------------------------------
def main():
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)
    print("[INFO] 🚀 Ingest server started at http://127.0.0.1:8765")
    print("       ↳ Forwards /receive_chunk → analyzer (port 5000)")
    print("       ↳ Forwards /heatmap → identity manager (port 7000)")
    web.run_app(app, host="127.0.0.1", port=8765)

if __name__ == "__main__":
    main()
