"""Pure state tests."""
import copy
from typing import Any, Dict, List

from app.state import (
    apply_additions,
    build_map,
    clean_text,
    is_confirm,
    is_echo,
    is_explicit_end,
    new_state,
    recent_language,
    speech_language,
    split_end,
    truncate_speech,
    unexpanded_points,
)


def test_additions_append_without_losing() -> None:
    state: Dict[str, Any] = new_state("目标")
    state["decisions"] = ["已有决定"]
    out: Dict[str, Any] = apply_additions(state, {"add_decisions": ["新决定"], "add_points": [{"point": "要点", "status": "未展开"}]})
    assert out["decisions"] == ["已有决定", "新决定"]
    assert out["main_points"] == [{"point": "要点", "status": "未展开", "under": ""}]


def test_exact_duplicates_dropped() -> None:
    out: Dict[str, Any] = apply_additions(new_state("g"), {"add_todos": ["做", "做"], "add_points": [{"point": "p", "status": "未展开"}, {"point": "p", "status": "已展开"}]})
    assert out["todos"] == ["做"]
    assert len(out["main_points"]) == 1


def test_expand_and_resolve_only_matching() -> None:
    state: Dict[str, Any] = new_state("g")
    state["main_points"] = [{"point": "甲", "status": "未展开"}, {"point": "乙", "status": "未展开"}]
    state["open_questions"] = ["问题一", "问题二"]
    out: Dict[str, Any] = apply_additions(state, {"expand_points": ["甲", "不存在"], "resolve_questions": ["问题一", "没有"]})
    assert out["main_points"][0]["status"] == "已展开"
    assert out["main_points"][1]["status"] == "未展开"
    assert out["open_questions"] == ["问题二"]


def test_caps_and_no_mutation() -> None:
    state: Dict[str, Any] = new_state("g")
    before: Dict[str, Any] = copy.deepcopy(state)
    out: Dict[str, Any] = apply_additions(state, {"add_todos": [str(i) for i in range(250)]})
    assert len(out["todos"]) == 200
    assert state == before


def test_end_and_confirm_exact_only() -> None:
    for phrase in ["结束", "结束吧", "结束了", "停止", "停", "我说完了", "说完了", "就到这", "就到这里", "到这吧", "不说了", "先这样"]:
        assert is_explicit_end(phrase) is True
    assert is_explicit_end("结束。") is True
    assert is_explicit_end("怎么结束项目") is False
    assert is_explicit_end("我想讨论怎么结束") is False
    assert is_explicit_end("") is False
    for phrase in ["对", "是", "好", "好的", "嗯", "可以", "是的"]:
        assert is_confirm(phrase) is True
    assert is_confirm("好的。") is True
    assert is_confirm("好吧") is False
    assert clean_text(" 结 束 ， ") == "结束"


def test_english_end_and_confirm_exact_only() -> None:
    for phrase in ["stop", "end", "finish", "done", "I'm done", "that's all", "that's it", "we're done", "let's stop", "let's end", "wrap up"]:
        assert is_explicit_end(phrase) is True
    assert is_explicit_end("Stop.") is True
    assert is_explicit_end("I'm done.") is True
    # An end word used as a topic, or inside a longer sentence, is not an end.
    assert is_explicit_end("stop using the old design") is False
    assert is_explicit_end("That part is done") is False
    assert is_explicit_end("I want to stop") is False
    for phrase in ["yes", "yeah", "yep", "ok", "okay", "sure", "right"]:
        assert is_confirm(phrase) is True
    assert is_confirm("OK.") is True
    assert is_confirm("yes please continue") is False


def test_all_lists_capped_and_alias_keys() -> None:
    out: Dict[str, Any] = apply_additions(new_state("g"), {"add_parking": [str(i) for i in range(250)], "add_questions": ["q"], "add_contradictions": ["c"], "add_points": [{"point": str(i), "status": "未展开"} for i in range(250)]})
    assert len(out["parking_lot"]) == 200
    assert len(out["main_points"]) == 200
    assert out["open_questions"] == ["q"]
    assert unexpanded_points(out)[0] == "0"


def test_invalid_additions_ignored() -> None:
    out: Dict[str, Any] = apply_additions(new_state("g"), {"add_todos": "notalist", "add_decisions": [123, "", "  ", "ok"], "add_points": [{"point": ""}, {"point": "p", "status": "bogus"}]})
    assert out["todos"] == []
    assert out["decisions"] == ["ok"]
    assert out["main_points"] == [{"point": "p", "status": "未展开", "under": ""}]


# --- split_end ---------------------------------------------------------

def test_split_end_filler_only_prefix_ends_with_no_content() -> None:
    assert split_end("好，结束。") == ("", True)
    assert split_end("好了结束") == ("", True)


def test_split_end_keeps_content_before_final_clause() -> None:
    content, ends = split_end("首先我觉得有个问题，好，结束")
    assert ends is True
    assert content == "首先我觉得有个问题"


def test_split_end_does_not_end_on_end_as_topic() -> None:
    assert split_end("我想讨论怎么结束这个项目") == ("我想讨论怎么结束这个项目", False)
    assert split_end("结束这个项目") == ("结束这个项目", False)


def test_split_end_similar_phrase_is_not_an_end_phrase() -> None:
    # 到这里吧 is not in the end-phrase list (就到这里 / 到这吧 are).
    assert split_end("那就到这里吧") == ("那就到这里吧", False)


def test_split_end_english_phrases() -> None:
    assert split_end("OK, stop.") == ("", True)
    assert split_end("Stop.") == ("", True)
    assert split_end("I'm done.") == ("", True)
    assert split_end("first idea, ok, stop") == ("first idea", True)


def test_split_end_english_end_words_as_topics_do_not_end() -> None:
    assert split_end("That part is done.") == ("That part is done.", False)
    text: str = "I want to stop using the old design."
    assert split_end(text) == (text, False)


# --- speech_language / recent_language -----------------------------------

def test_speech_language() -> None:
    assert speech_language("想清楚比赛方案") == "zh"
    assert speech_language("Plan the demo") == "en"
    assert speech_language("demo 的方案") == "zh"
    assert speech_language("") == "en"


def test_recent_language() -> None:
    record: Dict[str, Any] = {
        "language": "zh",
        "history": [
            {"role": "user", "content": "先说中文", "at": "x"},
            {"role": "assistant", "content": "好的", "at": "x"},
            {"role": "user", "content": "Now English", "at": "x"},
        ],
    }
    assert recent_language(record) == "en"
    assert recent_language({"language": "en", "history": []}) == "en"
    assert recent_language({"language": "fr", "history": []}) == "zh"
    assert recent_language({}) == "zh"
    assert recent_language("nope") == "zh"


# --- apply_additions: object form, plain strings, links ----------------

def test_apply_additions_object_form_records_links() -> None:
    out: Dict[str, Any] = apply_additions(
        new_state("g"),
        {
            "add_points": [{"point": "主点", "status": "未展开", "under": ""}],
            "add_decisions": [{"text": "决定一", "under": "主点"}],
            "add_todos": [{"text": "待办一", "under": "主点"}],
            "add_questions": [{"text": "问题一", "under": "主点"}],
            "add_contradictions": [{"text": "矛盾一", "under": "主点"}],
        },
    )
    assert out["decisions"] == ["决定一"]
    assert out["todos"] == ["待办一"]
    assert out["open_questions"] == ["问题一"]
    assert out["contradictions"] == ["矛盾一"]
    assert out["links"]["决定一"] == "主点"
    assert out["links"]["待办一"] == "主点"
    assert out["links"]["问题一"] == "主点"
    assert out["links"]["矛盾一"] == "主点"


def test_apply_additions_plain_strings_still_work() -> None:
    out: Dict[str, Any] = apply_additions(
        new_state("g"),
        {
            "add_decisions": ["旧式决定"],
            "add_todos": ["旧式待办"],
            "add_questions": ["旧式问题"],
            "add_contradictions": ["旧式矛盾"],
            "add_parking": ["旧式停车"],
        },
    )
    assert out["decisions"] == ["旧式决定"]
    assert out["todos"] == ["旧式待办"]
    assert out["open_questions"] == ["旧式问题"]
    assert out["contradictions"] == ["旧式矛盾"]
    assert out["parking_lot"] == ["旧式停车"]
    # Plain strings carry no `under`, so they record no link.
    assert "旧式决定" not in out["links"]
    assert "旧式待办" not in out["links"]


def test_apply_additions_mixed_forms_and_point_under() -> None:
    out: Dict[str, Any] = apply_additions(
        new_state("g"),
        {
            "add_points": [
                {"point": "主点", "status": "已展开", "under": ""},
                {"point": "子点", "status": "未展开", "under": "主点"},
                "纯文字列点",
            ],
            "add_decisions": ["纯决定", {"text": "对象决定", "under": "主点"}],
        },
    )
    by_point: Dict[str, Any] = {p["point"]: p for p in out["main_points"]}
    assert by_point["子点"]["under"] == "主点"
    assert by_point["纯文字列点"]["under"] == ""
    assert out["decisions"] == ["纯决定", "对象决定"]
    assert out["links"]["对象决定"] == "主点"
    assert "纯决定" not in out["links"]


# --- build_map ---------------------------------------------------------

def _walk(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [node]
    for child in node.get("children", []):
        out.extend(_walk(child))
    return out


def _children_by_text(node: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(child.get("text", "")): child for child in node.get("children", [])}


def _state_with_nesting() -> Dict[str, Any]:
    state: Dict[str, Any] = apply_additions(
        new_state("想清楚方案"),
        {
            "add_points": [
                {"point": "主点", "status": "已展开", "under": ""},
                {"point": "子点", "status": "未展开", "under": "主点"},
                {"point": "游离点", "status": "未展开", "under": "不存在的点"},
            ],
            "add_decisions": [{"text": "决定一", "under": "主点"}],
            "add_todos": [{"text": "待办一", "under": "主点"}],
            "add_questions": [{"text": "问题一", "under": "主点"}],
            "add_contradictions": [{"text": "矛盾一", "under": "主点"}],
            "add_parking": ["火锅"],
        },
    )
    return state


def test_build_map_root_is_goal_and_points_nest() -> None:
    tree: Dict[str, Any] = build_map(_state_with_nesting())
    assert tree["kind"] == "goal"
    assert tree["text"] == "想清楚方案"
    root_children: Dict[str, Dict[str, Any]] = _children_by_text(tree)
    assert "主点" in root_children
    # A point whose `under` names no known point goes to the root.
    assert "游离点" in root_children
    main_children: Dict[str, Dict[str, Any]] = _children_by_text(root_children["主点"])
    # Sub-points nest under their point and precede other child kinds.
    assert "子点" in main_children
    assert main_children["子点"]["kind"] == "point"
    assert main_children["子点"]["status"] == "未展开"
    texts: List[str] = [str(n.get("text", "")) for n in _walk(tree)]
    assert texts.count("子点") == 1
    assert texts.count("游离点") == 1


def test_build_map_categories_under_their_point() -> None:
    tree: Dict[str, Any] = build_map(_state_with_nesting())
    main: Dict[str, Any] = _children_by_text(tree)["主点"]
    children: Dict[str, Dict[str, Any]] = _children_by_text(main)
    assert children["决定一"]["kind"] == "decision"
    assert children["待办一"]["kind"] == "todo"
    assert children["问题一"]["kind"] == "question"
    assert children["矛盾一"]["kind"] == "contradiction"
    # None of them leaked to the root.
    root_texts: List[str] = [str(c.get("text", "")) for c in tree["children"]]
    for text in ("决定一", "待办一", "问题一", "矛盾一"):
        assert text not in root_texts


def test_build_map_unknown_under_goes_to_root() -> None:
    state: Dict[str, Any] = apply_additions(
        new_state("g"),
        {
            "add_points": [{"point": "主点", "status": "未展开", "under": ""}],
            "add_decisions": [{"text": "无归属决定", "under": "查无此点"}],
            "add_todos": [{"text": "无归属待办", "under": "查无此点"}],
        },
    )
    tree: Dict[str, Any] = build_map(state)
    root_children: Dict[str, Dict[str, Any]] = _children_by_text(tree)
    assert root_children["无归属决定"]["kind"] == "decision"
    assert root_children["无归属待办"]["kind"] == "todo"


def test_build_map_cycle_neither_hangs_nor_loses_a_node() -> None:
    state: Dict[str, Any] = new_state("g")
    state["main_points"] = [
        {"point": "甲", "status": "未展开", "under": "乙"},
        {"point": "乙", "status": "未展开", "under": "甲"},
    ]
    tree: Dict[str, Any] = build_map(state)
    texts: List[str] = [str(n.get("text", "")) for n in _walk(tree) if n.get("kind") == "point"]
    assert sorted(texts) == ["乙", "甲"]


def test_build_map_ids_are_stable_across_calls() -> None:
    state: Dict[str, Any] = _state_with_nesting()
    first: Dict[str, Any] = build_map(state)
    second: Dict[str, Any] = build_map(copy.deepcopy(state))
    assert first == second
    ids_first: List[str] = [str(n.get("id", "")) for n in _walk(first)]
    ids_second: List[str] = [str(n.get("id", "")) for n in _walk(second)]
    assert ids_first == ids_second
    assert all(ids_first)


def test_build_map_old_format_plain_strings_without_under() -> None:
    # A session saved before `under`/`links` existed: plain strings in the
    # lists and point dicts with no `under` key at all.
    old_state: Dict[str, Any] = {
        "goal": "旧目标",
        "main_points": [
            {"point": "旧要点", "status": "未展开"},
            {"point": "旧要点二", "status": "已展开"},
        ],
        "parking_lot": ["旧停车"],
        "decisions": ["旧决定"],
        "todos": ["旧待办"],
        "open_questions": ["旧问题"],
        "contradictions": ["旧矛盾"],
    }
    tree: Dict[str, Any] = build_map(old_state)
    assert tree["text"] == "旧目标"
    nodes: List[Dict[str, Any]] = _walk(tree)
    texts: List[str] = [str(n.get("text", "")) for n in nodes]
    for text in ("旧要点", "旧要点二", "旧决定", "旧待办", "旧问题", "旧矛盾"):
        assert text in texts
    kinds: Dict[str, str] = {str(n.get("text", "")): str(n.get("kind", "")) for n in nodes}
    assert kinds["旧决定"] == "decision"
    assert kinds["旧待办"] == "todo"
    assert kinds["旧问题"] == "question"
    assert kinds["旧矛盾"] == "contradiction"


def test_build_map_tasks_appear_with_their_status() -> None:
    state: Dict[str, Any] = _state_with_nesting()
    tasks: List[Dict[str, Any]] = [
        {"id": "t1", "kind": "search", "instruction": "查价格", "status": "running", "conclusion": "", "detail": "", "sources": [], "created_at": "x", "under": "主点"},
        {"id": "t2", "kind": "search", "instruction": "查别的", "status": "done", "conclusion": "结论一", "detail": "", "sources": [], "created_at": "x"},
        {"id": "t3", "kind": "draft", "instruction": "写一段", "status": "failed", "conclusion": "没弄成", "detail": "", "sources": [], "created_at": "x"},
    ]
    tree: Dict[str, Any] = build_map(state, tasks)
    nodes: List[Dict[str, Any]] = [n for n in _walk(tree) if n.get("kind") == "task"]
    by_text: Dict[str, Dict[str, Any]] = {str(n.get("text", "")): n for n in nodes}
    # A running task shows its instruction; a done one its conclusion.
    assert by_text["查价格"]["status"] == "running"
    assert by_text["结论一"]["status"] == "done"
    assert by_text["写一段"]["status"] == "failed"
    # A task with a known `under` nests under that point.
    main: Dict[str, Any] = _children_by_text(tree)["主点"]
    main_task_texts: List[str] = [str(c.get("text", "")) for c in main["children"] if c.get("kind") == "task"]
    assert main_task_texts == ["查价格"]


def test_build_map_parking_lot_is_not_in_the_tree() -> None:
    tree: Dict[str, Any] = build_map(_state_with_nesting())
    texts: List[str] = [str(n.get("text", "")) for n in _walk(tree)]
    assert "火锅" not in texts
    assert all(n.get("kind") != "parking" for n in _walk(tree))


# --- is_echo -----------------------------------------------------------

def test_is_echo_exact_match() -> None:
    assert is_echo("黑屏开始我在听你直接说就行", "黑屏开始我在听你直接说就行") is True


def test_is_echo_different_punctuation_and_spaces() -> None:
    assert is_echo("黑屏开始，我在听。你直接说就行！", "黑屏开始我在听你直接说就行") is True
    assert is_echo("黑屏 开始， 我在听", "黑屏开始我在听你直接说就行") is True


def test_is_echo_garbled_around_seventy_percent() -> None:
    spoken: str = "黑屏开始我在听你直接说就行按空格暂停"
    # Roughly 70% of the heard characters are found in the spoken text.
    heard: str = "黑屏开始我在听你直接说就行按空格暂错错错错"
    assert is_echo(heard, spoken) is True


def test_is_echo_unrelated_text() -> None:
    assert is_echo("我明天一早先写提示词然后去开会讨论排期", "黑屏开始我在听你直接说就行") is False


def test_is_echo_sentence_containing_both() -> None:
    # Heard text contains the spoken line plus substantial real speech of
    # the user's own: under 60% of it is found in the spoken text.
    spoken: str = "黑屏开始我在听"
    heard: str = "黑屏开始我在听我明天一早先写提示词还要把方案第三点彻底想清楚再说"
    assert is_echo(heard, spoken) is False
    # And a heard text that is mostly the spoken line with a little extra
    # still counts as echo.
    heard_mostly: str = "黑屏开始我在听你直接说就行按空格暂停想结束就说结束或者按退出键吧"
    assert is_echo(heard_mostly, heard_mostly) is True


def test_is_echo_under_two_characters() -> None:
    assert is_echo("嗯", "完全无关的一句话") is True
    assert is_echo("", "完全无关的一句话") is True
    assert is_echo("好", "") is True
    assert is_echo("好的", "") is False


# --- truncate_speech -----------------------------------------------------

def test_truncate_speech_decimal_sentence_unchanged() -> None:
    text: str = "Muse Voice Transcribe costs $0.18 per hour of audio through the Meta Model API."
    assert truncate_speech(text) == text


def test_truncate_speech_long_english_cut_at_sentence_end_not_decimal() -> None:
    first: str = "Muse Voice Transcribe costs $0.18 per hour of audio. "
    second: str = "This price covers a full hour of clear audio transcription for the thinking session today. "
    text: str = first + second + "Then the speaker keeps talking about many more details of the plan without stopping at all today and tomorrow and beyond"
    assert len(text) > 160
    result: str = truncate_speech(text)
    assert result == (first + second).strip()
    assert result.endswith(".")
    assert "$0.18" in result
    assert not result.endswith("$0.")


def test_truncate_speech_thousands_separator_stays_whole() -> None:
    first: str = "The whole plan costs 1,000 dollars in total. "
    second: str = "That amount covers the venue and the equipment and the small team dinner after the demo rehearsal today. "
    text: str = first + second + "More spoken detail follows here and keeps going well beyond the spoken limit for a while longer today"
    assert len(text) > 160
    result: str = truncate_speech(text)
    assert "1,000" in result
    assert not result.endswith("1")
    assert not result.endswith("1,")
    # A text whose only mark within the limit is the comma in 1,000 must
    # not be cut there either.
    only: str = "It costs 1,000 " + "dollars and more words keep coming " * 10
    result_only: str = truncate_speech(only)
    assert "1,000" in result_only
    assert not result_only.endswith("1")


def test_truncate_speech_dotted_word_is_not_a_boundary() -> None:
    text: str = "Use muse-voice-transcribe-1.0 or example.com " + "and keep talking about the plan " * 10
    result: str = truncate_speech(text)
    assert "muse-voice-transcribe-1.0" in result
    assert "example.com" in result
    assert not result.endswith("muse-voice-transcribe-1.")
    assert not result.endswith("example.")


def test_truncate_speech_long_chinese_cut_at_sentence_end() -> None:
    text: str = "这是第一句完整的话。" * 10
    result: str = truncate_speech(text)
    assert result == "这是第一句完整的话。" * 6
    assert len(result) == 60
    assert result.endswith("。")


def test_truncate_speech_no_punctuation_falls_back_to_space() -> None:
    text: str = "word " * 50
    result: str = truncate_speech(text.strip())
    assert result == " ".join(["word"] * 32)
    assert not result.endswith(" ")


def test_truncate_speech_no_punctuation_or_space_hard_cut() -> None:
    assert truncate_speech("a" * 200) == "a" * 160
    assert truncate_speech("想" * 100) == "想" * 60
