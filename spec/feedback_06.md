Code review of the regenerated infrastructure found defects the tests missed. Fix these and return only `budget.py`, `build_with_muse.py`, `test_budget.py`, and `test_build_with_muse.py`, each with full content. Keep everything else unchanged.

## budget.py

1. CRITICAL, corrupt ledger fails open. `spent_usd` skips lines it cannot parse, so damage to the ledger silently lowers the recorded total and weakens the cap. A non-blank line that is not a JSON object with a numeric `usd` must raise `ValueError`. In `send`, for both transcription and metered calls, catch that `ValueError` and return `refusal_response` with a message saying the spend ledger is unreadable, without calling the API. Do not let it propagate out of `send`, because the SDK would retry it as a connection error.

2. HIGH, unpriced tools get through. Only tool types containing `search` are refused, so a built-in tool such as `image_generation` or `code_interpreter` adds charges the guard cannot see. Keep the existing message for search tools. Refuse any other tool whose `type` is not exactly `function` with `f"built-in tool {type!r} has no price in budget.py"`. A tool entry that is not an object is refused the same way.

3. HIGH, multipart requests raise. `_send_metered` reads `request.content`, which raises `httpx.RequestNotRead` for multipart bodies. The SDK then reports a connection error instead of a clear refusal. Call `request.read()` to get the bytes, so these requests get the normal 402 refusal.

## build_with_muse.py

4. CRITICAL, crash on the next run. `_collect_project` includes compiled files under `__pycache__`, and reading them raises `UnicodeDecodeError`, which is not caught. Skip any path with a `__pycache__` part, and skip any other file that cannot be decoded as UTF-8 with a logged warning.

5. HIGH, Windows paths. `_collect_project` labels files using `str(relative_path)`, which contains backslashes on Windows. The model can copy these into its output, where `is_allowed_path` rejects them. Use `.as_posix()`.

## Tests to add

`test_budget.py`:
- a corrupt ledger line makes `spent_usd` raise `ValueError`
- with a corrupt ledger, a metered call and a transcription both return 402 without reaching the API
- blank lines in the ledger are still fine
- `image_generation`, `code_interpreter`, and a non-object tool entry are refused without reaching the API
- a `function` tool is allowed
- a multipart POST to a path other than transcription returns 402 and does not reach the API

`test_build_with_muse.py`:
- using a temporary root that contains `app/__pycache__/x.pyc` with invalid UTF-8 bytes and `app/sub/y.py`, `build_input` does not raise, leaves out the compiled file, and labels the other file `app/sub/y.py` with forward slashes. Make the root injectable so this test does not depend on the real repository.
