"""Static checks for the eval talks and the demo talk script.

These read only JSON files (and the sample replay if it exists).
They make no calls and need no key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BEATS = [
    "open",
    "quiet",
    "drift",
    "lookup",
    "conflict",
    "answer",
    "todo",
    "open_question",
    "stop",
]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(key)
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def test_talks_json_is_valid() -> None:
    talks = _load(ROOT / "tests" / "evals" / "talks.json")
    assert isinstance(talks, list)
    assert len(talks) == 8
    languages = [talk["language"] for talk in talks]
    assert languages.count("en") == 4
    assert languages.count("zh") == 4
    samples = [talk for talk in talks if talk.get("sample")]
    assert len([t for t in samples if t["language"] == "en"]) == 1
    assert len([t for t in samples if t["language"] == "zh"]) == 1
    ids = [talk["id"] for talk in talks]
    assert len(set(ids)) == 8
    for talk in talks:
        assert 14 <= len(talk["lines"]) <= 24
        expects = [line.get("expect") for line in talk["lines"]]
        for kind in ("pull_back", "conflict", "task"):
            assert expects.count(kind) >= 1, (talk["id"], kind)
        assert expects[-1] == "end"
        for key in ("must_decide", "must_todo", "must_open", "must_park"):
            assert isinstance(talk[key], list) and talk[key]
            for pattern in talk[key]:
                re.compile(pattern, re.IGNORECASE)
        assert isinstance(talk["must_draft"], bool)


def test_sample_talks_end_with_a_writing_todo() -> None:
    talks = _load(ROOT / "tests" / "evals" / "talks.json")
    for talk in [t for t in talks if t.get("sample")]:
        assert talk["must_draft"] is True
        before_end = " ".join(line["text"] for line in talk["lines"][-3:])
        assert re.search(r"write|写", before_end, re.IGNORECASE)


def test_demo_talk_is_valid_and_in_time() -> None:
    demo = _load(ROOT / "docs" / "demo_talk.json")
    lines = demo["lines"]
    beats_seen: list[str] = []
    for line in lines:
        if line["beat"] not in beats_seen:
            beats_seen.append(line["beat"])
    assert beats_seen == EXPECTED_BEATS
    assert set(demo["captions"]) == set(EXPECTED_BEATS)
    for caption in demo["captions"].values():
        assert len(caption.split()) <= 12
    for caption in demo["scene_captions"].values():
        assert len(caption.split()) <= 12
    assert lines[-1]["say"] == "Stop."
    spoken = sum(len(line["say"].split()) / 2.6 for line in lines)
    pauses = sum(float(line["pause_after"]) for line in lines)
    assert spoken + pauses <= 105
    title = " ".join(demo["title_lines"])
    assert "Recorded live against the real Meta API. The voices are computer speech." in title
    closing = " ".join(demo["closing_lines"]).lower()
    assert "your own computer" in closing and "your own meta key" in closing


def test_sample_replay_if_present_has_no_owner() -> None:
    path = ROOT / "app" / "static" / "sample" / "en.json"
    if not path.exists():
        return
    payload = _load(path)
    assert payload["fictional"] is True
    assert "owner" not in _walk_keys(payload)
