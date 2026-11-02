"""Pure thinking-state functions. No I/O."""
import copy
import difflib
import hashlib
import re
from typing import Any, Dict, List, Tuple

END_PHRASES: frozenset = frozenset([
    "结束", "结束吧", "结束了", "停止", "停", "我说完了", "说完了", "就到这", "就到这里", "到这吧", "不说了", "先这样",
    "stop", "end", "finish", "done", "imdone", "thatsall", "thatsit", "weredone", "letsstop", "letsend", "wrapup",
])
CONFIRM_PHRASES: frozenset = frozenset([
    "对", "是", "好", "好的", "嗯", "可以", "是的",
    "yes", "yeah", "yep", "ok", "okay", "sure", "right",
])
_FILLERS: Tuple[str, ...] = ("好了", "好的", "那就", "OK", "ok", "好", "那", "行", "嗯", "可以")
_EN_FILLERS: frozenset = frozenset(["ok", "okay", "alright", "so", "yes"])
_EN_FILLER_RE: re.Pattern = re.compile(r"^(okay|ok|alright|so|yes)(?:\s+|$)", re.IGNORECASE)
_CLAUSE_SPLIT: re.Pattern = re.compile(r"[，。！？；：、,.!?;:\n\r]+")
_CJK_RE: re.Pattern = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_PUNCT: str = "，。！？；：、．·…—–-.,!?;:\"'()[]{}《》〈〉「」『』【】（） \n\t\r"
LIST_LIMIT: int = 200


def clean_text(text: str) -> str:
    """Remove punctuation and spaces."""
    return "".join(ch for ch in str(text).strip() if ch not in _PUNCT)


def truncate_speech(text: str) -> str:
    """Truncate spoken text at a real boundary, never inside a number or word.

    The limit is 60 characters for text containing any CJK character and
    160 otherwise. Beyond the limit, cut at the last sentence end within
    the limit, else the last clause mark, else the last space, else hard.
    A `.` or `,` with a digit immediately on both sides (0.18, 1,000) is
    never a boundary, and neither is a `.` inside a word (example.com).
    """
    original: str = str(text)
    limit: int = 60 if _CJK_RE.search(original) else 160
    if len(original) <= limit:
        return original
    window: str = original[:limit]

    def is_boundary(index: int) -> bool:
        char: str = window[index]
        if char not in ".,":
            return True
        previous: str = original[index - 1] if index > 0 else ""
        following: str = original[index + 1] if index + 1 < len(original) else ""
        if previous.isdigit() and following.isdigit():
            return False
        if char == "." and previous and following:
            if (previous.isalnum() or previous in "_-") and (following.isalnum() or following in "_-"):
                return False
        return True

    for marks in ("。！？.!?", "；，、;,"):
        for index in range(len(window) - 1, -1, -1):
            if window[index] in marks and is_boundary(index):
                return window[: index + 1]
    space_index: int = -1
    for index in range(len(window) - 1, -1, -1):
        if window[index].isspace():
            space_index = index
            break
    if space_index > 0:
        trimmed: str = window[:space_index].rstrip()
        if trimmed:
            return trimmed
    return window


def speech_language(text: str) -> str:
    """Return zh if the text has any CJK character, otherwise en."""
    return "zh" if _CJK_RE.search(str(text or "")) else "en"


def recent_language(record: Any) -> str:
    """Language of the most recent user utterance, else the record language, else zh."""
    if not isinstance(record, dict):
        return "zh"
    history: Any = record.get("history", [])
    if isinstance(history, list):
        for entry in reversed(history):
            if not isinstance(entry, dict) or entry.get("role") != "user":
                continue
            content: Any = entry.get("content")
            if isinstance(content, str) and content.strip():
                return speech_language(content)
    language: Any = record.get("language", "zh")
    return language if language in ("zh", "en") else "zh"


def _strip_fillers(clause: str) -> str:
    text: str = clause.strip()
    changed: bool = True
    while changed:
        changed = False
        for filler in _FILLERS:
            if text.startswith(filler):
                rest: str = text[len(filler):].lstrip(" ，,。")
                if rest:
                    text = rest
                    changed = True
                break
        if changed:
            continue
        match: Any = _EN_FILLER_RE.match(text)
        if match is not None:
            rest_en: str = text[match.end():].lstrip(" ,，")
            if rest_en:
                text = rest_en
                changed = True
    return text


def _is_filler_only(clause: str) -> bool:
    cleaned: str = clean_text(clause)
    if cleaned in {"好", "好了", "好的", "那", "那就", "行", "嗯", "可以", "OK", "ok"}:
        return True
    return cleaned.lower() in _EN_FILLERS


def split_end(text: str) -> Tuple[str, bool]:
    """Split a trailing end phrase from real content.

    Ends only when the last clause, after removing leading fillers,
    is exactly an end phrase. Content before it (minus filler-only
    clauses) is returned; a non-ending utterance returns (text, False).
    """
    raw: str = str(text).strip()
    clauses: List[str] = [c.strip() for c in _CLAUSE_SPLIT.split(raw) if c.strip()]
    if not clauses:
        return "", False
    last: str = _strip_fillers(clauses[-1])
    if clean_text(last).lower() not in END_PHRASES:
        return raw, False
    before: List[str] = clauses[:-1]
    while before and _is_filler_only(before[-1]):
        before.pop()
    separator: str = "，" if speech_language(raw) == "zh" else ", "
    return separator.join(before), True


def is_explicit_end(text: str) -> bool:
    """Exact end-phrase match on a whole utterance only."""
    return clean_text(text).lower() in END_PHRASES


def is_confirm(text: str) -> bool:
    """Exact confirmation match."""
    return clean_text(text).lower() in CONFIRM_PHRASES


def is_echo(heard: str, spoken: str) -> bool:
    """True if `heard` is (mostly) the AI's own spoken text heard back."""
    heard_clean: str = clean_text(heard)
    if len(heard_clean) < 2:
        return True
    spoken_clean: str = clean_text(spoken)
    if not spoken_clean:
        return False
    matcher: difflib.SequenceMatcher = difflib.SequenceMatcher(None, heard_clean, spoken_clean)
    matched: int = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(heard_clean) >= 0.6


def new_state(goal: str) -> Dict[str, Any]:
    """Create a fresh state."""
    return {"goal": goal, "main_points": [], "parking_lot": [], "decisions": [], "todos": [], "open_questions": [], "contradictions": [], "links": {}}


def _item_text_under(item: Any) -> Tuple[str, str]:
    if isinstance(item, dict):
        text: Any = item.get("text", item.get("point", ""))
        under: Any = item.get("under", "")
        return (text if isinstance(text, str) else "", under if isinstance(under, str) else "")
    if isinstance(item, str):
        return item, ""
    return "", ""


def _append_unique(target: List[str], values: Any, links: Dict[str, str]) -> None:
    if not isinstance(values, list):
        return
    for value in values:
        text, under = _item_text_under(value)
        if text.strip() and text not in target:
            target.append(text)
        if text.strip() and under:
            links[text] = under
        if len(target) >= LIST_LIMIT:
            break


def _apply_points(state: Dict[str, Any], additions: Dict[str, Any]) -> None:
    points: List[Dict[str, str]] = state["main_points"]
    raw: Any = additions.get("add_points", [])
    if isinstance(raw, list):
        existing: List[str] = [str(p.get("point", "")) for p in points if isinstance(p, dict)]
        for item in raw:
            if len(points) >= LIST_LIMIT:
                break
            if isinstance(item, dict):
                point: Any = item.get("point", "")
                status: Any = item.get("status", "未展开")
                under: Any = item.get("under", "")
            else:
                point, status, under = item, "未展开", ""
            if not isinstance(point, str) or not point.strip():
                continue
            if point in existing:
                continue
            points.append({"point": point, "status": status if status in ("已展开", "未展开") else "未展开", "under": under if isinstance(under, str) else ""})
            existing.append(point)
    expand: Any = additions.get("expand_points", [])
    if isinstance(expand, list):
        wanted: set = {x for x in expand if isinstance(x, str)}
        for point_obj in points:
            if isinstance(point_obj, dict) and point_obj.get("point") in wanted:
                point_obj["status"] = "已展开"


def apply_additions(state: Dict[str, Any], additions: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new state with model additions applied (old and new forms)."""
    result: Dict[str, Any] = copy.deepcopy(dict(state))
    for key, default in new_state(str(result.get("goal", ""))).items():
        result.setdefault(key, copy.deepcopy(default))
    if not isinstance(result.get("links"), dict):
        result["links"] = {}
    for point_obj in result.get("main_points", []):
        if isinstance(point_obj, dict):
            point_obj.setdefault("under", "")
    _apply_points(result, additions)
    links: Dict[str, str] = result["links"]
    _append_unique(result["parking_lot"], additions.get("add_parking", additions.get("add_parking_lot", [])), {})
    _append_unique(result["decisions"], additions.get("add_decisions", []), links)
    _append_unique(result["todos"], additions.get("add_todos", []), links)
    _append_unique(result["open_questions"], additions.get("add_questions", additions.get("add_open_questions", [])), links)
    _append_unique(result["contradictions"], additions.get("add_contradictions", []), links)
    resolve: Any = additions.get("resolve_questions", [])
    if isinstance(resolve, list):
        wanted: set = {x for x in resolve if isinstance(x, str)}
        result["open_questions"] = [q for q in result["open_questions"] if q not in wanted]
        for gone in wanted:
            links.pop(gone, None)
    for key in ("main_points", "parking_lot", "decisions", "todos", "open_questions", "contradictions"):
        result[key] = result[key][:LIST_LIMIT]
    return result


def unexpanded_points(state: Dict[str, Any]) -> List[str]:
    """Names of unexpanded points."""
    out: List[str] = []
    points: Any = state.get("main_points", [])
    if isinstance(points, list):
        for item in points:
            if isinstance(item, dict) and item.get("status") == "未展开" and isinstance(item.get("point"), str):
                out.append(item["point"])
    return out


def _node_id(kind: str, text: str) -> str:
    return hashlib.sha256(f"{kind}\x00{text}".encode("utf-8")).hexdigest()[:16]


def _make_node(kind: str, text: str, status: str = "") -> Dict[str, Any]:
    return {"id": _node_id(kind, text), "text": text, "kind": kind, "status": status, "children": []}


def build_map(state: Dict[str, Any], tasks: Any = None) -> Dict[str, Any]:
    """Deterministic tree. Nothing recorded is lost; cycles go to root."""
    safe_state: Dict[str, Any] = state if isinstance(state, dict) else {}
    root: Dict[str, Any] = _make_node("goal", str(safe_state.get("goal", "")))
    links: Dict[str, str] = safe_state.get("links", {}) if isinstance(safe_state.get("links"), dict) else {}
    point_nodes: Dict[str, Dict[str, Any]] = {}
    raw_points: List[Dict[str, Any]] = []
    points_in: Any = safe_state.get("main_points", [])
    if isinstance(points_in, list):
        for item in points_in:
            if isinstance(item, dict) and isinstance(item.get("point"), str) and item["point"]:
                raw_points.append(item)
                if item["point"] not in point_nodes:
                    point_nodes[item["point"]] = _make_node("point", item["point"], str(item.get("status", "未展开")))
    parents: Dict[str, str] = {}

    def is_descendant(candidate: str, ancestor_text: str) -> bool:
        seen: set = set()
        current: str = candidate
        while current and current not in seen:
            if current == ancestor_text:
                return True
            seen.add(current)
            current = parents.get(current, "")
        return False

    for item in raw_points:
        text: str = item["point"]
        node: Dict[str, Any] = point_nodes[text]
        if node in root["children"]:
            root["children"].remove(node)
        under: Any = item.get("under", "")
        under_text: str = under if isinstance(under, str) else ""
        parent: Any = None
        if under_text and under_text != text and under_text in point_nodes and not is_descendant(under_text, text):
            parent = point_nodes[under_text]
            parents[text] = under_text
        else:
            parents[text] = ""
        (parent if parent is not None else root)["children"].append(node)
    categories: List[Tuple[str, str]] = [("decisions", "decision"), ("todos", "todo"), ("open_questions", "question"), ("contradictions", "contradiction")]
    for key, kind in categories:
        values: Any = safe_state.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            text, stored_under = _item_text_under(value)
            if not text:
                continue
            node = _make_node(kind, text)
            under_text: str = stored_under or str(links.get(text, ""))
            parent = point_nodes.get(under_text) if under_text in point_nodes else root
            parent["children"].append(node)
    task_list: Any = tasks if isinstance(tasks, list) else []
    for task in task_list:
        if not isinstance(task, dict):
            continue
        status: str = str(task.get("status", "running"))
        if status == "done" and isinstance(task.get("conclusion"), str) and task["conclusion"]:
            text = task["conclusion"]
        elif isinstance(task.get("instruction"), str) and task["instruction"]:
            text = task["instruction"]
        elif isinstance(task.get("conclusion"), str):
            text = task["conclusion"]
        else:
            continue
        node = _make_node("task", text, status)
        under_text = task.get("under", "") if isinstance(task.get("under", ""), str) else ""
        parent = point_nodes.get(str(under_text)) if str(under_text) in point_nodes else root
        parent["children"].append(node)
    return root
