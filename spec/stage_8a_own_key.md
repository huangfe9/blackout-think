Implement stage 8, part A: everyone brings their own Meta key, and the key cannot leak.

This project is going public. People download it and run it on their own computer with their own Meta Model API key. A key is money, so a leak is the worst possible failure here. Today a person without a key lands on a black screen and hears nothing useful. Fix both.

Return the full content of exactly these files: `muse_client.py`, `budget.py`, `start.py` (new), `.env.example`, `.gitignore`, `app/keys.py` (new), `app/routes.py`, `app/main.py`, `app/security.py`, `app/static/index.html`, `app/static/setup.html` (new), `app/static/js/setup.js` (new), `app/static/js/start.js`, `app/static/js/i18n.js`, `app/static/app.css`, `tests/conftest.py`, `tests/test_keys.py` (new). Keep every existing behaviour you are not asked to change. Keep all existing i18n keys and CSS rules. No comments that restate code. No print or console.log of anything secret, ever.

## The rule that overrides everything
The key may exist in only three places: the saved key file, the process memory of the server, and the HTTPS request to `api.meta.ai`. It is never returned by any route, in whole or in part, not even masked. It is never logged, never put in an exception message, never put in a URL, never passed on a command line, never stored in the browser, and never written inside the repository folder.

## `muse_client.py`
- `saved_key_path() -> Path`: `BLACKOUT_KEY_FILE` if set. Otherwise `%LOCALAPPDATA%\Blackout\api_key` on Windows, falling back to `Path.home() / "Blackout" / "api_key"`, and `~/.blackout/api_key` elsewhere. It does not depend on `BLACKOUT_DATA_DIR`.
- `is_plausible_key(value) -> bool`: a string of 16 to 512 characters, every character between 0x21 and 0x7E, and not a placeholder. Placeholders are `your-api-key-here` and `your-key-here`.
- `save_key(value) -> None`: raises `ValueError` with a fixed message if not plausible. Creates the parent folder. On POSIX the folder gets mode 0o700. Writes a temporary file in the same folder with `os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)`, writes the key and a newline, flushes, fsyncs, then `os.replace`. On any failure it removes the temporary file and raises with a fixed message that does not contain the key.
- `read_saved_key() -> str | None`: the stripped file content if plausible, otherwise None. Any read error gives None.
- `delete_saved_key() -> bool`: removes the file and returns whether it existed.
- `load_api_key()`: environment variable, then `.env`, then the saved file. The error message says to run `python start.py` and paste a key into the page, and never contains a value.
- `key_source() -> str`: `environment`, `env_file`, `saved`, or `none`, using the same order and the same placeholder rules as `load_api_key`.

## `budget.py`
Change only how `STOP_AT_USD` is set:
- `DEFAULT_STOP_AT_USD = 10.0` and `MAX_STOP_AT_USD = 140.0`.
- `_resolve_stop_at() -> float`: read `BLACKOUT_STOP_AT_USD` from the environment, then from a line of that name in the `.env` file beside `budget.py`, parsed with plain string handling. Do not import `muse_client`, since it imports this module. A missing or invalid value, or one at or below zero, gives the default. A value above the maximum gives the maximum.
- `STOP_AT_USD: float = _resolve_stop_at()`.

## `app/keys.py` (new)
- `META_MODELS_URL = "https://api.meta.ai/v1/models"`, hard-coded. There is no setting that changes where a key is sent.
- `REQUIRED_MODELS = ("muse-spark-1.3", "muse-image-1.0", "muse-voice-transcribe-1.0")`.
- `check_key(key) -> str` returns `ok`, `invalid_key`, `missing_models`, or `network`. It calls `httpx.get(META_MODELS_URL, headers=..., timeout=15, follow_redirects=False)`. 200 with every required id in `data` is `ok`. 200 without them is `missing_models`. 401 and 403 are `invalid_key`. Everything else, including a redirect, a bad body, and any exception, is `network`. Log only the status code or the exception's class name, never the exception text, the headers, or the body.
- `cached_status() -> str` returns `no_key` when `load_api_key` raises, otherwise the result of `check_key`, cached in memory for 60 seconds when `ok` and 10 seconds otherwise. The cache is keyed by the SHA-256 hex digest of the key, and stores no key.
- `clear_cache() -> None`.

## `app/routes.py`
- `_key_status()` is a one-line wrapper around `keys.cached_status()`, so tests can replace it.
- `GET /api/setup` returns `{"has_key": bool, "source": str, "can_change": bool}`. `can_change` is true only for a loopback client when the source is `saved` or `none`. A non-loopback client gets only `has_key` and `can_change`. Header `Cache-Control: no-store`.
- `POST /api/setup/key` takes JSON `{"key": "..."}`, checks in this order, and returns the error envelope with these codes:
  1. Client not loopback: 403 `not_local`.
  2. `Origin` header missing, or `origin_allowed` false: 403 `forbidden_origin`. Unlike other routes, a missing Origin is refused here.
  3. `Content-Type` is not `application/json`: 415 `invalid_input`. A web page cannot send this content type across origins without a preflight, and no preflight is ever approved.
  4. `key_source()` is `environment` or `env_file`: 409 `key_from_env`.
  5. The stripped value is not plausible: 400 `invalid_key_format`.
  6. `keys.check_key` in a thread: `invalid_key` gives 400 `invalid_key`, `missing_models` gives 400 `key_missing_models`, `network` gives 502 `network`. Nothing is saved in these cases.
  7. `ok`: `save_key`, `keys.clear_cache()`, and `{"ok": true}`. A failed save gives 500 `key_save_failed`.
  Every response has `Cache-Control: no-store`. No message echoes the input.
- `DELETE /api/setup/key`: the same first two checks, then `delete_saved_key`, `keys.clear_cache()`, and `{"ok": true}`.
- `POST /api/sessions`: after validating the goal, read `_key_status()` in a thread. `no_key` gives 409 `no_key`, `invalid_key` gives 401 `key_rejected`, `missing_models` gives 403 `key_missing_models`, `network` gives 503 `network`. Only `ok` creates a session.

## `app/security.py`
- `CSP` currently allows `connect-src 'self' ws: wss:`, which would let a script reach any socket. Add `csp_for(host) -> str`: the same policy with `connect-src 'self' ws://HOST wss://HOST` for a validated host, where HOST must match `^[A-Za-z0-9.:\[\]-]+$`, and `connect-src 'self'` otherwise. Responses use it. Rejections made before the host is known keep `connect-src 'self'`. Keep `SECURITY_HEADERS` as the other headers.
- `_body_limit`: 8192 bytes for `/api/setup/key`.

## `app/main.py`
`GET /setup` serves `app/static/setup.html`. Tell uvicorn nothing new here.

## `start.py` (new, repo root)
`python start.py [--port N] [--no-browser]`.
- Before any third-party import, require Python 3.10 or newer, otherwise print the version needed and exit 1.
- Check with `importlib.util.find_spec` that fastapi, uvicorn, openai, websockets, and httpx exist. If not, print `pip install -r requirements.txt` and exit 1.
- Bind only to 127.0.0.1. Port: the requested one if free, else the first free port from 8000 to 8010, else any free port chosen by the OS.
- Run `uvicorn.run("app.main:app", host="127.0.0.1", port=port, access_log=False, log_level="warning")`.
- A daemon thread polls `/api/status` for up to 15 seconds with `urllib`, then opens the browser with `webbrowser.open` unless `--no-browser`.
- It prints one ASCII line: `Blackout is running at http://127.0.0.1:PORT - press Ctrl+C to stop.` It takes no key argument and prints no key.

## `.env.example` and `.gitignore`
`.env.example`:
```
# Optional. The easy way: run `python start.py` and paste your key into the page.
# Get a key at https://dev.meta.ai/api-keys/ . Never commit a real key.
MODEL_API_KEY=your-api-key-here
# Stop all paid calls at this total, in US dollars. Default 10, at most 140.
# BLACKOUT_STOP_AT_USD=10
```
`.gitignore`: keep what is there, and add `.env.*`, `!.env.example`, `api_key`, `*.pem`, `*.key`, `tls/`, `*.log`.

## `app/static/setup.html` and `app/static/js/setup.js` (new)
A page with one job. It loads only `/static/app.css`, `/static/js/i18n.js`, and `/static/js/setup.js`. It has the same dark look as the start page, one narrow column, and the same language toggle. No `<form>`, so nothing can navigate with the value.

Text, in `i18n.js`, in both languages:
- Heading: "先填你自己的 Meta key" / "Add your own Meta key"
- Line: "Blackout 在你自己的电脑上运行，用你的 key 调用 Meta 的模型。" / "Blackout runs on your computer and calls Meta's models with your key."
- Input placeholder: "粘贴 key" / "Paste your key". The input has `type="password"`, `autocomplete="off"`, `autocapitalize="off"`, `autocorrect="off"`, `spellcheck="false"`.
- Button: "保存并检查" / "Save and check"
- Link: "去 Meta 申请 key" / "Get a key from Meta", to `https://dev.meta.ai/api-keys/` with `target="_blank"` and `rel="noopener noreferrer"`.
- Three short facts:
  - "只存在这台电脑上，不会进入代码仓库。" / "It stays on this computer and never enters the code repository."
  - "只发给 api.meta.ai，页面和日志都不会再显示它。" / "It only goes to api.meta.ai. No page or log will show it again."
  - "费用从你自己的 Meta 账户扣，一次短谈大约 $0.20。" / "Costs come from your own Meta account, about $0.20 for a short talk."

States, from `GET /api/setup`:
- No key and `can_change`: the input and button.
- `source` is `saved` and `can_change`: "这台电脑上已经保存了一个 key。" / "A key is saved on this computer." with the buttons "换一个" / "Replace it", which shows the input, "删除" / "Delete it", and "返回" / "Back", which goes to `/`.
- `source` is `environment` or `env_file`: "正在使用 .env 或环境变量里的 key，要改请直接改那里。" / "Using the key from .env or the environment. Change it there." and Back.
- `can_change` false: "请在运行 Blackout 的那台电脑上设置 key。" / "Set the key on the computer that runs Blackout."

`setup.js`: read the value into a local variable, clear `input.value` immediately in the same tick before the request, send `POST /api/setup/key` with `Content-Type: application/json`, and show a message for each code through `error_<code>` keys in `i18n.js`. Never put the value in storage, the URL, the DOM, or a log. On success `location.replace("/")`. While the request runs, disable the button and show "正在检查…" / "Checking…".

Error text, in both languages:
- `error_invalid_key_format`: "这看起来不像 key，请重新复制。" / "That doesn't look like a key. Please copy it again."
- `error_invalid_key`: "Meta 没有接受这个 key。" / "Meta didn't accept this key."
- `error_key_missing_models`: "这个 key 不能使用 Blackout 需要的模型。" / "This key can't use the models Blackout needs."
- `error_network`: "连不上 Meta，请检查网络后再试。" / "Couldn't reach Meta. Check your connection and try again."
- `error_not_local`: "请在运行 Blackout 的那台电脑上设置 key。" / "Set the key on the computer that runs Blackout."
- `error_key_from_env`: "正在使用 .env 或环境变量里的 key，要改请直接改那里。" / "Using the key from .env or the environment. Change it there."
- `error_key_save_failed`: "key 没能保存，请再试一次。" / "The key couldn't be saved. Please try again."
- `error_key_rejected`: "Meta 不接受现在的 key，请点右上角换一个。" / "Meta rejected the current key. Use the link at the top to change it."

## `app/static/index.html` and `app/static/js/start.js`
- Add a quiet link beside the language toggle: `<a id="keyLink" class="lang-toggle key-link" href="/setup" data-i18n="keyLink">`, text "API key". It goes in a small top-right group with the toggle, styled the same, so they do not overlap.
- In `init`: fetch `/api/setup`. If `has_key` is false, `location.replace("/setup")`. A failed fetch does nothing.
- In `startNew`: a 409 `no_key` goes to `/setup`. The other codes already show through `errorMessage`.

## `tests/conftest.py`
Add to the autouse fixture: `BLACKOUT_KEY_FILE` set to a file in `tmp_path`, `MODEL_API_KEY` removed from the environment, `app.routes._key_status` replaced with a function returning `ok`, and `keys.clear_cache()` before and after. Tests that call the real `_key_status` restore it themselves.

## `tests/test_keys.py` (new)
Use the secret `FAKEKEY-do-not-leak-1234567890`. Use `TestClient(app, client=("127.0.0.1", 50000))` for a loopback client, and an `Origin` header of `http://testserver`. Cover:
- Save, read, delete. No temporary file is left. Mode 0o600 on POSIX, skipped on Windows.
- `is_plausible_key` refuses spaces, newlines, control characters, short values, and both placeholders.
- `load_api_key` order: environment, then `.env`, then saved. `key_source` matches.
- `POST /api/setup/key`: non-loopback 403, missing Origin 403, foreign Origin 403, wrong content type 415, from-env 409, bad format 400. With `keys.check_key` replaced: `invalid_key`, `missing_models`, and `network` save nothing, and `ok` saves it.
- The secret, and its last 8 characters, never appear in the body or headers of any response from `/api/setup`, `/api/setup/key`, `/api/status`, or `/api/sessions`, including error responses.
- With `caplog` at DEBUG, the secret never appears in logs, including when `httpx.get` raises an exception whose text contains the secret.
- `check_key` maps 200, 200 with a missing model, 401, 403, 302, 500, a bad body, and an exception correctly, and passes `follow_redirects=False`.
- `cached_status`: `no_key` without a key. The second call within 60 seconds does not call `check_key` again. The cache contents do not contain the key.
- `POST /api/sessions` with `_key_status` returning each value gives the right status and code, and only `ok` creates a session.
- `csp_for`: contains the host, has no bare `ws:` or `wss:`, and falls back for a strange host.
- `_resolve_stop_at`: default 10, an environment value, above the maximum gives 140, and invalid gives 10. Pass the `.env` path as a parameter so the test never reads the real file.
- `.env.example` holds a placeholder, and `.gitignore` covers `.env` and `api_key`.
