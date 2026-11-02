Implement stage 7, part C: the pages. Two requests from the project's owner: anyone opening the app sees it brand new, with nothing that looks like someone else's work; and it must work in English, because judges may not read Chinese.

The previous start page showed a sample picture about a specific plan and a placeholder mentioning it, so it looked like leftovers from another person. Remove all of that.

`/static/how_it_works_zh.jpg` and `/static/how_it_works_en.jpg` are already in place. They are three-panel hand-drawn strips drawn by Muse Image that explain the product and contain no specific content. Their ratio is about 1.75 to 1.

Return the full content of exactly these files: `app/static/js/i18n.js` (new), `app/static/index.html`, `app/static/observer.html`, `app/static/app.css`, `app/static/observer.css`, `app/static/js/start.js`, `app/static/js/black.js`, `app/static/js/result.js`, `app/static/js/speech.js`, `app/static/js/observer.js`. Keep lines under 120 characters, with one statement per line. No inline scripts or styles. Everything rendered uses `textContent`.

## `js/i18n.js`
`window.BlackoutI18n` with `lang()`, `set(lang)`, `t(key, values)`, and `apply(root)`, which fills elements carrying `data-i18n` and `data-i18n-placeholder`. Language: `localStorage` key `blackout_lang`, otherwise `navigator.language` starting with `zh` gives `zh`, otherwise `en`. Wrap storage in try/catch. It sets `document.documentElement.lang` and `document.title`. Every fixed string on every page comes from this table. Keep the existing Chinese strings. English:

Start page:
- Headline, in two lines: "Think it through" / "without looking at a screen."
- Sub line: "Just talk. When you're done, you get a one-page summary and a picture."
- Placeholder: "What do you want to figure out? For example: how to structure next week's talk"
- Button: "Lights off, start talking"
- Small line: "The screen goes black. Just start talking. Say “stop” and the lights come on."
- "Continue where I left off", "Past sessions ({count})", "View", "Continue", "Delete", "Delete this session?"
- Checkbox: "Recording a video: also open the star map window"
- Warning when no matching voice exists: "This device has no voice for this language, so you may not hear the AI. Try Chrome or Edge."
- Microphone errors: "Microphone access is needed to start. Allow it in the address bar and try again." and "No microphone found."

Chinese placeholder becomes: 这次想想清楚什么？比如：下周的汇报怎么讲. Chinese sub line: 你只管说。说完，给你一页总结和一张图。

Black screen:
- Hint: "Space to pause · Say “stop” or press Esc to finish"
- Entry line: "The screen is dark now. I'm listening, so just start talking. Press space to pause. To finish, say stop, or press Escape."
- Resume line: "Picking up where we left off."
- Ending: "OK, let me pull this together. One moment." Budget: "The budget is used up. Let me pull together what we have."
- Push-to-talk errors: "I didn't catch that. Please say it again."
- Permission: as above.

Result page:
- "Pulling together what you said…", "That didn't work, but everything you said is still here.", "Retry"
- "Drawing your picture…", "Download picture", "Draw another", "Couldn't draw the picture.", "Stop reading", "All done."
- Sections: "Mind map", "Decisions", "To do", "Still open", "Contradictions", "Unfinished", "Parking lot", "Looked up and drafted", "Paper sketch", "Original words:", "Your words ({count})", "Details", "Searching: {text}", "Writing: {text}"
- "Copy as Markdown", "Copied", "Add a paper sketch", "Start again", "Nothing was recorded this time.", degraded: "The AI summary didn't finish. Below is what was recorded during the session."

Star map:
- "Blackout · Star map", "Listening", "Paused", "You're talking", "AI speaking", "Offline"
- Actions: "Listening, not interrupting", "Follow-up", "Pulled back", "Moving on", "Answer", "Confirming the end"
- "Parking lot", "Said {n} · Spoke {m} · Pulled back {k}", "Lights on · {title}", and a message for a missing session.

On the star map, use the record's `language`, not the browser's.

## Language toggle
On the start page, top right, one quiet text control showing the other language: `English` when in Chinese and `中文` when in English. Clicking it switches the language at once, without reloading, including the picture and placeholder, and remembers it.

## Start page: brand new every time
- Default state: no list, no content from before, an empty input.
- Layout on wide screens: left column about 44% with Blackout, the two-line headline, the sub line, the input with the mic, the button, and the small line. Right column: the strip for the current language, shown flat with no tilt and no caption, on a soft paper-toned sheet. Its alt text describes the three panels. On phones the strip comes after the small line, full width. The headline must not leave a lone character on a line.
- **History is out of the way.** Below, one quiet text link, 之前的记录（N） or Past sessions (N), appears only if this browser has sessions, and it expands the list. The list starts closed on every visit. Only this browser's sessions ever appear, which the server now enforces.
- **继续上次** appears only if `localStorage` holds an active session, the server says it is still active and it belongs to this browser, and it was updated within the last 2 hours. Otherwise clear the stored id and show nothing.
- The checkbox stays small, near the bottom. No-voice warning: one small line.
- `POST /api/sessions` sends `language`. The goal mic calls `/api/transcribe?language=<lang>`. `black.js` receives the goal as before.

## Speech (`js/speech.js`)
Choose the voice by the text being spoken: any CJK character means Chinese, otherwise English, setting `utter.lang` to `zh-CN` or `en-US`. For each, prefer a natural or online voice. `hasVoice(lang)` replaces the Chinese-only check.

## Announcements in push-to-talk and errors
Errors from the server have Chinese messages. Where the page shows or speaks an error, map known `error.code` values to the i18n table and fall back to the server's message.
