Two tests fail because of how they are written. Return exactly `budget.py`, `tests/test_realtime.py`, and `tests/test_security.py`, each with full content.

1. `budget.py`: function defaults such as `ledger: Path = LEDGER_FILE` are bound when the module loads, so changing `budget.LEDGER_FILE` has no effect, and `tests/test_realtime.py` works around that by editing `__defaults__`, which fails. Change `spent_usd`, `ledger_ok`, `can_spend`, `record_audio_seconds`, and `BudgetedHttpClient.__init__` to take `ledger: Path | None = None`, and resolve `None` to the module's current `LEDGER_FILE` at call time. Add one small private helper for this. Behaviour is otherwise unchanged. `limit_usd` works the same way with `STOP_AT_USD`.

2. `tests/test_realtime.py`: delete `_use_temp_ledger` and its `__defaults__` editing. Use `monkeypatch.setattr(budget, "LEDGER_FILE", ledger)`.

3. `tests/test_security.py`, `test_token_nonascii_returns_401_not_error`: the test client cannot send a non-ASCII cookie, so that line raises in the client, before the app runs. Keep the query-parameter case. Replace the cookie case with a direct unit call of the token comparison in `app/security.py`, using a scope whose raw cookie header contains non-ASCII bytes, and assert it returns false without raising. Remove the part that configures a non-ASCII token.
