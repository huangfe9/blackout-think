An end-to-end run in real Chrome, with a fake microphone and the real API, worked: speech became text, the AI stayed quiet, hot pot was parked, a search returned the right answer in 4 seconds, and Esc and leaving fullscreen both ended the session. It also found the defects below. Fix them all. Return the full content of every changed file.

Your response must contain: `app/realtime.py`, `app/state.py`, `app/conductor.py`, `app/prompts.py`, `app/static/index.html`, `app/static/js/black.js`, `app/static/js/capture.js`, `app/static/js/speech.js`, `app/static/js/start.js`, `app/static/js/result.js`, `tests/test_realtime.py`, `tests/test_state.py`, `tests/test_conductor.py`, `tests/test_static.py`.

## Critical
1. **The user's words are lost while the AI speaks.** The browser mutes the microphone during speech. In the test, a nudge played as the user said "My todo is to write the prompts first thing tomorrow morning", so the todo was lost. Apply the updated spec sections: "The microphone stays on while the AI speaks" and "Echo and interruption".
   - `black.js`: `applyMuted` depends only on `paused`. Remove `scheduleUnmute`. `tts_started` carries the text. On `stop_speech`, cut off speech the same way Space does, without pausing.
   - `state.py`: add `is_echo`.
   - `realtime.py`: track suspect turns exactly as the spec says. A suspect turn must not block delivery or discard replies. A confirmed turn behaves like any other. `last_speech_end` and nudges are unaffected by echo.
   - Tests with the fake server: echo partial and `speechComplete` during playback produce no turn, no `stop_speech`, and no change to `user_speaking`; a different partial during playback sends `stop_speech` once and its `speechComplete` produces a turn; a reply computed while an echo turn is open is still delivered; `speechStart` 0.5 seconds after `tts_finished` is treated as suspect, and at 2 seconds is not. Unit tests for `is_echo`: exact match, match with different punctuation, a garbled version around 70% similar, unrelated text, a sentence containing both, and text under 2 characters.

2. **Fullscreen and the permission prompt.** Getting the microphone for the first time can show a browser prompt. If that drops fullscreen, the session ends at once, because leaving fullscreen means end. Ask for the microphone on the start page instead. In the 开始, 继续, and 继续上次 handlers: after priming audio, call a new `BlackoutCapture.ensurePermission()`, which calls `getUserMedia` and immediately stops the tracks. If refused, stay on the start page and show "需要麦克风权限才能开始。请在地址栏允许麦克风后重试。" in `#startErr`. If no microphone is found (`NotFoundError`), show "没有找到麦克风。". Only then create the session and enter the black screen. If `requestFullscreen` then fails because the user gesture expired, carry on without fullscreen. Add a generation check so a second click cannot start two flows; disable the buttons while starting.

## High
3. **Audio context on phones.** iOS only starts an AudioContext created or resumed in a user gesture, and `capture.js` creates it much later, after `ready`, so it would stay suspended and send nothing. Add `BlackoutCapture.prime()`, called synchronously in the click handler, which creates and resumes the 24 kHz context and stores it. The stream capture uses and owns that context. Always call `await ctx.resume()` before capture starts. Some browsers, such as Firefox, throw `NotSupportedError` when connecting a stream to a context at a different rate. Catch it in `graph.open`, close that context, and retry once with a default-rate context; the worklet already downsamples using `sampleRate`.

4. **Push-to-talk errors are silent.** In `stopPtt`, a non-OK response or a network failure says nothing, so an eyes-free user cannot tell it failed. Status 402: call `endSession("budget")`. Any other failure: say the server's message, or "没听清，再说一次。". The fallback wording says "按住说话", but the control is press to start and press to stop. Change it everywhere, `black.js` and `realtime.py`, to "自动听写断了。现在按空格开始说话，说完再按一次。".

5. **Dropped speech leaves the server waiting.** In `say`, when `epoch !== speechEpoch` the text is dropped without `tts_finished`, so the server blocks delivery for up to 20 seconds. If the mode is realtime, send `tts_finished` in that case.

6. **Late task results on the result page.** A search can finish after the session ends, and the page never updates. In `result.js`: when a shown result has a task with status `running`, poll `GET /api/sessions/{id}` every 3 seconds, for up to 3 minutes, and re-render from `record.result` when it changes. Stop polling when nothing is running or the page is left. Show running tasks as "还在查……" or "还在写……" using their `instruction`.

7. **Sources hidden.** `makeTasks` only shows sources inside `if (task.detail)`. A task with sources and no detail shows none. Show the expandable section when there is a detail or a source.

## Medium
8. **Nudge wording** in `conductor.nudge_text`:
   - The name is cut mid-word ("state tracki"). Allow up to 16 characters, cut at the last space or punctuation inside that limit when there is one, and otherwise cut at 16.
   - The second nudge repeats the first. Use the point in the first nudge only. The second nudge is always "还在吗？卡住的话，先说一个最小的问题。".
   - Add tests.

9. **Prompt:** a question handed to a background task must not also go into `add_questions`, because in the test "how much does it cost" stayed in 还没想清楚 even after it was answered. Record additions in the language the person spoke.

10. **Favicon:** the page logs a 404 for `/favicon.ico`. Add `<link rel="icon" href="data:,">` to `index.html`. The policy allows `img-src data:`. Add a check to `tests/test_static.py`.

All tests must pass and stay quick.
