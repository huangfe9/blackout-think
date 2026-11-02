"use strict";
window.BlackoutI18n = (function () {
  const STORAGE_KEY = "blackout_lang";
  const STRINGS = {
    zh: {
      appTitle: "Blackout 黑屏思考",
      observerTitle: "Blackout 星图",
      headline1: "不看屏幕，",
      headline2: "说着把事想清楚。",
      subline: "你只管说。说完，给你一页总结和一张图。",
      goalPlaceholder: "这次想想清楚什么？",
      startButton: "关灯，开始说",
      smallLine: "屏幕会变黑，直接开口。说「结束」，灯亮，出图。",
      continueLast: "继续上次",
      pastSessions: "之前的记录（{count}）",
      view: "查看",
      continueButton: "继续",
      deleteButton: "删除",
      deleteConfirm: "确定删除这次思考吗？",
      observerCheck: "同时打开星图窗口（第二块屏幕）",
      noVoice: "这台设备没有中文语音，AI 的声音可能听不到。建议用 Chrome 或 Edge，或安装中文语音。",
      micNeeded: "需要麦克风权限才能开始。请在地址栏允许麦克风后重试。",
      noMic: "没有找到麦克风。",
      goalRecording: "正在录目标，再点一次结束。",
      goalRequired: "请先说一下本次目标。",
      networkError: "网络不太好，请重试。",
      didntCatch: "没听清，请再说一次。",
      howAlt: "三格手绘图：一个人开口说话，屏幕变黑安静思考，最后出现一页总结和一张图。",
      blackHint: "空格暂停 · 说“结束”或按 Esc 结束",
      entryLine: "黑屏开始。我在听，你直接说就行。按空格暂停，想结束就说结束，或者按 Esc。",
      resumeLine: "接着刚才的继续。",
      endingLine: "好，我来整理，稍等一下。",
      budgetLine: "预算用完了，我把内容整理出来。",
      fallbackLine: "自动听写断了。现在按空格开始说话，说完再按一次。",
      permissionLine: "需要麦克风权限，请允许后重试。",
      pending: "正在整理你说的话…",
      finishError: "整理失败了，你说的话都还在。",
      retry: "重试",
      drawing: "正在画总结图…",
      downloadPicture: "下载这张图",
      drawAnother: "重画一张",
      posterFailed: "画图没成功。",
      stopReading: "停止朗读",
      allDone: "整理好了。",
      degradedSpoken: "整理没有完成，你说的原话都在页面上。",
      draftReadySpoken: "第一份草稿也写好了。",
      draftAlmostSpoken: "第一份草稿马上就好。",
      firstDraft: "第一份草稿",
      copyDraft: "复制草稿",
      drafting: "正在起草：{text}",
      wordsLabel: "原话",
      closePicture: "关闭",
      openPicture: "看大图",
      countersConflicts: " · 抓到矛盾 {k} 次",
      resultFallback: "成果",
      mindMap: "思维导图",
      decisions: "决定",
      todos: "待办",
      stillOpen: "还没想清楚",
      contradictions: "还没解决的矛盾",
      unfinished: "没说完的点",
      parkingLot: "停车场",
      tasksSection: "后台查到和写好的",
      paperSketch: "纸上草稿",
      originalWords: "原话：",
      yourWords: "你说的原话（{count} 句）",
      details: "详情",
      searching: "还在查……{text}",
      writing: "还在写……{text}",
      searchingPlain: "还在查……",
      writingPlain: "还在写……",
      copyMarkdown: "复制为 Markdown",
      copied: "已复制",
      addSketch: "加入纸上草稿",
      startAgain: "再来一次",
      emptyRecorded: "这次没有记下内容。",
      degraded: "AI 整理没有完成，下面是对话中记录的原始内容。",
      recognizing: "正在识别…",
      imageFailed: "图片处理失败",
      imageReadFailed: "图片读取失败",
      sketchFailed: "草稿识别失败，请再试一次。",
      posterAlt: "总结图",
      observerBrand: "Blackout · 星图",
      micListening: "在听",
      micPaused: "暂停",
      micUserSpeaking: "你在说",
      micAiSpeaking: "AI 在说",
      micOffline: "未连接",
      actionListen: "听着，没打断",
      actionFollowUp: "追问没说完的点",
      actionPullBack: "拉回主线",
      actionContinue: "推进",
      actionAnswer: "回答",
      actionSummarize: "确认结束",
      counters: "说了 {n} 句 · 开口 {m} 次 · 拉回 {k} 次",
      lightsOn: "灯亮了 · {title}",
      missingSession: "还没有指定要看的星图。从开始页勾选“录视频：同时打开星图窗口”再开始。",
      loadFailed: "加载失败。",
      keyLink: "API key",
      setupHeading: "先填你自己的 Meta key",
      setupLine: "Blackout 在你自己的电脑上运行，用你的 key 调用 Meta 的模型。",
      keyPlaceholder: "粘贴 key",
      saveKey: "保存并检查",
      getKey: "去 Meta 申请 key",
      noKeyExample: "还没有 key？先看一个真实例子",
      exampleBanner: "这是一场虚构谈话的真实回放，不需要 key。",
      runYourself: "自己运行",
      exampleSkip: "跳到结果",
      exampleNoAudio: "回放不播放声音。",
      exampleNeedServer: "这个例子需要通过网页服务打开。",
      factLocal: "只存在这台电脑上，不会进入代码仓库。",
      factMetaOnly: "只发给 api.meta.ai，页面和日志都不会再显示它。",
      factCost: "费用从你自己的 Meta 账户扣，一次短谈大约 $0.20。",
      savedKey: "这台电脑上已经保存了一个 key。",
      replaceKey: "换一个",
      deleteKey: "删除",
      back: "返回",
      envKey: "正在使用 .env 或环境变量里的 key，要改请直接改那里。",
      notLocalKey: "请在运行 Blackout 的那台电脑上设置 key。",
      checking: "正在检查…",
      error_budget_exhausted: "预算用完了。",
      error_not_found: "没有找到这次思考。",
      error_session_not_found: "没有找到这次思考。",
      error_rate_limited: "请求太频繁，请稍后再试。",
      error_too_large: "内容太大了。",
      error_payload_too_large: "内容太大了。",
      error_invalid_request: "这次请求没有成功，请再试一次。",
      error_validation_error: "这次请求没有成功，请再试一次。",
      error_invalid_key_format: "这看起来不像 key，请重新复制。",
      error_invalid_key: "Meta 没有接受这个 key。",
      error_key_missing_models: "这个 key 不能使用 Blackout 需要的模型。",
      error_network: "连不上 Meta，请检查网络后再试。",
      error_not_local: "请在运行 Blackout 的那台电脑上设置 key。",
      error_key_from_env: "正在使用 .env 或环境变量里的 key，要改请直接改那里。",
      error_key_save_failed: "key 没能保存，请再试一次。",
      error_key_rejected: "Meta 不接受现在的 key，请点右上角换一个。",
      error_no_key: "请先设置 API key。"
    },
    en: {
      appTitle: "Blackout",
      observerTitle: "Blackout · Star map",
      headline1: "Think it through",
      headline2: "without looking at a screen.",
      subline: "Just talk. When you're done, you get a one-page summary and a picture.",
      goalPlaceholder: "What do you want to figure out?",
      startButton: "Lights off, start talking",
      smallLine: "The screen goes black. Just start talking. Say “stop” and the lights come on.",
      continueLast: "Continue where I left off",
      pastSessions: "Past sessions ({count})",
      view: "View",
      continueButton: "Continue",
      deleteButton: "Delete",
      deleteConfirm: "Delete this session?",
      observerCheck: "Also open the star map (for a second screen)",
      noVoice: "This device has no voice for this language, so you may not hear the AI. Try Chrome or Edge.",
      micNeeded: "Microphone access is needed to start. Allow it in the address bar and try again.",
      noMic: "No microphone found.",
      goalRecording: "Recording your goal. Tap again to finish.",
      goalRequired: "Please say what you want to figure out first.",
      networkError: "Network trouble. Please try again.",
      didntCatch: "I didn't catch that. Please say it again.",
      howAlt: "Three hand-drawn panels: a person speaking, a black screen for quiet thinking, then a summary and picture.",
      blackHint: "Space to pause · Say “stop” or press Esc to finish",
      entryLine: "The screen is dark now. I'm listening, so just start talking. Press space to pause. To finish, say stop, or press Escape.",
      resumeLine: "Picking up where we left off.",
      endingLine: "OK, let me pull this together. One moment.",
      budgetLine: "The budget is used up. Let me pull together what we have.",
      fallbackLine: "Automatic listening stopped. Press space to start talking, and press again when done.",
      permissionLine: "Microphone access is needed. Allow it and try again.",
      pending: "Pulling together what you said…",
      finishError: "That didn't work, but everything you said is still here.",
      retry: "Retry",
      drawing: "Drawing your picture…",
      downloadPicture: "Download picture",
      drawAnother: "Draw another",
      posterFailed: "Couldn't draw the picture.",
      stopReading: "Stop reading",
      allDone: "All done.",
      degradedSpoken: "The summary didn't finish. Your words are all on the page.",
      draftReadySpoken: "Your first draft is ready too.",
      draftAlmostSpoken: "Your first draft is almost ready.",
      firstDraft: "First draft",
      copyDraft: "Copy draft",
      drafting: "Drafting: {text}",
      wordsLabel: "Your words",
      closePicture: "Close",
      openPicture: "View full size",
      countersConflicts: " · Caught {k} changes",
      resultFallback: "Results",
      mindMap: "Mind map",
      decisions: "Decisions",
      todos: "To do",
      stillOpen: "Still open",
      contradictions: "Unresolved tensions",
      unfinished: "Unfinished",
      parkingLot: "Parking lot",
      tasksSection: "Looked up and drafted",
      paperSketch: "Paper sketch",
      originalWords: "Original words: ",
      yourWords: "Your words ({count})",
      details: "Details",
      searching: "Searching: {text}",
      writing: "Writing: {text}",
      searchingPlain: "Searching…",
      writingPlain: "Writing…",
      copyMarkdown: "Copy as Markdown",
      copied: "Copied",
      addSketch: "Add a paper sketch",
      startAgain: "Start again",
      emptyRecorded: "Nothing was recorded this time.",
      degraded: "The AI summary didn't finish. Below is what was recorded during the session.",
      recognizing: "Recognizing…",
      imageFailed: "Could not process the image.",
      imageReadFailed: "Could not read the image.",
      sketchFailed: "Could not read the sketch. Please try again.",
      posterAlt: "Summary picture",
      observerBrand: "Blackout · Star map",
      micListening: "Listening",
      micPaused: "Paused",
      micUserSpeaking: "You're talking",
      micAiSpeaking: "AI speaking",
      micOffline: "Offline",
      actionListen: "Listening, not interrupting",
      actionFollowUp: "Follow-up",
      actionPullBack: "Pulled back",
      actionContinue: "Moving on",
      actionAnswer: "Answer",
      actionSummarize: "Confirming the end",
      counters: "Said {n} · Spoke {m} · Pulled back {k}",
      lightsOn: "Lights on · {title}",
      missingSession: "No session is selected. On the start page, tick the star map option and start again.",
      loadFailed: "Could not load.",
      keyLink: "API key",
      setupHeading: "Add your own Meta key",
      setupLine: "Blackout runs on your computer and calls Meta's models with your key.",
      keyPlaceholder: "Paste your key",
      saveKey: "Save and check",
      getKey: "Get a key from Meta",
      noKeyExample: "No key yet? See a real example",
      exampleBanner: "A real replay of a fictional talk. No key needed.",
      runYourself: "Run it yourself",
      exampleSkip: "Skip to the result",
      exampleNoAudio: "No audio is played.",
      exampleNeedServer: "This example needs to be served over HTTP.",
      factLocal: "It stays on this computer and never enters the code repository.",
      factMetaOnly: "It only goes to api.meta.ai. No page or log will show it again.",
      factCost: "Costs come from your own Meta account, about $0.20 for a short talk.",
      savedKey: "A key is saved on this computer.",
      replaceKey: "Replace it",
      deleteKey: "Delete it",
      back: "Back",
      envKey: "Using the key from .env or the environment. Change it there.",
      notLocalKey: "Set the key on the computer that runs Blackout.",
      checking: "Checking…",
      error_budget_exhausted: "The budget is used up.",
      error_not_found: "This session was not found.",
      error_session_not_found: "This session was not found.",
      error_rate_limited: "Too many requests. Please wait and try again.",
      error_too_large: "That is too large.",
      error_payload_too_large: "That is too large.",
      error_invalid_request: "That request did not work. Please try again.",
      error_validation_error: "That request did not work. Please try again.",
      error_invalid_key_format: "That doesn't look like a key. Please copy it again.",
      error_invalid_key: "Meta didn't accept this key.",
      error_key_missing_models: "This key can't use the models Blackout needs.",
      error_network: "Couldn't reach Meta. Check your connection and try again.",
      error_not_local: "Set the key on the computer that runs Blackout.",
      error_key_from_env: "Using the key from .env or the environment. Change it there.",
      error_key_save_failed: "The key couldn't be saved. Please try again.",
      error_key_rejected: "Meta rejected the current key. Use the link at the top to change it.",
      error_no_key: "Please set an API key first."
    }
  };
  function storedLang() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      if (value === "zh" || value === "en") { return value; }
    } catch (e) {}
    return "";
  }
  function detectLang() {
    const stored = storedLang();
    if (stored) { return stored; }
    const nav = String((window.navigator && window.navigator.language) || "");
    return nav.toLowerCase().indexOf("zh") === 0 ? "zh" : "en";
  }
  let current = detectLang();
  function lang() { return current; }
  function has(key) {
    return Boolean(STRINGS[current] && Object.prototype.hasOwnProperty.call(STRINGS[current], key));
  }
  function t(key, values) {
    let text = has(key) ? STRINGS[current][key] : key;
    if (!has(key) && STRINGS.zh[key]) { text = STRINGS.zh[key]; }
    const vals = values || {};
    Object.keys(vals).forEach(function (name) {
      text = text.split("{" + name + "}").join(String(vals[name]));
    });
    return text;
  }
  function pageTitle() {
    const path = String((window.location && window.location.pathname) || "");
    return path.indexOf("observer") >= 0 ? t("observerTitle") : t("appTitle");
  }
  function apply(root) {
    const base = root || document;
    if (!base || !base.querySelectorAll) { return; }
    base.querySelectorAll("[data-i18n]").forEach(function (node) {
      node.textContent = t(String(node.getAttribute("data-i18n") || ""));
    });
    base.querySelectorAll("[data-i18n-placeholder]").forEach(function (node) {
      node.setAttribute("placeholder", t(String(node.getAttribute("data-i18n-placeholder") || "")));
    });
    base.querySelectorAll("[data-i18n-alt]").forEach(function (node) {
      node.setAttribute("alt", t(String(node.getAttribute("data-i18n-alt") || "")));
    });
  }
  function set(next, persist) {
    current = next === "en" ? "en" : "zh";
    if (persist !== false) {
      try { window.localStorage.setItem(STORAGE_KEY, current); } catch (e) {}
    }
    document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
    document.title = pageTitle();
    apply(document);
  }
  document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
  document.title = pageTitle();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { apply(document); });
  } else {
    apply(document);
  }
  return { lang: lang, set: set, t: t, apply: apply, has: has };
})();
