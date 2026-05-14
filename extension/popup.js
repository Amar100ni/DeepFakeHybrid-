// popup.js — Enhanced MeetingVerifier (Face + Liveness + Heatmap)

const INGEST_URL = "http://127.0.0.1:8765";  // Unified gateway for all requests
const IDENTITY_URL = "http://127.0.0.1:7000"; // For direct status updates
const STORAGE_KEY_NAME = "dfh_user_name";
const STORAGE_KEY_HEATMAP = "dfh_heatmap_enabled";

// ---------------------- 🔧 Storage Helpers ----------------------
async function getStorage(key) {
  return new Promise(res => chrome.storage.local.get([key], data => res(data[key])));
}
async function setStorage(key, val) {
  return new Promise(res => chrome.storage.local.set({ [key]: val }, res));
}
async function delStorage(key) {
  return new Promise(res => chrome.storage.local.remove([key], res));
}

// ---------------------- 🔄 Status Check ----------------------
async function updateStatus() {
  const name = await getStorage(STORAGE_KEY_NAME);
  document.getElementById("username").value = name || "";

  if (!name) {
    document.getElementById("statusText").textContent = "No user enrolled";
    return;
  }

  try {
    const r = await fetch(`${IDENTITY_URL}/status?name=${encodeURIComponent(name)}`);
    const data = await r.json();
    if (data.face_enrolled) {
      document.getElementById("statusText").textContent =
        `Enrolled | Threshold: ${data.threshold?.toFixed(2)}`;
    } else {
      document.getElementById("statusText").textContent = "Not enrolled yet";
    }
  } catch {
    document.getElementById("statusText").textContent = "Server offline";
  }
}

// ---------------------- 🧠 Enrollment ----------------------
async function enrollUser() {
  const name = document.getElementById("username").value.trim();
  if (!name) return alert("Please enter your name first.");
  await setStorage(STORAGE_KEY_NAME, name);

  document.getElementById("result").textContent = "📸 Capturing face for enrollment...";

  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func: async (name) => {
        const WIDTH = 224, HEIGHT = 224;
        const video = document.querySelector("video");
        if (!video) return "No video found";

        const canvas = document.createElement("canvas");
        canvas.width = WIDTH; canvas.height = HEIGHT;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);

        const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.7));
        const buf = await blob.arrayBuffer();
        const face_b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));

        const res = await fetch(`${IDENTITY_URL}/enroll`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, face: face_b64 })
        });
        return await res.json();
      },
      args: [name]
    }, (res) => {
      const result = res[0]?.result || res[0];
      document.getElementById("result").textContent = "Enrollment complete";
      updateStatus();
      console.log("Enrollment Result:", result);
    });
  });
}

// ---------------------- 🔍 Verification ----------------------
async function verifyUser() {
  const name = document.getElementById("username").value.trim();
  if (!name) return alert("Enter your name first!");
  document.getElementById("result").textContent = "🔍 Verifying face...";

  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func: async (name) => {
        const WIDTH = 224, HEIGHT = 224;
        const video = document.querySelector("video");
        if (!video || video.readyState < 2) return { error: "No valid video frame" };

        const canvas = document.createElement("canvas");
        canvas.width = WIDTH;
        canvas.height = HEIGHT;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);

        const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.7));
        const buf = await blob.arrayBuffer();
        const face_b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));

        const res = await fetch(`${IDENTITY_URL}/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, face: face_b64 })
        });

        const data = await res.json();
        return data;
      },
      args: [name]
    }, (res) => {
      const data = res[0]?.result || res[0];
      if (!data) {
        document.getElementById("result").textContent = "Verification failed";
        return;
      }

      // 🧾 Update UI metrics
      document.getElementById("faceSim").textContent = data.face_similarity ?? "--";
      document.getElementById("liveScore").textContent = data.liveness_score ?? "--";
      document.getElementById("finalConf").textContent = data.final_confidence ?? "--";

      const verdictBox = document.getElementById("verdictText");
      verdictBox.textContent = `Verdict: ${data.verdict}`;
      verdictBox.className = "verdict " + (data.verdict === "REAL" ? "real" : "fake");

      document.getElementById("result").textContent = "Verification Complete";
      console.log("Verification Result:", data);
    });
  });
}

// ---------------------- 🌈 Generate Heatmap ----------------------
async function showHeatmap() {
  document.getElementById("result").textContent = "Generating heatmap...";

  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func: async () => {
        const WIDTH = 224, HEIGHT = 224;
        const video = document.querySelector("video");
        if (!video || video.readyState < 2) return { error: "No valid video frame" };

        const canvas = document.createElement("canvas");
        canvas.width = WIDTH;
        canvas.height = HEIGHT;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);

        const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.7));
        const buf = await blob.arrayBuffer();
        const face_b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
        return face_b64;
      }
    }, async (res) => {
      const face_b64 = res[0]?.result;
      if (!face_b64) {
        document.getElementById("result").textContent = "Failed to capture frame";
        return;
      }

      try {
        const r = await fetch(`${INGEST_URL}/heatmap`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ face: face_b64 })
        });
        const data = await r.json();

        if (data.heatmap || data.heatmap_frame) {
          const imgData = data.heatmap || data.heatmap_frame;
          const imgElem = document.getElementById("heatmapImg");
          imgElem.src = "data:image/jpeg;base64," + imgData;
          imgElem.style.display = "block";
          document.getElementById("result").textContent = "Heatmap generated!";
        } else {
          document.getElementById("result").textContent = "No heatmap data received.";
        }
      } catch (err) {
        console.error(err);
        document.getElementById("result").textContent = "Heatmap generation failed.";
      }
    });
  });
}

// ---------------------- 🔥 Heatmap Toggle ----------------------
async function toggleHeatmap() {
  const current = await getStorage(STORAGE_KEY_HEATMAP);
  const newVal = !current;
  await setStorage(STORAGE_KEY_HEATMAP, newVal);
  document.getElementById("result").textContent =
    `Heatmap ${newVal ? "enabled" : "disabled"}`;
}

// ---------------------- ♻️ Reset User ----------------------
async function resetUser() {
  await delStorage(STORAGE_KEY_NAME);
  document.getElementById("username").value = "";
  document.getElementById("statusText").textContent = "User reset";
  document.getElementById("result").textContent = "";
  document.getElementById("faceSim").textContent = "--";
  document.getElementById("liveScore").textContent = "--";
  document.getElementById("finalConf").textContent = "--";
  document.getElementById("verdictText").textContent = "Verdict: --";
  document.getElementById("verdictText").className = "verdict";
  document.getElementById("heatmapImg").style.display = "none";
}

// ---------------------- 🧩 Event Listeners ----------------------
document.getElementById("btnEnroll").addEventListener("click", enrollUser);
document.getElementById("btnVerify").addEventListener("click", verifyUser);
document.getElementById("btnShowHeatmap").addEventListener("click", showHeatmap);
document.getElementById("btnToggleHeatmap").addEventListener("click", toggleHeatmap);
document.getElementById("btnReset").addEventListener("click", resetUser);

updateStatus();
