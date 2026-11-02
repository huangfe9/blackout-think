"""Run the fictional talks in talks.json through the real model.

Usage: python -m tests.evals.run_evals [--only id]

This makes real, paid calls and is never run under pytest. Sessions live
in a temporary BLACKOUT_DATA_DIR; spending uses the normal ledger.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

# app.store reads BLACKOUT_DATA_DIR at import time, so set it first.
os.environ["BLACKOUT_DATA_DIR"] = tempfile.mkdtemp(prefix="blackout-evals-")

import budget  # noqa: E402
from app import conductor, store, summary  # noqa: E402
from app.state import build_map  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TALKS_PATH = Path(__file__).resolve().with_name("talks.json")
REFLECTION_MARKERS = ("So far", "Still open", "现在定了", "还没定")
PLACEHOLDER_RE = re.compile(r"\[.+?\]|【.+?】|placeholder|待确认|待补充", re.IGNORECASE)


def spoken_seconds(text: str, language: str) -> float:
    """Estimated spoken length of one line."""
    if language == "zh":
        return len(text) / 4.5
    return len(text.split()) / 2.6


def load_talks() -> list[dict[str, Any]]:
    """Load the fictional talks."""
    return json.loads(TALKS_PATH.read_text(encoding="utf-8"))


def _tasks(session_id: str) -> list[dict[str, Any]]:
    return list(store.get_session_copy(session_id).get("tasks", []))


def _wait_for_tasks(session_id: str, timeout: float) -> None:
    """Wait until no background task is running, up to timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(t.get("status") == "running" for t in _tasks(session_id)):
            return
        time.sleep(2.0)


def _wait_for_draft(session_id: str, timeout: float) -> None:
    """Wait up to timeout for a draft task to appear and finish."""
    deadline = time.monotonic() + timeout
    grace_deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        drafts = [t for t in _tasks(session_id) if t.get("kind") == "draft"]
        if drafts and not any(t.get("status") == "running" for t in drafts):
            return
        if not drafts and time.monotonic() > grace_deadline:
            return
        time.sleep(2.0)


def wait_for_picture(session_id: str, timeout: float) -> None:
    """Wait up to timeout for the session poster to finish drawing."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        poster = store.get_session_copy(session_id).get("poster") or {}
        if poster.get("status") in ("done", "failed"):
            return
        time.sleep(2.0)


def _count_matches(patterns: list[str], items: list[Any]) -> dict[str, int]:
    texts = [str(item) for item in items]
    found = 0
    for pattern in patterns:
        if any(re.search(pattern, text, re.IGNORECASE) for text in texts):
            found += 1
    return {"found": found, "expected": len(patterns)}


def _is_reflection(reply: str, action: str) -> bool:
    lowered = reply.lower()
    if action == "continue":
        return True
    return any(m.lower() in lowered for m in REFLECTION_MARKERS)


def run_talk(
    talk: dict[str, Any],
    collect_frames: bool = False,
    picture_timeout: float = 0.0,
) -> dict[str, Any]:
    """Run one talk through conductor and summary; return details."""
    language = str(talk.get("language", "zh"))
    clear = getattr(conductor, "clear_memory", None)
    if callable(clear):
        clear()
    start_spent = float(budget.spent_usd())
    record = store.create_session(str(talk["goal"]), owner="", language=language)
    session_id = str(record["id"])
    ts = time.time()
    elapsed = 0.0
    frames: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    durations: list[float] = []
    budget_hit = False
    for line in talk["lines"]:
        if not budget.can_spend():
            budget_hit = True
            break
        text = str(line["text"])
        started = time.monotonic()
        turn = conductor.process_speech(session_id, text, now=ts)
        durations.append(time.monotonic() - started)
        advance = spoken_seconds(text, language) + 1.0
        ts += advance
        elapsed += advance
        turns.append({"line": line, "turn": turn})
        if collect_frames:
            copy = store.get_session_copy(session_id)
            state = copy.get("state", {})
            frames.append(
                {
                    "t": round(elapsed, 1),
                    "heard": text,
                    "reply": str(turn.get("reply", "")),
                    "action": str(turn.get("action", "")),
                    "map": build_map(state, copy.get("tasks", [])),
                    "parking": list(state.get("parking_lot", [])),
                    "stats": dict(copy.get("stats", {})),
                }
            )
        if turn.get("budget_exhausted"):
            budget_hit = True
            break
    _wait_for_tasks(session_id, 90.0)
    result = summary.finish(session_id)
    _wait_for_draft(session_id, 60.0)
    if picture_timeout > 0:
        wait_for_picture(session_id, picture_timeout)
    result = (store.get_session_copy(session_id) or {}).get("result") or result
    record_out = _score(talk, turns, durations, result, session_id)
    record_out["cost_usd"] = round(float(budget.spent_usd()) - start_spent, 6)
    return {
        "record": record_out,
        "frames": frames,
        "result": result,
        "session_id": session_id,
        "budget_exhausted": budget_hit or bool(record_out.get("budget_exhausted")),
    }


def _score(
    talk: dict[str, Any],
    turns: list[dict[str, Any]],
    durations: list[float],
    result: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    def expected(kind: str) -> list[dict[str, Any]]:
        return [t for t in turns if t["line"].get("expect") == kind]

    pull = expected("pull_back")
    conflicts = expected("conflict")
    tasks = expected("task")
    conflict_indices = [i for i, t in enumerate(turns) if t["line"].get("expect") == "conflict"]
    used_followups: set[int] = set()
    asked = 0
    for ci in conflict_indices:
        for j in range(ci, min(len(turns), ci + 3)):
            if j in used_followups:
                continue
            cand = turns[j]["turn"]
            cand_reply = str(cand.get("reply", "")).strip()
            if cand.get("action") == "follow_up" and cand_reply:
                asked += 1
                used_followups.add(j)
                break
    false_interruptions = 0
    ai_spoke = 0
    for idx, item in enumerate(turns):
        turn = item["turn"]
        reply = str(turn.get("reply", "")).strip()
        action = str(turn.get("action", ""))
        if reply:
            ai_spoke += 1
            if idx in used_followups:
                continue
            if action == "summarize":
                continue
            if "expect" in item["line"]:
                continue
            if _is_reflection(reply, action):
                continue
            false_interruptions += 1
    drafts = [t for t in _tasks(session_id) if t.get("kind") == "draft"]
    done_drafts = [t for t in drafts if t.get("status") == "done"]
    draft_text = ""
    if done_drafts:
        draft_text = str(done_drafts[-1].get("detail") or done_drafts[-1].get("conclusion") or "")
    return {
        "id": talk["id"],
        "language": talk["language"],
        "goal": talk["goal"],
        "lines": len(turns),
        "ai_spoke": ai_spoke,
        "pull_backs": {
            "expected": len(pull),
            "hit": sum(1 for t in pull if t["turn"].get("action") == "pull_back"),
        },
        "conflicts": {
            "expected": len(conflicts),
            "asked": asked,
        },
        "tasks": {
            "expected": len(tasks),
            "started": sum(1 for t in tasks if t["turn"].get("task_started")),
        },
        "false_interruptions": false_interruptions,
        "decisions": _count_matches(talk.get("must_decide", []), result.get("decisions", [])),
        "todos": _count_matches(talk.get("must_todo", []), result.get("todos", [])),
        "open_questions": _count_matches(talk.get("must_open", []), result.get("open_questions", [])),
        "parking_lot": _count_matches(talk.get("must_park", []), result.get("parking_lot", [])),
        "draft": {
            "expected": bool(talk.get("must_draft")),
            "finished": bool(done_drafts),
            "has_placeholder": bool(draft_text and PLACEHOLDER_RE.search(draft_text)),
        },
        "median_turn_seconds": round(statistics.median(durations), 3) if durations else 0.0,
        "slowest_turn_seconds": round(max(durations), 3) if durations else 0.0,
        "budget_exhausted": any(bool(t["turn"].get("budget_exhausted")) for t in turns),
        "degraded": bool(result.get("degraded")),
    }


def _totals(records: list[dict[str, Any]]) -> dict[str, Any]:
    def pair(key: str, hit_key: str) -> dict[str, Any]:
        expected = sum(r[key]["expected"] for r in records)
        hit = sum(r[key][hit_key] for r in records)
        return {"expected": expected, "hit": hit, "percent": round(100.0 * hit / expected, 1) if expected else 0.0}

    def content(key: str) -> dict[str, Any]:
        expected = sum(r[key]["expected"] for r in records)
        found = sum(r[key]["found"] for r in records)
        return {"expected": expected, "found": found, "percent": round(100.0 * found / expected, 1) if expected else 0.0}

    return {
        "talks": len(records),
        "lines": sum(r["lines"] for r in records),
        "ai_spoke": sum(r["ai_spoke"] for r in records),
        "pull_backs": pair("pull_backs", "hit"),
        "conflicts": pair("conflicts", "asked"),
        "tasks": pair("tasks", "started"),
        "false_interruptions": sum(r["false_interruptions"] for r in records),
        "decisions": content("decisions"),
        "todos": content("todos"),
        "open_questions": content("open_questions"),
        "parking_lot": content("parking_lot"),
        "drafts_expected": sum(1 for r in records if r["draft"]["expected"]),
        "drafts_finished": sum(1 for r in records if r["draft"]["finished"]),
        "cost_usd": round(sum(r["cost_usd"] for r in records), 6),
    }


def _markdown(records: list[dict[str, Any]], totals: dict[str, Any], run_date: str, capped: bool) -> str:
    average_cost = float(totals.get("cost_usd", 0.0)) / len(records) if records else 0.0
    lines = [
        "# Evaluation results",
        "",
        f"Run date: {run_date}",
        "",
        f"Average cost per talk: ${average_cost:.4f}",
        "",
        "These are fictional talks typed through the same code path as real "
        "speech, skipping only speech recognition, and scored by simple "
        "rules. They measure behaviour \u2014 when the AI stays quiet, pulls "
        "the speaker back, asks about contradictions, and records what was "
        "said \u2014 not whether the product helps people.",
        "",
        "| Talk | Language | Lines | AI spoke | Pull-backs | Conflicts asked | Tasks started | False interruptions | Decisions | Todos | Open questions | Parked | Draft done | Median turn (s) | Slowest turn (s) | Cost (USD) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in records:
        draft_done = "yes, unasked" if r['draft']['finished'] and not r['draft']['expected'] else ('yes' if r['draft']['finished'] else 'no')
        lines.append(
            f"| {r['id']} | {r['language']} | {r['lines']} | {r['ai_spoke']} | "
            f"{r['pull_backs']['hit']}/{r['pull_backs']['expected']} | "
            f"{r['conflicts']['asked']}/{r['conflicts']['expected']} | "
            f"{r['tasks']['started']}/{r['tasks']['expected']} | "
            f"{r['false_interruptions']} | "
            f"{r['decisions']['found']}/{r['decisions']['expected']} | "
            f"{r['todos']['found']}/{r['todos']['expected']} | "
            f"{r['open_questions']['found']}/{r['open_questions']['expected']} | "
            f"{r['parking_lot']['found']}/{r['parking_lot']['expected']} | "
            f"{draft_done} | "
            f"{r['median_turn_seconds']} | {r['slowest_turn_seconds']} | {r['cost_usd']:.4f} |"
        )
    t = totals
    lines.append(
        f"| **Total** |  | {t['lines']} | {t['ai_spoke']} | "
        f"{t['pull_backs']['hit']}/{t['pull_backs']['expected']} ({t['pull_backs']['percent']}%) | "
        f"{t['conflicts']['hit']}/{t['conflicts']['expected']} ({t['conflicts']['percent']}%) | "
        f"{t['tasks']['hit']}/{t['tasks']['expected']} ({t['tasks']['percent']}%) | "
        f"{t['false_interruptions']} | "
        f"{t['decisions']['found']}/{t['decisions']['expected']} ({t['decisions']['percent']}%) | "
        f"{t['todos']['found']}/{t['todos']['expected']} ({t['todos']['percent']}%) | "
        f"{t['open_questions']['found']}/{t['open_questions']['expected']} ({t['open_questions']['percent']}%) | "
        f"{t['parking_lot']['found']}/{t['parking_lot']['expected']} ({t['parking_lot']['percent']}%) | "
        f"{t['drafts_finished']}/{t['drafts_expected']} |  |  | {t['cost_usd']:.4f} |"
    )
    if capped:
        lines += ["", "The spending cap was reached, so this run is incomplete."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run talks and write docs/evals.json and docs/evals.md."""
    parser = argparse.ArgumentParser(prog="tests.evals.run_evals")
    parser.add_argument("--only", default=None, help="Run only the talk with this id")
    parser.add_argument("--from-json", action="store_true", help="Rebuild docs/evals.md from an existing docs/evals.json without running any talk")
    args = parser.parse_args(argv)
    docs = ROOT / "docs"
    if args.from_json:
        payload = json.loads((docs / "evals.json").read_text(encoding="utf-8"))
        records = list(payload.get("talks", []))
        totals = dict(payload.get("totals", {})) or _totals(records)
        run_date = str(payload.get("date", datetime.date.today().isoformat()))
        capped = bool(payload.get("budget_exhausted")) or not bool(payload.get("complete", True))
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "evals.md").write_text(_markdown(records, totals, run_date, capped), encoding="utf-8")
        print(f"Wrote {docs / 'evals.md'}")
        return 0
    talks = load_talks()
    if args.only:
        talks = [t for t in talks if t["id"] == args.only]
        if not talks:
            parser.error(f"unknown talk id: {args.only}")
    records: list[dict[str, Any]] = []
    capped = False
    for talk in talks:
        if not budget.can_spend():
            capped = True
            break
        outcome = run_talk(talk)
        records.append(outcome["record"])
        if outcome["budget_exhausted"] or not budget.can_spend():
            capped = True
            break
    totals = _totals(records)
    run_date = datetime.date.today().isoformat()
    docs.mkdir(parents=True, exist_ok=True)
    payload = {"date": run_date, "complete": not capped, "budget_exhausted": capped, "talks": records, "totals": totals}
    (docs / "evals.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (docs / "evals.md").write_text(_markdown(records, totals, run_date, capped), encoding="utf-8")
    print(f"Wrote {docs / 'evals.md'} and {docs / 'evals.json'}")
    print(f"Total cost: ${totals['cost_usd']:.4f}")
    if capped:
        print("Spending cap reached; the run is incomplete and partial results were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
