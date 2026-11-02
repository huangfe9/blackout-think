The redirect check added to `app/asr.py` breaks speech everywhere. Fix it. Return the full content of exactly these files: `app/asr.py`, `tests/test_hardening.py`. Change only what is listed.

`_matches_expected_endpoint` compares `ws.remote_address[0]`, an IP address, with the URL's host name. For the real address `wss://api.meta.ai/v1/asr/realtime` the remote address is an IP, never the name `api.meta.ai`, so every real connection is refused and hands-free speech never starts. 33 tests in `tests/test_realtime.py` fail for the same reason.

The installed `websockets` is 16.0. Its `connect` has no `max_redirects` parameter, and after connecting, `ws.request` is the final handshake request, after any redirect, with its headers. Do this instead:
- Expected value: the URL's netloc without any user info, lowercased: for example `api.meta.ai` for `wss://api.meta.ai/v1/asr/realtime`, and `127.0.0.1:61727` for `ws://127.0.0.1:61727/x`.
- Actual value: `ws.request.headers.get("Host", "")`, lowercased.
- If they differ, a redirect moved the connection to another place: close the socket and return False before sending anything. If `ws.request` or its headers are missing, refuse the same way, failing closed.
- Remove `_connect_kwargs`, the `inspect` import, and the remote-address comparison.

`tests/test_hardening.py`: keep the two-server redirect test, which must still pass. Add unit tests of the check with fake connection objects: `Host: api.meta.ai` with the real URL is accepted whatever the remote address is; `Host: evil.example` is refused; a missing request is refused; and `127.0.0.1:61727` matches `ws://127.0.0.1:61727/x`.
