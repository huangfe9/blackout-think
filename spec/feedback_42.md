A security review of key handling found no critical or high issues, and these medium and low ones. Fix them. Return the full content of exactly these files: `app/asr.py`, `build_with_muse.py`, `start.py`, `app/phone.py`, `app/routes.py`, `app/security.py`, `app/keys.py`, `app/main.py`, `muse_client.py`, `.gitignore`, `conftest.py` (new, repo root), `tests/test_hardening.py` (new). Change only what is listed. Keep every existing behaviour and test passing.

## M1. The speech socket follows redirects before sending the key (`app/asr.py`)
`websockets.connect` follows 3xx redirects across hosts, then `connect` sends the handshake containing the key to wherever it ended up. Pass `max_redirects=0` if the installed `websockets` accepts it; otherwise, after connecting, compare the connected host and port with those of `self.url` and close and return False before sending anything. Test with a fake server that answers 302 to a second fake server: the second server never receives a frame.

## M2. The generator can send `.env` as context (`build_with_muse.py`)
`_collect_selected` accepts any path. Refuse context paths that are absolute, contain `..`, or whose name is `.env`, starts with `.env.`, is `api_key`, or ends in `.pem` or `.key`. Before writing a run file, refuse if the current key from `load_api_key()`, when one exists, appears in the raw output, and say so without printing it.

## M4. Loopback trust and proxies (`start.py`, `app/phone.py`, `app/routes.py`)
- Pass `proxy_headers=False` to `uvicorn.run` in `start.py` and in `app/phone.py`, so a forwarded-for header is never trusted.
- `_setup_local_and_origin` also refuses with 403 `not_local` when any of `x-forwarded-for`, `forwarded`, `x-real-ip`, or `via` is present, or when the Host's name is not `127.0.0.1`, `localhost`, or `::1`.

## L1. Redaction learns late (`app/keys.py`, `app/main.py`)
- `cached_status()` calls `remember_secret` on the key it loaded, so a key changed in `.env` after startup is protected from its first check.
- `remember_secret` also remembers the JSON-escaped and `repr` forms of the value.
- `app/main.py` sets `logging.getLogger("websockets")` to at least INFO, because its DEBUG frame log prints the start of the handshake.

## L2. Keys from the environment and `.env` skip the format check (`muse_client.py`, `app/routes.py`)
`_env_key` and `_file_key` also require `is_plausible_key`, so a value with control or non-ASCII characters is treated as absent. In `app/routes.py`, the error path that returns an exception's text to the browser, around the transcription and turn handlers, returns a fixed message instead.

## L4. Cross-site requests (`app/security.py`)
For non-GET HTTP requests to `/api/`, also refuse with 403 `forbidden_origin` when `Sec-Fetch-Site` is `cross-site` or `same-site`. A missing header still passes, since it is a defence in depth on top of the Origin check.

## L5. Root tests and the real key (`conftest.py`, new, at the repo root)
`pytest_configure` runs before any test module is imported. It removes `MODEL_API_KEY` from the environment, sets `BLACKOUT_KEY_FILE` to a file in a new temporary directory, and sets `muse_client.ENV_FILE` to a missing file in that directory. Then no test, in the root or in `tests/`, can load a real key from this computer. `tests/conftest.py` stays as it is.

## L6. `.gitignore`
Keep what is there, and add: `*.env`, `.envrc`, `.api_key.*`, `*api_key*`, `*secret*`, `credentials*.json`, `.venv/`, `venv/`. `.env.example` must stay tracked.

## L7. The key file's location (`muse_client.py`)
- `saved_key_path` refuses a `BLACKOUT_KEY_FILE` inside the repository folder, falling back to the default location with a warning that names no value.
- `save_key` changes the folder's mode only for a folder it created.
- `delete_saved_key` also removes leftover `.api_key.*.tmp` files beside the key.

## `tests/test_hardening.py` (new)
One test per item above that has behaviour: the redirect, the generator's refused paths and output check, the forwarded headers and Host rule on `/api/setup/key`, the late redaction, the escaped forms, the env-key format check, the `Sec-Fetch-Site` refusal, the root conftest's isolation, the ignore rules (with `git check-ignore` when git is available, skipped otherwise), and the key-file location rules.
