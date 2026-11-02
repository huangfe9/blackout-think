Finish bringing the tests up to date. Do not change anything in `app/` or `budget.py`; if a test exposes a real defect, leave the test failing and describe the defect in a comment at its top.

Return exactly these files, each with full content: `test_budget.py`, `tests/test_conductor.py`, `tests/test_tasks.py`, `tests/test_summary.py`, `tests/test_phone.py`, `tests/test_store.py`.

## `test_budget.py`
- `spent_usd` raises `ValueError` on negative, NaN, and infinite values; `can_spend` is then false.
- `record_spend` refuses negative or non-finite amounts.
- `record_spend` retries: an `open` that fails twice with `PermissionError` then succeeds records once and sets no latch.
- `record_spend` failing every time sets the latch: `can_spend` is false and `BudgetedHttpClient` refuses the next paid call with a 402 without reaching the API. `reset_record_failure()` clears it.
- A transport error from the API after sending records the worst case and re-raises. A 500 response records nothing.
- Ledger location: `BLACKOUT_DATA_DIR` does not change it; `BLACKOUT_LEDGER_FILE` does. Migration copies the old repository ledger once only when the default ledger does not exist, and never overwrites an existing one. Test these by calling the path and migration functions with temporary paths, without touching the real files.

## `tests/test_conductor.py`
- Each end case from the spec at the conductor level: 好，结束。 makes no model call; 首先我觉得有个问题，好，结束 records the content in history, applies its additions, returns `end: true`, and has no spoken reply; 我已经说结束了你怎么还在 with a model `summarize` ends straight away; 今天差不多了 with a model `summarize` still asks for confirmation.
- Task ceiling: a session stops starting tasks at the limit, using `BLACKOUT_MAX_TASKS_PER_SESSION`; the refusal reply is said and the instruction lands in open questions; `task_started` is false then.
- A duplicate instruction, differing only by punctuation and spaces, does not start a second task.
- `conductor.py` never sets `live.mic` to `ai_speaking`.
- Additions with `under` place points and items correctly in the state.

## `tests/test_tasks.py`
- The task records `under`, and `build_map` shows it under that point.
- A late result refreshes `result.map` as well as `result.tasks` and `result.markdown`.

## `tests/test_summary.py`
- Markdown includes a 思路 section with the tree as a nested list.
- `result.map` is present and comes from the state rather than the model's wording.

## `tests/test_phone.py`
- `uvicorn.run` is called with `access_log=False`.
- The certificate has `ca=False`.
- Running `main` prints the token only as part of the start-up URL, and the environment is restored afterward.

## `tests/test_store.py`
- `is_valid_id` rejects an id with a trailing newline.
- `get_session_copy` with a garbage id does not grow the lock table.
- On platforms with POSIX permissions, session files are `0o600`. Skip on Windows.
