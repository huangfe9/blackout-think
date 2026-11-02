"""Build the replayable sample files from the talks marked as samples.

Usage: python -m tests.evals.make_samples

This makes real, paid calls and is never run under pytest. For each
sample talk it runs the talk like run_evals, waits for the picture,
and writes app/static/sample/{language}.json plus the picture file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from tests.evals.run_evals import ROOT, load_talks, run_talk

SAMPLE_DIR = ROOT / "app" / "static" / "sample"
DROP_KEYS = {"owner", "session_id", "sessionId"}
TIMESTAMP_KEYS = {"at", "timestamp", "time", "created_at", "added_at"}


def _clean(value: Any, session_id: str) -> Any:
    """Remove owner, session ids, and transcript timestamps recursively."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in DROP_KEYS:
                continue
            if key == "id" and item == session_id:
                continue
            if key == "transcript" and isinstance(item, list):
                cleaned[key] = [_clean_transcript_line(line, session_id) for line in item]
                continue
            cleaned[key] = _clean(item, session_id)
        return cleaned
    if isinstance(value, list):
        return [_clean(item, session_id) for item in value]
    return value


def _clean_transcript_line(line: Any, session_id: str) -> Any:
    if not isinstance(line, dict):
        return _clean(line, session_id)
    return {
        key: _clean(item, session_id)
        for key, item in line.items()
        if key not in TIMESTAMP_KEYS and key not in DROP_KEYS
    }


def _write_picture(session_id: str, language: str) -> str:
    """Write the poster as JPEG if Pillow exists, else copy it as PNG."""
    from app.poster import poster_path

    source = Path(poster_path(session_id))
    if not source.exists():
        raise FileNotFoundError(f"poster file not found for session {session_id}")
    try:
        from PIL import Image
    except ImportError:
        target = SAMPLE_DIR / f"{language}.png"
        shutil.copyfile(source, target)
        return f"sample/{language}.png"
    target = SAMPLE_DIR / f"{language}.jpg"
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        if rgb.width > 1400:
            height = round(rgb.height * 1400 / rgb.width)
            rgb = rgb.resize((1400, height), Image.LANCZOS)
        rgb.save(target, "JPEG", quality=85)
    return f"sample/{language}.jpg"


def make_sample(talk: dict[str, Any]) -> Path:
    """Run one sample talk and write its replay JSON and picture."""
    language = str(talk["language"])
    outcome = run_talk(talk, collect_frames=True, picture_timeout=150.0)
    session_id = str(outcome["session_id"])
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    src = _write_picture(session_id, language)
    result = _clean(outcome["result"], session_id)
    result["poster"] = {"status": "done", "version": 1, "error": "", "src": src}
    frames: list[dict[str, Any]] = []
    for frame in outcome["frames"]:
        stats = frame.get("stats", {})
        if isinstance(stats, dict):
            kept = {k: stats[k] for k in ("user_turns", "ai_spoke", "pull_backs", "conflicts_asked") if k in stats}
        else:
            kept = {}
        cleaned_frame = dict(frame)
        cleaned_frame["stats"] = kept
        frames.append(cleaned_frame)
    payload = {
        "language": language,
        "goal": talk["goal"],
        "fictional": True,
        "frames": frames,
        "result": result,
    }
    path = SAMPLE_DIR / f"{language}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {path}")
    return path


def main() -> int:
    """Build every talk marked as a sample."""
    samples = [talk for talk in load_talks() if talk.get("sample")]
    for talk in samples:
        make_sample(talk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
