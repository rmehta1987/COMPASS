"""The one place a rule is stated twice is held to the place it is stated first.

`CLAUDE.md` §Critical anchors copies three rules out of `AGENTS.md` so that they
survive if `AGENTS.md` fails to load. 08f040a had reduced them to pointers into
`AGENTS.md`, which are useless in exactly the case the section exists for, so
they were restored as quotations. A quotation can drift from its source like any
other copy; this keeps every anchor sentence a verbatim part of `AGENTS.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent


def _anchors() -> list[str]:
    """Return each numbered item of `CLAUDE.md` §Critical anchors.

    Returns:
        The items' text, whitespace collapsed, in file order.
    """
    text = (ROOT / "CLAUDE.md").read_text()
    section = text.split("## Critical anchors", 1)[1].split("\n## ", 1)[0]
    items = re.split(r"\n(?=\d+\. )", section)
    return [" ".join(re.sub(r"^\d+\. ", "", i).split())
            for i in items if re.match(r"\d+\. ", i)]


def test_every_critical_anchor_is_quoted_verbatim_from_agents_md() -> None:
    """A red names the anchor sentence that no longer appears in `AGENTS.md`."""
    anchors = _anchors()
    assert len(anchors) >= 3, f"CLAUDE.md §Critical anchors lists {len(anchors)} items"
    agents = " ".join((ROOT / "AGENTS.md").read_text().split())
    for anchor in anchors:
        for sentence in re.split(r"(?<=\.) (?=\S)", anchor):
            assert sentence.rstrip(".") in agents, (
                f"CLAUDE.md anchor {sentence!r} is not verbatim in AGENTS.md; "
                "re-copy it from AGENTS.md, which wins")
