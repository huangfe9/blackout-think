One test fix. Return the full content of exactly `tests/test_keys.py`. Change only this.

In `test_setup_key_guards`, the remote client is `TestClient(app, client=("203.0.113.9", 50000))`, whose Host is `testserver`, while it sends `Origin: http://127.0.0.1:8000`. The security middleware refuses that mismatch with `forbidden_origin` before the route runs, so the test never reaches the `not_local` check it means to test. Give the remote client the same `base_url="http://127.0.0.1:8000"` as `local_client()`, so only its client address differs, and keep expecting 403 `not_local`.
