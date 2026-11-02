from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_HTML = ROOT / "app" / "static" / "example.html"
EXAMPLE_JS = ROOT / "app" / "static" / "js" / "example.js"
FORBIDDEN = ("/api/", "WebSocket", "getUserMedia")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_example_files_have_no_api_socket_or_microphone() -> None:
    for path in (EXAMPLE_HTML, EXAMPLE_JS):
        text = _read(path)
        for needle in FORBIDDEN:
            assert needle not in text, f"{needle} in {path.name}"


def test_example_script_and_stylesheet_urls_are_relative() -> None:
    html = _read(EXAMPLE_HTML)
    script_urls = re.findall(r'<script[^>]+\bsrc="([^"]+)"', html)
    assert script_urls
    style_urls = re.findall(r'<link[^>]+\brel="stylesheet"[^>]+\bhref="([^"]+)"', html)
    style_urls += re.findall(r'<link[^>]+\bhref="([^"]+)"[^>]+\brel="stylesheet"', html)
    assert style_urls
    for url in script_urls + style_urls:
        assert not url.startswith("/"), url
        assert not url.startswith("//"), url
        assert "://" not in url, url


def test_example_loads_sample_with_relative_url() -> None:
    js = _read(EXAMPLE_JS)
    assert "sample/" in js
    assert '"/sample/' not in js
    assert r"'\/sample\/" not in js
