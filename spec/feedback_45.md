Keys from the environment must now look like real keys, at least 16 printable characters, and the speech socket's handshake request is checked. Some test data is too short or too thin for that. Update the tests only. Return the full content of exactly these files: `tests/test_realtime.py`, `tests/test_speaking.py`, `test_muse_client.py`. Change only what is listed.

1. `tests/test_realtime.py`, line 30: the fake key `"test-secret-key"` has 15 characters, so it now counts as no key and every bridge test falls back. Use `"test-secret-key-0123456789"` there, and anywhere else that file compares against that value, for example a test that checks the key never appears in logs.

2. `tests/test_speaking.py`, `test_asr_auth_failed_on_unauthorized`: the fake socket returned by `fake_connect` needs a `request` attribute whose `headers` is a dict with `"Host"` equal to the netloc of the URL it was connected to, so the new check passes and the test reaches the Unauthorized message as before. Build it from the `url` argument with `urllib.parse.urlparse(url).netloc`.

3. `test_muse_client.py`, line 49: `"env-key"` is too short to be accepted. Use `"env-key-0123456789abcdef"`, and update the assertion that compares the loaded key to match.
