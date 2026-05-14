// background.js
chrome.runtime.onInstalled.addListener(() => {
  console.log("[MeetingVerifier] Installed and background service active.");
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log("[MeetingVerifier] Message received:", message);
  sendResponse({ ok: true });
});
