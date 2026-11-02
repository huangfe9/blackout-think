Screenshots of stage 5 and a security review found the items below. The concept works and should be kept. Fix these. Return the full content of every changed or new file.

Your response must contain: `app/static/map.css` (new), `app/static/js/map.js`, `app/static/observer.html`, `app/static/observer.css`, `app/static/index.html`, `app/static/app.css`, `app/static/js/observer.js`, `app/static/js/result.js`, `app/static/js/black.js`, `app/phone.py`, `app/security.py`, `app/store.py`, `app/tasks.py`, `app/conductor.py`, `app/routes.py`, `app/prompts.py`, `budget.py`, `muse_client.py`. Tests and documentation come in a later step, so do not return `tests/` or docs in this response.

## Map rendering (`js/map.js`, new `map.css`)
1. **The Content-Security-Policy blocks the injected style.** `render` adds a `<style>` element to the SVG, so every reload logs a violation, and the glow and pulse animations do nothing. Remove it. Put all map styling, including keyframes and the reduced-motion rule, in a new `app/static/map.css` linked from both `index.html` and `observer.html`. The svg gets a class `map-night` or `map-paper`.

2. **Lines strike through text.** Give labels a class `map-label` with `paint-order: stroke; stroke-linejoin: round; stroke-width: 5px`, and a stroke equal to the background (`#000` on night, `#f6f1e7` on paper), so a connector passing behind a label does not cross it. Connectors from the root must stop at the edge of the goal text: compute an ellipse around the wrapped goal text, and start each line where it leaves that ellipse.

3. **The goal wraps badly.** "想清楚比赛 demo 的技术方案" leaves a lone "案" on the second line. Balance it: choose the number of lines (1 to 3) from its length, then split so lines are close to equal in width. Goal text is 24 px at weight 300, with the soft glow on night.

4. **Too small and too spidery.** Labels are 15 px and shrink further as the map scales down. Make the base label 17 px, weight 400 on paper and 300 on night, and decisions 600. Reduce ring radii to about 170, 300, 420 for depths 1, 2, 3, then 110 more per level. Stretch horizontally by a factor of about 1.45, since the window is wide; apply it to x when computing positions, keeping label anchors the same. Guarantee room: if the outermost ring has less than about 44 px of arc per leaf, scale all radii up so it does. Node positions must be computed in the same stretched space used for the bounding box.

5. **Contradiction connector.** After a new contradiction animates, it stays solid, because the final draw still treats it as new. Update `seen` before the final draw, so it ends dashed.

6. **Node reveal and tweening.** Add easing (ease-out cubic) to the 600 ms tween. Do not remove and re-add every element on each frame if a simple attribute update will do; pulses restart otherwise. Reuse elements keyed by node id, adding and removing only what changed.

7. **Phone width.** A radial map is unreadable at 390 px. Add `BlackoutMap.renderOutline(container, tree)`: a nested list with the same marks drawn by CSS, full text with no truncation, and indentation showing structure, using `textContent` only. `result.js` uses the outline when the page is narrower than 640 px, and the SVG otherwise, and re-chooses on resize.

## Star map window
8. **Subtitles cover the map.** The bottom subtitles overlap nodes. Give the map its own area: top about 44 px, bottom about 150 px, right about 250 px, so it never sits under the subtitle area or the parking column. The SVG fills that area with `preserveAspectRatio="xMidYMid meet"`. Pin the parking column to the top of the right edge, under the mic state.

9. **Mic state after a text turn.** The label can stay on AI 在说 when nothing is speaking. `live.mic` must only become `ai_speaking` from the bridge during actual playback. `conductor.py` must not set it to `ai_speaking`.

## Search wording
10. Spoken conclusions came out as "每小时收费零点一八美元". Tell the search prompt to use Arabic numerals and keep units, such as "每小时 0.18 美元".

## Security review findings
11. **Phone token in logs (medium).** `app/phone.py` runs uvicorn with the access log on, so the first request `GET /?token=...` prints the token. Pass `access_log=False`. The token must only appear in the one start-up URL and QR code.

12. **The spend cap can undercount (medium), in `budget.py`:**
    - Reject negative or non-finite amounts in `spent_usd` and in `record_spend` by raising `ValueError`. NaN must not pass any check; `can_spend` returns false.
    - `record_spend` retries an append up to 5 times over about 1 second, because a sync client or antivirus can briefly lock the file. If it still fails, set a module-level latch that makes `can_spend` false and makes `BudgetedHttpClient` refuse further paid calls in this process, with a message saying spend could not be recorded. A paid call that cannot be recorded must not be followed by more.
    - If `super().send` raises a transport error or timeout after the request was sent, record the worst case and re-raise, because the provider may have billed it. Non-2xx responses still record nothing.
    - Move the ledger out of the repository. Default `LEDGER_FILE` is `%LOCALAPPDATA%\Blackout\spend.jsonl` on Windows and `~/.blackout/spend.jsonl` elsewhere, honouring `BLACKOUT_DATA_DIR`. **The running total must not reset:** if the new file does not exist and the old `<repo>/.muse_spend.jsonl` does, copy it over once, and keep the old file in place. `budget.py` must not import from `app`.

13. **No ceiling on background work (medium).** Any speech, including a TV in the room, can start a search on every turn. In `tasks.py`/`conductor.py`: a session may start at most `BLACKOUT_MAX_TASKS_PER_SESSION` tasks (default 12). A task whose instruction, after removing punctuation and spaces, equals one already started in this session does not start again. When refused by the cap, the reply is "这次后台的事够多了，我先记下这个问题。", and the instruction is added to open questions so it is not lost. Only a real start counts towards `task_started`.

14. **`testserver` in the production allow-list (low).** Remove it from `ALLOWED_DEFAULT_HOSTS` in `app/security.py`. The test configuration will set it.

15. **Clickjacking (low).** Add `frame-ancestors 'none'; base-uri 'none'; form-action 'self'` to the Content-Security-Policy, and an `X-Frame-Options: DENY` header.

16. **Ids and state-changing GET (low).** In `app/store.py`, use `fullmatch` for ids, because `$` also accepts a trailing newline. `get_session_copy` and every function taking a session id must validate before calling `get_lock`, so garbage ids do not grow the lock table. Change `GET /api/sessions/{id}/announcements`, which drains state, to `POST`, and update `black.js`.

17. **Chunked bodies (low).** Non-GET `/api/*` requests with neither `Content-Length` nor a safe empty body are not size-checked. Browsers always send `Content-Length` for `fetch` with JSON or FormData, so in `app/security.py` respond 411 to a POST, PUT, or PATCH to `/api/*` that has `Transfer-Encoding` and no `Content-Length`. `POST .../finish` with no body stays allowed.

18. **Files at rest (low).** Create the data directory with mode `0o700`, and session and ledger files with `0o600`, where the platform supports it, without failing where it does not. In `app/phone.py`, set `BasicConstraints(ca=False)`.

Keep every other behaviour the same. Everything rendered still uses `textContent`, and there are still no inline scripts or styles.
