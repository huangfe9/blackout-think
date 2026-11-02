Review of the evaluation scripts found these. Return the full content of exactly these files: `tests/evals/run_evals.py`, `tests/evals/make_samples.py`, `build_with_muse.py`. Change only what is listed.

## `tests/evals/run_evals.py`
1. `from app import budget, conductor, store, summary` fails, because `budget` is a module at the repo root. Use `import budget` and `from app import conductor, store, summary`.
2. `run_talk` keeps the result returned by `summary.finish`, taken before the draft and picture finish. After all the waits, re-read it: `result = (store.get_session_copy(session_id) or {}).get("result") or result`, and use that for scoring and for the return value, so a finished draft and picture are included.
3. `_is_reflection` looks at the user's line, which is wrong. A reply is a reflection when the turn's `action` is `continue`, or the reply contains "So far", "Still open", "现在定了", or "还没定". Pass the AI's reply and action. A closing line, `action == "summarize"`, is never counted as an interruption.
4. A conflict question may be held back and asked up to two lines later, by design. A conflict counts as asked if a `follow_up` reply occurs on the expected line or on either of the next two lines. That `follow_up` is then not counted as a false interruption. Count each follow-up against only one expected conflict.
5. A task acknowledgement on a line with `expect` of `task` is not an interruption, which is already so. A pull-back on a line with `expect` of `pull_back` is not one either. A task started on a line with no `expect` does count.

## `tests/evals/make_samples.py`
It uses `outcome["result"]`, which after the change above holds the final result. Keep that. Also remove `frames` entries' `stats` keys other than `user_turns`, `ai_spoke`, `pull_backs`, and `conflicts_asked`, and write the JSON compactly with no indent, since it is served to browsers.

## `build_with_muse.py`
Add `"start.py"` to `INFRA_FILES`. Change nothing else.
