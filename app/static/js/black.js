"use strict";
window.BlackoutBlack = (function () {
  const STORAGE_KEY = "blackout_active_session_id";
  let sessionId = "";
  let sessionGoal = "";
  let socket = null;
  let capture = null;
  let recorder = null;
  let mode = "realtime";
  let paused = false;
  let finishing = false;
  let entered = false;
  let readySeen = false;
  let fallbackSeen = false;
  let intentionalClose = false;
  let wasFullscreen = false;
  let skipFullscreen = false;
  let wakeLock = null;
  let resumedEntry = false;
  let speechEpoch = 0;
  let speechChain = Promise.resolve();
  let ttsPlaying = false;
  let readyTimer = 0;
  let pollTimer = 0;
  let hintTimer = 0;
  let hintRemoveTimer = 0;
  let longPressTimer = 0;
  let suppressTapUntil = 0;
  let pttRecording = false;
  let pttStarting = false;
  let flowGeneration = 0;
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function serverErrorText(data) {
    if (data && data.error && data.error.code) {
      const key = "error_" + String(data.error.code);
      if (window.BlackoutI18n.has(key)) { return t(key); }
    }
    return t("didntCatch");
  }
  function showBlack() {
    el("page-start").hidden = true;
    el("page-result").hidden = true;
    el("page-black").hidden = false;
  }
  function showStart() {
    el("page-black").hidden = true;
    el("page-result").hidden = true;
    el("page-start").hidden = false;
    document.dispatchEvent(new CustomEvent("blackout:restart"));
  }
  function setDot(state) { el("dot").className = "dot " + state; }
  function sendJson(payload) {
    try { if (socket && socket.readyState === WebSocket.OPEN) { socket.send(JSON.stringify(payload)); } } catch (e) {}
  }
  function applyMuted() {
    if (capture) { capture.setMuted(paused); }
  }
  function say(text, kind) {
    const epoch = speechEpoch;
    const spoken = String(text || "");
    if (!spoken) { return Promise.resolve(); }
    speechChain = speechChain.then(async function () {
      if (epoch !== speechEpoch || !entered) {
        if (mode === "realtime") { sendJson({ type: "tts_finished" }); }
        return;
      }
      if (kind === "announcement") { window.BlackoutCues.chime(); }
      ttsPlaying = true;
      applyMuted();
      setDot("speaking");
      if (mode === "realtime") { sendJson({ type: "tts_started", text: spoken }); }
      try { await window.BlackoutSpeech.speak(spoken); }
      finally {
        if (mode === "realtime") { sendJson({ type: "tts_finished" }); }
        ttsPlaying = false;
        if (entered && !finishing) { setDot(paused ? "paused" : "listening"); }
        applyMuted();
      }
    });
    return speechChain;
  }
  function cutOffSpeech() {
    speechEpoch += 1;
    window.BlackoutSpeech.cancel();
  }
  async function requestWakeLock() {
    try { if (navigator.wakeLock && navigator.wakeLock.request) { wakeLock = await navigator.wakeLock.request("screen"); } } catch (e) {}
  }
  async function releaseWakeLock() {
    try { if (wakeLock && wakeLock.release) { await wakeLock.release(); } } catch (e) {}
    wakeLock = null;
  }
  async function requestFullscreen() {
    if (skipFullscreen) { return; }
    try {
      if (document.documentElement.requestFullscreen && !document.fullscreenElement) { await document.documentElement.requestFullscreen(); }
      if (document.fullscreenElement) { wasFullscreen = true; }
    } catch (e) {}
  }
  async function leaveFullscreen() {
    try { if (document.exitFullscreen && document.fullscreenElement) { await document.exitFullscreen(); } } catch (e) {}
  }
  function resetHint() {
    window.clearTimeout(hintTimer);
    window.clearTimeout(hintRemoveTimer);
    let hint = el("hint");
    if (!hint) {
      hint = document.createElement("div");
      hint.id = "hint";
      hint.className = "hint";
      el("page-black").appendChild(hint);
    }
    hint.textContent = t("blackHint");
    hint.classList.remove("fading");
    hintTimer = window.setTimeout(function () {
      hint.classList.add("fading");
      hintRemoveTimer = window.setTimeout(function () { if (hint.parentNode) { hint.parentNode.removeChild(hint); } }, 1100);
    }, 5000);
  }
  function stopPolling() { window.clearInterval(pollTimer); pollTimer = 0; }
  async function stopCapture() {
    if (capture) { const current = capture; capture = null; await current.stop(); }
    if (recorder) {
      const currentRecorder = recorder;
      recorder = null;
      pttRecording = false;
      pttStarting = false;
      await currentRecorder.cancel();
    }
  }
  function closeSocket() {
    intentionalClose = true;
    window.clearTimeout(readyTimer);
    if (socket) { const current = socket; socket = null; try { current.close(); } catch (e) {} }
  }
  async function returnToStartForPermission() {
    flowGeneration += 1;
    await stopCapture();
    closeSocket();
    stopPolling();
    entered = false;
    await leaveFullscreen();
    await releaseWakeLock();
    showStart();
    window.BlackoutSpeech.speak(t("permissionLine"));
  }
  function isPermissionError(error) {
    return Boolean(error && (error.name === "NotAllowedError" || error.name === "SecurityError"));
  }
  async function startRealtimeCapture(gen) {
    capture = window.BlackoutCapture.createStreamCapture(function (frame) {
      try { if (socket && socket.readyState === WebSocket.OPEN && mode === "realtime") { socket.send(frame); } } catch (e) {}
    });
    applyMuted();
    try {
      const opened = await capture.start();
      if (!opened || gen !== flowGeneration || !entered) { await stopCapture(); return; }
    } catch (e) {
      if (gen !== flowGeneration || !entered) { return; }
      if (isPermissionError(e)) { await returnToStartForPermission(); } else { handleFallback(t("fallbackLine")); }
    }
  }
  function pollAnnouncements() {
    stopPolling();
    pollTimer = window.setInterval(async function () {
      if (!entered || mode !== "ptt" || finishing) { return; }
      try {
        const response = await fetch("/api/sessions/" + sessionId + "/announcements", { method: "POST" });
        if (!response.ok) { return; }
        const data = await response.json();
        (data.announcements || []).forEach(function (item) { if (item && item.text) { say(String(item.text), String(item.kind || "announcement")); } });
      } catch (e) {}
    }, 5000);
  }
  function handleFallback(message) {
    if (fallbackSeen || finishing || !entered) { return; }
    fallbackSeen = true;
    mode = "ptt";
    window.clearTimeout(readyTimer);
    if (capture) { const current = capture; capture = null; current.stop(); }
    closeSocket();
    setDot("listening");
    pollAnnouncements();
    say(String(message || t("fallbackLine")), "reply");
  }
  function onSocketMessage(event) {
    let data = null;
    try { data = JSON.parse(String(event.data)); } catch (e) { return; }
    if (!data || !data.type) { return; }
    if (data.type === "ready") {
      readySeen = true;
      window.clearTimeout(readyTimer);
      setDot("listening");
      startRealtimeCapture(flowGeneration);
      say(resumedEntry ? t("resumeLine") : t("entryLine"), "reply");
    } else if (data.type === "say") {
      say(String(data.text || ""), String(data.kind || "reply"));
    } else if (data.type === "tick") {
      window.BlackoutCues.tick();
    } else if (data.type === "stop_speech") {
      if (ttsPlaying || window.BlackoutSpeech.speaking()) { cutOffSpeech(); }
    } else if (data.type === "end") {
      endSession(String(data.reason || "phrase"));
    } else if (data.type === "fallback") {
      handleFallback(t("fallbackLine"));
    } else if (data.type === "reconnecting") {
      setDot("reconnecting");
    }
  }
  function connectSocket() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(scheme + "//" + window.location.host + "/ws/sessions/" + sessionId);
    socket.binaryType = "arraybuffer";
    socket.onmessage = onSocketMessage;
    socket.onerror = function () { if (!intentionalClose && !fallbackSeen && !finishing) { handleFallback(t("fallbackLine")); } };
    socket.onclose = function () { if (!intentionalClose && !fallbackSeen && !finishing && entered) { handleFallback(t("fallbackLine")); } };
    readyTimer = window.setTimeout(function () { if (!readySeen && !fallbackSeen && entered) { handleFallback(t("fallbackLine")); } }, 8000);
  }
  async function togglePause() {
    paused = !paused;
    if (paused) { sendJson({ type: "pause" }); window.BlackoutCues.fall(); setDot("paused"); }
    else { sendJson({ type: "resume" }); window.BlackoutCues.rise(); setDot("listening"); }
    applyMuted();
  }
  async function startPtt() {
    if (pttRecording || pttStarting || finishing) { return; }
    pttStarting = true;
    recorder = window.BlackoutCapture.createWavRecorder();
    const gen = flowGeneration;
    try {
      const opened = await recorder.start();
      if (!opened || gen !== flowGeneration || !entered) {
        if (recorder) { await recorder.cancel(); recorder = null; }
        pttStarting = false;
        return;
      }
      pttRecording = true;
      pttStarting = false;
      window.BlackoutCues.rise();
      setDot("speaking");
    } catch (e) {
      pttStarting = false;
      recorder = null;
      if (isPermissionError(e)) { await returnToStartForPermission(); }
    }
  }
  async function stopPtt() {
    if (!pttRecording || !recorder) { return; }
    pttRecording = false;
    const current = recorder;
    recorder = null;
    window.BlackoutCues.fall();
    setDot("listening");
    const wav = await current.stop();
    if (!entered || finishing) { return; }
    const form = new FormData();
    form.append("audio", wav, "speech.wav");
    let response = null;
    let data = null;
    try {
      response = await fetch("/api/sessions/" + sessionId + "/turns", { method: "POST", body: form });
      data = await response.json();
    } catch (e) { say(t("didntCatch"), "reply"); return; }
    if (!response.ok) {
      if (response.status === 402) { endSession("budget"); return; }
      say(serverErrorText(data), "reply");
      return;
    }
    if (data.budget_exhausted) { endSession("budget"); return; }
    if (data.end) { endSession("phrase"); return; }
    if (data.action === "listen" || !data.reply) { window.BlackoutCues.tick(); } else { say(String(data.reply), "reply"); }
  }
  function toggleAction() {
    if (!entered || finishing) { return; }
    if (ttsPlaying || window.BlackoutSpeech.speaking()) { cutOffSpeech(); return; }
    if (mode === "ptt") { if (pttRecording) { stopPtt(); } else { startPtt(); } return; }
    togglePause();
  }
  async function attemptFinish() {
    window.BlackoutResult.showPending(sessionGoal);
    let result = null;
    try {
      const response = await fetch("/api/sessions/" + sessionId + "/finish", { method: "POST" });
      const data = await response.json();
      if (!response.ok) { throw new Error(serverErrorText(data)); }
      result = data;
    } catch (e) {
      window.BlackoutResult.showFinishError(attemptFinish);
      return;
    }
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) {}
    entered = false;
    window.BlackoutResult.showResult(result, sessionId, { read: true });
  }
  async function endSession(reason) {
    if (finishing || !entered) { return; }
    finishing = true;
    flowGeneration += 1;
    stopPolling();
    window.clearTimeout(readyTimer);
    window.clearTimeout(hintTimer);
    window.clearTimeout(hintRemoveTimer);
    cutOffSpeech();
    await stopCapture();
    closeSocket();
    const line = reason === "budget" ? t("budgetLine") : t("endingLine");
    const spoken = window.BlackoutSpeech.speak(line);
    spoken.catch(function () {});
    await leaveFullscreen();
    await releaseWakeLock();
    await attemptFinish();
  }
  async function enter(id, resumed, goal, options) {
    sessionId = String(id);
    sessionGoal = String(goal || "");
    resumedEntry = Boolean(resumed);
    skipFullscreen = Boolean(options && options.skipFullscreen);
    mode = "realtime";
    paused = false;
    finishing = false;
    entered = true;
    readySeen = false;
    fallbackSeen = false;
    intentionalClose = false;
    wasFullscreen = false;
    speechEpoch += 1;
    speechChain = Promise.resolve();
    ttsPlaying = false;
    flowGeneration += 1;
    try { window.localStorage.setItem(STORAGE_KEY, sessionId); } catch (e) {}
    window.BlackoutResult.setSession(sessionId);
    showBlack();
    setDot("reconnecting");
    resetHint();
    requestFullscreen();
    requestWakeLock();
    connectSocket();
  }
  function stopForUnload() {
    flowGeneration += 1;
    stopPolling();
    cutOffSpeech();
    if (capture) { capture.stop(); capture = null; }
    if (recorder) { recorder.cancel(); recorder = null; }
    closeSocket();
  }
  function init() {
    document.addEventListener("keydown", function (event) {
      if (el("page-black").hidden) { return; }
      if (event.code === "Space") {
        if (event.repeat) { return; }
        event.preventDefault();
        toggleAction();
      } else if (event.key === "Escape") {
        event.preventDefault();
        endSession("phrase");
      }
    });
    el("page-black").addEventListener("click", function () {
      if (Date.now() < suppressTapUntil) { return; }
      toggleAction();
    });
    el("page-black").addEventListener("touchstart", function () {
      window.clearTimeout(longPressTimer);
      longPressTimer = window.setTimeout(function () { suppressTapUntil = Date.now() + 700; endSession("phrase"); }, 800);
    }, { passive: true });
    el("page-black").addEventListener("touchend", function () { window.clearTimeout(longPressTimer); }, { passive: true });
    document.addEventListener("fullscreenchange", function () {
      if (document.fullscreenElement) { wasFullscreen = true; return; }
      if (wasFullscreen && entered && !el("page-black").hidden && !finishing) { endSession("phrase"); }
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && entered && !el("page-black").hidden) { requestWakeLock(); }
    });
    window.addEventListener("beforeunload", stopForUnload);
    window.addEventListener("pagehide", stopForUnload);
  }
  document.addEventListener("DOMContentLoaded", init);
  return { enter: enter, endSession: endSession };
})();
