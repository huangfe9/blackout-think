"use strict";
window.BlackoutResult = (function () {
  let sessionId = "";
  let markdown = "";
  let pollTimer = 0;
  let pollDeadline = 0;
  let currentPoster = null;
  let currentPosterJson = "";
  let lastTasksJson = "";
  let hasRunningTasks = false;
  let mapTree = null;
  let mapHero = null;
  let mapNarrow = null;
  let resizeTimer = 0;
  let readingGeneration = 0;
  let readingActive = false;
  let finishRetryHandler = null;
  let posterOverlay = null;
  const STORAGE_KEY = "blackout_active_session_id";
  let posterFigureEl = document.getElementById("posterFigure");
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function serverErrorText(data, fallbackKey) {
    if (data && data.error && data.error.code) {
      const key = "error_" + String(data.error.code);
      if (window.BlackoutI18n.has(key)) { return t(key); }
    }
    if (data && data.error && data.error.message) { return String(data.error.message); }
    return t(fallbackKey || "networkError");
  }
  function actionsRow() {
    const button = el("copyBtn");
    if (!button) { return null; }
    if (typeof button.closest === "function") {
      return button.closest(".result-top-actions") || button.closest(".result-actions");
    }
    return null;
  }
  function setActionsHidden(hidden) {
    const row = actionsRow();
    if (row) { row.hidden = hidden; }
  }
  function updateSessionControls() {
    const hasSession = Boolean(sessionId);
    const sketchLabel = el("sketchLabel");
    if (sketchLabel) { sketchLabel.hidden = !hasSession; }
    const sketchInput = el("sketchInput");
    if (sketchInput) { sketchInput.hidden = true; }
    const sketchWrap = sketchInput && typeof sketchInput.closest === "function" ? sketchInput.closest("label") : null;
    if (sketchWrap && sketchWrap !== sketchLabel) { sketchWrap.hidden = !hasSession; }
    const restart = el("restartBtn");
    if (restart) { restart.hidden = !hasSession; }
  }
  function showPage(page) {
    if (page !== "result") { stopPolling(); stopReading(); }
    el("page-start").hidden = page !== "start";
    el("page-black").hidden = page !== "black";
    el("page-result").hidden = page !== "result";
    if (page !== "result") { window.scrollTo(0, 0); }
  }
  function stopPolling() {
    window.clearInterval(pollTimer);
    pollTimer = 0;
    pollDeadline = 0;
  }
  function hasRunningTask(result) {
    const tasks = (result && result.tasks) || [];
    return tasks.some(function (task) { return Boolean(task && task.status === "running"); });
  }
  function posterIsDrawing() {
    return Boolean(currentPoster && currentPoster.status === "drawing");
  }
  function anythingPending() {
    return hasRunningTasks || posterIsDrawing();
  }
  function startPolling() {
    if (!sessionId || !anythingPending()) { stopPolling(); return; }
    if (!pollDeadline) { pollDeadline = Date.now() + 3 * 60 * 1000; }
    if (!pollTimer) { pollTimer = window.setInterval(pollOnce, 3000); }
  }
  async function pollOnce() {
    if (!sessionId || !pollDeadline) { return; }
    if (Date.now() > pollDeadline || el("page-result").hidden) { stopPolling(); return; }
    let record = null;
    try {
      const response = await fetch("/api/sessions/" + sessionId);
      if (!response.ok) { return; }
      record = await response.json();
    } catch (e) { return; }
    if (!record) { return; }
    const polledResult = record.result || {};
    const polledPoster = polledResult.poster || record.poster || null;
    const tasksJson = JSON.stringify(polledResult.tasks || []);
    if (tasksJson !== lastTasksJson) {
      const merged = polledResult;
      if (!merged.poster && record.poster) { merged.poster = record.poster; }
      if (!merged.map && record.map) { merged.map = record.map; }
      showResult(merged, sessionId, { preserveScroll: true });
      return;
    }
    if (polledPoster && JSON.stringify(polledPoster) !== currentPosterJson) { renderPoster(polledPoster); }
    hasRunningTasks = hasRunningTask(polledResult);
    if (!anythingPending()) { stopPolling(); }
  }
  function stopReading() {
    readingGeneration += 1;
    readingActive = false;
    const button = el("stopReadingBtn");
    if (button) { button.hidden = true; }
    if (window.BlackoutSpeech) { window.BlackoutSpeech.cancel(); }
  }
  function firstTwoSentences(text) {
    const parts = String(text).match(/[^。！？!?]+[。！？!?]?/g) || [];
    const cleaned = parts.map(function (part) { return part.trim(); }).filter(function (part) { return part.length > 0; });
    if (cleaned.length === 0) { return String(text); }
    return cleaned.slice(0, 2).join("");
  }
  function isEmptyResult(data) {
    const lists = [data.decisions, data.todos, data.open_questions, data.parking_lot, data.contradictions, data.unexpanded_points, data.tasks, data.sketches];
    const hasList = lists.some(function (list) { return Boolean(list && list.length); });
    return !hasList && !String(data.summary || "").trim();
  }
  function maybeSpeakSummary(data, options) {
    const shouldSpeak = Boolean(options && typeof options === "object" && (options.speakSummary || options.read));
    if (!shouldSpeak) { return; }
    let spokenText = "";
    if (data && data.degraded) {
      spokenText = t("degradedSpoken");
    } else {
      spokenText = String((data && data.summary) || "").trim();
      if (!spokenText && isEmptyResult(data || {})) { spokenText = t("allDone"); }
      if (spokenText.length > 120) { spokenText = firstTwoSentences(spokenText); }
    }
    const tasks = (data && data.tasks) || [];
    const draft = tasks.find(function (task) { return Boolean(task && task.kind === "draft"); });
    if (draft && draft.status === "done") {
      spokenText = spokenText ? spokenText + t("draftReadySpoken") : t("draftReadySpoken");
    } else if (draft && draft.status === "running") {
      spokenText = spokenText ? spokenText + t("draftAlmostSpoken") : t("draftAlmostSpoken");
    }
    if (!spokenText) { return; }
    const generation = ++readingGeneration;
    readingActive = true;
    const button = el("stopReadingBtn");
    if (button) { button.hidden = false; }
    const finished = window.BlackoutSpeech.speak(spokenText);
    Promise.resolve(finished).then(function () {
      if (generation !== readingGeneration) { return; }
      readingActive = false;
      if (button) { button.hidden = true; }
    });
  }
  function showPending(goal) {
    stopPolling();
    setActionsHidden(true);
    finishRetryHandler = null;
    markdown = "";
    mapTree = null;
    mapHero = null;
    mapNarrow = null;
    hasRunningTasks = false;
    lastTasksJson = "";
    el("resultTitle").textContent = String(goal || "");
    const goalNode = el("resultGoal");
    goalNode.textContent = "";
    goalNode.hidden = true;
    el("degradedNotice").hidden = true;
    el("resultErr").textContent = "";
    const summaryNode = el("resultSummary");
    summaryNode.textContent = "";
    summaryNode.hidden = true;
    el("stopReadingBtn").hidden = true;
    renderPoster(null);
    const box = el("result");
    box.replaceChildren();
    const line = document.createElement("p");
    line.className = "pending-line";
    line.textContent = t("pending");
    box.appendChild(line);
    const page = el("page-result");
    page.classList.add("light-fade");
    el("page-start").hidden = true;
    el("page-black").hidden = true;
    page.hidden = false;
    window.scrollTo(0, 0);
  }
  function showFinishError(onRetry) {
    setActionsHidden(false);
    finishRetryHandler = typeof onRetry === "function" ? onRetry : null;
    const box = el("result");
    box.replaceChildren();
    const line = document.createElement("p");
    line.className = "finish-error-line";
    line.textContent = t("finishError");
    box.appendChild(line);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quiet-btn";
    button.textContent = t("retry");
    button.addEventListener("click", function () {
      if (finishRetryHandler) { finishRetryHandler(); }
    });
    box.appendChild(button);
  }
  function isNarrowMap() {
    return window.innerWidth < 640;
  }
  function hasMapNodes(tree) {
    if (!tree) { return false; }
    const children = tree.children || [];
    return children.length > 0;
  }
  function renderCurrentMap() {
    if (!mapHero || !mapTree) { return; }
    if (!window.BlackoutMap) { return; }
    const narrow = isNarrowMap();
    mapNarrow = narrow;
    mapHero.replaceChildren();
    if (narrow) {
      const outline = document.createElement("div");
      mapHero.appendChild(outline);
      if (window.BlackoutMap.renderOutline) { window.BlackoutMap.renderOutline(outline, mapTree); }
      return;
    }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    mapHero.appendChild(svg);
    if (window.BlackoutMap.render) { window.BlackoutMap.render(svg, mapTree, { theme: "paper", animate: false }); }
  }
  function onResize() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      if (!mapHero || !mapTree) { return; }
      if (el("page-result").hidden) { return; }
      if (!mapHero.isConnected) { return; }
      if (isNarrowMap() === mapNarrow) { renderCurrentMap(); return; }
      renderCurrentMap();
    }, 150);
  }
  function itemText(item) {
    if (item === null || item === undefined) { return ""; }
    if (typeof item === "string") { return item; }
    return String(item.text || item.point || item.content || item.title || "");
  }
  function quoteText(value) {
    if (value === null || value === undefined) { return ""; }
    if (typeof value === "string") { return value; }
    if (Array.isArray(value)) { return value.map(quoteText).filter(Boolean).join(" "); }
    return String(value.quote || value.original || value.text || value.content || value.transcript || "");
  }
  function evidenceFor(text, evidence) {
    if (!evidence || !text) { return ""; }
    if (Array.isArray(evidence)) {
      for (let index = 0; index < evidence.length; index += 1) {
        const entry = evidence[index];
        if (!entry || typeof entry !== "object") { continue; }
        const entryItem = itemText(entry.item || entry.text || entry.point || entry.content || entry.name || "");
        const aliasList = entry.items || entry.texts || [];
        const matchesAlias = Array.isArray(aliasList) && aliasList.map(itemText).indexOf(text) >= 0;
        if (entryItem !== text && !matchesAlias) { continue; }
        const found = quoteText(entry.quote || entry.quotes || entry.original || entry.evidence || entry.sources || "");
        if (found) { return found; }
      }
      return "";
    }
    if (typeof evidence === "object") {
      if (!Object.prototype.hasOwnProperty.call(evidence, text)) { return ""; }
      return quoteText(evidence[text]);
    }
    return "";
  }
  function markerFor(kind) {
    if (kind !== "decision" && kind !== "todo") { return null; }
    const marker = document.createElement("span");
    marker.className = "item-marker marker-" + kind;
    marker.setAttribute("aria-hidden", "true");
    marker.textContent = kind === "decision" ? "◆" : "□";
    return marker;
  }
  function makeListItem(text, evidence, kind) {
    const li = document.createElement("li");
    if (kind) { li.className = "marked-item kind-" + kind; }
    const marker = markerFor(kind);
    if (marker) { li.appendChild(marker); }
    const quote = evidenceFor(text, evidence);
    if (!quote) {
      const span = document.createElement("span");
      span.textContent = text;
      li.appendChild(span);
      return li;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "evidence-btn";
    button.setAttribute("aria-expanded", "false");
    const label = document.createElement("span");
    label.textContent = text;
    button.appendChild(label);
    const tag = document.createElement("span");
    tag.className = "evidence-tag";
    tag.textContent = t("wordsLabel");
    button.appendChild(tag);
    const arrow = document.createElement("span");
    arrow.className = "evidence-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "›";
    button.appendChild(arrow);
    li.appendChild(button);
    const quoteNode = document.createElement("div");
    quoteNode.className = "evidence-quote";
    const srPrefix = document.createElement("span");
    srPrefix.className = "sr-only";
    srPrefix.textContent = t("originalWords");
    quoteNode.appendChild(srPrefix);
    const quoteSpan = document.createElement("span");
    quoteSpan.textContent = quote;
    quoteNode.appendChild(quoteSpan);
    quoteNode.hidden = true;
    li.appendChild(quoteNode);
    button.addEventListener("click", function () {
      const open = quoteNode.hidden;
      quoteNode.hidden = !open;
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.classList.toggle("open", open);
    });
    return li;
  }
  function makeSection(title, items, evidence, kind) {
    const box = document.createElement("div");
    box.className = "sec";
    const head = document.createElement("h3");
    head.textContent = title;
    box.appendChild(head);
    const list = document.createElement("ul");
    if (kind) { list.className = "marked-list"; }
    (items || []).forEach(function (item) {
      const text = itemText(item);
      if (text) { list.appendChild(makeListItem(text, evidence, kind)); }
    });
    box.appendChild(list);
    return box;
  }
  function isWebUrl(value) {
    try {
      const parsed = new URL(String(value));
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch (e) { return false; }
  }
  function makeTasks(tasks) {
    const box = document.createElement("div");
    box.className = "sec";
    const head = document.createElement("h3");
    head.textContent = t("tasksSection");
    box.appendChild(head);
    const list = document.createElement("ul");
    (tasks || []).forEach(function (task) {
      const li = document.createElement("li");
      const main = document.createElement("span");
      if (task.status === "running") {
        const detailText = String(task.instruction || "");
        if (task.kind === "draft") { main.textContent = detailText ? t("writing", { text: detailText }) : t("writingPlain"); }
        else { main.textContent = detailText ? t("searching", { text: detailText }) : t("searchingPlain"); }
      } else {
        main.textContent = String(task.conclusion || task.instruction || "");
      }
      li.appendChild(main);
      const sources = (task.sources || []).filter(function (source) { return Boolean(source && isWebUrl(source.url)); });
      if (task.detail || sources.length > 0) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = t("details");
        details.appendChild(summary);
        if (task.detail) {
          const body = document.createElement("p");
          body.textContent = String(task.detail);
          details.appendChild(body);
        }
        sources.forEach(function (source) {
          const link = document.createElement("a");
          link.href = String(source.url);
          link.rel = "noopener noreferrer";
          link.textContent = String(source.title || source.url);
          const line = document.createElement("p");
          line.appendChild(link);
          details.appendChild(line);
        });
        li.appendChild(details);
      }
      list.appendChild(li);
    });
    box.appendChild(list);
    return box;
  }
  function makeDraft(task) {
    const box = document.createElement("div");
    box.className = "sec draft-sec";
    const headRow = document.createElement("div");
    headRow.className = "draft-head";
    const head = document.createElement("h3");
    head.textContent = t("firstDraft");
    headRow.appendChild(head);
    const draftText = String(task.detail || task.conclusion || "");
    if (task.status !== "running" && draftText) {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "quiet-btn draft-copy";
      copy.textContent = t("copyDraft");
      copy.addEventListener("click", async function () {
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(draftText); }
          else { await fallbackCopy(draftText); }
        } catch (e) { await fallbackCopy(draftText); }
        copy.textContent = t("copied");
        window.setTimeout(function () { copy.textContent = t("copyDraft"); }, 1500);
      });
      headRow.appendChild(copy);
    }
    box.appendChild(headRow);
    const instruction = String(task.instruction || "");
    if (instruction) {
      const small = document.createElement("p");
      small.className = "draft-instruction";
      small.textContent = instruction;
      box.appendChild(small);
    }
    if (task.status === "running") {
      const line = document.createElement("p");
      line.className = "draft-running";
      line.textContent = instruction ? t("drafting", { text: instruction }) : t("writingPlain");
      box.appendChild(line);
      return box;
    }
    const body = document.createElement("div");
    body.className = "draft-body";
    body.textContent = draftText;
    box.appendChild(body);
    return box;
  }
  function transcriptTexts(transcript) {
    const texts = [];
    (transcript || []).forEach(function (entry) {
      if (typeof entry === "string") { if (entry.trim()) { texts.push(entry); } return; }
      if (!entry || typeof entry !== "object") { return; }
      const text = String(entry.content || entry.text || entry.transcript || "");
      if (text.trim()) { texts.push(text); }
    });
    return texts;
  }
  function makeTranscript(transcript) {
    const texts = transcriptTexts(transcript);
    const box = document.createElement("details");
    box.className = "sec transcript-sec";
    const summary = document.createElement("summary");
    summary.textContent = t("yourWords", { count: texts.length });
    box.appendChild(summary);
    const list = document.createElement("ul");
    texts.forEach(function (text) {
      const li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
    box.appendChild(list);
    return box;
  }
  function posterUrl(poster) {
    if (poster && poster.src) { return String(poster.src); }
    const version = poster && poster.version !== undefined ? poster.version : 0;
    return "/api/sessions/" + sessionId + "/poster?v=" + encodeURIComponent(String(version));
  }
  function makeRedrawButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = t("drawAnother");
    button.addEventListener("click", redrawPoster);
    return button;
  }
  function closePosterOverlay() {
    if (posterOverlay && posterOverlay.parentNode) { posterOverlay.parentNode.removeChild(posterOverlay); }
    posterOverlay = null;
  }
  function openPosterOverlay(src, alt) {
    closePosterOverlay();
    const overlay = document.createElement("div");
    overlay.className = "poster-overlay";
    const image = document.createElement("img");
    image.src = src;
    image.alt = alt || t("posterAlt");
    overlay.appendChild(image);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "poster-overlay-close";
    close.textContent = t("closePicture");
    close.addEventListener("click", closePosterOverlay);
    overlay.appendChild(close);
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) { closePosterOverlay(); }
    });
    document.body.appendChild(overlay);
    posterOverlay = overlay;
  }
  function renderPoster(poster) {
    currentPoster = poster && typeof poster === "object" ? poster : null;
    currentPosterJson = currentPoster ? JSON.stringify(currentPoster) : "";
    const figure = posterFigureEl;
    if (!figure) { return; }
    figure.replaceChildren();
    const topActions = el("posterActions");
    if (topActions) { topActions.replaceChildren(); }
    const status = currentPoster ? String(currentPoster.status || "none") : "none";
    if (!currentPoster || status === "none") { figure.hidden = true; return; }
    figure.hidden = false;
    if (status === "drawing") {
      const placeholder = document.createElement("div");
      placeholder.className = "poster-placeholder";
      placeholder.textContent = t("drawing");
      figure.appendChild(placeholder);
      return;
    }
    if (status === "done") {
      const hasSrc = Boolean(currentPoster.src);
      const image = document.createElement("img");
      image.src = posterUrl(currentPoster);
      image.alt = String(el("resultTitle").textContent || t("posterAlt"));
      image.className = "poster-openable";
      image.setAttribute("title", t("openPicture"));
      image.addEventListener("click", function () { openPosterOverlay(image.src, image.alt); });
      figure.appendChild(image);
      if (topActions) {
        const download = document.createElement("a");
        download.href = posterUrl(currentPoster);
        download.setAttribute("download", "");
        download.textContent = t("downloadPicture");
        topActions.appendChild(download);
        if (!hasSrc) { topActions.appendChild(makeRedrawButton()); }
      }
      return;
    }
    if (status === "failed") {
      const line = document.createElement("p");
      line.className = "poster-error";
      line.textContent = String(currentPoster.error || t("posterFailed"));
      figure.appendChild(line);
      if (topActions && !currentPoster.src) { topActions.appendChild(makeRedrawButton()); }
    }
  }
  async function redrawPoster() {
    if (!sessionId) { return; }
    if (currentPoster && currentPoster.src) { return; }
    el("resultErr").textContent = "";
    try {
      const response = await fetch("/api/sessions/" + sessionId + "/poster", { method: "POST" });
      const data = await response.json();
      if (!response.ok) { throw new Error(serverErrorText(data, "posterFailed")); }
      const nextPoster = data.poster || { status: "drawing", version: 0, error: "" };
      renderPoster(nextPoster);
      pollDeadline = Date.now() + 3 * 60 * 1000;
      startPolling();
    } catch (e) {
      el("resultErr").textContent = String((e && e.message) || t("posterFailed"));
    }
  }
  function showResult(result, id, options) {
    const preserveScroll = Boolean(options && typeof options === "object" && options.preserveScroll);
    const savedScrollY = window.scrollY || 0;
    if (id === null) {
      sessionId = "";
      stopPolling();
    } else if (id) {
      const changedSession = sessionId !== String(id);
      sessionId = String(id);
      if (changedSession) { stopPolling(); }
    }
    if (!preserveScroll) { stopReading(); }
    window.BlackoutI18n.apply(document);
    setActionsHidden(false);
    updateSessionControls();
    finishRetryHandler = null;
    const data = result || {};
    lastTasksJson = JSON.stringify(data.tasks || []);
    const lightsOn = Boolean(options && (options.lightsOn || options === true));
    markdown = String(data.markdown || "");
    el("resultTitle").textContent = String(data.title || t("resultFallback"));
    const goalNode = el("resultGoal");
    if (goalNode) {
      goalNode.textContent = data.goal && data.goal !== data.title ? String(data.goal) : "";
      goalNode.hidden = !goalNode.textContent;
    }
    el("degradedNotice").hidden = !data.degraded;
    el("resultErr").textContent = "";
    const summaryNode = el("resultSummary");
    const summaryText = String(data.summary || "").trim();
    summaryNode.textContent = summaryText;
    summaryNode.hidden = !summaryText;
    if (!preserveScroll || !readingActive) { el("stopReadingBtn").hidden = true; }
    const box = el("result");
    box.replaceChildren();
    mapTree = null;
    mapHero = null;
    mapNarrow = null;
    let hasContent = Boolean(summaryText) || posterIsDrawing();
    if (currentPoster && currentPoster.status === "done") { hasContent = true; }
    if (currentPoster && currentPoster.status === "failed") { hasContent = true; }
    const evidence = data.evidence || null;
    const columns = document.createElement("div");
    columns.className = "result-top-columns";
    const left = document.createElement("div");
    left.className = "result-top-left";
    const right = document.createElement("div");
    right.className = "result-top-right";
    if (posterFigureEl) { right.appendChild(posterFigureEl); }
    columns.appendChild(left);
    columns.appendChild(right);
    box.appendChild(columns);
    renderPoster(data.poster || null);
    if (currentPoster && currentPoster.status === "done") { hasContent = true; }
    if (currentPoster && currentPoster.status === "failed") { hasContent = true; }
    if (posterIsDrawing()) { hasContent = true; }
    if ((data.decisions || []).length > 0) { hasContent = true; left.appendChild(makeSection(t("decisions"), data.decisions, evidence, "decision")); }
    if ((data.todos || []).length > 0) { hasContent = true; left.appendChild(makeSection(t("todos"), data.todos, evidence, "todo")); }
    if ((data.open_questions || []).length > 0) { hasContent = true; left.appendChild(makeSection(t("stillOpen"), data.open_questions, evidence)); }
    const allTasks = data.tasks || [];
    const drafts = allTasks.filter(function (task) { return Boolean(task && task.kind === "draft"); });
    const otherTasks = allTasks.filter(function (task) { return !(task && task.kind === "draft"); });
    drafts.forEach(function (task) { hasContent = true; box.appendChild(makeDraft(task)); });
    if (otherTasks.length > 0) { hasContent = true; box.appendChild(makeTasks(otherTasks)); }
    if (hasMapNodes(data.map) && window.BlackoutMap) {
      hasContent = true;
      mapTree = data.map;
      const mapSection = document.createElement("div");
      mapSection.className = "sec";
      const mapHead = document.createElement("h3");
      mapHead.textContent = t("mindMap");
      mapSection.appendChild(mapHead);
      const hero = document.createElement("div");
      hero.className = "map-hero";
      mapSection.appendChild(hero);
      box.appendChild(mapSection);
      mapHero = hero;
      renderCurrentMap();
    }
    if ((data.parking_lot || []).length > 0) { hasContent = true; box.appendChild(makeSection(t("parkingLot"), data.parking_lot, evidence)); }
    if ((data.contradictions || []).length > 0) { hasContent = true; box.appendChild(makeSection(t("contradictions"), data.contradictions, evidence)); }
    if ((data.unexpanded_points || []).length > 0) { hasContent = true; box.appendChild(makeSection(t("unfinished"), data.unexpanded_points, evidence)); }
    const sketches = data.sketches || [];
    const sketchTexts = sketches.map(function (sketch) { return String((sketch && sketch.description) || ""); });
    const filledSketches = sketchTexts.filter(function (text) { return text.length > 0; });
    if (filledSketches.length > 0) { hasContent = true; box.appendChild(makeSection(t("paperSketch"), filledSketches, evidence)); }
    const spokenTexts = transcriptTexts(data.transcript);
    if (spokenTexts.length > 0) { hasContent = true; box.appendChild(makeTranscript(data.transcript)); }
    if (!hasContent) {
      const empty = document.createElement("p");
      empty.className = "empty-line";
      empty.textContent = t("emptyRecorded");
      box.appendChild(empty);
    }
    const page = el("page-result");
    page.classList.toggle("light-fade", lightsOn);
    el("page-start").hidden = true;
    el("page-black").hidden = true;
    page.hidden = false;
    updateSessionControls();
    if (preserveScroll) { window.scrollTo(0, savedScrollY); } else { window.scrollTo(0, 0); }
    hasRunningTasks = hasRunningTask(data);
    pollDeadline = 0;
    if (sessionId) { startPolling(); } else { stopPolling(); }
    maybeSpeakSummary(data, options);
  }
  function fallbackCopy(text) {
    return new Promise(function (resolve) {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); } catch (e) {}
      area.remove();
      resolve();
    });
  }
  async function copyMarkdown() {
    const button = el("copyBtn");
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(markdown); }
      else { await fallbackCopy(markdown); }
    } catch (e) { await fallbackCopy(markdown); }
    button.textContent = t("copied");
    window.setTimeout(function () { button.textContent = t("copyMarkdown"); }, 1500);
  }
  function scaleImage(file) {
    return new Promise(function (resolve, reject) {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = function () {
        try {
          const longSide = Math.max(image.naturalWidth, image.naturalHeight) || 1;
          const ratio = Math.min(1, 1600 / longSide);
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
          canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
          const ctx = canvas.getContext("2d");
          ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
          URL.revokeObjectURL(url);
          canvas.toBlob(function (blob) { if (blob) { resolve(blob); } else { reject(new Error(t("imageFailed"))); } }, "image/jpeg", 0.85);
        } catch (e) { URL.revokeObjectURL(url); reject(e); }
      };
      image.onerror = function () { URL.revokeObjectURL(url); reject(new Error(t("imageReadFailed"))); };
      image.src = url;
    });
  }
  async function uploadSketch(file) {
    if (!sessionId) { return; }
    const label = el("sketchLabel");
    const input = el("sketchInput");
    el("resultErr").textContent = "";
    label.textContent = t("recognizing");
    try {
      const blob = await scaleImage(file);
      const form = new FormData();
      form.append("image", blob, "sketch.jpg");
      const response = await fetch("/api/sessions/" + sessionId + "/sketches", { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) { throw new Error(serverErrorText(data, "sketchFailed")); }
      showResult(data, sessionId);
    } catch (e) {
      el("resultErr").textContent = String((e && e.message) || t("sketchFailed"));
    } finally {
      label.textContent = t("addSketch");
      input.value = "";
    }
  }
  function backToStart() {
    stopPolling();
    stopReading();
    closePosterOverlay();
    mapTree = null;
    mapHero = null;
    mapNarrow = null;
    try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) {}
    showPage("start");
    window.scrollTo(0, 0);
    document.dispatchEvent(new CustomEvent("blackout:restart"));
  }
  function init() {
    if (!posterFigureEl) { posterFigureEl = el("posterFigure"); }
    if (el("copyBtn")) { el("copyBtn").addEventListener("click", copyMarkdown); }
    if (el("restartBtn")) { el("restartBtn").addEventListener("click", backToStart); }
    if (el("stopReadingBtn")) { el("stopReadingBtn").addEventListener("click", stopReading); }
    if (el("sketchInput")) { el("sketchInput").addEventListener("change", function () {
      const input = el("sketchInput");
      if (input.files && input.files[0]) { uploadSketch(input.files[0]); }
    }); }
    updateSessionControls();
    document.addEventListener("click", function () {
      if (!readingActive) { return; }
      if (el("page-result").hidden) { return; }
      const button = el("stopReadingBtn");
      if (button && !button.hidden) { return; }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && posterOverlay) { closePosterOverlay(); return; }
      if (el("page-result").hidden) { return; }
      if (!readingActive) { return; }
      if (event.code !== "Space") { return; }
      event.preventDefault();
      stopReading();
    });
    window.addEventListener("resize", onResize);
  }
  document.addEventListener("DOMContentLoaded", init);
  return {
    showResult: showResult,
    showPending: showPending,
    showFinishError: showFinishError,
    showPage: showPage,
    backToStart: backToStart,
    stopTaskPolling: stopPolling,
    stopPolling: stopPolling,
    stopReading: stopReading,
    setSession: function (id) { sessionId = String(id || ""); updateSessionControls(); }
  };
})();
