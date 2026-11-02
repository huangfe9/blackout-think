The application changed in stages 5 and after, and the tests have not caught up: many now fail. Bring the tests up to date without weakening them. Do not change anything in `app/` or `budget.py`; if a test exposes a real defect, leave the test failing and describe the defect in a comment at its top.

Return exactly these files, each with full content: `tests/conftest.py`, `tests/test_state.py`, `tests/test_static.py`, `tests/test_security.py`, `tests/test_routes.py`.

## `tests/conftest.py`
- `testserver` is no longer in the production allow-list. The autouse fixture sets `BLACKOUT_ALLOWED_HOSTS=testserver` (and a test that needs another value sets its own).
- Points `budget.LEDGER_FILE` at a temporary file and calls `budget.reset_record_failure()`. No test may touch the real ledger.
- Keeps deleting `BLACKOUT_ACCESS_TOKEN`, setting `BLACKOUT_DATA_DIR`, and clearing in-memory state as it does now.

## `tests/test_state.py`
- Points now carry `under`. Update the expectations in `test_additions_append_without_losing` and `test_invalid_additions_ignored`.
- `split_end`: 好，结束。 and 好了结束 end with no content. 首先我觉得有个问题，好，结束 ends with the content 首先我觉得有个问题. 我想讨论怎么结束这个项目 does not end. 结束这个项目 does not end. 那就到这里吧 is not an end phrase.
- `apply_additions`: new object form and old plain strings both work, and `links` records `under`.
- `build_map`: nesting of points; decisions, todos, questions, and contradictions under their point; an unknown `under` goes to the root; a cycle neither hangs nor loses a node; ids are stable across calls; a session saved in the old format with plain strings and no `under` still builds; tasks appear with their status; parking lot items are not in the tree.

## `tests/test_static.py`
- `test_no_external_urls_anywhere`: `http://www.w3.org/2000/svg` is the SVG namespace, not an external resource. Allow only that exact URL.
- `test_observer_uses_textcontent_and_new_mic_values`: the mic labels now come from the values `listening`, `paused`, `user_speaking`, `ai_speaking`, `offline`, shown as 在听, 暂停, 你在说, AI 在说, 未连接. Keep checking those five.
- `test_referenced_static_files_exist_and_mime`: cover `map.css`, `map.js`, `observer.css`, `observer.js`.
- New: `observer.js` contains neither `/api/status` nor `spent`, and neither `observer.html` nor `observer.js` mentions a dollar sign or 花费.
- New: no JS or HTML file creates a `style` element or uses `setAttribute("style"`, which the policy would block.

## `tests/test_security.py`
- `testserver` passes only through `BLACKOUT_ALLOWED_HOSTS`: with that variable empty, `testserver` is refused with 400, while `localhost` and `127.0.0.1` pass.
- Headers on `/` include `X-Frame-Options: DENY`, and the policy includes `frame-ancestors 'none'`, `base-uri 'none'`, and `form-action 'self'`, on normal, rejection, and redirect responses.
- A POST to `/api/sessions` with `Transfer-Encoding: chunked` and no `Content-Length` returns 411 in the error envelope. A POST to `.../finish` with no body passes this check.
- Keep the rest passing.

## `tests/test_routes.py`
- `/announcements` is now `POST`; `GET` must not drain anything.
- `GET /api/sessions/{id}` includes `map`, and its root text is the goal.
- `/finish` includes `map`.
- An invalid id, including one with a trailing newline encoded as `%0a`, returns 404 and does not add to the lock table.
- Keep the rest passing.
