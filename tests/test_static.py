"""Static frontend tests: CSP hygiene, MIME types, and forbidden constructs."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app

STATIC_DIR: Path = Path(__file__).resolve().parent.parent / "app" / "static"
# The one URL that may appear in frontend code: the SVG XML namespace
# identifier. It is never fetched; it only names the SVG element type.
SVG_NAMESPACE: str = "http://www.w3.org/2000/svg"
META_KEY_URL: str = "https://dev.meta.ai/api-keys/"


@pytest.fixture(autouse=True)
def setup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLACKOUT_DATA_DIR", str(tmp_path / "data"))
    store.clear_memory()


def _html_files() -> List[Path]:
    return sorted(STATIC_DIR.rglob("*.html"))


def _js_files() -> List[Path]:
    return sorted((STATIC_DIR / "js").rglob("*.js"))


def _css_files() -> List[Path]:
    return sorted(STATIC_DIR.rglob("*.css"))


def _text_files() -> List[Path]:
    return [path for path in _html_files() + _js_files() + _css_files() if path.is_file()]


def test_no_inline_script_style_or_handlers() -> None:
    files: List[Path] = _html_files()
    assert files, "no HTML files under app/static"
    names: List[str] = [path.name for path in files]
    assert "index.html" in names and "observer.html" in names
    for path in files:
        text: str = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<script\b([^>]*)>", text, flags=re.IGNORECASE):
            assert "src=" in match.group(1).lower(), f"inline script in {path.name}"
        assert not re.search(r"\sstyle\s*=", text, flags=re.IGNORECASE), f"style= in {path.name}"
        assert not re.search(r"<style\b", text, flags=re.IGNORECASE), f"style block in {path.name}"
        assert not re.search(r"\son[a-z]+\s*=", text, flags=re.IGNORECASE), f"inline handler in {path.name}"


def test_index_html_has_no_inline_script_or_style() -> None:
    text: str = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for match in re.finditer(r"<script\b([^>]*)>", text, flags=re.IGNORECASE):
        assert "src=" in match.group(1).lower(), "inline script in index.html"
    assert not re.search(r"<style\b", text, flags=re.IGNORECASE), "style block in index.html"
    assert not re.search(r"\sstyle\s*=", text, flags=re.IGNORECASE), "style= in index.html"
    assert not re.search(r"\son[a-z]+\s*=", text, flags=re.IGNORECASE), "inline handler in index.html"


def test_referenced_static_files_exist_and_mime() -> None:
    client: TestClient = TestClient(app)
    all_refs: List[str] = []
    for page_name in ("index.html", "observer.html"):
        page: Path = STATIC_DIR / page_name
        assert page.is_file(), page_name
        text: str = page.read_text(encoding="utf-8")
        refs: List[str] = re.findall(r"(?:src|href)=\"(/static/[^\"]+)\"", text)
        assert refs, f"{page_name} references no static files"
        all_refs.extend(refs)
        for ref in refs:
            local: Path = STATIC_DIR / ref[len("/static/"):]
            assert local.is_file(), f"missing referenced file {ref}"
            response: Any = client.get(ref)
            assert response.status_code == 200, ref
            content_type: str = response.headers.get("content-type", "")
            if ref.endswith(".js"):
                assert "javascript" in content_type, (ref, content_type)
            elif ref.endswith(".css"):
                assert "text/css" in content_type, (ref, content_type)
    # The star-map assets must be among the referenced files.
    for ref in ("/static/map.css", "/static/js/map.js", "/static/observer.css", "/static/js/observer.js"):
        assert ref in all_refs, f"{ref} is not referenced by any page"
        response = client.get(ref)
        assert response.status_code == 200, ref
        content_type = response.headers.get("content-type", "")
        if ref.endswith(".js"):
            assert "javascript" in content_type, (ref, content_type)
        elif ref.endswith(".css"):
            assert "text/css" in content_type, (ref, content_type)
    root: Any = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    observer: Any = client.get("/observer")
    assert observer.status_code == 200
    assert "text/html" in observer.headers.get("content-type", "")


def test_no_external_urls_anywhere() -> None:
    candidates: List[Path] = _html_files() + _js_files() + _css_files()
    assert candidates
    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"'<>)]+", text):
            if url == SVG_NAMESPACE:
                continue
            if url == META_KEY_URL and path.name == "setup.html":
                continue
            if url == "https://github.com/huangfe9/blackout-think#run-it" and path.name in ("example.html", "example.js"):
                continue
            raise AssertionError(f"external URL {url!r} in {path}")
        assert not re.search(r"src=\"//", text), f"protocol-relative URL in {path}"


def test_no_innerhtml_eval_or_function_constructor() -> None:
    files: List[Path] = _js_files()
    assert len(files) >= 7, "expected the split js modules plus observer.js"
    for path in files:
        text: str = path.read_text(encoding="utf-8")
        assert not re.search(r"\.innerHTML\s*=", text), f"innerHTML assignment in {path.name}"
        assert "eval(" not in text, f"eval in {path.name}"
        assert "new Function" not in text, f"new Function in {path.name}"


def test_no_style_element_or_style_attribute_via_dom() -> None:
    # The CSP has no 'unsafe-inline' for styles, so a <style> element or a
    # style attribute created from JS would be blocked at runtime; the
    # code must not create either.
    for path in _js_files() + _html_files():
        text: str = path.read_text(encoding="utf-8")
        assert not re.search(r"createElement\(\s*['\"]style['\"]", text), f"style element created in {path.name}"
        assert not re.search(r"createElementNS\([^)]*['\"]style['\"]", text), f"style element created in {path.name}"
        assert not re.search(r"setAttribute\(\s*['\"]style['\"]", text), f'setAttribute("style") in {path.name}'


def test_expected_modules_exist() -> None:
    for name in ("cues.js", "speech.js", "capture.js", "black.js", "result.js", "start.js", "observer.js", "map.js", "i18n.js"):
        assert (STATIC_DIR / "js" / name).is_file(), name
    assert (STATIC_DIR / "app.css").is_file()
    assert (STATIC_DIR / "observer.css").is_file()
    assert (STATIC_DIR / "map.css").is_file()
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "observer.html").is_file()


def test_favicon_declared_inline_data() -> None:
    for page_name in ("index.html", "observer.html"):
        text: str = (STATIC_DIR / page_name).read_text(encoding="utf-8")
        assert '<link rel="icon" href="data:,">' in text, page_name


def test_observer_uses_textcontent_and_new_mic_values() -> None:
    js: str = (STATIC_DIR / "js" / "observer.js").read_text(encoding="utf-8")
    assert "textContent" in js
    assert "innerHTML" not in js
    mic_match: Optional[re.Match[str]] = re.search(r"MIC_KEYS\s*=\s*\{([^}]*)\}", js)
    assert mic_match is not None, "MIC_KEYS table missing in observer.js"
    mic_block: str = mic_match.group(1)
    pairs: Dict[str, str] = dict(re.findall(r"(\w+)\s*:\s*[\"']([^\"']+)[\"']", mic_block))
    for value in ("listening", "paused", "user_speaking", "ai_speaking", "offline"):
        assert value in pairs, f"mic value {value} not mapped in MIC_KEYS"
    i18n_text: str = (STATIC_DIR / "js" / "i18n.js").read_text(encoding="utf-8")
    zh_block: str = _language_block(i18n_text, "zh")
    en_block: str = _language_block(i18n_text, "en")
    zh_keys: Set[str] = _table_keys(zh_block)
    en_keys: Set[str] = _table_keys(en_block)
    for label_key in pairs.values():
        assert label_key in zh_keys, f"mic i18n key {label_key} missing from zh table"
        assert label_key in en_keys, f"mic i18n key {label_key} missing from en table"
    html: str = (STATIC_DIR / "observer.html").read_text(encoding="utf-8")
    assert "/static/observer.css" in html and "/static/js/observer.js" in html


def test_observer_never_shows_money() -> None:
    # The star map is for recording video: it must not show spend at all.
    # A bare `$` is not money — e.g. the `$` ending the session-id regular
    # expression in observer.js — so only flag a dollar sign that actually
    # formats an amount: one followed by a digit, or a template expression
    # interpolating a money value.
    js: str = (STATIC_DIR / "js" / "observer.js").read_text(encoding="utf-8")
    html: str = (STATIC_DIR / "observer.html").read_text(encoding="utf-8")
    assert "/api/status" not in js
    assert "spent" not in js
    for name, text in (("observer.js", js), ("observer.html", html)):
        assert "花费" not in text, f"花费 in {name}"
        assert not re.search(r"\$(?=\d)", text), f"dollar amount in {name}"
        assert not re.search(
            r"\$\{[^}]*(?:spent|usd|money|cost|price|amount|花费)",
            text,
            flags=re.IGNORECASE,
        ), f"money template expression in {name}"


# --- Stage 7 how-it-works pictures and product copy ---------------------------

def test_how_it_works_pictures_exist_and_served_as_jpeg() -> None:
    assert not list(STATIC_DIR.rglob("sample_poster.jpg")), "sample_poster.jpg should be gone"
    client: TestClient = TestClient(app)
    for name in ("how_it_works_zh.jpg", "how_it_works_en.jpg"):
        matches: List[Path] = sorted(STATIC_DIR.rglob(name))
        assert matches, f"{name} missing under app/static"
        picture: Path = matches[0]
        assert picture.is_file() and picture.stat().st_size > 0
        # A JPEG starts with the SOI marker.
        assert picture.read_bytes()[:2] == b"\xff\xd8", name
        relative: str = picture.relative_to(STATIC_DIR).as_posix()
        response: Any = client.get(f"/static/{relative}")
        assert response.status_code == 200, name
        assert "image/jpeg" in response.headers.get("content-type", ""), name
        assert response.content == picture.read_bytes(), name


def test_no_static_file_mentions_weekend_or_demo() -> None:
    # User-visible copy must describe the product generically: no leftover
    # scenario wording and no demo wording in any shipped text file.
    candidates: List[Path] = _text_files()
    assert candidates
    for path in candidates:
        text: str = path.read_text(encoding="utf-8")
        assert "周末" not in text, f"周末 in {path.name}"
        assert not re.search(r"demo", text, flags=re.IGNORECASE), f"demo in {path.name}"


def _balanced_block(text: str, opening: int) -> str:
    """Return the brace-balanced block whose ``{`` is at ``opening``."""
    depth: int = 0
    quote: Optional[str] = None
    escaped: bool = False
    index: int = opening
    while index < len(text):
        char: str = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening:index + 1]
        index += 1
    raise AssertionError("unbalanced braces in i18n.js")


def _language_block(text: str, language: str) -> str:
    match: Optional[re.Match] = re.search(r"['\"]?" + language + r"['\"]?\s*:\s*\{", text)
    assert match is not None, f"no {language!r} table in i18n.js"
    return _balanced_block(text, match.end() - 1)


def _table_keys(block: str) -> Set[str]:
    keys: Set[str] = set()
    # Keys sit at the table's top level, one per entry; accepting quoted or
    # bare keys keeps this a check of the table, not of its formatting.
    for match in re.finditer(r"(?:^|[,{])\s*['\"]?([A-Za-z_$][A-Za-z0-9_$-]*)['\"]?\s*:", block):
        keys.add(match.group(1))
    return keys


def test_i18n_has_the_same_keys_for_zh_and_en() -> None:
    path: Path = STATIC_DIR / "js" / "i18n.js"
    assert path.is_file(), "i18n.js missing"
    text: str = path.read_text(encoding="utf-8")
    tables: Dict[str, Set[str]] = {}
    for language in ("zh", "en"):
        keys: Set[str] = _table_keys(_language_block(text, language))
        assert keys, f"no keys parsed for {language} in i18n.js"
        tables[language] = keys
    assert tables["zh"] == tables["en"], (
        f"only in zh: {sorted(tables['zh'] - tables['en'])}, "
        f"only in en: {sorted(tables['en'] - tables['zh'])}"
    )


def test_index_states_what_product_does() -> None:
    html: str = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "不看屏幕" in html
    assert "关灯，开始说" in html


def test_start_and_result_pages_never_show_money() -> None:
    # The start page and the result page are the same index.html plus the
    # start/result scripts; none of them may mention spend or an amount.
    candidates: List[Path] = [STATIC_DIR / "index.html"]
    for name in ("start.js", "result.js"):
        path: Path = STATIC_DIR / "js" / name
        assert path.is_file(), name
        candidates.append(path)
    for path in candidates:
        text: str = path.read_text(encoding="utf-8")
        assert "花费" not in text, f"花费 in {path.name}"
        assert "/api/status" not in text, f"status endpoint in {path.name}"
        assert not re.search(r"\$(?=\d)", text), f"dollar amount in {path.name}"
        assert not re.search(
            r"\$\{[^}]*(?:spent|usd|money|cost|price|amount|花费)",
            text,
            flags=re.IGNORECASE,
        ), f"money template expression in {path.name}"
