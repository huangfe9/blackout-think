"use strict";
(function () {
  const ACTION_KEYS = {
    listen: "actionListen",
    follow_up: "actionFollowUp",
    pull_back: "actionPullBack",
    continue: "actionContinue",
    answer: "actionAnswer",
    summarize: "actionSummarize"
  };
  let timers = [];
  let loadGeneration = 0;
  let resultData = null;
  let finished = false;
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function clearTimers() {
    timers.forEach(function (timer) { window.clearTimeout(timer); });
    timers = [];
  }
  function schedule(delay, fn) {
    const timer = window.setTimeout(fn, Math.max(0, delay));
    timers.push(timer);
    return timer;
  }
  function sampleLanguage() {
    return window.BlackoutI18n.lang() === "zh" ? "zh" : "en";
  }
  function updateToggle() {
    const button = el("exampleLangToggle");
    if (button) { button.textContent = window.BlackoutI18n.lang() === "zh" ? "English" : "中文"; }
  }
  function renderParking(parking) {
    const list = el("exampleParking");
    if (!list) { return; }
    const items = parking || [];
    list.replaceChildren();
    items.forEach(function (item) {
      const li = document.createElement("li");
      li.textContent = String(item || "");
      list.appendChild(li);
    });
    const panel = el("exampleParkingPanel");
    if (panel) { panel.classList.toggle("no-parking", items.length === 0); }
    const svg = el("exampleMap");
    if (svg) { svg.classList.toggle("no-parking", items.length === 0); }
  }
  function renderFrame(frame) {
    if (!frame) { return; }
    const svg = el("exampleMap");
    if (svg && frame.map && window.BlackoutMap) {
      svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
      window.BlackoutMap.render(svg, frame.map, { theme: "night", animate: true });
    }
    el("exampleCaption").textContent = String(frame.heard || "");
    const replyNode = el("exampleReply");
    const reply = String(frame.reply || "");
    replyNode.textContent = reply;
    if (reply) {
      schedule(4000, function () {
        if (replyNode.textContent === reply) { replyNode.textContent = ""; }
      });
    }
    const action = String(frame.action || "");
    const decision = el("exampleDecision");
    if (decision) { decision.textContent = action ? t(ACTION_KEYS[action] || "actionListen") : ""; }
    renderParking(frame.parking || []);
    const stats = frame.stats || {};
    const values = { n: String(stats.user_turns || 0), m: String(stats.ai_spoke || 0), k: String(stats.pull_backs || 0) };
    let counters = t("counters", values);
    const conflicts = Number(stats.conflicts_asked || 0);
    if (conflicts > 0) { counters += t("countersConflicts", { k: String(conflicts) }); }
    el("exampleCounters").textContent = counters;
    const mic = el("exampleMic");
    if (mic) { mic.textContent = t("micListening"); }
  }
  function finish() {
    if (finished) { return; }
    finished = true;
    clearTimers();
    const stage = el("exampleStage");
    if (stage) { stage.hidden = true; }
    document.body.classList.add("example-result");
    if (resultData && window.BlackoutResult) {
      window.BlackoutResult.showResult(resultData, null);
      window.BlackoutI18n.apply(document);
    }
  }
  function play(data) {
    clearTimers();
    finished = false;
    resultData = data.result || null;
    const frames = data.frames || [];
    if (frames.length === 0) { finish(); return; }
    const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      renderFrame(frames[frames.length - 1]);
      finish();
      return;
    }
    frames.forEach(function (frame) {
      schedule(Number(frame.t || 0) * 1000 / 1.5, function () { renderFrame(frame); });
    });
    const last = frames[frames.length - 1];
    schedule(Number(last.t || 0) * 1000 / 1.5 + 1500, finish);
  }
  function showFetchError() {
    clearTimers();
    const error = el("exampleError");
    if (error) { error.hidden = false; }
    const skip = el("exampleSkipBtn");
    if (skip) { skip.hidden = true; }
  }
  async function load() {
    const generation = ++loadGeneration;
    clearTimers();
    finished = false;
    resultData = null;
    const error = el("exampleError");
    if (error) { error.hidden = true; }
    const skip = el("exampleSkipBtn");
    if (skip) { skip.hidden = false; }
    const stage = el("exampleStage");
    if (stage) { stage.hidden = false; }
    document.body.classList.remove("example-result");
    const sample = sampleLanguage();
    window.BlackoutI18n.apply(document);
    try {
      const response = await fetch("sample/" + sample + ".json");
      if (!response.ok) { throw new Error("sample"); }
      const data = await response.json();
      if (generation !== loadGeneration) { return; }
      play(data);
    } catch (e) {
      if (generation !== loadGeneration) { return; }
      showFetchError();
    }
  }
  function init() {
    window.BlackoutI18n.apply(document);
    updateToggle();
    const noAudio = el("exampleNoAudio");
    if (noAudio) { noAudio.textContent = t("exampleNoAudio"); }
    el("exampleSkipBtn").addEventListener("click", finish);
    el("exampleLangToggle").addEventListener("click", function () {
      const next = window.BlackoutI18n.lang() === "zh" ? "en" : "zh";
      window.BlackoutI18n.set(next);
      window.BlackoutI18n.apply(document);
      updateToggle();
      const resultPage = el("page-result");
      const wasResult = Boolean(resultPage && !resultPage.hidden);
      if (wasResult && resultData) {
        load().then(function () {
          if (resultData) { finish(); }
          window.BlackoutI18n.apply(document);
        });
        return;
      }
      load();
    });
    load();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
