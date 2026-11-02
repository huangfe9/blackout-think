Acceptance found three real defects. Fix them. Return the full content of exactly these files: `app/state.py`, `app/tasks.py`, `app/conductor.py`, `app/static/js/map.js`, `tests/test_tasks.py`, `tests/test_state.py`, `tests/test_summary.py`. Change nothing else.

## 1. Spoken answers are cut at a decimal point
A search returned "Muse Voice Transcribe costs $0.18 per hour of audio through the Meta Model API." The person heard "Muse Voice Transcribe costs $0." `_truncate_spoken` in `app/tasks.py` cuts to 60 characters and then at the last punctuation mark, and a decimal point counts as one. `truncate_reply` in `app/conductor.py` has the same rule. 60 characters is also far too short for English, where it cut off ordinary answers.

Add one shared pure function `state.truncate_speech(text) -> str` and use it in both places:
- The limit is 60 characters if the text has any CJK character, and 160 otherwise. Text within the limit comes back unchanged.
- Beyond the limit, cut at the last sentence end within the limit (`。！？.!?`). If there is none, the last clause mark (`；，、;,`). If there is none, the last space. Only then, a hard cut.
- A `.` or `,` with a digit immediately on both sides is never a boundary: 0.18 and 1,000 stay whole. Neither is a `.` inside a word, such as `muse-voice-transcribe-1.0` or `example.com`.

Tests in `tests/test_state.py`: the exact sentence above is unchanged; a long English sentence with $0.18 early and a sentence end later is cut at the sentence end; 1,000 stays whole; long Chinese text is cut at a sentence end; no punctuation falls back to a space; a text with neither gets a hard cut.

## 2. A late search result erases the clean mind map
`_finish_task` in `app/tasks.py` runs `result["map"] = build_map(...)` when a task finishes after the session has ended, replacing the organized map from the final pass with the raw one. Only do that for a result with no final pass, meaning a degraded result or an empty summary. Otherwise keep `result["map"]` as it is, and refresh `result["tasks"]` and `result["markdown"]`. Test this in `tests/test_tasks.py`, covering both cases.

Also add to `tests/test_summary.py` that `build_markdown` still includes the clean outline after a late task result.

## 3. Negative viewBox in the map
`animateRender` in `app/static/js/map.js` computes `rawProgress = Math.min(1, (now - startedAt) / 600)`. The `requestAnimationFrame` timestamp can be earlier than `performance.now()` taken at the start, by a long way in a background window, so progress goes negative, extrapolation produces a negative width or height, and the browser logs an error. Clamp progress to the range 0 to 1 on both ends. If `document.hidden` is true when a render starts, skip the tween and finish immediately, because animation frames do not run in a hidden window and the map would otherwise stop updating. In `paintFrame`, never set a `viewBox` whose width or height is not a positive finite number.
