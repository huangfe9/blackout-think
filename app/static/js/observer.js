"use strict";
window.BlackoutObserver = (function () {
  const MIC_KEYS = {
    listening: "micListening",
    paused: "micPaused",
    user_speaking: "micUserSpeaking",
    ai_speaking: "micAiSpeaking",
    speaking: "micUserSpeaking",
    offline: "micOffline"
  };
  const ACTION_KEYS = {
    listen: "actionListen",
    follow_up: "actionFollowUp",
    pull_back: "actionPullBack",
    continue: "actionContinue",
    answer: "actionAnswer",
    summarize: "actionSummarize"
  };
  const POSTER_WAIT_LIMIT_MS = 3 * 60 * 1000;
  let sessionId = "";
  let timer = 0;
  let subtitleTimer = 0;
  let lastParkingJson = "";
  let parkingSeen = false;
  let lastSubtitleText = "";
  let finishedAt = 0;
  let posterShown = false;
  let appliedLang = "";
  let lastReplyText = "";
  let lastReplyAt = 0;
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function sessionParam() {
    try {
      return new URLSearchParams(window.location.search).get("session") || "";
    } catch (e) {
      return "";
    }
  }
  function showMessage(text) {
    const node = el("obsMessage");
    node.textContent = String(text || "");
    node.hidden = !text;
  }
  function armSubtitleFade(text) {
    if (text === lastSubtitleText) { return; }
    lastSubtitleText = text;
    const box = el("obsSubtitles");
    if (box) { box.classList.remove("faded"); }
    window.clearTimeout(subtitleTimer);
    subtitleTimer = window.setTimeout(function () {
      if (box) { box.classList.add("faded"); }
    }, 8000);
  }
  function renderParking(parking) {
    const list = el("obsParking");
    const items = parking || [];
    const json = JSON.stringify(items);
    const isNew = parkingSeen && json !== lastParkingJson;
    list.replaceChildren();
    items.forEach(function (item, index) {
      const li = document.createElement("li");
      li.textContent = String(item || "");
      if (isNew && index === items.length - 1) { li.className = "new"; }
      list.appendChild(li);
    });
    parkingSeen = true;
    lastParkingJson = json;
    const svg = el("obsMap");
    if (svg) { svg.classList.toggle("no-parking", items.length === 0); }
    const panel = el("obsParkingPanel");
    if (panel) { panel.classList.toggle("no-parking", items.length === 0); }
  }
  function resultOf(record) {
    const result = record && record.result;
    return result && typeof result === "object" ? result : {};
  }
  function posterOf(record) {
    const resultPoster = resultOf(record).poster;
    if (resultPoster && typeof resultPoster === "object") { return resultPoster; }
    const recordPoster = record && record.poster;
    if (recordPoster && typeof recordPoster === "object") { return recordPoster; }
    return {};
  }
  function posterStatusOf(record) {
    return String(posterOf(record).status || "");
  }
  function titleOf(record) {
    const title = resultOf(record).title;
    return title ? String(title) : t("resultFallback");
  }
  function mapOf(record) {
    const resultMap = resultOf(record).map;
    if (record && record.status === "finished" && resultMap) { return resultMap; }
    return record ? record.map : null;
  }
  function applyRecordLanguage(record) {
    const value = String((record && record.language) || "");
    if (value !== "zh" && value !== "en") { return; }
    if (value === appliedLang && value === window.BlackoutI18n.lang()) { return; }
    appliedLang = value;
    window.BlackoutI18n.set(value, false);
    window.BlackoutI18n.apply(document);
  }
  function renderMap(record) {
    if (!window.BlackoutMap || !record) { return; }
    const tree = mapOf(record);
    if (!tree) { return; }
    const svg = el("obsMap");
    if (!svg) { return; }
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    window.BlackoutMap.render(svg, tree, { theme: "night", animate: true });
    svg.classList.add("map");
    svg.classList.add("map-night");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }
  function micLabel(live) {
    const raw = String((live && live.mic) || "offline");
    if (raw === "speaking") {
      const action = String((live && live.last_action) || "");
      if (action && action !== "listen") { return t("micAiSpeaking"); }
    }
    const key = MIC_KEYS[raw] || "micOffline";
    return t(key);
  }
  function renderDecision(action, reason, reply) {
    let decision = "";
    if (action === "listen") { decision = t("actionListen"); }
    else if (action) { decision = t(ACTION_KEYS[action] || "actionListen") + (reason ? " · " + reason : ""); }
    el("obsDecision").textContent = reply ? decision : decision;
  }
  function renderSession(record, live) {
    applyRecordLanguage(record);
    const state = (record && record.state) || {};
    renderMap(record);
    const micNode = el("obsMic");
    micNode.hidden = false;
    const rawMic = String((live && live.mic) || "offline");
    micNode.textContent = micLabel(live || {});
    micNode.className = "corner corner-right" + (rawMic === "ai_speaking" ? " mic-ai" : "");
    const caption = String(live.partial || live.last_user || "");
    el("obsCaption").textContent = caption;
    const reply = String(live.last_reply || "");
    if (reply && reply !== lastReplyText) {
      lastReplyText = reply;
      lastReplyAt = Date.now();
    }
    if (!reply) {
      lastReplyText = "";
      lastReplyAt = 0;
    }
    const replyFresh = Boolean(reply && lastReplyAt && Date.now() - lastReplyAt <= 12000);
    el("obsReply").textContent = replyFresh ? reply : "";
    const action = String(live.last_action || "");
    const reason = String(live.last_reason || "");
    renderDecision(action, reason, reply);
    armSubtitleFade(caption + "|" + reply + "|" + action + "|" + reason);
    renderParking(state.parking_lot || []);
    const stats = record.stats || {};
    const values = { n: String(stats.user_turns || 0), m: String(stats.ai_spoke || 0), k: String(stats.pull_backs || 0) };
    let counters = t("counters", values);
    const conflicts = Number(stats.conflicts_asked || 0);
    if (conflicts > 0) { counters += t("countersConflicts", { k: String(conflicts) }); }
    el("obsCounters").textContent = counters;
  }
  function stopPolling() {
    window.clearInterval(timer);
    timer = 0;
  }
  function showPoster(record) {
    if (posterShown) { return; }
    posterShown = true;
    const poster = posterOf(record);
    const version = poster.version;
    let src = "/api/sessions/" + sessionId + "/poster";
    if (typeof version === "number" || typeof version === "string") {
      src += "?v=" + encodeURIComponent(String(version));
    }
    const image = el("posterImage");
    image.src = src;
    image.alt = t("posterAlt");
    el("posterTitle").textContent = t("lightsOn", { title: titleOf(record) });
    const banner = el("obsFinished");
    banner.hidden = true;
    const subtitles = el("obsSubtitles");
    if (subtitles) { subtitles.hidden = true; }
    const parkingPanel = el("obsParkingPanel");
    if (parkingPanel) { parkingPanel.hidden = true; }
    const svg = el("obsMap");
    if (svg) { svg.classList.add("map-faded"); }
    window.clearTimeout(subtitleTimer);
    const wrap = el("posterWrap");
    wrap.hidden = false;
    window.requestAnimationFrame(function () { wrap.classList.add("visible"); });
    stopPolling();
  }
  function handleFinished(record, live) {
    if (!finishedAt) { finishedAt = Date.now(); }
    renderSession(record, live || {});
    const micNode = el("obsMic");
    micNode.textContent = t("micOffline");
    micNode.hidden = true;
    const banner = el("obsFinished");
    banner.textContent = t("lightsOn", { title: titleOf(record) });
    banner.hidden = false;
    const status = posterStatusOf(record);
    if (status === "done") { showPoster(record); return; }
    if (status === "failed") { stopPolling(); return; }
    if (Date.now() - finishedAt >= POSTER_WAIT_LIMIT_MS) { stopPolling(); }
  }
  async function fetchJson(url) {
    const response = await fetch(url);
    const data = await response.json();
    if (!response.ok) {
      let message = t("loadFailed");
      if (data && data.error && data.error.code) {
        const key = "error_" + String(data.error.code);
        if (window.BlackoutI18n.has(key)) { message = t(key); }
        else if (data.error.message) { message = String(data.error.message); }
      }
      throw new Error(message);
    }
    return data;
  }
  async function pollOnce() {
    if (!sessionId) { return; }
    let record = null;
    try {
      record = await fetchJson("/api/sessions/" + sessionId);
    } catch (e) {
      showMessage(t("missingSession"));
      stopPolling();
      return;
    }
    applyRecordLanguage(record);
    let live = {};
    try { live = await fetchJson("/api/sessions/" + sessionId + "/live"); } catch (e) {}
    if (record.status === "finished") { handleFinished(record, live || {}); return; }
    renderSession(record, live || {});
  }
  function init() {
    window.BlackoutI18n.apply(document);
    sessionId = sessionParam();
    if (!/^[0-9a-f]{32}$/.test(sessionId)) {
      showMessage(t("missingSession"));
      return;
    }
    pollOnce();
    timer = window.setInterval(pollOnce, 1000);
  }
  document.addEventListener("DOMContentLoaded", init);
  return { init: init, pollOnce: pollOnce };
})();
