Review of stage 1 found the defects below. Fix them all. Return the full content of every changed file.

## Your response must include these root files
The previous response left out every root-file change that `spec/stage_1_backend.md` asked for, so background search is refused by the spending guard today. Apply that section now, and return: `budget.py`, `test_budget.py`, `muse_client.py`, `test_muse_client.py`, `build_with_muse.py`, `.gitignore`, `requirements.txt`. Add a test to `test_muse_client.py` that `transcribe_wav` sends `languageBias` containing `Mandarin Chinese`.

## Critical
1. **Blocking the event loop.** `api_text_turn`, `api_audio_turn`, `api_transcribe`, and `api_sketch` are `async def` and call the conductor, `transcribe_wav`, and `process_sketch` directly. A model call takes seconds. That freezes every WebSocket on the server and will break real-time audio pacing. Run all blocking work with `run_in_threadpool`. Add a test where a fake conductor, a fake `transcribe_wav`, and a fake sketch processor each assert that `asyncio.get_running_loop()` raises `RuntimeError`, proving they are off the loop.

2. **Locks held across model calls.** `process_speech`, `summary.finish`, and `sketch.process_sketch` hold the session lock during model calls, so a slow model call blocks background tasks and every reader. Change all three to: take a deep-copied snapshot under the lock; call the model with no lock held; re-acquire the lock, re-read the record, apply the changes, and save. If the session was deleted meanwhile, raise `KeyError` and write nothing. Add a test that another thread can acquire the session lock while a fake model call is in progress.

3. **Summary can erase decisions.** In `summary.finish`, if the model returns an empty `decisions`, `todos`, or `open_questions` while the state's list is not empty, keep the state's list. Add a test.

4. **Sketch prompt not used.** `process_sketch` imports `SKETCH_SYSTEM_PROMPT` and never sends it, so "record only what is visible" does nothing. Send it as a system message. Add a test inspecting the request.

5. **Web text fallback.** `_message_text_and_sources` falls back to `output_text` when the last message is empty, which returns the interim "正在查……" line as the answer. When an `output` list is present and the last message has no text, treat the search as failed.

## High
6. **Data location.** Thinking sessions must not be written inside the repository, because this project may sit in a cloud-synced folder and a session could be committed by accident. Default data directory: `%LOCALAPPDATA%\Blackout` on Windows, otherwise `~/.blackout`. `BLACKOUT_DATA_DIR` still overrides it. `app/phone.py` will keep TLS files under the same directory. Keep `data/` in `.gitignore` for safety.

7. **Windows file locking.** `os.replace` raises `PermissionError` on Windows when a sync client or antivirus briefly holds the file. In `save_session`, retry up to 6 times with growing delays totalling about 1 second, and use a unique temp file name in the same directory. If it still fails, log the error, keep the record in the cache, and do not raise, so a turn is not lost; the next save writes it. Add a test using a monkeypatched `os.replace` that fails twice then succeeds, and one that always fails.

8. **Reads without a lock.** `GET /api/sessions/{id}` serializes the live cached object while another thread may mutate it. Return a deep copy made under the session lock. Since locks are no longer held during model calls, this does not block.

9. **Delete race.** `delete_session` must take the session lock, so a concurrent save cannot bring a deleted session back. `_finish_task` must not recreate a deleted session; keep that check.

10. **Finished session gets speech.** `process_speech` on a finished session must not change the record. Return `end: true` with an empty reply. The bridge will rely on this.

11. **Late task results.** A search can finish after the user has ended the session. `_finish_task` must, when the record is finished and has a result, update `result.tasks` and regenerate `result.markdown` without a model call. `summary.finish` on a finished session must also refresh tasks from the record, without a model call, when only tasks changed. Add tests.

12. **Upload limit bypass.** `Content-Length` can be absent with chunked encoding. Read uploads with `await file.read(limit + 1)` and reject if over the limit, for audio and images.

13. **Empty session summary.** `summary.finish` with no history and no sketches must make no model call and return the base result with `degraded: false`.

## Medium
14. Source titles: annotation sources lose their title because `add_source(url, url)` is used. Use the annotation's `title`. Prefer `results` titles if the annotation has none.
15. Spoken conclusion: strip Markdown characters (`*`, `#`, backticks) and any URL from `conclusion`, and cap it with the same rule as `truncate_reply`. The stored `detail` keeps its formatting.
16. Search input: send only the instruction and the goal, not the whole state. Less private text goes through a search-enabled call, and it cuts tokens.
17. `/api/status`: add `"ledger_ok": bool` and `"can_spend": bool`. A corrupt ledger must not report 0 spent as if everything were fine.
18. Code quality: remove `isinstance(task_obj, Mapping := dict)` and use a plain `isinstance(task_obj, dict)`. Move `import json` to the top of `summary.py`. `process_speech` and `finish` are over 50 lines: split them into small named functions. Remove the unused imports. Remove the aliases `initial_state`, `new_initial_state`, `apply_turn`, and `clear_all`, and the `Mapping` usage if unused, updating the tests that used them.

## Prompts
19. `TURN_SYSTEM_PROMPT` is too terse for its job. Rewrite it in Chinese with concrete guidance:
- State plainly that `current_user_text` is what the person just said, and that they are thinking out loud while not looking at a screen.
- Silence is the product's main behaviour. Someone developing a thought, listing points, or stating a decision gets `listen`, even though they are not finished, and even when an addition should be recorded.
- Give a short worked example for each action: what was said, the action, and the reply. Include: a list of three points with only the first developed, which is `listen` first and `follow_up` when the person moves on; hot pot in the middle of a technical discussion, which is `pull_back`; "这个方案你觉得行吗", which is `answer`; "帮我查一下 X 的价格", which is `search` with a self-contained instruction; "帮我写一段介绍", which is `draft`; "今天差不多了", which is `summarize`.
- A parked idea is recorded as the person's own words, briefly. Do not repeat what they said back at them. Do not praise. Do not start a reply with "好的".
- Do not start a task already in `running_task_instructions`. Do not ask about something already answered in the history.

## Tests
The stage 1 list of required test cases was not fully covered. Compare `spec/stage_1_backend.md` against the tests and add every case that is missing, for all of `test_state.py`, `test_store.py`, `test_conductor.py`, `test_tasks.py`, `test_summary.py`, `test_sketch.py`, and `test_routes.py`.
