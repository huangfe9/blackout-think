"""Generate project files with Muse. Model output is untrusted.

Use --context with comma-separated paths to include only those files (plus the
spec and feedback) in the prompt instead of the whole project. Use --expect
with comma-separated paths to refuse a response that contains any other path
or a nearly empty file; in that case nothing is written.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from muse_client import DEFAULT_MODEL, create_client, load_api_key
from budget import spent_usd

logger: logging.Logger = logging.getLogger(__name__)
ROOT: Path = Path(__file__).parent
SPEC_PATH: Path = ROOT / "spec" / "blackout_spec.md"
RUNS_DIR: Path = ROOT / "muse_runs"
MIN_FILE_CHARS: int = 10
INFRA_FILES: frozenset[str] = frozenset({"budget.py", "muse_client.py", "build_with_muse.py", "check_connection.py", "start.py", "test_budget.py", "test_muse_client.py", "test_build_with_muse.py", "requirements.txt", ".env.example", ".gitignore", "LICENSE"})


def is_allowed_path(path: str, allow_infra: bool = False) -> bool:
    """Check whether model output may write to path."""
    if not path:
        return False
    if path.startswith("/"):
        return False
    if "\\" in path or ":" in path:
        return False
    parts: list[str] = path.split("/")
    if any(p == ".." for p in parts):
        return False
    if path == ".env" or path.startswith(".env/"):
        return False
    if path == ".git" or path.startswith(".git/"):
        return False
    if path == ".github" or path.startswith(".github/"):
        return False
    if path == "data" or path.startswith("data/"):
        return False
    if path == "README.md":
        return True
    for prefix in ("app/", "tests/", "docs/"):
        if path.startswith(prefix) and len(path) > len(prefix) and not path.endswith("/"):
            return True
    if allow_infra and path in INFRA_FILES:
        return True
    return False


def write_files(files: list[dict[str, str]], root: Path = ROOT, allow_infra: bool = False) -> list[str]:
    """Validate all paths, then write them with LF newlines."""
    bad: list[str] = [str(f.get("path", "")) for f in files if not is_allowed_path(str(f.get("path", "")), allow_infra)]
    if bad:
        raise ValueError(f"rejected paths: {', '.join(bad)}")
    written: list[str] = []
    for item in files:
        rel: str = str(item.get("path", ""))
        content: str = str(item.get("content", ""))
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        dest: Path = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        written.append(rel)
    return written


def generate(model: str, prompt: str) -> tuple[list[dict[str, str]], str]:
    """Call Muse and parse the files JSON."""
    schema: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": {"files": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}, "required": ["files"]}
    client: Any = create_client().with_options(timeout=1800, max_retries=0)
    resp: Any = client.responses.create(model=model, input=[{"role": "user", "content": prompt}], max_output_tokens=60000, reasoning={"effort": "medium"}, text={"format": {"type": "json_schema", "name": "project_files", "schema": schema, "strict": True}})
    raw: str = str(resp.output_text)
    data: Any = json.loads(raw)
    files: Any = data.get("files")
    if not isinstance(files, list):
        raise ValueError("model output has no files list")
    out: list[dict[str, str]] = [{"path": str(f["path"]), "content": str(f["content"])} for f in files]
    return out, raw


def parse_path_list(value: str | None) -> list[str]:
    """Parse a comma-separated list of file paths."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def validate_response_files(files: list[dict[str, str]], expect: list[str] | None) -> None:
    """Refuse a response with an unexpected path or a nearly empty file."""
    if expect is not None:
        allowed: set[str] = set(expect)
        for item in files:
            path: str = str(item.get("path", ""))
            if path not in allowed:
                raise ValueError(f"unexpected path: {path}")
    for item in files:
        content: str = str(item.get("content", ""))
        if len(content.strip()) < MIN_FILE_CHARS:
            raise ValueError(f"nearly empty file: {str(item.get('path', ''))}")


def _read_text_file(path: Path) -> str | None:
    """Read a UTF-8 text file; skip binary and non-UTF-8 files."""
    try:
        data: bytes = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        logger.warning("skipping binary file %s", path)
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning("skipping non-utf8 file %s: %s", path, exc)
        return None


def _is_refused_context_path(raw: str) -> bool:
    """True for paths that must never be sent to the model as context."""
    if not raw or not raw.strip():
        return True
    value: str = raw.strip()
    if value.startswith("/") or value.startswith("\\") or Path(value).is_absolute():
        return True
    parts: list[str] = value.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        return True
    name: str = parts[-1] if parts else ""
    lower: str = name.lower()
    if lower == ".env" or lower.startswith(".env."):
        return True
    if name == "api_key":
        return True
    if lower.endswith(".pem") or lower.endswith(".key"):
        return True
    return False


def raw_contains_current_key(raw: str) -> bool:
    """True when raw output contains the current key, without revealing it."""
    try:
        key: str = load_api_key()
    except Exception:
        return False
    return bool(key) and key in raw


def _collect_selected(context: list[str], root: Path = ROOT) -> str:
    """Dump only the selected project files as text."""
    chunks: list[str] = []
    for rel in context:
        if _is_refused_context_path(rel):
            logger.warning("refusing context path: %s", rel)
            continue
        content: str | None = _read_text_file(root / rel)
        if content is None:
            continue
        chunks.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(chunks)


def _collect_project(allow_infra: bool = False, root: Path = ROOT) -> str:
    """Dump current project files as text, never data/ or caches."""
    rels: list[str] = ["README.md"]
    for base in ("app", "tests", "docs"):
        bdir: Path = root / base
        if bdir.is_dir():
            for p in sorted(bdir.rglob("*")):
                if p.is_file():
                    if "__pycache__" in p.parts:
                        continue
                    rels.append(str(p.relative_to(root).as_posix()))
    if allow_infra:
        for name in sorted(INFRA_FILES):
            if name not in rels and (root / name).is_file():
                rels.append(name)
    chunks: list[str] = []
    for rel in rels:
        content: str | None = _read_text_file(root / rel)
        if content is None:
            continue
        chunks.append(f"--- {rel} ---\n{content}")
    return "\n\n".join(chunks)


def build_input(feedback: str | None, allow_infra: bool = False, root: Path = ROOT, context: list[str] | None = None) -> str:
    """Build the model prompt from spec, project, and feedback."""
    spec_file: Path = root / "spec" / "blackout_spec.md"
    if spec_file.is_file():
        spec_text: str = spec_file.read_text(encoding="utf-8")
    else:
        spec_text = SPEC_PATH.read_text(encoding="utf-8")
    if context is not None:
        project: str = _collect_selected(context, root)
        prompt: str = spec_text
        if project:
            prompt += "\n\n# Current project\n" + project
        if feedback is not None:
            prompt += "\n\n# Feedback\n" + feedback + "\n\nReturn only files that must change."
        return prompt
    if feedback is None:
        return spec_text
    project = _collect_project(allow_infra, root)
    return spec_text + "\n\n# Current project\n" + project + "\n\n# Feedback\n" + feedback + "\n\nReturn only files that must change."


def _next_run_path() -> Path:
    """Next muse_runs/run_NN.json path."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[Path] = sorted(RUNS_DIR.glob("run_*.json"))
    num: int = len(existing) + 1
    while (RUNS_DIR / f"run_{num:02d}.json").exists():
        num += 1
    return RUNS_DIR / f"run_{num:02d}.json"


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Generate project with Muse")
    parser.add_argument("--feedback", default=None, help="Feedback file")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-usd", type=float, default=30.0)
    parser.add_argument("--allow-infra", action="store_true")
    parser.add_argument("--context", default=None, help="Comma-separated files to include as context")
    parser.add_argument("--expect", default=None, help="Comma-separated files expected in the response")
    args: argparse.Namespace = parser.parse_args(argv)
    spent_before: float = spent_usd()
    if spent_before >= float(args.max_usd):
        logger.error("refusing to start: spent $%.4f at or past max $%.2f", spent_before, float(args.max_usd))
        sys.exit(1)
    feedback_text: str | None = None
    if args.feedback is not None:
        feedback_text = Path(str(args.feedback)).read_text(encoding="utf-8")
    context: list[str] | None = parse_path_list(str(args.context)) if args.context is not None else None
    expect: list[str] | None = parse_path_list(str(args.expect)) if args.expect is not None else None
    prompt: str = build_input(feedback_text, bool(args.allow_infra), context=context)
    try:
        files: list[dict[str, str]]
        raw: str
        files, raw = generate(str(args.model), prompt)
    except Exception as exc:
        logger.error("generation failed: %s", exc)
        sys.exit(1)
    if raw_contains_current_key(raw):
        logger.error("refusing response: model output contains the current API key; nothing written")
        sys.exit(1)
    if expect is not None:
        try:
            validate_response_files(files, expect)
        except ValueError as exc:
            logger.error("refusing response, nothing written: %s", exc)
            sys.exit(1)
    run_path: Path = _next_run_path()
    try:
        run_path.write_text(json.dumps({"model": str(args.model), "raw": raw}), encoding="utf-8")
    except OSError as exc:
        logger.error("cannot save run: %s", exc)
        sys.exit(1)
    try:
        written: list[str] = write_files(files, ROOT, bool(args.allow_infra))
    except ValueError as exc:
        logger.error("bad paths: %s", exc)
        sys.exit(1)
    except OSError as exc:
        logger.error("write failed: %s", exc)
        sys.exit(1)
    spent_after: float = spent_usd()
    logger.info("wrote files: %s", ", ".join(written))
    logger.info("this run cost $%.4f, total $%.4f", spent_after - spent_before, spent_after)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
