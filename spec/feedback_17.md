Apply these backend fixes from a security review. Return exactly these files, each with full content: `budget.py`, `app/phone.py`, `app/security.py`, `app/store.py`, `app/tasks.py`, `app/conductor.py`, `app/routes.py`, `app/prompts.py`. Do not return anything else. Keep every other behaviour the same.

1. **Phone token in logs.** `app/phone.py` runs uvicorn with the access log on, so the first request `GET /?token=...` prints the token. Pass `access_log=False`. The token must only appear in the one start-up URL and QR code.

2. **The spend cap can undercount, in `budget.py`:**
   - Reject negative or non-finite amounts in `spent_usd` and in `record_spend` by raising `ValueError`. NaN must not pass any check; `can_spend` returns false.
   - `record_spend` retries an append up to 5 times over about 1 second, because a sync client or antivirus can briefly lock the file. If it still fails, set a module-level latch that makes `can_spend` false and makes `BudgetedHttpClient` refuse further paid calls in this process, with a message saying spend could not be recorded. A paid call that cannot be recorded must not be followed by more. Provide `reset_record_failure()` for tests.
   - If `super().send` raises a transport error or timeout after the request was sent, record the worst case and re-raise, because the provider may have billed it. Non-2xx responses still record nothing.
   - Move the ledger out of the repository. Default `LEDGER_FILE` is `%LOCALAPPDATA%\Blackout\spend.jsonl` on Windows and `~/.blackout/spend.jsonl` elsewhere, honouring `BLACKOUT_DATA_DIR`. **The running total must not reset:** if the new file does not exist and the old `<repo>/.muse_spend.jsonl` does, copy it over once at import, and keep the old file in place. A failure during this copy must not crash the import; if the old file exists and the copy failed, keep using the old path. `budget.py` must not import from `app`.

3. **No ceiling on background work.** Any speech, including a TV in the room, can start a search on every turn. In `app/tasks.py` and `app/conductor.py`: a session may start at most `BLACKOUT_MAX_TASKS_PER_SESSION` tasks (default 12). A task whose instruction, after removing punctuation and spaces, equals one already started in this session does not start again. When refused by the cap, the reply is "这次后台的事够多了，我先记下这个问题。", and the instruction is added to open questions so it is not lost. Only a real start counts towards `task_started`.

4. **`testserver` in the production allow-list.** Remove it from `ALLOWED_DEFAULT_HOSTS` in `app/security.py`. The test configuration will set it.

5. **Clickjacking.** Add `frame-ancestors 'none'; base-uri 'none'; form-action 'self'` to the Content-Security-Policy, and an `X-Frame-Options: DENY` header, including on rejection and redirect responses.

6. **Ids and state-changing GET.** In `app/store.py`, use `fullmatch` for ids, because `$` also accepts a trailing newline. `get_session_copy` and every function taking a session id must validate before calling `get_lock`, so garbage ids do not grow the lock table. In `app/routes.py`, change `GET /api/sessions/{id}/announcements`, which drains state, to `POST`.

7. **Chunked bodies.** In `app/security.py`, respond 411 in the error envelope to a POST, PUT, or PATCH to `/api/*` that has `Transfer-Encoding` and no `Content-Length`. Browsers always send `Content-Length` for `fetch`. A POST with no body and no `Transfer-Encoding`, such as `/finish`, stays allowed.

8. **Files at rest.** Create the data directory with mode `0o700`, and session files with `0o600`, where the platform supports it, without failing where it does not. In `app/phone.py`, set `BasicConstraints(ca=False)`.

9. **Mic state.** `live.mic` must only become `ai_speaking` from the bridge during actual playback. `app/conductor.py` must not set it to `ai_speaking`, or a text turn leaves the label stuck.

10. **Search wording.** Spoken conclusions came out as "每小时收费零点一八美元". Tell the search prompt in `app/prompts.py` to use Arabic numerals and keep units, such as "每小时 0.18 美元".
