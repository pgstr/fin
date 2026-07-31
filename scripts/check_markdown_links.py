from __future__ import annotations

import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|[^\s]+)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
SKIPPED_PARTS = {".git", ".venv", ".pytest_cache", ".ruff_cache", ".code-review-graph"}


def _markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in SKIPPED_PARTS for part in path.relative_to(root).parts)
    )


def _destinations(path: Path) -> list[tuple[int, str]]:
    destinations: list[tuple[int, str]] = []
    fence: str | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        destinations.extend((line_number, match.group(1)) for match in INLINE_LINK.finditer(line))
        reference = REFERENCE_LINK.match(line)
        if reference:
            destinations.append((line_number, reference.group(1)))
    return destinations


def _slug(value: str) -> str:
    value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = html.unescape(value).replace("`", "").replace("*", "").replace("_", "")
    value = re.sub(r"[^\w\s-]", "", value.casefold())
    return re.sub(r"[\s-]+", "-", value).strip("-")


def _anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: defaultdict[str, int] = defaultdict(int)
    fence: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        base = _slug(match.group(1))
        if not base:
            continue
        count = counts[base]
        anchors.add(base if count == 0 else f"{base}-{count}")
        counts[base] += 1
    return anchors


def check_links(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in _markdown_files(root):
        for line_number, raw_destination in _destinations(source):
            destination = raw_destination.removeprefix("<").removesuffix(">")
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc:
                continue
            relative_path = unquote(parsed.path)
            if relative_path:
                target = (
                    root / relative_path.lstrip("/")
                    if relative_path.startswith("/")
                    else source.parent / relative_path
                ).resolve()
            else:
                target = source.resolve()
            location = f"{source.relative_to(root)}:{line_number}"
            if not target.is_relative_to(root):
                errors.append(f"{location}: link escapes repository: {destination}")
                continue
            if not target.exists():
                errors.append(f"{location}: missing target: {destination}")
                continue
            fragment = unquote(parsed.fragment).casefold()
            if fragment and target.suffix.casefold() == ".md":
                anchors = anchor_cache.setdefault(target, _anchors(target))
                if fragment not in anchors:
                    errors.append(f"{location}: missing heading: {destination}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    errors = check_links(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Checked internal links in {len(_markdown_files(root))} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
