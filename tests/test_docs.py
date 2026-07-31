from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_markdown_links.py"


def _checker_module():
    spec = importlib.util.spec_from_file_location("check_markdown_links", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_markdown_links_are_valid() -> None:
    assert _checker_module().check_links(ROOT) == []


def test_markdown_link_checker_reports_missing_files_and_headings(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("# Existing heading\n", encoding="utf-8")
    (tmp_path / "index.md").write_text(
        "[Missing](missing.md)\n[Wrong heading](guide.md#absent)\n",
        encoding="utf-8",
    )

    errors = _checker_module().check_links(tmp_path)

    assert errors == [
        "index.md:1: missing target: missing.md",
        "index.md:2: missing heading: guide.md#absent",
    ]
