Stage 4 review found the defects below. Return exactly these files, each with full content: `app/phone.py`, `tests/test_phone.py`, `tests/conftest.py`, `build_with_muse.py`, `test_build_with_muse.py`.

1. **A test pollutes the whole test run.** `tests/test_phone.py` runs `phone.main()`, which writes `BLACKOUT_ACCESS_TOKEN` into `os.environ` and never restores it. Every test after it then gets a 401: 37 tests fail in the full run while each file passes on its own. Fix the test using `monkeypatch.setenv` or `patch.dict(os.environ)`, so the environment is restored.

2. **Add `tests/conftest.py`** with an autouse fixture that protects every test in `tests/`: delete `BLACKOUT_ACCESS_TOKEN` and `BLACKOUT_ALLOWED_HOSTS`; set `BLACKOUT_DATA_DIR` to a temporary directory; point `budget.LEDGER_FILE` at a temporary file, so no test can touch the real spend ledger; call `store.clear_memory()`, `conductor.clear_memory()`, `security.reset_rate_limit()`, and clear `realtime._bridges`.

3. **The private key can land in a synced folder.** `tls_dir()` falls back to `data/tls` under the working directory. Use `store.data_dir() / "tls"`, so TLS files live with the rest of the data, outside the repository. Keep `BLACKOUT_TLS_DIR` as an override. Add a test.

4. **Private key permissions.** The key is written and then restricted, leaving a short window. Create the key file with `os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`.

5. **Remove the aliases** `detect_lan_ip`, `find_lan_ip`, `generate_access_token`, `create_access_token`, `cert_matches_ip`, `certificate_valid_for_ip`, `ensure_certificates`, and `get_or_create_certificate`. Update the tests. Move the `cryptography` and `uvicorn` imports to the top of the module; they are required dependencies. Keep `segno` optional.

6. **Print the firewall note.** Add one printed line saying that if the phone cannot connect, the computer's firewall may be blocking port 8443.

7. **`build_with_muse.py`:** add `LICENSE` to the infrastructure files, which stage 1 asked for and was missed. A whole batch of output was refused because of it. Add a test: `LICENSE` is refused by default and allowed with `allow_infra=True`.

The full `tests/` run and the root tests must pass together.
