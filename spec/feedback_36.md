Tests changed behaviour on purpose in stage 8, and a few tests or helpers need to follow. Return the full content of exactly these files: `app/messages.py`, `tests/test_keys.py`, `tests/test_realtime.py`, `tests/test_summary.py`, `tests/test_tasks.py`. Change only what is listed. Every other line of each file stays the same.

1. `app/messages.py`: `message()` raises `KeyError` when a template has a placeholder the caller did not pass, because the new `reflect_*` messages use `{decision}` and `{open}`, and a test passes only `point` and `conclusion`. Use `template.format_map(_Keep(values))`, where `_Keep` is a small `dict` subclass whose `__missing__` returns the placeholder unchanged as `"{name}"`. Add nothing else.

2. `tests/test_keys.py`, `test_secret_never_in_responses_or_logs`: it replaces `keys.check_key` with a lambda at the top, then later calls `keys.check_key(SECRET)` expecting the real function. Keep a reference to the real function before replacing it, as `real_check = keys.check_key`, and call `real_check(SECRET)` in the last part.

3. `tests/test_realtime.py`, `test_tts_timeout_allows_next`: the test never calls `asr([])`, so the bridge connects to the real Meta address with a fake key and depends on network timing. A test must not touch the real network. Add `asr([])` after `make_session()`, as the other tests do.

4. `tests/test_summary.py`, `test_verbatim_fields` and `test_finish_returns_summary_language_map_evidence_and_transcript`: a good final result now has `unexpanded_points == []`, by design, because points never returned to become open questions. Change those expectations to `[]`. Degraded results keep the stored list, and any test about a degraded result stays as it is.

5. `tests/test_tasks.py`, `test_search_last_message_sources`: at most 3 sources are now kept, with cited ones first. Change the expected count to 3 and check that the cited source comes first.
