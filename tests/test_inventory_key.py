"""The inventory-backed key table, and the pre-registration it is bound by.

Everything here runs against `tests/fake_tiered_inventory.json`. The real
inventory is on the key side and may never be in this clone, so nothing below
asserts against a real row, a real pmid or a real tier count.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from benchmark.cohort_papers import COHORT_PAPERS

# --- task 0: the pre-registration -----------------------------------------
#
# The document is a guarantee like any other, so it is tested like one: a rule
# silently dropped from it reddens here rather than being noticed by a reader
# who happens to remember the earlier draft.

PREREG = Path("benchmark/INVENTORY_DISCOVERY.md")

#: A dictionary key: module prefix, colon, question id. The pre-registration
#: must carry none, whatever its source -- a key in a public document is the
#: half of an inventory row that makes the other half guessable.
KEY_SHAPE = re.compile(r"\bm\d+:Q[\d.]+")

#: The symbols the four rules are stated in. Named individually, because the
#: failure this catches is one rule going missing while the others read fine.
RULE_SYMBOLS = (
    # rule 1: two ceilings, never pooled, and the one line a rate compares to
    "ceiling_under_prevalence_key",
    "ceiling_under_inventory",
    "papers_matchable_and_in_frame",
    # rule 2: the match rule, and what never matches
    "outcomes[].key",
    "exposures[].key",
    '`status == "present"`',
    "`confident == true`",
    "baseline_score.keys_of",
    "folded to the CONSTRUCT",
    # rule 3: the excluded side, counted
    "`confident == false`",
    "excluded_sides",
    # rule 4: the frame test, enumerated and never hand-typed
    "generate/funnel.py::s2_prune",
    "pipeline/pose.py::construct_index",
    "--frame-only",
)


def flat(text: str) -> str:
    """Whitespace collapsed, so an assertion is not a claim about line wrapping.

    A test asserting across a line wrap went red in this repository once
    already (`ATTEMPTS.md`, brief 2 item 2 attempt 1); the sentence was right
    and the assertion was about the fill width.

    Args:
        text: The document.

    Returns:
        The same text with every whitespace run collapsed to one space.
    """
    return re.sub(r"\s+", " ", text)


def test_the_preregistration_states_all_four_rules():
    text = flat(PREREG.read_text())
    missing = [s for s in RULE_SYMBOLS if s not in text]
    assert not missing, f"the pre-registration no longer names: {missing}"
    # the pooling ban and the comparison rule are the two sentences a reader
    # acts on, so they are asserted as claims, not just as symbols
    assert "never averaged" in text and "summed" in text
    assert "only line the observed rate may be compared to" in text
    assert "NEVER match" in text, "rule 2's modality clause"
    assert "UNKNOWN, never as 0" in text, "rule 4's absent-frame clause"


def test_the_preregistration_carries_no_row_of_the_key():
    """No pmid, no dictionary key, no published inventory figure.

    The document is on a public working branch and the inventory is not. A
    pmid beside a key, or a key beside a status, is a row of the answer key
    however few of them there are.
    """
    text = flat(PREREG.read_text())
    assert not KEY_SHAPE.findall(text), KEY_SHAPE.findall(text)
    present = [p.pmid for p in COHORT_PAPERS if p.pmid in text]
    assert not present, f"bibliography pmids in the pre-registration: {present}"
    # the handoff's own counts are published, but restating them here would put
    # an inventory figure in a document whose whole claim is that it holds none
    handoff = json.loads(Path("handoff/for_harness.json").read_text())
    figures = {v for v in handoff["row_counts"].values()} | {
        v for v in handoff["fixture_sizes"].values()} | set(
        handoff["tier_counts"].values()) | {handoff["modal_covariate_set_size"]}
    seen = {int(n) for n in re.findall(r"\b\d+\b", text)}
    overlap = sorted(f for f in figures if f >= 10 and f in seen)
    assert not overlap, f"inventory figures restated: {overlap}"
