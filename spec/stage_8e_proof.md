Implement stage 8, part E: proof that works without a key.

Most people who look at this project will never paste a key. They need to see what it does, and to see measured evidence, with nothing to install and nothing to spend. Everything in this part is honest: real output from real runs of fictional talks, labelled as such.

Return the full content of exactly these files: `tests/evals/talks.json` (new), `tests/evals/run_evals.py` (new), `tests/evals/make_samples.py` (new), `app/static/example.html` (new), `app/static/js/example.js` (new), `app/static/js/result.js`, `app/static/app.css`, `app/static/setup.html`, `app/static/js/i18n.js`, `docs/demo_talk.json` (new), `tests/test_example.py` (new). Keep every behaviour and id you are not asked to change. Add nothing else.

## 1. `tests/evals/talks.json`
Write 8 fictional talks, 4 in English and 4 in Chinese, each 14 to 24 spoken lines in natural, rambling speech with fillers, about everyday work and life decisions: a job offer, a team offsite, a move, a side project, a small launch, a family trip, and so on. Never health or mental health, politics, or real people or companies. Exactly one English and one Chinese talk have `"sample": true`.

Each talk: `{"id", "language", "goal", "sample", "lines": [{"text", "expect"}], "must_decide": [regex], "must_todo": [regex], "must_open": [regex], "must_park": [regex], "must_draft": bool}`. `expect` is `"pull_back"` for a clearly off-topic line, `"conflict"` for a line stating a fact that differs from an earlier one without pointing out the change, `"task"` for a "look this up" request, `"end"` for the last line, and absent otherwise. Regexes are case-insensitive and tolerant, since the final wording will vary. Each talk has at least one of each of pull_back, conflict, and task. At least 3 of the 8 include a sentence that should not be treated as a conflict, because the speaker points out the change themselves, and that line has no `expect`.

The sample talks: an English one where the person decides how to run a small product launch and a Chinese one where the person decides whether to take a side project. Both end with a todo to write something, and have `must_draft` true.

## 2. `tests/evals/run_evals.py`
`python -m tests.evals.run_evals [--only id]`. It uses the real model through the normal code path and the normal spending ledger, with sessions in a temporary `BLACKOUT_DATA_DIR`. It calls `conductor.process_speech(session_id, text, now=ts)` with simulated time: each line advances `ts` by its spoken length, at 4.5 characters per second for Chinese and 2.6 words per second for English, plus 1 second. Then it waits up to 90 seconds for background tasks and calls `summary.finish`, then waits up to 60 seconds for the draft task. No picture wait.

For each talk, record: lines, AI spoke count; pull-backs expected and hit; conflicts expected and asked; tasks expected and started; false interruptions, meaning the AI spoke on a line with no `expect` and it was not a reflection line; decisions, todos, open questions, and parked items found versus expected, by regex over the final lists; whether a draft finished and contains the placeholder rule's text only if needed; median and slowest turn seconds; the cost of the talk from `budget.spent_usd`.

Write `docs/evals.json` and `docs/evals.md`. The Markdown has a one-paragraph note saying these are fictional talks typed through the same code path, skipping speech recognition, scored by simple rules, and that they measure behaviour and not whether the product helps people. Then one table with a row per talk, a totals row with percentages, and the run date. It prints the path and the total cost. If the spending cap is reached, it writes what it has and says so. Never print a key.

## 3. `tests/evals/make_samples.py`
`python -m tests.evals.make_samples`. For each talk with `"sample": true`, run it as above but also wait up to 150 seconds for the picture, and write:
- `app/static/sample/{language}.json`: `{"language", "goal", "fictional": true, "frames": [...], "result": {...}}`. Each frame is `{"t": seconds, "heard": text, "reply": text, "action": str, "map": build_map(state, tasks), "parking": [...], "stats": {...}}`, taken after each turn. `result` is the final result with `owner`, session ids, and `transcript` timestamps removed. `result["poster"]` is `{"status": "done", "version": 1, "error": "", "src": "sample/{language}.jpg"}`.
- `app/static/sample/{language}.jpg`: the picture, converted with Pillow to JPEG at quality 85 and at most 1400 pixels wide, or copied as `.png` with the `src` to match if Pillow is missing.

## 4. `app/static/example.html` and `app/static/js/example.js`
A page that works in three places: from the app at `/static/example.html`, from GitHub Pages at any sub-path, and needing no server at all beyond static files. So every URL in the page and in `example.js` is relative, like `app.css`, `js/map.js`, `sample/en.json`. It makes no call to `/api/`, opens no socket, and needs no microphone.

The page includes the same markup `result.js` needs, the star map styles, and a banner at the top: "这是一场虚构谈话的真实回放，不需要 key。" / "A real replay of a fictional talk. No key needed." with a language toggle and a link "自己运行" / "Run it yourself" to `https://github.com/huangfe9/blackout-think#run-it`.

`example.js` loads the JSON for the browser's language, then plays the replay in a star map view, black like the real one:
- `BlackoutMap` draws each frame's `map` in the night theme, at 1.5 times real speed, with the caption showing `heard`, the AI's `reply` in amber for about 4 seconds, the parking lot, and the counters, using the same labels as the star map window. It says no audio is played.
- A button "跳到结果" / "Skip to the result" is visible all the time.
- At the end, the page fades to paper and `BlackoutResult.showResult(result, null)` shows the real result page.
- Respect `prefers-reduced-motion` by going straight to the last frame, then the result.
- If `fetch` fails, for example when opened from `file://`, show one line saying it needs to be served, with a link to the repo.

## 5. `app/static/js/result.js`
- If `poster.src` exists, it is the image URL and takes priority over `/api/sessions/...`, for showing and for the download link. Draw another is hidden.
- With a null session id, nothing polls, and "add a paper sketch" and "start again" are hidden.

## 6. `app/static/setup.html` and `i18n.js`
On the setup page, under the link for getting a key, add a quiet link `static/example.html` written as the absolute path `/static/example.html`: "还没有 key？先看一个真实例子" / "No key yet? See a real example".

## 7. `docs/demo_talk.json`
The script of the 3-minute demo, in English, for one person thinking out loud. It will be spoken by a synthesized voice into the real app through the real API, so nothing can depend on tone. It must be natural speech, and short sentences recognise better.

`{"goal": str, "lines": [{"say": str, "pause_after": seconds, "beat": str}], "captions": {"beat": "caption text"}, "title_lines": [str], "closing_lines": [str]}`.

The total of spoken time, at 2.6 words per second, plus pauses, is at most 105 seconds. The goal is about running a small product launch this week. Beats in order, each `beat` naming which it is:
- `open`: says there are three things to sort out: the launch day, support cover, and the announcement.
- `quiet`: thinks aloud, with a clear decision ("Okay, decided: we launch Thursday morning.") and a clear fact, that three people are on support.
- `drift`: a standalone off-topic line about wanting hot pot tonight, `pause_after` 7.
- `lookup`: "Please look up what time of day launch emails get the most opens.", `pause_after` 4, then one or two lines of continuing to talk, because looking something up does not stop the thinking.
- `conflict`: a line that casually says five people on support can cover the weekend, without pointing out the change, `pause_after` 9.
- `answer`: "Right, it's three..." and a decision that weekend support is on-call only, `pause_after` 7, so the search result has room to be spoken.
- `todo`: "I need to write a short launch email to customers by Wednesday, saying what's new and that weekend support is on-call only."
- `open_question`: something still not known, for example whether marketing can review it in time.
- `stop`: exactly "Stop."

Each caption is at most 12 words, for a viewer who has never seen this, and states what is happening: for `quiet`, for instance, "The AI stays silent and quietly builds the map." `title_lines` are the opening card, and include the sentence "Recorded live against the real Meta API. The voices are computer speech." `closing_lines` are the closing card, and include that it runs on your own computer with your own Meta key.

## `tests/test_example.py` (new)
Static checks: `example.html` and `example.js` have no `/api/`, `WebSocket`, or `getUserMedia`, and every script and stylesheet URL is relative. `talks.json` is valid with 8 talks, 4 per language, exactly one sample per language, and at least one each of pull_back, conflict, and task per talk. `demo_talk.json` is valid, has each beat in order, and stays within 105 seconds by the rule above. If `app/static/sample/en.json` exists, it has no `owner` key anywhere, and `fictional` is true.
