A real user tried the app and could not tell how to stop. This product is used without looking at the screen, so every state and every instruction must be audible. Fix the following and keep everything else unchanged.

## app/static/index.html

1. CRITICAL, Esc in fullscreen. Browsers use Esc to leave fullscreen and may not deliver the keydown to the page, so the page stays black with no way out. Add a `fullscreenchange` listener: if the document was fullscreen, is no longer fullscreen, and the black page is visible, end the session. Fullscreen must never be left without ending the session.

2. CRITICAL, one way to end. Add a single `endSession()` used by Esc, `fullscreenchange`, and voice end. It must:
   - do nothing if already ending
   - stop any recording and release the microphone
   - cancel speech that is playing
   - invalidate any in-flight turn with a turn counter, so a late reply is neither spoken nor able to trigger a second finish
   - say "好，我来整理" so the user knows the app heard them, then call `finish()`
   `finish()` must show the result page even if that speech fails or never ends. Do not wait for speech to finish before starting the request. Show the result page without waiting for the speech to end, and let `speechSynthesis` play out.

3. HIGH, spoken instructions. On entering the black screen, speak: "黑屏开始。按空格说话，说完再按一次。想结束就说结束，或者按 Esc。" A key press or click during this speech interrupts it and starts recording as usual.

4. HIGH, audible recording state. Play a short Web Audio cue, about 120 ms at low gain: rising tones when recording starts, falling tones when it stops. Create or resume one shared AudioContext for cues, separate from the capture context. A cue failure must never block recording. Start capture only after the start cue has played so the cue is not recorded.

5. HIGH, key handling. Ignore `e.repeat` on Space, because holding Space currently toggles recording rapidly. Add a `starting` flag so a press during the async setup in `startRecording` cannot open a second microphone stream. Ignore Space while the end flow is running.

6. MEDIUM, visible dot. The dot colours are nearly invisible on black. Use idle #2a2a2a, recording #b02a2a, thinking #2a5a8a, playing #2a7a3a.

7. LOW. Remove the dead `setupPipeline` function. Update the start page text to also say that the app explains the controls aloud.

## app/sessions.py and app/main.py

8. HIGH, voice end phrases. `is_explicit_end` only accepts the exact word "结束". After removing punctuation and spaces, also accept exactly these: 结束吧, 结束了, 停止, 停, 我说完了, 说完了, 就到这, 就到这里, 到这吧, 不说了, 先这样. Do not match longer sentences that merely contain these words, for example "我想讨论怎么结束这个项目" must not end the session.

9. HIGH, explicit end skips the model. When `is_explicit_end` is true, do not call the chat model and do not add the phrase to state. Return `{"transcript": ..., "action": "summarize", "reply": "好，我来整理", "end": true}`. In the frontend, when a turn returns `end: true`, go through `endSession()` rather than speaking the reply separately, so the phrase is not said twice.

10. CRITICAL, never lose the user's work. `api_finish` currently returns an error on model failure and on budget exhaustion, which leaves the user on a black screen and hides everything they said. On any model error, budget error included, or parse failure, return status 200 with the result built from the stored session state and `_fallback_markdown`, plus `"degraded": true`. Log the failure with `logger.exception`. On success return `"degraded": false`. Show a one-line notice on the result page when degraded, using textContent: "AI 整理没有完成，下面是对话中记录的原始内容。"

## tests/test_app.py

11. Update the tests to match, and add:
   - every new end phrase ends the session
   - a longer sentence containing 结束 does not end the session
   - explicit end does not call `responses.create`
   - finish returns 200 with `degraded: true` and the stored state, for a model error, a 402, and a parse failure
   - finish returns `degraded: false` on success

## README.md and docs/demo_script.md

12. README: describe how to stop (say 结束 or a listed phrase, or press Esc) and that controls and states are audible. docs/demo_script.md: add the spoken instructions and the start and stop cues where the black screen begins.
