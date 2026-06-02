// content_script.js — Auto-enroll + Auto-verify + Breakdown + Heatmap
(function () {
  const INGEST_URL   = "http://127.0.0.1:8765/receive_chunk";  // relay -> Flask /analyze
  const HEATMAP_URL  = "http://127.0.0.1:5000/heatmap";        // Flask /heatmap
  const ID_URL_BASE  = "http://127.0.0.1:7000";                // Identity Manager base

  const CAPTURE_WINDOW_SEC = 1.5;
  const ENROLL_SEC = 2.0;
  const FRAME_RATE = 6;
  const WIDTH = 224, HEIGHT = 224;

  console.log("[MeetingVerifier] content_script loaded");

  // ------------------ storage helpers (chrome.storage with fallback) ------------------
  const storage = {
    async get(key, def = null) {
      try {
        return await new Promise(res => {
          chrome.storage?.local?.get([key], obj => res(obj?.[key] ?? def));
        });
      } catch {
        try { return JSON.parse(localStorage.getItem(key)) ?? def; } catch { return def; }
      }
    },
    async set(key, val) {
      try {
        return await new Promise(res => chrome.storage?.local?.set({ [key]: val }, res));
      } catch {
        localStorage.setItem(key, JSON.stringify(val));
      }
    }
  };

  // ------------------ small UI panel ------------------
  const panel = document.createElement("div");
  panel.style.position = "fixed";
  panel.style.top = "10px";
  panel.style.right = "10px";
  panel.style.padding = "12px 16px";
  panel.style.background = "rgba(0,0,0,0.75)";
  panel.style.color = "#fff";
  panel.style.fontFamily = "Arial, sans-serif";
  panel.style.borderRadius = "10px";
  panel.style.width = "250px";
  panel.style.zIndex = 999999;
  panel.style.fontSize = "14px";
  panel.innerHTML = `
    <div id="hdr" style="font-weight:bold;font-size:18px;">Analyzing...</div>
    <div style="margin-top:6px;">
      User: <span id="uname">--</span><br/>
      Face Realism: <span id="vs">--</span><br/>
      Voice Authenticity: <span id="as">--</span><br/>
      Lip-Sync: <span id="mf">--</span>
    </div>
    <div id="enroll" style="margin-top:8px; font-size:12px; opacity:0.9;"></div>
  `;
  document.body.appendChild(panel);

  function setVerdict(v, conf) {
    const hdr = panel.querySelector("#hdr");
    hdr.textContent = `${v} ${conf != null ? "(" + (conf*100).toFixed(1) + "%)" : ""}`;
    if (v === "REAL") {
      hdr.style.color = "#00FF72";
      panel.style.background = "rgba(0,60,0,0.75)";
    } else if (v === "FAKE") {
      hdr.style.color = "#FF4D4D";
      panel.style.background = "rgba(90,0,0,0.75)";
    } else {
      hdr.style.color = "#FFFFFF";
      panel.style.background = "rgba(0,0,0,0.75)";
    }
  }

  function setEnrollMsg(msg) {
    panel.querySelector("#enroll").textContent = msg || "";
  }

  // ------------------ utils ------------------
  function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
  function arrayBufferToBase64(buf) {
    let binary = '', bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  function findVideos() {
    const vids = Array.from(document.querySelectorAll("video")).filter(v => {
      const rect = v.getBoundingClientRect();
      return rect.width > 80 && rect.height > 80 && getComputedStyle(v).visibility !== "hidden";
    });
    vids.sort((a,b)=>(b.videoWidth*b.videoHeight)-(a.videoWidth*a.videoHeight));
    return vids;
  }

  async function captureFrames(videoEl, sec = CAPTURE_WINDOW_SEC, fps = FRAME_RATE) {
    const frames = [];
    const canvas = document.createElement("canvas");
    canvas.width = WIDTH; canvas.height = HEIGHT;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const total = Math.max(1, Math.floor(sec * fps));
    for (let i=0;i<total;i++){
      try{
        ctx.drawImage(videoEl, 0, 0, WIDTH, HEIGHT);
        const blob = await new Promise(res=>canvas.toBlob(res,"image/jpeg",0.6));
        const buf = await blob.arrayBuffer();
        frames.push(arrayBufferToBase64(buf));
      }catch(e){ console.warn("[MV] frame err", e); }
      await sleep(1000/fps);
    }
    return frames;
  }

  async function captureAudioFromVideo(videoEl, sec){
    try{
      if(!videoEl.captureStream) return null;
      const stream = videoEl.captureStream();
      if(!stream || stream.getAudioTracks().length===0) return null;
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm" }); // WEBM/OPUS
      const chunks = [];
      rec.ondataavailable = e => { if(e.data && e.data.size) chunks.push(e.data); };
      const done = new Promise(res => rec.onstop = res);
      rec.start();
      await sleep(sec*1000);
      rec.stop();
      await done;
      const blob = new Blob(chunks, { type: "audio/webm" });
      const buf = await blob.arrayBuffer();
      return arrayBufferToBase64(buf); // NOTE: identity server treats audio as optional
    }catch(e){
      console.warn("[MV] audio capture failed", e);
      return null;
    }
  }

  function showHeatmapOverlay(b64) {
    const img = document.createElement("img");
    img.src = "data:image/jpeg;base64," + b64;
    img.style.position = "fixed";
    img.style.top = "0"; img.style.left = "0";
    img.style.width = "100%"; img.style.height = "100%";
    img.style.opacity = "0.22";
    img.style.zIndex = "9999";
    document.body.appendChild(img);
    setTimeout(()=>img.remove(), 1300);
  }

  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts);
    const t = await r.text();
    try { return JSON.parse(t); } catch { return t; }
  }

  // ------------------ name handling ------------------
  async function resolveUserName() {
    // Try stored value first
    let name = await storage.get("dfh_user_name", null);
    if (name) return name;

    // Try to guess from DOM (Meet changes often, so we keep it simple)
    let guess = null;
    try {
      const els = Array.from(document.querySelectorAll("[aria-label]"));
      const mine = els.find(e => /you|your/i.test(e.getAttribute("aria-label")));
      if (mine) guess = mine.getAttribute("aria-label").replace(/\(You\)/i,'').trim();
    } catch {}

    // Ask user if not found
    if (!guess) {
      guess = prompt("Enter your display name for identity enrollment:", "user");
    }
    if (!guess) guess = "user";

    await storage.set("dfh_user_name", guess);
    return guess;
  }

  // ------------------ auto-enroll logic ------------------
  async function ensureEnrolled(name, videoEl) {
    try {
      // Check server status
      const stat = await fetchJSON(`${ID_URL_BASE}/status?name=${encodeURIComponent(name)}`);
      if (stat && stat.face_enrolled) {
        setEnrollMsg(`Enrolled ✓ (voice: ${stat.voice_enrolled ? "yes" : "no"})`);
        return true;
      }

      // Not enrolled -> capture short clip for face (and optional audio)
      setEnrollMsg("Enrolling... capturing 3s sample");
      const frames = await captureFrames(videoEl, ENROLL_SEC, FRAME_RATE);
      if (frames.length === 0) {
        setEnrollMsg("Enroll failed: no frames");
        return false;
      }
      const face_b64 = frames[Math.floor(frames.length/2)]; // pick a mid frame
      const audio_b64 = await captureAudioFromVideo(videoEl, ENROLL_SEC); // may be null

      const body = { name, face: face_b64 };
      if (audio_b64) body.audio = audio_b64;

      const res = await fetchJSON(`${ID_URL_BASE}/enroll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });

      if (res && (res.status === "enrolled" || res.success === true)) {
        await storage.set("dfh_enrolled", true);
        setEnrollMsg(`Enrolled ✓ (voice: ${res.voice_enrolled ? "yes" : "no"})`);
        return true;
      } else {
        setEnrollMsg(`Enroll failed: ${JSON.stringify(res)}`);
        return false;
      }
    } catch (e) {
      console.warn("[MV] enroll error", e);
      setEnrollMsg("Enroll failed (server not reachable?)");
      return false;
    }
  }

  // ------------------ main loop ------------------
  async function main() {
    const name = await resolveUserName();
    panel.querySelector("#uname").textContent = name;

    // wait for a visible video
    let video = null;
    for (let i=0;i<30;i++){
      const vids = findVideos();
      if (vids.length) { video = vids[0]; break; }
      setVerdict("Waiting for video...", null);
      await sleep(500);
    }
    if (!video) {
      setVerdict("No video stream", null);
      return;
    }

    // auto-enroll once if needed
    await ensureEnrolled(name, video);

    // analysis + verification loop
    let tick = 0;
    while (true) {
      try {
        // Capture frames and audio concurrently for speed
        const [frames, audio_b64] = await Promise.all([
          captureFrames(video),
          captureAudioFromVideo(video, CAPTURE_WINDOW_SEC)
        ]);

        // send to analyzer (deepfake)
        const payload = { frames, audio: audio_b64, motion_flag: true };
        const ana = await fetchJSON(INGEST_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (ana && ana.verdict) {
          setVerdict(ana.verdict, ana.confidence ?? null);
          panel.querySelector("#vs").textContent = ana.video_score != null ? (ana.video_score*100).toFixed(1)+"%" : "--";
          panel.querySelector("#as").textContent = ana.audio_score != null ? (ana.audio_score*100).toFixed(1)+"%" : "--";
          panel.querySelector("#mf").textContent = ana.motion_flag ? "Synced" : "Desync";
        } else {
          setVerdict("Analyzing...", null);
        }

        // heatmap (optional)
        if (frames.length > 0) {
          fetch(HEATMAP_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ frame: frames[0] })
          })
          .then(r => r.json())
          .then(h => { if (h && (h.heatmap || h.heatmap_frame)) showHeatmapOverlay(h.heatmap || h.heatmap_frame); })
          .catch(()=>{});
        }

        // every ~5s, verify identity (face required, audio optional)
        tick += 1;
        if (tick % 6 === 0) {
          const verifyBody = { name, face: frames[Math.floor(frames.length/2)] };
          if (audio_b64) verifyBody.audio = audio_b64;
          fetchJSON(`${ID_URL_BASE}/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(verifyBody)
          }).then(v => {
            if (v && v.verdict) {
              // we could also reflect identity verdict in UI:
              // e.g., append " | ID: REAL/FAKE" to header
              const hdr = panel.querySelector("#hdr");
              hdr.textContent += `  |  ID:${v.verdict} ${(v.final_confidence*100).toFixed(0)}%`;
            }
          }).catch(()=>{ /* ignore */ });
        }

      } catch (e) {
        console.warn("[MeetingVerifier] loop error", e);
        setVerdict("⚠️ Connection Lost", null);
      }
      await sleep(400);
    }
  }

  main().catch(e => console.error("[MeetingVerifier] crashed", e));
})();
