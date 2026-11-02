"use strict";
window.BlackoutSetup = (function () {
  function el(id) { return document.getElementById(id); }
  function t(key, values) { return window.BlackoutI18n.t(key, values); }
  function errorMessage(data) {
    if (data && data.error && data.error.code) {
      const key = "error_" + String(data.error.code);
      if (window.BlackoutI18n.has(key)) { return t(key); }
    }
    return t("networkError");
  }
  function show(id) {
    ["setupInputView", "setupSavedView", "setupEnvView", "setupNotLocalView"].forEach(function (name) {
      el(name).hidden = name !== id;
    });
  }
  function updateLangChrome() {
    window.BlackoutI18n.apply(document);
    const toggle = el("setupLangToggle");
    if (toggle) { toggle.textContent = window.BlackoutI18n.lang() === "zh" ? "English" : "中文"; }
  }
  function toggleLanguage() {
    const next = window.BlackoutI18n.lang() === "zh" ? "en" : "zh";
    window.BlackoutI18n.set(next);
    updateLangChrome();
  }
  async function loadStatus() {
    try {
      const response = await fetch("/api/setup", { headers: { "Accept": "application/json" } });
      const data = await response.json();
      if (!data.can_change) {
        if (data.source === "environment" || data.source === "env_file") { show("setupEnvView"); return; }
        show("setupNotLocalView");
        return;
      }
      if (data.source === "saved") { show("setupSavedView"); return; }
      if (data.source === "environment" || data.source === "env_file") { show("setupEnvView"); return; }
      show("setupInputView");
    } catch (e) {
      show("setupInputView");
    }
  }
  async function saveKey() {
    const input = el("keyInput");
    const button = el("saveKeyBtn");
    const value = input.value;
    input.value = "";
    el("setupMsg").textContent = "";
    button.disabled = true;
    button.textContent = t("checking");
    try {
      const response = await fetch("/api/setup/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: value })
      });
      const data = await response.json();
      if (!response.ok) {
        el("setupMsg").textContent = errorMessage(data);
        return;
      }
      window.location.replace("/");
    } catch (e) {
      el("setupMsg").textContent = t("error_network");
    } finally {
      button.disabled = false;
      button.textContent = t("saveKey");
    }
  }
  async function deleteKey() {
    el("setupMsg").textContent = "";
    try {
      const response = await fetch("/api/setup/key", { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) {
        el("setupMsg").textContent = errorMessage(data);
        return;
      }
      show("setupInputView");
    } catch (e) {
      el("setupMsg").textContent = t("error_network");
    }
  }
  function back() { window.location.replace("/"); }
  function init() {
    el("setupLangToggle").addEventListener("click", toggleLanguage);
    el("saveKeyBtn").addEventListener("click", saveKey);
    el("replaceKeyBtn").addEventListener("click", function () { show("setupInputView"); });
    el("deleteKeyBtn").addEventListener("click", deleteKey);
    el("savedBackBtn").addEventListener("click", back);
    el("envBackBtn").addEventListener("click", back);
    updateLangChrome();
    loadStatus();
  }
  document.addEventListener("DOMContentLoaded", init);
  return { loadStatus: loadStatus };
})();
