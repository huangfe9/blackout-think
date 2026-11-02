"""Tests for build_with_muse.py path guard."""
from pathlib import Path
from typing import Any

import pytest

from build_with_muse import build_input, is_allowed_path, validate_response_files, write_files


def test_allowed_app_tests_docs_readme() -> None:
    """App, tests, docs, and README are allowed."""
    assert is_allowed_path("app/main.py") is True
    assert is_allowed_path("tests/test_app.py") is True
    assert is_allowed_path("docs/demo_script.md") is True
    assert is_allowed_path("README.md") is True


def test_rejected_paths() -> None:
    """Empty, absolute, traversal, backslash, colon rejected."""
    assert is_allowed_path("") is False
    assert is_allowed_path("/etc/passwd") is False
    assert is_allowed_path("../secret") is False
    assert is_allowed_path("app/../../etc") is False
    assert is_allowed_path("a\\b") is False
    assert is_allowed_path("C:foo") is False
    assert is_allowed_path("random.txt") is False


def test_infra_rejected_by_default() -> None:
    """Infra files need allow_infra."""
    assert is_allowed_path("budget.py") is False
    assert is_allowed_path("muse_client.py") is False
    assert is_allowed_path("requirements.txt") is False
    assert is_allowed_path(".env.example") is False
    assert is_allowed_path(".gitignore") is False


def test_infra_allowed_with_flag() -> None:
    """Infra files allowed with allow_infra=True."""
    assert is_allowed_path("budget.py", allow_infra=True) is True
    assert is_allowed_path("muse_client.py", allow_infra=True) is True
    assert is_allowed_path("build_with_muse.py", allow_infra=True) is True
    assert is_allowed_path("check_connection.py", allow_infra=True) is True
    assert is_allowed_path("requirements.txt", allow_infra=True) is True
    assert is_allowed_path(".env.example", allow_infra=True) is True
    assert is_allowed_path(".gitignore", allow_infra=True) is True


def test_license_infra_only() -> None:
    """LICENSE is an infra file: refused by default, allowed with the flag."""
    assert is_allowed_path("LICENSE") is False
    assert is_allowed_path("LICENSE", allow_infra=True) is True


def test_env_never_allowed() -> None:
    """Dotenv is never writable."""
    assert is_allowed_path(".env") is False
    assert is_allowed_path(".env", allow_infra=True) is False


def test_git_never_allowed() -> None:
    """Git internals are never writable."""
    assert is_allowed_path(".git/config") is False
    assert is_allowed_path(".git/config", allow_infra=True) is False
    assert is_allowed_path(".github/workflows/x.yml") is False
    assert is_allowed_path(".github/workflows/x.yml", allow_infra=True) is False


def test_one_bad_path_writes_nothing(tmp_path: Path) -> None:
    """Any rejected path aborts the whole write."""
    files: list[dict[str, str]] = [{"path": "app/ok.py", "content": "x"}, {"path": "/bad", "content": "y"}]
    with pytest.raises(ValueError):
        write_files(files, root=tmp_path)
    assert not (tmp_path / "app" / "ok.py").exists()


def test_write_ok(tmp_path: Path) -> None:
    """Allowed files are written with LF."""
    files: list[dict[str, str]] = [{"path": "app/a.py", "content": "a\r\nb"}]
    out: Any = write_files(files, root=tmp_path)
    assert out == ["app/a.py"]
    text: str = (tmp_path / "app" / "a.py").read_text(encoding="utf-8")
    assert "\r" not in text


def test_build_input_skips_pycache_and_uses_posix(tmp_path: Path) -> None:
    """Compiled files are skipped and labels use forward slashes."""
    (tmp_path / "spec").mkdir(parents=True, exist_ok=True)
    (tmp_path / "spec" / "blackout_spec.md").write_text("spec text", encoding="utf-8")
    (tmp_path / "app" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "__pycache__" / "x.pyc").write_bytes(b"\xff\xfe\xfd\x00not-utf8")
    (tmp_path / "app" / "sub").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "sub" / "y.py").write_text("print('hi')\n", encoding="utf-8")
    out: str = build_input("please fix", root=tmp_path)
    assert "--- app/sub/y.py ---" in out
    assert "__pycache__" not in out
    assert "x.pyc" not in out


def test_context_limits_prompt_to_selected_files(tmp_path: Path) -> None:
    """With context, only the selected files are included in the prompt."""
    (tmp_path / "spec").mkdir(parents=True, exist_ok=True)
    (tmp_path / "spec" / "blackout_spec.md").write_text("spec text", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "a.py").write_text("CONTENT_A_MARKER\n", encoding="utf-8")
    (tmp_path / "app" / "b.py").write_text("CONTENT_B_MARKER\n", encoding="utf-8")
    out: str = build_input("please fix", root=tmp_path, context=["app/a.py"])
    assert "spec text" in out
    assert "please fix" in out
    assert "--- app/a.py ---" in out
    assert "CONTENT_A_MARKER" in out
    assert "app/b.py" not in out
    assert "CONTENT_B_MARKER" not in out


def test_expect_refuses_unexpected_path() -> None:
    """A response path outside the expect list is refused."""
    files: list[dict[str, str]] = [{"path": "app/other.py", "content": "x" * 40}]
    with pytest.raises(ValueError):
        validate_response_files(files, ["app/expected.py"])


def test_expect_refuses_nearly_empty_file() -> None:
    """A nearly empty expected file is refused."""
    files: list[dict[str, str]] = [{"path": "app/expected.py", "content": "hello"}]
    with pytest.raises(ValueError):
        validate_response_files(files, ["app/expected.py"])


def test_expect_accepts_expected_nonempty_file() -> None:
    """An expected path with real content passes validation."""
    files: list[dict[str, str]] = [{"path": "app/expected.py", "content": "x" * 40}]
    validate_response_files(files, ["app/expected.py"])