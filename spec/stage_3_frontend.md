Implement stage 3 of the v2 spec above: the whole user-facing frontend except the observer window. Return the full content of every changed or new file.

The backend is complete. Read its routes and bridge in the current project and match them exactly. Do not change backend behaviour, except for this one fix, which you must also return: in `budget.py`, `can_spend` allows a new session when spending is exactly at the limit. With `additional_usd` of zero it must return `spent < limit`; with a positive amount, `spent + additional_usd <= limit`. `tests/test_realtime.py::test_10_budget_check_with_real_can_spend_and_temp_ledger` covers this and must pass.

Your response must contain every file listed under "Implement now", plus `budget.py` and `tests/test_static.py`. Also change `app/main.py` only if needed to serve the new static files correctly.

The old single-file frontend's inline script is gone: `index.html` is markup only. The Content-Security-Policy in `app/security.py` blocks inline scripts and styles, so a leftover inline block would silently break the page.

## Implement now
- `app/static/index.html`: markup only. No inline script, inline style, or `style=` attribute, because of the Content-Security-Policy.
- `app/static/app.css`
- `app/static/js/cues.js`: shared AudioContext and the tick, chime, rise, and fall cues. Failures never throw.
- `app/static/js/speech.js`: `speak(text)` returning a promise that always resolves, with the fallback timer, Chinese voice selection, and a check for whether a Chinese voice exists. `getVoices()` can be empty until `voiceschanged`, so wait up to 1 second for it before deciding.
- `app/static/js/capture.js`: microphone capture, the AudioWorklet from a Blob URL, 24 kHz conversion, 80 ms 16-bit frames, and a muted mode that sends zeroed frames. Also WAV recording for push-to-talk and the goal mic.
- `app/static/js/black.js`: the black screen, including the WebSocket, half duplex, reconnect handling, pause, push-to-talk fallback, and `endSession()`.
- `app/static/js/result.js`: the result page and sketch upload.
- `app/static/js/start.js`: the start page, recent sessions, resume, delete, and the observer checkbox.
- Use plain script files loaded with `defer`, or ES modules. Ensure `/static/*` serves JS with the correct MIME type.

## Details to get right
- A Blob URL worklet needs `blob:` in `script-src`, which the policy allows. No `eval`.
- The goal mic and the black-screen capture must not leave a microphone open. Every exit path stops all tracks and closes the capture context. This includes: ending during `getUserMedia`, ending during worklet setup, WebSocket failure, page unload, and permission denial. Use a generation counter checked after every `await`.
- Permission denied on the black screen: say "需要麦克风权限，请允许后重试。" and return to the start page rather than leaving the user on black.
- WebSocket URL: `wss:` when the page is HTTPS, otherwise `ws:`. Use `location.host`.
- Start capture only after the server sends `ready`. Until `ready` or a fallback arrives, the dot shows reconnecting. If nothing arrives in 8 seconds, use the fallback.
- Speak only one thing at a time. Space during speech cuts it off, sends `tts_finished`, and resumes the mic after 300 ms. A `say` arriving during playback waits in a local queue; the server should not send one, but do not break if it does.
- Send `tts_started` before speaking and `tts_finished` afterward. Always send `tts_finished`, including on errors and when no voice exists.
- `end` from the server goes through `endSession()`. With reason `budget`, say "预算用完了，我把内容整理出来。" instead of the normal line.
- `fallback`: speak the message and switch to push-to-talk without leaving the black screen. In push-to-talk, a response with `end: true` goes through `endSession()`, and `budget_exhausted` is treated like budget `end`.
- Keep the Esc, `fullscreenchange`, and 800 ms long-press paths going through one `endSession()`. A long press must not also count as a tap. Only treat leaving fullscreen as an end if the page actually was fullscreen.
- `beforeunload` and `pagehide` stop capture. The session remains `active` on the server and can be resumed from the start page.
- Resume an active session: reuse its id, go straight to the black screen, and say "接着刚才的继续。" rather than the entry line.
- Reopening a finished session shows its saved result by calling `GET /api/sessions/{id}`, without calling finish again.
- 再来一次 returns to the start page and refreshes the list. Clear the stored active session id when a session finishes or is deleted.
- Copy as Markdown uses `navigator.clipboard` with a fallback, because LAN HTTP or some browsers may refuse. Show a brief "已复制" state on the button.
- Sketch upload: show a working state on the button and report errors on the page using `textContent`.
- Text in Chinese. Layout works at phone width with no horizontal scroll. Respect `prefers-color-scheme` on the start and result pages; the black page stays pure black always.
- No transcript, reply, or status text ever appears on the black page after the hint fades.

## Tests
`tests/test_static.py`: no `<script>` without `src` and no `style=` or inline event handlers in any HTML; all referenced static files exist and are served with correct MIME types; no external URLs in HTML, CSS, or JS; no `innerHTML` assignment anywhere in the JS; no `eval(` or `new Function`.
