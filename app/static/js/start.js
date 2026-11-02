"use strict";
window.BlackoutStart = (function () {
  const STORAGE_KEY = "blackout_active_session_id";
  const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
  let goalRecorder = null;
  let goalRecording = false;
  let goalStarting = false;
  let starting = false;
  let startGeneration = 0;
  let pastOpen = false;
  let pastCount = 0;
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function errorMessage(data) {
    if (data && data.error && data.error.code) {
      const key = "error_" + String(data.error.code);
      if (window.BlackoutI18n.has(key)) { return t(key); }
    }
    if (data && data.error && data.error.message) { return String(data.error.message); }
    return t("networkError");
  }
  function primeAudio() {
    window.BlackoutCues.ensure();
    if (window.BlackoutCapture && window.BlackoutCapture.prime) { window.BlackoutCapture.prime(); }
    window.BlackoutSpeech.prime();
  }
  function setStartButtonsDisabled(disabled) {
    ["startBtn", "continueLastBtn", "micBtn", "langToggle"].forEach(function (id) {
      const node = el(id);
      if (node) { node.disabled = disabled; }
    });
  }
  async function ensureMic(generation) {
    try { await window.BlackoutCapture.ensurePermission(); }
    catch (e) {
      if (generation !== startGeneration) { return false; }
      if (e && e.name === "NotFoundError") { el("startErr").textContent = t("noMic"); }
      else { el("startErr").textContent = t("micNeeded"); }
      return false;
    }
    return generation === startGeneration;
  }
  function storedId() {
    try { return window.localStorage.getItem(STORAGE_KEY) || ""; } catch (e) { return ""; }
  }
  function clearStored() {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  }
  async function fetchJson(url, options) {
    const response = await fetch(url, options || {});
    const data = await response.json();
    if (!response.ok) {
      const failure = new Error(errorMessage(data));
      if (data && data.error && data.error.code) { failure.code = String(data.error.code); }
      failure.status = response.status;
      throw failure;
    }
    return data;
  }
  function applySessionLanguage(record) {
    const value = record && String(record.language || "");
    if (value === "zh" || value === "en") { window.BlackoutI18n.set(value, false); }
    updateLangChrome();
  }
  async function openFinished(id) {
    const record = await fetchJson("/api/sessions/" + id);
    if (record.result) {
      applySessionLanguage(record);
      clearStored();
      const result = record.result;
      if (!result.poster && record.poster) { result.poster = record.poster; }
      if (!result.map && record.map) { result.map = record.map; }
      window.BlackoutResult.showResult(result, id);
      window.scrollTo(0, 0);
    }
  }
  async function enterActive(id, resumed, goal) {
    if (starting) { return; }
    starting = true;
    const generation = ++startGeneration;
    primeAudio();
    setStartButtonsDisabled(true);
    try {
      if (!await ensureMic(generation)) { return; }
      if (generation !== startGeneration) { return; }
      try { window.localStorage.setItem(STORAGE_KEY, id); } catch (e) {}
      window.BlackoutBlack.enter(id, resumed, String(goal || ""));
    } finally {
      starting = false;
      setStartButtonsDisabled(false);
    }
  }
  function makeSessionButton(text, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", handler);
    return button;
  }
  function formatDate(value) {
    try {
      const date = new Date(String(value || ""));
      if (isNaN(date.getTime())) { return ""; }
      const locale = window.BlackoutI18n.lang() === "zh" ? "zh-CN" : "en-US";
      return date.toLocaleDateString(locale) + " " + date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
    } catch (e) { return ""; }
  }
  function renderPastToggle() {
    const toggle = el("pastToggle");
    toggle.hidden = pastCount === 0;
    toggle.textContent = t("pastSessions", { count: pastCount });
    const section = el("recentSection");
    if (section) { section.hidden = !pastOpen || pastCount === 0; }
  }
  async function validateContinue() {
    const button = el("continueLastBtn");
    const id = storedId();
    if (!id) { button.hidden = true; return null; }
    let record = null;
    try { record = await fetchJson("/api/sessions/" + id); }
    catch (e) { clearStored(); button.hidden = true; return null; }
    const updated = new Date(String(record.updated_at || record.created_at || "")).getTime();
    const fresh = !isNaN(updated) && Date.now() - updated <= TWO_HOURS_MS;
    if (record.status !== "active" || !fresh) { clearStored(); button.hidden = true; return null; }
    button.hidden = false;
    return record;
  }
  async function refreshList() {
    const box = el("recentList");
    box.replaceChildren();
    pastOpen = false;
    pastCount = 0;
    renderPastToggle();
    await validateContinue();
    try {
      const data = await fetchJson("/api/sessions");
      const sessions = data.sessions || [];
      pastCount = sessions.length;
      renderPastToggle();
      sessions.forEach(function (session) {
        const item = document.createElement("div");
        item.className = "session-item";
        const goal = document.createElement("span");
        goal.className = "session-goal";
        goal.textContent = String(session.goal || "");
        item.appendChild(goal);
        const date = document.createElement("span");
        date.className = "session-date";
        date.textContent = formatDate(session.updated_at || session.created_at);
        item.appendChild(date);
        if (session.status === "finished") {
          item.appendChild(makeSessionButton(t("view"), function () { primeAudio(); openFinished(String(session.id)); }));
        } else {
          const label = t("continueButton");
          item.appendChild(makeSessionButton(label, function () { primeAudio(); enterActive(String(session.id), true, String(session.goal || "")); }));
        }
        item.appendChild(makeSessionButton(t("deleteButton"), async function () {
          if (!window.confirm(t("deleteConfirm"))) { return; }
          await fetch("/api/sessions/" + session.id, { method: "DELETE" });
          if (storedId() === String(session.id)) { clearStored(); }
          refreshList();
        }));
        box.appendChild(item);
      });
    } catch (e) {}
  }
  function setMicRecording(on) {
    const btn = el("micBtn");
    btn.classList.toggle("recording", Boolean(on));
    btn.setAttribute("aria-label", on ? t("stopReading") : t("goalPlaceholder"));
  }
  async function stopGoalRecorder(send) {
    if (!goalRecording || !goalRecorder) { return; }
    goalRecording = false;
    const recorder = goalRecorder;
    goalRecorder = null;
    setMicRecording(false);
    if (!send) { await recorder.cancel(); return; }
    const wav = await recorder.stop();
    const form = new FormData();
    form.append("audio", wav, "goal.wav");
    try {
      const url = "/api/transcribe?language=" + encodeURIComponent(window.BlackoutI18n.lang());
      const data = await fetchJson(url, { method: "POST", body: form });
      el("goalInput").value = String(data.transcript || "");
    } catch (e) {
      el("startErr").textContent = String((e && e.message) || t("didntCatch"));
    }
  }
  async function toggleGoalMic() {
    if (goalStarting || starting) { return; }
    if (goalRecording) { await stopGoalRecorder(true); return; }
    goalStarting = true;
    goalRecorder = window.BlackoutCapture.createWavRecorder();
    try {
      const opened = await goalRecorder.start();
      if (!opened) { goalRecorder = null; goalStarting = false; return; }
      goalRecording = true;
      setMicRecording(true);
      el("startErr").textContent = t("goalRecording");
    } catch (e) {
      goalRecorder = null;
      setMicRecording(false);
      el("startErr").textContent = t("micNeeded");
    }
    goalStarting = false;
  }
  async function startNew() {
    if (starting) { return; }
    starting = true;
    const generation = ++startGeneration;
    primeAudio();
    setStartButtonsDisabled(true);
    try {
      const goal = el("goalInput").value.trim();
      el("startErr").textContent = "";
      if (!goal) { el("startErr").textContent = t("goalRequired"); return; }
      if (!await ensureMic(generation)) { return; }
      if (generation !== startGeneration) { return; }
      const data = await fetchJson("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: goal, language: window.BlackoutI18n.lang() })
      });
      if (generation !== startGeneration) { return; }
      const id = String(data.session_id);
      try { window.localStorage.setItem(STORAGE_KEY, id); } catch (e) {}
      let skipFullscreen = false;
      if (el("openObserver").checked) {
        skipFullscreen = true;
        window.open("/observer?session=" + encodeURIComponent(id), "_blank");
      }
      window.BlackoutBlack.enter(id, false, goal, { skipFullscreen: skipFullscreen });
    } catch (e) {
      if (e && e.code === "no_key") { window.location.replace("/setup"); return; }
      if (generation === startGeneration) { el("startErr").textContent = String((e && e.message) || t("networkError")); }
    } finally {
      starting = false;
      setStartButtonsDisabled(false);
    }
  }
  async function continueLast() {
    if (starting) { return; }
    const record = await validateContinue();
    if (!record) { refreshList(); return; }
    applySessionLanguage(record);
    if (record.status === "finished" && record.result) {
      clearStored();
      const result = record.result;
      if (!result.poster && record.poster) { result.poster = record.poster; }
      if (!result.map && record.map) { result.map = record.map; }
      window.BlackoutResult.showResult(result, storedId());
      window.scrollTo(0, 0);
      return;
    }
    const goal = String((record.state && record.state.goal) || record.goal || "");
    enterActive(String(record.id || storedId()), true, goal);
  }
  function backToStart() {
    el("page-black").hidden = true;
    el("page-result").hidden = true;
    el("page-start").hidden = false;
    window.scrollTo(0, 0);
    refreshList();
  }
  async function refreshVoiceWarning() {
    const has = await window.BlackoutSpeech.hasVoice(window.BlackoutI18n.lang());
    el("voiceWarning").hidden = has;
  }
  function updateLangChrome() {
    window.BlackoutI18n.apply(document);
    const toggle = el("langToggle");
    if (toggle) { toggle.textContent = window.BlackoutI18n.lang() === "zh" ? "English" : "中文"; }
    const img = el("howItWorksImg");
    if (img) {
      const name = window.BlackoutI18n.lang() === "zh" ? "how_it_works_zh.jpg" : "how_it_works_en.jpg";
      img.src = "/static/" + name;
      img.alt = t("howAlt");
    }
    renderPastToggle();
  }
  function toggleLanguage() {
    const next = window.BlackoutI18n.lang() === "zh" ? "en" : "zh";
    window.BlackoutI18n.set(next);
    updateLangChrome();
    refreshVoiceWarning();
    if (pastCount > 0) { refreshList(); }
  }
  async function checkSetup() {
    try {
      const response = await fetch("/api/setup");
      const data = await response.json();
      if (data && data.has_key === false) { window.location.replace("/setup"); }
    } catch (e) {}
  }
  async function init() {
    el("startBtn").addEventListener("click", startNew);
    el("continueLastBtn").addEventListener("click", continueLast);
    el("micBtn").addEventListener("click", toggleGoalMic);
    el("langToggle").addEventListener("click", toggleLanguage);
    el("pastToggle").addEventListener("click", function () { pastOpen = !pastOpen; renderPastToggle(); });
    document.addEventListener("blackout:restart", refreshList);
    document.addEventListener("blackout:restart", function () { window.scrollTo(0, 0); });
    window.addEventListener("beforeunload", function () {
      if (goalRecorder) { goalRecorder.cancel(); goalRecorder = null; goalRecording = false; }
    });
    updateLangChrome();
    el("goalInput").value = "";
    checkSetup();
    refreshList();
    refreshVoiceWarning();
  }
  document.addEventListener("DOMContentLoaded", init);
  return { backToStart: backToStart, refreshList: refreshList };
})();
