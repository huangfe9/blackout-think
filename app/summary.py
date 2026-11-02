"""Result page generation and the final organizing pass."""
import copy
import json
import logging
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from muse_client import DEFAULT_MODEL, create_client
from app import store
from app.messages import message
from app.prompts import FINAL_SCHEMA, FINAL_SYSTEM_PROMPT, build_final_user_content
from app.state import build_map, recent_language, unexpanded_points

logger: logging.Logger = logging.getLogger(__name__)
_NODE_KINDS: frozenset = frozenset({"point", "decision", "todo", "question"})
_POSTER_TYPES: frozenset = frozenset({"timeline", "flow", "list", "compare", "note"})
_LABELS: Dict[str, Dict[str, str]] = {
    "zh": {
        "goal": "目标：", "outline": "思路", "decisions": "决定", "todos": "待办", "parking_lot": "停车场",
        "open_questions": "还没想清楚", "contradictions": "前后矛盾", "unexpanded_points": "没说完的点",
        "tasks": "后台查到和写好的", "sketches": "纸上草稿",
    },
    "en": {
        "goal": "Goal: ", "outline": "Outline", "decisions": "Decisions", "todos": "To do", "parking_lot": "Parking lot",
        "open_questions": "Still open", "contradictions": "Contradictions", "unexpanded_points": "Unfinished",
        "tasks": "Looked up and drafted", "sketches": "Paper sketch",
    },
}


class _ParseFailure(Exception):
    """The final-pass output could not be parsed."""


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def _state_of(record: Dict[str, Any]) -> Dict[str, Any]:
    state: Any = record.get("state", {})
    return state if isinstance(state, dict) else {}


def user_utterances(record: Dict[str, Any]) -> List[str]:
    """All user utterances in order."""
    out: List[str] = []
    for entry in record.get("history", []):
        if isinstance(entry, dict) and entry.get("role") == "user":
            content: Any = entry.get("content")
            if isinstance(content, str):
                out.append(content)
    return out


def valid_from_numbers(value: Any, total: int) -> List[int]:
    """Keep only utterance numbers in 1..total, deduplicated in order."""
    if not isinstance(value, list):
        return []
    out: List[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if 1 <= item <= total and item not in out:
            out.append(item)
    return out


def _normalize_for_cover(text: Any) -> str:
    raw: str = str(text or "").lower()
    chars: List[str] = []
    for char in raw:
        if char.isspace():
            continue
        if unicodedata.category(char).startswith("P"):
            continue
        chars.append(char)
    return "".join(chars)


def _bigrams(text: str) -> set:
    return {text[index:index + 2] for index in range(len(text) - 1)}


def covered_by_todo(item: Any, todos: Any) -> bool:
    """True when at least half of the item's character bigrams appear in one todo."""
    normalized: str = _normalize_for_cover(item)
    if not normalized or not isinstance(todos, list):
        return False
    if len(normalized) < 2:
        for todo in todos:
            if normalized in _normalize_for_cover(todo):
                return True
        return False
    item_bigrams: set = _bigrams(normalized)
    if not item_bigrams:
        return False
    for todo in todos:
        todo_bigrams: set = _bigrams(_normalize_for_cover(todo))
        if len(item_bigrams & todo_bigrams) * 2 >= len(item_bigrams):
            return True
    return False


def clean_items(value: Any, total: int) -> List[Dict[str, Any]]:
    """Drop items with no valid cited utterance."""
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text: Any = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        numbers: List[int] = valid_from_numbers(item.get("from"), total)
        if not numbers:
            continue
        out.append({"text": text.strip(), "from": numbers})
    return out


def clean_nodes(value: Any, total: int) -> List[Dict[str, Any]]:
    """Drop leaf nodes with no valid citation; group nodes may stay."""
    if not isinstance(value, list):
        return []
    candidates: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        node_id: Any = item.get("id")
        parent: Any = item.get("parent")
        label: Any = item.get("label")
        if isinstance(node_id, bool) or not isinstance(node_id, int):
            continue
        if isinstance(parent, bool) or not isinstance(parent, int):
            continue
        if node_id in seen_ids or not isinstance(label, str) or not label.strip():
            continue
        seen_ids.add(node_id)
        kind: Any = item.get("kind")
        candidates.append({
            "id": node_id, "parent": parent, "label": label.strip(),
            "kind": kind if kind in _NODE_KINDS else "point",
            "from": valid_from_numbers(item.get("from"), total),
        })
    parent_ids: set = {node["parent"] for node in candidates}
    kept: List[Dict[str, Any]] = []
    for node in candidates:
        if node["from"] or node["id"] in parent_ids:
            kept.append(node)
    return kept


def _tree_node(node: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(node["id"]), "text": node["label"], "kind": node["kind"], "status": "", "children": []}


def build_clean_map(nodes: Any, goal: str) -> Dict[str, Any]:
    """Build a state.build_map-shaped tree; unknown parents and cycles go to root."""
    root: Dict[str, Any] = {"id": "goal", "text": str(goal), "kind": "goal", "status": "", "children": []}
    if not isinstance(nodes, list):
        return root
    created: Dict[int, Dict[str, Any]] = {}
    cleaned: List[Dict[str, Any]] = []
    for item in nodes:
        if len(created) >= 60:
            break
        if not isinstance(item, dict):
            continue
        node_id: Any = item.get("id")
        label: Any = item.get("label", item.get("text"))
        if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id in created:
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        kind: Any = item.get("kind")
        node: Dict[str, Any] = {
            "id": node_id, "parent": item.get("parent") if isinstance(item.get("parent"), int) else -1,
            "label": label.strip(), "kind": kind if kind in _NODE_KINDS else "point",
            "from": item.get("from") if isinstance(item.get("from"), list) else [],
        }
        created[node_id] = _tree_node(node)
        cleaned.append(node)
    parents: Dict[int, int] = {}
    for node in cleaned:
        node_id = int(node["id"])
        parent_id: Any = node["parent"]
        tree_node: Dict[str, Any] = created[node_id]
        target: Dict[str, Any] = root
        if isinstance(parent_id, int) and not isinstance(parent_id, bool) and parent_id in created and parent_id != node_id:
            candidate: int = parent_id
            creates_cycle: bool = False
            seen: set = set()
            cursor: int = candidate
            while cursor in parents and cursor not in seen:
                if cursor == node_id:
                    creates_cycle = True
                    break
                seen.add(cursor)
                cursor = parents[cursor]
            if cursor == node_id:
                creates_cycle = True
            if not creates_cycle:
                target = created[parent_id]
                parents[node_id] = parent_id
        if target is root:
            parents[node_id] = -1
        target["children"].append(tree_node)
    return root


def clean_poster_brief(value: Any) -> Dict[str, Any]:
    """Validate a poster brief from the final pass."""
    if not isinstance(value, dict):
        return {"title": "", "blocks": []}
    title: Any = value.get("title")
    blocks: List[Dict[str, Any]] = []
    raw_blocks: Any = value.get("blocks")
    if isinstance(raw_blocks, list):
        for block in raw_blocks[:4]:
            if not isinstance(block, dict):
                continue
            block_type: Any = block.get("type")
            heading: Any = block.get("heading")
            items: List[str] = _str_list(block.get("items"))[:7]
            blocks.append({
                "type": block_type if block_type in _POSTER_TYPES else "list",
                "heading": heading.strip() if isinstance(heading, str) else "",
                "items": items,
            })
    return {"title": title.strip() if isinstance(title, str) else "", "blocks": blocks}


def poster_brief_has_items(brief: Any) -> bool:
    """Whether the brief has at least one block with items."""
    if not isinstance(brief, dict):
        return False
    for block in brief.get("blocks", []):
        if isinstance(block, dict) and isinstance(block.get("items"), list) and block["items"]:
            return True
    return False


def _poster_slim(record: Dict[str, Any]) -> Dict[str, Any]:
    poster: Any = record.get("poster")
    if isinstance(poster, dict):
        version: Any = poster.get("version", 0)
        error: Any = poster.get("error", "")
        return {
            "status": str(poster.get("status", "none")),
            "version": version if isinstance(version, int) and not isinstance(version, bool) else 0,
            "error": error if isinstance(error, str) else "",
        }
    return {"status": "none", "version": 0, "error": ""}


def _map_lines(node: Dict[str, Any], depth: int, lines: List[str]) -> None:
    indent: str = "  " * depth
    kind: str = str(node.get("kind", ""))
    text: str = str(node.get("text", ""))
    suffix: str = ""
    if kind == "point":
        suffix = f"（{node.get('status', '')}）" if node.get("status") else ""
    elif kind == "task":
        suffix = f"（{node.get('status', '')}）" if node.get("status") else ""
    lines.append(f"{indent}- {text}{suffix}")
    for child in node.get("children", []):
        if isinstance(child, dict):
            _map_lines(child, depth + 1, lines)


def build_markdown(result: Dict[str, Any]) -> str:
    """Render Markdown with headings in the result language, omitting empty sections."""
    language: Any = result.get("language")
    lang: str = language if language in _LABELS else "zh"
    labels: Dict[str, str] = _LABELS[lang]
    title: Any = result.get("title")
    heading_title: str = title.strip() if isinstance(title, str) and title.strip() else message(lang, "default_title")
    lines: List[str] = [f"# {heading_title}"]
    summary_text: Any = result.get("summary")
    if isinstance(summary_text, str) and summary_text.strip():
        lines.extend(["", summary_text.strip()])
    lines.extend(["", f"{labels['goal']}{result.get('goal', '')}"])
    map_tree: Any = result.get("map")
    if isinstance(map_tree, dict) and map_tree.get("children"):
        lines.extend(["", f"## {labels['outline']}"])
        _map_lines(map_tree, 0, lines)
    sections: List[Tuple[str, Any]] = [
        (labels["decisions"], result.get("decisions", [])), (labels["todos"], result.get("todos", [])),
        (labels["parking_lot"], result.get("parking_lot", [])), (labels["open_questions"], result.get("open_questions", [])),
        (labels["contradictions"], result.get("contradictions", [])), (labels["unexpanded_points"], result.get("unexpanded_points", [])),
    ]
    for section_title, items in sections:
        if not items:
            continue
        lines.extend(["", f"## {section_title}"])
        lines.extend(f"- {item}" for item in items)
    tasks_list: Any = result.get("tasks", [])
    if isinstance(tasks_list, list) and tasks_list:
        lines.extend(["", f"## {labels['tasks']}"])
        for task in tasks_list:
            if isinstance(task, dict):
                lines.append(f"- {task.get('conclusion', '') or task.get('instruction', '')}")
                if task.get("detail"):
                    lines.append(str(task["detail"]))
                for source in task.get("sources", []):
                    if isinstance(source, dict):
                        lines.append(f"- {source.get('title', '')} {source.get('url', '')}")
    sketches: Any = result.get("sketches", [])
    if isinstance(sketches, list) and sketches:
        lines.extend(["", f"## {labels['sketches']}"])
        for sketch in sketches:
            if isinstance(sketch, dict):
                lines.append(f"- {sketch.get('description', '')}")
    return "\n".join(lines)


def _base_result(record: Dict[str, Any], degraded: bool) -> Dict[str, Any]:
    state: Dict[str, Any] = _state_of(record)
    utterances: List[str] = user_utterances(record)
    language: str = recent_language(record)
    return {
        "title": message(language, "default_title"), "goal": str(state.get("goal", "")),
        "summary": "", "language": language,
        "decisions": list(state.get("decisions", [])), "todos": list(state.get("todos", [])),
        "parking_lot": list(state.get("parking_lot", [])), "open_questions": list(state.get("open_questions", [])),
        "contradictions": list(state.get("contradictions", [])), "unexpanded_points": unexpanded_points(state),
        "tasks": copy.deepcopy(list(record.get("tasks", []))), "sketches": copy.deepcopy(list(record.get("sketches", []))),
        "map": build_map(state, record.get("tasks", [])),
        "evidence": {}, "transcript": utterances,
        "poster": _poster_slim(record),
        "markdown": "", "degraded": degraded,
    }


def _refresh_finished(session_id: str) -> Optional[Dict[str, Any]]:
    """Return a finished result without a model call if sketches are unchanged."""
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.get("status") != "finished" or not isinstance(record.get("result"), dict):
            return None
        result: Dict[str, Any] = copy.deepcopy(record["result"])
        sketches_now: List[Any] = list(record.get("sketches", []))
        if result.get("sketches", []) != sketches_now:
            return None
        result["tasks"] = copy.deepcopy(list(record.get("tasks", [])))
        result["sketches"] = copy.deepcopy(sketches_now)
        if not isinstance(result.get("map"), dict) or not result["map"].get("children"):
            result["map"] = build_map(_state_of(record), record.get("tasks", []))
        result.setdefault("summary", "")
        if result.get("language") not in ("zh", "en"):
            result["language"] = recent_language(record)
        result.setdefault("evidence", {})
        result["transcript"] = user_utterances(record)
        result["poster"] = _poster_slim(record)
        result["markdown"] = build_markdown(result)
        if result != record["result"]:
            record["result"] = result
            store.save_session(record)
        return result


def _call_final_once(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    state: Dict[str, Any] = _state_of(snapshot)
    utterances: List[str] = user_utterances(snapshot)
    content: str = build_final_user_content(
        str(state.get("goal", "")), utterances, state,
        snapshot.get("tasks", []), snapshot.get("sketches", []),
    )
    client: Any = create_client()
    resp: Any = client.responses.create(
        model=DEFAULT_MODEL,
        input=[{"role": "system", "content": FINAL_SYSTEM_PROMPT}, {"role": "user", "content": content}],
        max_output_tokens=12000, reasoning={"effort": "low"},
        text={"format": {"type": "json_schema", "name": "blackout_final", "schema": FINAL_SCHEMA, "strict": True}},
    )
    status: Any = getattr(resp, "status", None)
    if isinstance(status, str) and status != "completed":
        raise RuntimeError("incomplete")
    raw: Any = getattr(resp, "output_text", "")
    if not isinstance(raw, str) or not raw.strip():
        raise _ParseFailure("empty final output")
    try:
        parsed: Any = json.loads(raw)
    except Exception as exc:
        raise _ParseFailure("invalid final json") from exc
    if not isinstance(parsed, dict):
        raise _ParseFailure("final output is not an object")
    return parsed


def _call_final(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """One final-pass call, with one retry on parse failure."""
    try:
        return _call_final_once(snapshot)
    except _ParseFailure:
        logger.warning("final pass parse failed; retrying once")
        return _call_final_once(snapshot)


def _evidence(cleaned: Dict[str, List[Dict[str, Any]]], utterances: List[str]) -> Dict[str, List[str]]:
    evidence: Dict[str, List[str]] = {}
    for items in cleaned.values():
        for item in items:
            texts: List[str] = []
            for number in item["from"]:
                if 1 <= number <= len(utterances):
                    texts.append(utterances[number - 1])
            evidence[str(item["text"])] = texts
    return evidence


def _merge_model(snapshot: Dict[str, Any], parsed: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    state: Dict[str, Any] = _state_of(snapshot)
    utterances: List[str] = user_utterances(snapshot)
    total: int = len(utterances)
    result: Dict[str, Any] = _base_result(snapshot, False)
    title: Any = parsed.get("title")
    if isinstance(title, str) and title.strip():
        result["title"] = title.strip()
    summary_text: Any = parsed.get("summary")
    if isinstance(summary_text, str):
        result["summary"] = summary_text.strip()
    language: Any = parsed.get("language")
    result["language"] = language if language in ("zh", "en") else "zh"
    cleaned: Dict[str, List[Dict[str, Any]]] = {}
    for field in ("decisions", "todos", "open_questions", "contradictions", "parking_lot"):
        cleaned[field] = clean_items(parsed.get(field), total)
    fallback_keys: Dict[str, str] = {"decisions": "decisions", "todos": "todos", "open_questions": "open_questions"}
    for field, state_key in fallback_keys.items():
        texts: List[str] = [str(item["text"]) for item in cleaned[field]]
        state_list: List[str] = list(state.get(state_key, []))
        if not texts and state_list:
            result[field] = state_list
        else:
            result[field] = texts
    result["contradictions"] = [str(item["text"]) for item in cleaned["contradictions"]]
    parking_texts: List[str] = [str(item["text"]) for item in cleaned["parking_lot"]]
    if parking_texts:
        result["parking_lot"] = parking_texts
    else:
        kept_parking: List[str] = []
        for parking_item in state.get("parking_lot", []):
            if isinstance(parking_item, str) and parking_item and not covered_by_todo(parking_item, result["todos"]):
                kept_parking.append(parking_item)
        result["parking_lot"] = kept_parking
    result["unexpanded_points"] = []
    result["evidence"] = _evidence(cleaned, utterances)
    nodes: List[Dict[str, Any]] = clean_nodes(parsed.get("nodes"), total)
    clean_map: Dict[str, Any] = build_clean_map(nodes, str(state.get("goal", "")))
    if clean_map.get("children"):
        result["map"] = clean_map
    else:
        result["map"] = build_map(state, snapshot.get("tasks", []))
    brief: Dict[str, Any] = clean_poster_brief(parsed.get("poster"))
    return result, brief


def _save_result(session_id: str, result: Dict[str, Any], degraded: bool) -> Dict[str, Any]:
    with store.get_lock(session_id):
        record: Optional[Dict[str, Any]] = store.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        state: Dict[str, Any] = _state_of(record)
        if degraded:
            result["parking_lot"] = list(state.get("parking_lot", []))
            result["decisions"] = list(state.get("decisions", []))
            result["todos"] = list(state.get("todos", []))
            result["open_questions"] = list(state.get("open_questions", []))
            result["contradictions"] = list(state.get("contradictions", []))
            result["summary"] = ""
            result["language"] = recent_language(record)
            if not isinstance(result.get("title"), str) or not result["title"].strip():
                result["title"] = message(result["language"], "default_title")
            result["map"] = build_map(state, record.get("tasks", []))
            result["unexpanded_points"] = unexpanded_points(state)
        else:
            result["unexpanded_points"] = []
            if not isinstance(result.get("parking_lot"), list):
                result["parking_lot"] = []
        if not degraded and (not isinstance(result.get("map"), dict) or not result["map"].get("children")):
            result["map"] = build_map(state, record.get("tasks", []))
        result["tasks"] = copy.deepcopy(list(record.get("tasks", [])))
        result["sketches"] = copy.deepcopy(list(record.get("sketches", [])))
        result["goal"] = str(state.get("goal", ""))
        result["degraded"] = degraded
        result["transcript"] = user_utterances(record)
        result.setdefault("summary", "")
        result.setdefault("language", "zh")
        result.setdefault("evidence", {})
        result["poster"] = _poster_slim(record)
        result["markdown"] = build_markdown(result)
        record["result"] = result
        record["status"] = "finished"
        store.save_session(record)
        return result


def _finish_empty(session_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = _base_result(snapshot, False)
    return _save_result(session_id, result, False)


def _poster_not_started(record: Optional[Dict[str, Any]]) -> bool:
    if record is None:
        return False
    poster: Any = record.get("poster")
    if not isinstance(poster, dict):
        return True
    attempts: Any = poster.get("attempts", 0)
    if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts > 0:
        return False
    return str(poster.get("status", "none")) in ("", "none")


def _maybe_start_poster(session_id: str, result: Dict[str, Any], brief: Dict[str, Any]) -> None:
    if result.get("degraded"):
        return
    if not poster_brief_has_items(brief):
        return
    current: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    if not _poster_not_started(current):
        return
    language: str = str(result.get("language", "zh"))
    from app import poster as poster_mod
    started: bool = poster_mod.start_poster(session_id, brief, language)
    if started:
        refreshed: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
        if refreshed is not None and isinstance(refreshed.get("result"), dict):
            result["poster"] = _poster_slim(refreshed)


def _maybe_start_draft(session_id: str, saved: Dict[str, Any], parsed: Dict[str, Any]) -> None:
    """Start the automatic first draft, if the final pass asked for one."""
    try:
        if not isinstance(saved, dict) or saved.get("degraded"):
            return
        if not isinstance(parsed, dict):
            return
        transcript: Any = saved.get("transcript")
        if not isinstance(transcript, list) or not transcript:
            return
        first_draft: Any = parsed.get("first_draft")
        if not isinstance(first_draft, dict):
            return
        instruction: Any = first_draft.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            return
        if not valid_from_numbers(first_draft.get("from"), len(transcript)):
            return
        from app import tasks as tasks_mod
        task: Optional[Dict[str, Any]] = tasks_mod.start_task(session_id, "draft", instruction.strip(), "", auto=True)
        if task is None:
            return
        refreshed: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
        if refreshed is not None:
            saved["tasks"] = copy.deepcopy(list(refreshed.get("tasks", [])))
            saved["markdown"] = build_markdown(saved)
    except Exception:
        logger.exception("automatic first draft failed to start")


def finish(session_id: str) -> Dict[str, Any]:
    """Snapshot, call model unlocked, re-lock and save; failures degrade."""
    refreshed: Optional[Dict[str, Any]] = _refresh_finished(session_id)
    if refreshed is not None:
        return refreshed
    snapshot: Optional[Dict[str, Any]] = store.get_session_copy(session_id)
    if snapshot is None:
        raise KeyError(session_id)
    if not snapshot.get("history") and not snapshot.get("sketches"):
        return _finish_empty(session_id, snapshot)
    try:
        parsed: Dict[str, Any] = _call_final(snapshot)
        result, brief = _merge_model(snapshot, parsed)
        saved: Dict[str, Any] = _save_result(session_id, result, False)
    except Exception:
        logger.exception("final pass failed; using stored state")
        return _save_result(session_id, _base_result(snapshot, True), True)
    _maybe_start_poster(session_id, saved, brief)
    _maybe_start_draft(session_id, saved, parsed)
    return saved
