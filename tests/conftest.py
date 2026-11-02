"""Global test isolation: no test may touch the real env, data, or ledger."""
import pytest

import budget
import muse_client


@pytest.fixture(autouse=True)
def _blackout_isolation(tmp_path: pytest.FixtureDef, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[valid-type]
    """Protect every test in tests/ from real environment and data."""
    monkeypatch.delenv("BLACKOUT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("BLACKOUT_KEY_FILE", str(tmp_path / "api_key"))
    monkeypatch.setenv("BLACKOUT_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(muse_client, "ENV_FILE", tmp_path / "no.env")
    monkeypatch.setattr(budget, "LEDGER_FILE", tmp_path / "spend.jsonl")
    budget.reset_record_failure()
    from app import conductor as conductor_mod
    from app import keys as keys_mod
    from app import routes as routes_mod
    from app import store as store_mod
    import app.security as security_mod

    original_key_status = routes_mod._key_status
    monkeypatch.setattr(routes_mod, "_key_status", lambda: "ok")
    keys_mod.clear_cache()
    store_mod.clear_memory()
    conductor_mod.clear_memory()
    security_mod.reset_rate_limit()
    try:
        from app import realtime as realtime_mod

        realtime_mod._bridges.clear()
    except Exception:
        pass
    yield  # type: ignore[misc]
    keys_mod.clear_cache()
    store_mod.clear_memory()
    conductor_mod.clear_memory()
    security_mod.reset_rate_limit()
    budget.reset_record_failure()
    try:
        from app import realtime as realtime_mod2

        realtime_mod2._bridges.clear()
    except Exception:
        pass
