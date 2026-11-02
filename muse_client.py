"""Shared client for the Meta Model API."""
import json
import logging
import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

import openai

from budget import BudgetedHttpClient, TRANSCRIBE_MODEL

logger: logging.Logger = logging.getLogger(__name__)

BASE_URL: str = "https://api.meta.ai/v1"
DEFAULT_MODEL: str = "muse-spark-1.3"
DEFAULT_ENV_FILE: Path = Path(__file__).parent / ".env"
ENV_FILE: Path = DEFAULT_ENV_FILE
KEY_NAME: str = "MODEL_API_KEY"
PLACEHOLDER: str = "your-api-key-here"
PLACEHOLDERS: frozenset = frozenset({"your-api-key-here", "your-key-here"})


def read_key_from_env_file(path: Path = ENV_FILE) -> str | None:
    """Read MODEL_API_KEY from a .env file."""
    try:
        text: str = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    for line in text.splitlines():
        stripped: str = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            continue
        key: str
        _: str
        value: str
        key, _, value = line.partition("=")
        if key.strip() != KEY_NAME:
            continue
        val: str = value.strip()
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1].strip()
        if not val:
            return None
        return val
    return None


def _default_saved_key_path() -> Path:
    """Default path of the key saved by the setup page, outside the repository."""
    if os.name == "nt":
        local: str = os.environ.get("LOCALAPPDATA") or ""
        if local:
            return Path(local) / "Blackout" / "api_key"
        return Path.home() / "Blackout" / "api_key"
    return Path.home() / ".blackout" / "api_key"


def saved_key_path() -> Path:
    """Path of the key saved by the setup page, outside the repository."""
    explicit: str = os.environ.get("BLACKOUT_KEY_FILE") or ""
    if explicit:
        candidate: Path = Path(explicit).expanduser()
        try:
            resolved: Path = candidate.resolve()
        except Exception:
            resolved = candidate.absolute()
        repo: Path = Path(__file__).resolve().parent
        try:
            inside: bool = resolved.is_relative_to(repo)  # type: ignore[attr-defined]
        except AttributeError:
            inside = str(resolved) == str(repo) or str(resolved).startswith(str(repo) + os.sep)
        except Exception:
            inside = False
        if inside:
            logger.warning("BLACKOUT_KEY_FILE points inside the repository; using the default key location instead")
            return _default_saved_key_path()
        return Path(explicit)
    return _default_saved_key_path()


def is_plausible_key(value: object) -> bool:
    """Whether a value could be a real key, without revealing anything."""
    if not isinstance(value, str):
        return False
    if value in PLACEHOLDERS:
        return False
    if len(value) < 16 or len(value) > 512:
        return False
    return all(0x21 <= ord(char) <= 0x7E for char in value)


def save_key(value: str) -> None:
    """Save a key atomically with owner-only permissions where supported."""
    if not is_plausible_key(value):
        raise ValueError("invalid key format")
    path: Path = saved_key_path()
    parent: Path = path.parent
    temp: Path = parent / (".api_key." + uuid4().hex + ".tmp")
    created: bool = False
    try:
        parent_existed: bool = parent.is_dir()
        parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt" and not parent_existed:
            os.chmod(parent, 0o700)
        descriptor: int = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
        created = False
        if os.name != "nt":
            os.chmod(path, 0o600)
    except Exception:
        if created:
            try:
                temp.unlink()
            except OSError:
                pass
        raise OSError("could not save key") from None


def read_saved_key() -> str | None:
    """Read the saved key if present and plausible."""
    try:
        value: str = saved_key_path().read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return value if is_plausible_key(value) else None


def delete_saved_key() -> bool:
    """Remove the saved key and report whether one existed."""
    path: Path = saved_key_path()
    existed: bool = False
    try:
        path.unlink()
        existed = True
    except FileNotFoundError:
        existed = False
    except OSError:
        existed = False
    try:
        for leftover in path.parent.glob(".api_key.*.tmp"):
            try:
                leftover.unlink()
            except OSError:
                pass
    except Exception:
        pass
    return existed


def _env_key() -> str | None:
    value: Optional[str] = os.environ.get(KEY_NAME)
    if value is not None and value != "" and value not in PLACEHOLDERS and is_plausible_key(value):
        return value
    return None


def _file_key() -> str | None:
    value: str | None = read_key_from_env_file(ENV_FILE)
    if value is not None and value != "" and value not in PLACEHOLDERS and is_plausible_key(value):
        return value
    return None


def load_api_key() -> str:
    """Load API key from env, then .env file, then the saved key file."""
    env_val: str | None = _env_key()
    if env_val is not None:
        return env_val
    if os.environ.get(KEY_NAME) == PLACEHOLDER:
        logger.warning("placeholder key in environment")
    file_val: str | None = _file_key()
    if file_val is not None:
        return file_val
    saved_val: str | None = read_saved_key()
    if saved_val is not None:
        return saved_val
    raise RuntimeError(f"MODEL_API_KEY is not set. Create a key at https://dev.meta.ai/api-keys/ , then run python start.py and paste it into the page, or put it in {ENV_FILE} as MODEL_API_KEY=...")


def key_source() -> str:
    """Where the effective key comes from, without returning the key."""
    if _env_key() is not None:
        return "environment"
    if _file_key() is not None:
        return "env_file"
    if read_saved_key() is not None:
        return "saved"
    return "none"


def create_client() -> openai.OpenAI:
    """Create an OpenAI SDK client with the budget guard."""
    return openai.OpenAI(base_url=BASE_URL, api_key=load_api_key(), http_client=BudgetedHttpClient())


def transcribe_wav(wav: bytes, languages: tuple[str, ...] = ("Mandarin Chinese", "English")) -> str:
    """Transcribe 16-bit mono WAV audio to text."""
    key: str = load_api_key()
    settings: dict[str, object] = {"mode": "PUSH_TO_TALK", "model": TRANSCRIBE_MODEL, "audioEncoding": "WAV", "languageBias": list(languages)}
    payload: str = json.dumps(settings)
    files: dict[str, object] = {"request": (None, payload, "application/json"), "audio": ("speech.wav", wav, "audio/wav")}
    headers: dict[str, str] = {"Authorization": f"Bearer {key}"}
    url: str = f"{BASE_URL}/asr/transcribe"
    with BudgetedHttpClient(timeout=120) as client:
        resp = client.post(url, files=files, headers=headers)  # type: ignore[arg-type]
        resp.raise_for_status()
        data: object = resp.json()
    if not isinstance(data, dict):
        raise ValueError("bad transcribe response")
    out: object = data.get("transcript")
    if not isinstance(out, str):
        raise ValueError("missing transcript")
    return out
