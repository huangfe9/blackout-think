Seven tests fail because of how they are written. Do not change anything under `app/`, and do not weaken what the tests check. Return the full content of exactly these files: `tests/test_owner.py`, `tests/test_routes.py`, `tests/test_security.py`, `tests/test_static.py`, `tests/test_store.py`, `tests/test_summary.py`.

1. `tests/test_owner.py` (`test_malformed_owner_cookie_is_replaced`, `test_empty_owner_cookie_is_replaced`) and `tests/test_security.py` (`test_owner_cookie_set_hashed_and_replaced`): reading `client.cookies["blackout_owner"]` raises `httpx.CookieConflict`, because the client now holds both the malformed cookie and the replacement. Check the replacement through the response's `set-cookie` header instead. Send the malformed cookie as a raw `Cookie` request header on a fresh client, rather than storing it in the client's jar.

2. `tests/test_routes.py`, `test_blocking_work_off_event_loop`: the route now calls `transcribe_wav(data, languages)`, and the fake takes one argument, so it raises and the route returns 502. Make the fake accept the extra argument. Keep the assertion that it runs off the event loop.

3. `tests/test_static.py`, `test_observer_uses_textcontent_and_new_mic_values`: the labels moved to `i18n.js`. Check that `observer.js` maps the five mic values `listening`, `paused`, `user_speaking`, `ai_speaking`, and `offline`, and that `i18n.js` has both languages' labels for them.

4. `tests/test_store.py`, `test_delete_and_list_order`: `list_sessions` now needs an owner. Create the sessions with an owner and list with it. Add a case that a different owner sees none.

5. `tests/test_summary.py`, `test_finish_markdown_begins_with_title_and_summary_and_has_map_section`: the fake model reply sets `language` to `en`, so headings are English. Set it to `zh` for that test and expect 思路. Add a matching case for `en` expecting `Outline`.
