"use strict";
window.BlackoutSpeech = (function () {
  let currentFinish = null;
  function listVoices() {
    try {
      return window.speechSynthesis.getVoices() || [];
    } catch (e) {
      return [];
    }
  }
  function voiceLang(voice) {
    return String((voice && voice.lang) || "").toLowerCase().replace(/_/g, "-");
  }
  function langPrefix(value) {
    return String(value || "").toLowerCase().indexOf("zh") === 0 ? "zh" : "en";
  }
  function langForText(text) {
    const cjk = /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
    return cjk.test(String(text || "")) ? "zh-CN" : "en-US";
  }
  function voicesFor(prefix, voices) {
    return (voices || []).filter(function (voice) { return voiceLang(voice).indexOf(prefix) === 0; });
  }
  function preferredVoice(prefix, voices) {
    const matches = voicesFor(prefix, voices);
    for (let i = 0; i < matches.length; i += 1) {
      const name = String(matches[i].name || "").toLowerCase();
      if (name.indexOf("natural") >= 0 || name.indexOf("online") >= 0) { return matches[i]; }
    }
    return matches.length > 0 ? matches[0] : null;
  }
  function voiceForText(text, voices) {
    return preferredVoice(langPrefix(langForText(text)), voices);
  }
  function chineseVoice(voices) {
    return preferredVoice("zh", voices);
  }
  function waitForVoices() {
    return new Promise(function (resolve) {
      const existing = listVoices();
      if (existing.length > 0 || !("speechSynthesis" in window)) {
        resolve(existing);
        return;
      }
      let done = false;
      function finish() {
        if (done) { return; }
        done = true;
        try { window.speechSynthesis.removeEventListener("voiceschanged", finish); } catch (e) {}
        resolve(listVoices());
      }
      try { window.speechSynthesis.addEventListener("voiceschanged", finish); } catch (e) {}
      window.setTimeout(finish, 1000);
    });
  }
  async function hasVoice(lang) {
    if (!("speechSynthesis" in window)) { return false; }
    const voices = await waitForVoices();
    return preferredVoice(langPrefix(lang), voices) !== null;
  }
  async function hasChineseVoice() {
    return hasVoice("zh");
  }
  function prime() {
    try {
      const utter = new SpeechSynthesisUtterance("");
      window.speechSynthesis.speak(utter);
    } catch (e) {}
  }
  function speak(text) {
    const spoken = String(text || "");
    return new Promise(function (resolve) {
      if (!spoken) { resolve(); return; }
      let settled = false;
      function finish() {
        if (settled) { return; }
        settled = true;
        window.clearTimeout(timer);
        if (currentFinish === finish) { currentFinish = null; }
        resolve();
      }
      const timer = window.setTimeout(finish, Math.max(1500, spoken.length * 350));
      currentFinish = finish;
      try {
        if (!("speechSynthesis" in window)) { return; }
        const utter = new SpeechSynthesisUtterance(spoken);
        utter.lang = langForText(spoken);
        const voice = voiceForText(spoken, listVoices());
        if (voice) { utter.voice = voice; }
        utter.onend = finish;
        utter.onerror = finish;
        window.speechSynthesis.speak(utter);
      } catch (e) {
        finish();
      }
    });
  }
  function cancel() {
    try {
      if ("speechSynthesis" in window) { window.speechSynthesis.cancel(); }
    } catch (e) {}
    if (currentFinish) {
      const finish = currentFinish;
      currentFinish = null;
      finish();
    }
  }
  function speaking() {
    try {
      return Boolean(window.speechSynthesis && window.speechSynthesis.speaking);
    } catch (e) {
      return false;
    }
  }
  return {
    speak: speak,
    cancel: cancel,
    prime: prime,
    speaking: speaking,
    hasVoice: hasVoice,
    hasChineseVoice: hasChineseVoice,
    checkChineseVoice: hasChineseVoice,
    chineseVoice: chineseVoice,
    langForText: langForText
  };
})();
