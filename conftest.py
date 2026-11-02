"""Repo-root pytest isolation: runs before any test module is imported.

No test, in the root or in tests/, may load a real key from this computer.
"""
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import muse_client

_isolation_dir: Optional[Path] = None


def pytest_configure(config: Any = None) -> None:
    """Remove real-key sources before test modules are imported."""
    global _isolation_dir
    os.environ.pop("MODEL_API_KEY", None)
    if _isolation_dir is None:
        _isolation_dir = Path(tempfile.mkdtemp(prefix="blackout-test-"))
    _isolation_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BLACKOUT_KEY_FILE"] = str(_isolation_dir / "api_key")
    muse_client.ENV_FILE = _isolation_dir / "missing.env"
