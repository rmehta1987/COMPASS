"""The site checks' own reported figures must describe the tree, not the session.

These checks are the instrument the rest of the page is audited with, so a count
one of them prints is held to the same rule as a count the page prints: an
unstated denominator is not a number. The scan itself was never weak -- it
covered more files than it had to -- but its printed total moved on its own,
which is the defect the checks exist to catch elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "site" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from no_instrument import SKIP_DIRS, SKIP_SUFFIXES, site_files  # noqa: E402


def _tree(root: Path) -> None:
    """Write a miniature site: one page, one artifact, one binary.

    Args:
        root: Directory to populate.
    """
    (root / "artifacts").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><html lang=en></html>",
                                     encoding="utf-8")
    (root / "artifacts" / "index.json").write_text('{"files": []}', encoding="utf-8")
    (root / "artifacts" / "weights.safetensors").write_bytes(b"\x00\x01")


def test_a_generated_cache_does_not_change_what_the_scan_reports(
        tmp_path: Path) -> None:
    """A `__pycache__` appearing must not move the scanned file count.

    MEASURED 2026-09-16: `site_files` walked everything under the site root
    filtered only on four binary suffixes, so it counted
    `site/tools/__pycache__/*.pyc`. The printed total read 29, 30, 31 and 32
    within one session while the tree never changed, because those files come
    and go with whatever was last imported.

    Args:
        tmp_path: Pytest's per-test directory.
    """
    _tree(tmp_path)
    before = site_files(tmp_path)

    cache = tmp_path / "tools" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "common.cpython-312.pyc").write_bytes(b"\x00cache")
    (cache / "no_instrument.cpython-312.pyc").write_bytes(b"\x00cache")

    assert site_files(tmp_path) == before, (
        "a generated cache moved the scanned file list, so the count the check "
        "prints is a property of what was last imported rather than of the tree"
    )


def test_the_scan_still_reaches_the_files_that_matter(tmp_path: Path) -> None:
    """Anti-vacuity: the exclusions must not empty the scan.

    A filter that dropped everything would satisfy the invariance test above
    while certifying nothing, so pin what has to remain: the page and the
    artifact are scanned, and only the binary is dropped for its suffix.

    Args:
        tmp_path: Pytest's per-test directory.
    """
    _tree(tmp_path)
    found = {p.relative_to(tmp_path).as_posix() for p in site_files(tmp_path)}
    assert "index.html" in found
    assert "artifacts/index.json" in found
    assert "artifacts/weights.safetensors" not in found
    assert found == {"index.html", "artifacts/index.json"}


def test_the_excluded_directories_are_named_and_include_the_cache() -> None:
    """The exclusion is declared, so the printed line can state it.

    `main` prints `SKIP_DIRS` and the suffix count beside the total, which is
    what makes the number readable. Keeping the set explicit is what that line
    depends on.
    """
    assert "__pycache__" in SKIP_DIRS
    assert ".git" in SKIP_DIRS
    assert SKIP_SUFFIXES, "the binary-suffix filter must not be empty"
