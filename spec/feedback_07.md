`test_muse_client.py` depends on the machine having no `.env`: `test_placeholder_rejected` and `test_missing_key_message` fail when a real `.env` exists in the project, which is always the case in real use.

Fix the test file only. Return only `test_muse_client.py` with full content. Do not change `muse_client.py`.

Every test that calls `load_api_key` or `create_client` must control both key sources, with `monkeypatch.setenv` or `monkeypatch.delenv` for the environment and `monkeypatch.setattr(muse_client, "read_key_from_env_file", ...)` for the file. Add a test that a real key in the file is used when the environment holds the placeholder, because that is what `load_api_key` does. No test may read the real `.env` or make a network call.
