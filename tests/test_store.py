"""Store tests."""
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from app import store


@pytest.fixture(autouse=True)
def temp_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path))
    store.clear_memory()
    return tmp_path


def test_round_trip(temp_data: Path) -> None:
    record: Dict[str, Any] = store.create_session("想清楚方案")
    record["state"]["decisions"] = ["决定一"]
    store.save_session(record)
    store.clear_memory()
    loaded: Any = store.get_session(record["id"])
    assert loaded["state"]["decisions"] == ["决定一"]
    assert (temp_data / "sessions" / f"{record['id']}.json").is_file()


def test_invalid_id_creates_no_file(temp_data: Path) -> None:
    assert store.get_session("../../etc/passwd") is None
    assert store.session_path("../../etc/passwd") is None
    assert store.get_session("zzzz" * 8) is None
    assert store.get_session("") is None
    assert store.get_session(None) is None  # type: ignore[arg-type]
    assert not list(temp_data.rglob("passwd*"))


def test_delete_and_list_order() -> None:
    first: Dict[str, Any] = store.create_session("第一", owner="owner-a")
    second: Dict[str, Any] = store.create_session("第二", owner="owner-a")
    listed: Any = store.list_sessions("owner-a")
    assert listed[0]["id"] == second["id"]
    assert listed[0].keys() == {"id", "goal", "status", "created_at", "updated_at"}
    # A different owner sees none of these sessions.
    assert store.list_sessions("owner-b") == []
    assert store.delete_session(first["id"]) is True
    assert store.get_session(first["id"]) is None
    assert store.delete_session(first["id"]) is False
    assert store.delete_session("../bad") is False


def test_running_task_becomes_failed() -> None:
    record: Dict[str, Any] = store.create_session("目标")
    record["tasks"] = [{"id": "t1", "kind": "search", "instruction": "查", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x"}]
    store.save_session(record)
    store.clear_memory()
    loaded: Any = store.load_session(record["id"])
    assert loaded["tasks"][0]["status"] == "failed"


def test_default_data_dir_outside_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BLACKOUT_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    if os.name != "nt":
        assert store.data_dir() == tmp_path / ".blackout"
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "custom"))
    assert store.data_dir() == tmp_path / "custom"


def test_replace_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch, temp_data: Path) -> None:
    record: Dict[str, Any] = store.create_session("目标")
    calls: Dict[str, int] = {"n": 0}
    real_replace: Any = os.replace
    def flaky(src: Any, dst: Any) -> None:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("locked")
        real_replace(src, dst)
    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda _s: None)
    store.save_session(record)
    assert calls["n"] == 3
    assert (temp_data / "sessions" / f"{record['id']}.json").is_file()


def test_replace_always_fails_keeps_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    record: Dict[str, Any] = store.create_session("目标")
    def always(_src: Any, _dst: Any) -> None:
        raise PermissionError("locked")
    monkeypatch.setattr(store.os, "replace", always)
    monkeypatch.setattr(store.time, "sleep", lambda _s: None)
    store.save_session(record)
    assert store.get_session(record["id"])["state"]["goal"] == "目标"


def test_get_session_copy_is_deep() -> None:
    record: Dict[str, Any] = store.create_session("目标")
    copied: Any = store.get_session_copy(record["id"])
    copied["state"]["decisions"].append("改动")
    assert store.get_session(record["id"])["state"]["decisions"] == []


def test_announcements_and_live() -> None:
    record: Dict[str, Any] = store.create_session("目标")
    sid: str = str(record["id"])
    store.add_announcement(sid, "你好")
    assert store.drain_announcements(sid) == [{"text": "你好", "kind": "announcement"}]
    assert store.drain_announcements(sid) == []
    store.update_live(sid, mic="listening", partial="半句", bogus="x")  # type: ignore[call-arg]
    live: Any = store.get_live(sid)
    assert live["mic"] == "listening" and live["partial"] == "半句" and "bogus" not in live


def test_delete_takes_lock() -> None:
    record: Dict[str, Any] = store.create_session("目标")
    lock: Any = store.get_lock(record["id"])
    acquired: threading.Event = threading.Event()
    def deleter() -> None:
        store.delete_session(record["id"])
        acquired.set()
    lock.acquire()
    try:
        thread: threading.Thread = threading.Thread(target=deleter)
        thread.start()
        time.sleep(0.05)
        assert not acquired.is_set()
    finally:
        lock.release()
    thread.join(timeout=2)
    assert acquired.is_set()


# --- Session-id validation and file permissions ---------------------------

def test_is_valid_id_rejects_trailing_newline() -> None:
    valid: str = "0123456789abcdef" * 2
    assert store.is_valid_id(valid) is True
    # A `$`-anchored match would let a trailing newline slip through;
    # the id must be exactly 32 lowercase hex characters and nothing else.
    assert store.is_valid_id(valid + "\n") is False
    assert store.is_valid_id(valid + "\r\n") is False
    assert store.is_valid_id("\n" + valid) is False
    assert store.is_valid_id(valid + " ") is False
    assert store.is_valid_id(valid.upper()) is False
    assert store.is_valid_id(valid[:-1]) is False
    assert store.is_valid_id(valid + "0") is False
    assert store.is_valid_id("") is False
    assert store.is_valid_id(None) is False  # type: ignore[arg-type]
    assert store.session_path(valid + "\n") is None


def test_get_session_copy_with_garbage_id_does_not_grow_lock_table() -> None:
    locks_before: set = set(store._locks.keys())
    for garbage in ("not-a-session", "../../etc/passwd", "0" * 32 + "\n", "g" * 32, "", "0" * 31):
        assert store.get_session_copy(garbage) is None
        assert garbage not in store._locks
    assert set(store._locks.keys()) == locks_before


def test_session_files_are_owner_only_on_posix(temp_data: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not applicable on Windows")
    record: Dict[str, Any] = store.create_session("目标")
    path: Path = temp_data / "sessions" / f"{record['id']}.json"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Re-saving keeps the restrictive mode.
    record["state"]["decisions"] = ["决定一"]
    store.save_session(record)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
