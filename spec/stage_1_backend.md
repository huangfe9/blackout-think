Implement stage 1 of the v2 spec above: the backend core, without WebSockets. The existing frontend must keep working against these routes until stage 3 replaces it.

Return the full content of every changed or new file.

## Implement now
- `app/state.py`, `app/store.py`, `app/conductor.py`, `app/tasks.py`, `app/summary.py`, `app/sketch.py`, `app/prompts.py`, `app/routes.py`, `app/main.py`, exactly as specified. Remove `app/sessions.py` by returning it with the single line `# Replaced by state.py and store.py.`. Stage 2 adds `realtime.py` and `security.py`; leave out the WebSocket route for now.
- All HTTP routes in the spec except `WS`. `/live` can return in-memory values updated by the conductor.
- `tests/test_state.py`, `tests/test_store.py`, `tests/test_conductor.py`, `tests/test_tasks.py`, `tests/test_summary.py`, `tests/test_sketch.py`, `tests/test_routes.py`. Replace `tests/test_app.py` by returning it with the single line `# Replaced by the focused test modules.`.

## Changes to root files
`budget.py`:
- Add `WEB_SEARCH_USD_PER_QUERY = 0.0025` and `WEB_SEARCH_WORST_CASE_QUERIES = 10`.
- `refusal_reason`: allow a tool whose `type` is exactly `web_search`, on `/v1/responses` only. Other tool types containing `search` stay refused with the existing message. Other built-in tools stay refused.
- `worst_case_usd`: when a `web_search` tool is present, add the worst-case queries times the price.
- After a successful metered call, add the price for each item of type `web_search_call` in the response `output`, on top of the token cost.
- Add `can_spend(usd: float, ledger: Path = LEDGER_FILE, limit_usd: float = STOP_AT_USD) -> bool`: false if over the limit or if the ledger is unreadable.
- Add `record_audio_seconds(seconds: float, ledger: Path = LEDGER_FILE) -> None`: records seconds divided by 3600 times the hourly price, under `TRANSCRIBE_MODEL`.
- Keep every existing name and behaviour otherwise. Update `test_budget.py`: `web_search` is now allowed and its queries are charged; `web_search_preview` is refused on `/v1/responses`; `web_search` is refused on `/v1/chat/completions`; test both new functions.

`muse_client.py`: change the default of `transcribe_wav` to `("Mandarin Chinese", "English")`. Add `REALTIME_URL = "wss://api.meta.ai/v1/asr/realtime"`.

`build_with_muse.py`: add `LICENSE` to the infrastructure files.

`.gitignore`: add `data/`.

`requirements.txt`: add `websockets>=13`, `cryptography>=42`, `segno>=1.6`.

## Required test cases (at minimum)
`test_state.py`: additions append without losing existing items; exact duplicates are dropped; `expand_points` and `resolve_questions` affect only matching entries; list caps hold; inputs are never mutated.

`test_store.py`: atomic save and load round-trip; an invalid id such as `../../etc/passwd` is not found and creates no file; delete; list order; a `running` task loaded after a restart becomes `failed`; the data directory comes from `BLACKOUT_DATA_DIR`.

`test_conductor.py`:
- the model's input contains `current_user_text` with the text just spoken
- a `listen` turn has an empty reply, still records history and additions, and increments `listened`
- a `follow_up` within the speaking gap becomes `listen` but keeps additions; with `user_asked_ai` true it stays
- `pull_back` is exempt from the gap and stores the parking item
- every end phrase ends with no model call; a longer sentence containing 结束 does not end
- model `summarize` asks for confirmation without ending; 对 then ends; any other speech clears the flag
- a model exception then parse failure falls back to `listen` with the user text saved
- a 402 returns `budget_exhausted` true
- a `task` starts exactly one task and an empty reply becomes the acknowledgement
- `nudge_text` timing: nothing before the threshold, first text at the threshold, second after another 120 seconds, none after, none while paused or a task runs; the text names an 未展开 point when there is one and truncates it

`test_tasks.py`: search uses only the last message when output has an interim message first; sources combine annotations and `results`, drop non-http URLs including `javascript:`, dedupe, and cap at 8; a failed task is marked and announced; a draft is not spoken; web text never reaches the state.

`test_summary.py`: parking lot and contradictions come verbatim from the record even when the model returns different content; model failure and 402 both return 200-level results with `degraded` true; a finished session with no new sketches makes no model call; Markdown is all Chinese headings and omits empty sections.

`test_sketch.py`: non-image bytes are refused; an oversized file is refused; JPEG, PNG, and WebP magic bytes pass; a sketch adds items and regenerates the result.

`test_routes.py`: full flow from session to finish using fakes; the error envelope for 400 and 404; validation errors are 400, not 422; persistence across a simulated restart (clear in-memory caches, then read back); `/api/status`.
