"""Static checks for stage 8D look-and-feel changes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(rel: str) -> str:
    return (STATIC / rel).read_text(encoding="utf-8")


NEW_KEYS = [
    "degradedSpoken",
    "draftReadySpoken",
    "draftAlmostSpoken",
    "firstDraft",
    "copyDraft",
    "drafting",
    "wordsLabel",
    "closePicture",
    "openPicture",
    "countersConflicts",
]

INDEX_IDS = [
    "page-start", "page-black", "page-result", "goalInput", "micBtn",
    "startBtn", "continueLastBtn", "voiceWarning", "startErr",
    "openObserver", "pastToggle", "recentSection", "recentList", "dot",
    "hint", "resultTitle", "resultGoal", "degradedNotice", "resultSummary",
    "stopReadingBtn", "posterFigure", "result", "resultErr", "copyBtn",
    "sketchLabel", "sketchInput", "restartBtn", "langToggle", "keyLink",
    "howItWorksImg",
]

CHANGED = [
    "js/map.js", "map.css", "js/observer.js", "observer.css",
    "js/result.js", "app.css", "js/i18n.js", "js/start.js", "index.html",
]


def test_result_css_features() -> None:
    css = read("app.css")
    assert "white-space: pre-wrap" in css
    assert "position: sticky" in css
    assert "@media (min-width: 1000px)" in css


def test_observer_and_map_features() -> None:
    css = read("observer.css")
    assert "top: 44px" in css
    assert "bottom: 90px" in css
    assert "220px" in css
    js = read("js/map.js")
    assert "NIGHT_LABEL_CSS = 18" in js
    assert "NIGHT_BRANCH_CSS = 20" in js
    assert "NIGHT_GOAL_CSS = 24" in js
    assert "PAPER_LABEL_CSS = 15" in js
    assert "0.55" in js
    assert "countersConflicts" not in js


def test_result_js_features() -> None:
    js = read("js/result.js")
    assert "aria-expanded" in js
    assert "scrollTo(0, 0)" in js
    assert "white-space: pre-wrap" in read("app.css")
    assert "firstDraft" in js
    assert "preserveScroll" in js
    assert "poster-overlay" in js


def test_start_scrolls_to_top() -> None:
    assert "scrollTo(0, 0)" in read("js/start.js")
    assert "scrollTo(0, 0)" in read("js/result.js")


def test_i18n_new_keys_both_languages() -> None:
    text = read("js/i18n.js")
    zh, _, en = text.partition("en: {")
    for key in NEW_KEYS:
        assert f"{key}:" in zh, key
        assert f"{key}:" in en, key


def test_observer_check_copy() -> None:
    text = read("js/i18n.js")
    for line in text.splitlines():
        if "observerCheck" in line:
            assert "录视频" not in line
            assert "Recording a video" not in line
    assert "第二块屏幕" in text
    assert "second screen" in text


def test_no_inner_html_in_changed_files() -> None:
    for rel in CHANGED:
        assert "innerHTML" not in read(rel), rel


def test_index_ids_preserved() -> None:
    html = read("index.html")
    for element_id in INDEX_IDS:
        assert f'id="{element_id}"' in html, element_id
