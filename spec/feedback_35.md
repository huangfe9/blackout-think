Review of stage 8a found a real leak path and some wrong tests. Fix them. Return the full content of exactly these files: `muse_client.py`, `app/keys.py`, `app/main.py`, `app/routes.py`, `start.py`, `tests/conftest.py`, `tests/test_keys.py`, `tests/test_static.py`. Change nothing else.

## 1. Tests must never see a real key
On a computer with a real `.env`, the tests read it through `load_api_key`, several failed because of it, and pytest printed the start of the real key in an assertion message. This must be impossible.

`tests/conftest.py`, in the autouse fixture: `monkeypatch.setattr(muse_client, "ENV_FILE", tmp_path / "no.env")`, beside what is already there. `_file_key` already looks up `ENV_FILE` when called, so this covers it. Add a test that `load_api_key` raises inside the fixture even when a real `.env` exists next to `muse_client.py`, by checking `muse_client.ENV_FILE` is under `tmp_path`.

Assertions in `tests/test_keys.py` compare keys with `==` only against the fake secret, and every other check of a key uses `assert (value == expected) is True` style or checks a boolean, so that a failure never prints a key.

## 2. Secrets cannot reach a log, even by accident
Add to `app/keys.py`:
- `remember_secret(value) -> None` keeps a value in a module-level set, ignoring values shorter than 16 characters.
- `redact(text) -> str` replaces every remembered secret in `text` with `[key]`.
- `install_log_redaction() -> None`, safe to call more than once, wraps `logging.setLogRecordFactory`. The wrapped factory calls the previous one, then:
  - if a remembered secret is in `record.getMessage()`, it sets `record.msg` to the redacted message and `record.args` to `()`;
  - if `record.exc_info` is a real exception tuple, it formats it with `traceback.format_exception`, redacts it, and sets `record.exc_text` to the result with the trailing newline removed, so a formatter uses that text instead of formatting the exception again. Do this only when a secret appears in the formatted text, otherwise leave the record alone.
  - any error inside the factory is swallowed and the record is returned, because logging must not break the app.
- At install time, and in `refresh_secrets()`, remember what `load_api_key()` returns, if anything.

`app/main.py` calls `keys.install_log_redaction()` at import.

`app/routes.py`, in `POST /api/setup/key`: call `keys.remember_secret(value)` right after the plausibility check and before `check_key`, so a rejected key is also protected.

Tests: with a real `logging.Handler` and `logging.Formatter`, after `install_log_redaction` and `remember_secret`, these all come out without the secret: `logger.warning("x %s", secret)`, `logger.warning(secret)`, and `logger.exception` inside `except` for an exception whose text contains the secret. Restore the previous factory at the end of the test.

## 3. Keep the help in the error
`load_api_key`'s message lost the address. It must be: `MODEL_API_KEY is not set. Create a key at https://dev.meta.ai/api-keys/ , then run python start.py and paste it into the page, or put it in {ENV_FILE} as MODEL_API_KEY=...`, keeping the existing first words and the file path, so `test_muse_client.py` passes as it is.

## 4. Wrong tests
- `test_csp_for` asserts `" ws:" not in csp`, which is false for the correct value `ws://127.0.0.1:8000`. Assert that `"ws: "` and `"wss: "` are not in it, and that `"ws://127.0.0.1:8000"` is.
- `tests/test_static.py::test_no_external_urls_anywhere` must allow exactly `https://dev.meta.ai/api-keys/`, the link where a person gets their own key, in `setup.html` and nowhere else. Every other external address still fails it.

## 5. `start.py`
`_open_browser` uses `urllib.request.urlopen`, which goes through a system proxy on some computers and then never sees the local server. Use `urllib.request.build_opener(urllib.request.ProxyHandler({}))`.

## Must still be true
Everything in `spec/stage_8a_own_key.md`.
