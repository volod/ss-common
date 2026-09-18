"""Validate relative links and Markdown heading anchors across project documentation.

Run: `python -m ss_kit.quality.doc_links [--root DIR]` (or `make lint-doc-links`).
"""

import argparse
import logging
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from urllib.parse import unquote

from ss_kit.quality.project_root import discover_project_root

_LOG = logging.getLogger(__name__)

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_HEADING = re.compile(r"^(#{1,6}) (.+?)\s*#*\s*$")
_HEADING_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")
_EXTERNAL = ("http://", "https://", "mailto:", "/")
_ROOT_DOCS = ("README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".codex", "projects/README.md")


def heading_anchor(title: str) -> str:
    """Return the common Git-host slug for one heading."""
    text = _HEADING_LINK.sub(r"\1", title).replace("`", "").strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def anchors(path: Path) -> set[str]:
    """Return every heading fragment, including numbered duplicate fragments."""
    found: set[str] = set()
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        found.update(_HTML_ANCHOR.findall(line))
        matched = _HEADING.match(line)
        if not matched:
            continue
        base = heading_anchor(matched.group(2))
        anchor = base
        repeat = 0
        while anchor in found:
            repeat += 1
            anchor = f"{base}-{repeat}"
        found.add(anchor)
    return found


def documentation_files(project_root: Path) -> list[Path]:
    """Return checked documentation without depending on repository initialization."""
    files = [project_root / name for name in _ROOT_DOCS if (project_root / name).is_file()]
    docs = project_root / "docs"
    if docs.is_dir():
        files.extend(docs.rglob("*.md"))
    cursor = project_root / ".cursor"
    if cursor.is_dir():
        files.extend(cursor.rglob("*.mdc"))
    return sorted(set(files))


def relative_links(document: Path) -> Iterator[tuple[int, str]]:
    """Yield non-external link targets outside fenced code blocks and inline code."""
    fenced = False
    for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if fenced:
            continue
        for target in _LINK.findall(_INLINE_CODE.sub("", line)):
            if not target.startswith(_EXTERNAL):
                yield number, unquote(target.strip("<>"))


def _landing_failure(
    document: Path,
    target: str,
    known_anchors: dict[Path, set[str]],
) -> str | None:
    path_part, _, anchor = target.partition("#")
    resolved = (document.parent / path_part).resolve() if path_part else document.resolve()
    if not resolved.exists():
        return "missing file"
    if not anchor or not resolved.is_file() or resolved.suffix.lower() != ".md":
        return None
    if resolved not in known_anchors:
        known_anchors[resolved] = anchors(resolved)
    return None if anchor in known_anchors[resolved] else "missing anchor"


def broken_links(project_root: Path) -> list[str]:
    """Return every broken relative file or heading target."""
    findings: list[str] = []
    known_anchors: dict[Path, set[str]] = {}
    for document in documentation_files(project_root):
        for number, target in relative_links(document):
            failure = _landing_failure(document, target, known_anchors)
            if failure:
                relative = document.relative_to(project_root)
                findings.append(f"{relative}:{number}: {failure} -> {target}")
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the documentation-link gate."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="check relative documentation links")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else discover_project_root()
    findings = broken_links(root)
    for finding in findings:
        _LOG.error("ERROR: %s", finding)
    _LOG.info("[doc-links] %d broken link(s)", len(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
