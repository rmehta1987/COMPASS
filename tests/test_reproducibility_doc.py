"""`REPRODUCIBILITY.md` must name every site artifact and every builder.

The page deliberately prints no run stamps, so that document is where a reader
is sent to find out where a figure came from. A document in that position goes
stale silently: an artifact is added, a builder is written, and the one place
that was supposed to explain them says nothing. These tests make the omission
loud. They cannot check that a row is TRUE -- only that it exists.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "REPRODUCIBILITY.md"
ARTIFACTS = ROOT / "site" / "artifacts"


def test_every_loaded_artifact_is_named() -> None:
    """Each file the page loads, plus the index itself, must appear."""
    text = DOC.read_text(encoding="utf-8")
    listed = json.loads((ARTIFACTS / "index.json").read_text(encoding="utf-8"))["files"]
    missing = [f for f in [*listed, "index.json"] if f not in text]
    assert not missing, (
        f"{', '.join(missing)} reach the page but REPRODUCIBILITY.md does not say "
        "where they come from or whether a clone can rebuild them")


def test_every_builder_is_named() -> None:
    """Each `site/tools/build_*.py` must appear, with its inputs described."""
    text = DOC.read_text(encoding="utf-8")
    builders = sorted(p.name for p in (ROOT / "site" / "tools").glob("build_*.py"))
    assert builders, "no builders found; this test would pass vacuously"
    missing = [b for b in builders if b not in text]
    assert not missing, (
        f"{', '.join(missing)} writes an artifact the page serves and "
        "REPRODUCIBILITY.md does not mention it")


def test_the_doc_states_where_each_builder_can_run() -> None:
    """Anti-vacuity: the table has to carry the runs-where column's vocabulary.

    Naming a builder is not enough -- the question the document exists to answer
    is whether a reader can rebuild the artifact. `training` marks the builders
    that need the withheld inputs, and the declared gap marks the three that no
    machine can rebuild today.
    """
    text = DOC.read_text(encoding="utf-8")
    for phrase in ("training", "nowhere, today", "withheld", "Declared gap"):
        assert phrase in text, f"REPRODUCIBILITY.md no longer says {phrase!r}"
