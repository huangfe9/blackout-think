The last test updates for the stricter key rules. Return the full content of exactly these files: `muse_client.py`, `tests/test_keys.py`, `test_muse_client.py`. Change only what is listed.

1. `muse_client.py`: add `DEFAULT_ENV_FILE: Path = Path(__file__).parent / ".env"` and set `ENV_FILE: Path = DEFAULT_ENV_FILE`. Nothing else changes. The root `conftest.py` replaces `ENV_FILE` during tests, so a test that wants the documented default must read `DEFAULT_ENV_FILE`.

2. `test_muse_client.py`:
   - `test_base_url_correct` checks `ENV_FILE.name == ".env"`. Check `muse_client.DEFAULT_ENV_FILE.name == ".env"` and that its parent is the folder holding `muse_client.py`.
   - `test_file_key_used_when_env_has_placeholder` returns a file key that is now too short to count as a key. Use `"file-key-0123456789abcdef"` and update the matching assertion. Make sure any other key value in this file that is expected to load is at least 16 printable characters.

3. `tests/test_keys.py`: setup writes are now accepted only when the Host is `127.0.0.1`, `localhost`, or `::1`, but the test client's default Host is `testserver`.
   - `local_client()` returns `TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))`.
   - `ORIGIN` becomes `{"Origin": "http://127.0.0.1:8000"}`.
   - A test of a foreign Origin uses `http://evil.example` with that client and still expects 403 `forbidden_origin`.
   - Add one test showing that a loopback client sending `Host: testserver` with a matching Origin gets 403 `not_local`.
   Keep every other test and assertion.
