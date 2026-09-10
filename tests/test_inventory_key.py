"""The inventory-backed key table, and the pre-registration it is bound by.

Everything here runs against `tests/fake_tiered_inventory.json`. The real
inventory is on the key side and may never be in this clone, so nothing below
asserts against a real row, a real pmid or a real tier count.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from benchmark import baseline_score as B
from benchmark.cohort_papers import COHORT_PAPERS
from benchmark.inventory_key import (
    SideCounts,
    fold,
    key_table_from_inventory,
    side_exclusions,
)
from benchmark.tiered_score import HandoffMismatch, git_blob_hash
from generate.funnel import load_constructs
from pipeline.pose import construct_index
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

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


# --- task 1: the inventory-backed key table --------------------------------
#
# Against `tests/fake_tiered_inventory.json` only. Its keys are real instrument
# keys so the fold can actually run; every label, status and paper id in it is
# invented, and no real inventory row is in this clone.

FAKE = json.loads(Path("tests/fake_tiered_inventory.json").read_text())
PAPER = {p["paper"]: p for p in FAKE["papers"]}

#: The fixture's fA exposure: a MEMBER key whose construct is a different
#: string. The construct and its siblings are read from the build, never
#: written down here -- a hand-typed member list drifts from the dictionary.
FA_KEY = "m3:Q16.1_2"

#: A harness good enough to read rows under. The pin it carries is checked
#: against `inventory/schema.py` where that file exists, and this clone bars
#: it, so the tests that must see the pin BITE supply their own schema file.
HARNESS = json.loads(Path("handoff/for_harness.json").read_text())


@pytest.fixture(scope="module")
def index():
    try:
        constructs, _ = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    return construct_index(constructs)


def _record_on(key: str, construct_key: str) -> RetrievalRecord:
    """A resolved retrieval record whose hit landed on `key` in `construct_key`."""
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="sha256:x", role="exposure",
                                source="instrument"),
        query="sha256:x", dictionary_hash="3dc8415eccfe", min_cos=0.72,
        best_cos=0.9, margin=0.9 - 0.72, margin_12=0.1, abstained=False,
        nearest_key=key,
        hit=Hit(key=key, construct_key=construct_key,
                dict_construct_key=construct_key, module=key[1], target_id=1,
                fold_size=1, n_siblings=0, members=(key,), stratum="s",
                unmeasured_stratum=False))


def _table(papers, index, harness=None) -> dict:
    return {k.pmid: k for k in key_table_from_inventory(
        papers, HARNESS if harness is None else harness, index=index)}


# --- the fold, first: it is the trap the fixture was built to set ------------


def test_a_member_key_and_its_construct_fold_to_the_same_set(index):
    """The trap the fixture was built to set.

    Its own note: a scorer comparing keys as strings scores a correct
    resolution as a miss.
    """
    construct = index[FA_KEY].construct_key
    assert construct != FA_KEY, "the fixture's premise: member is not construct"
    assert fold(FA_KEY, index) == fold(construct, index)
    assert {FA_KEY, construct} <= fold(FA_KEY, index)
    assert fold("m9:Q99.9", index) == frozenset(), "an unheld key folds to nothing"


def test_a_folded_key_meets_a_record_on_the_construct_and_on_a_sibling(index):
    """Both directions of rule 2's fold, with a negative control.

    One: the inventory names a MEMBER and the run resolved to the CONSTRUCT.
    Two: the run resolved to a DIFFERENT member of the same construct, which
    no string comparison of the two keys can reach. The control is a key from
    another construct, which must not meet it -- a fold that matched
    everything would pass both directions and mean nothing.
    """
    construct = index[FA_KEY].construct_key
    sibling = next(m for m in index[FA_KEY].member_keys if m != FA_KEY)
    keys = frozenset(_table([PAPER["fA"]], index)["fA"].exposure_keys)

    assert keys & B.keys_of(_record_on(construct, construct)), "member -> construct"
    assert keys & B.keys_of(_record_on(sibling, construct)), "member -> sibling"
    other = PAPER["fA"]["outcomes"][0]["key"]
    assert not keys & B.keys_of(_record_on(other, other)), other


# --- the table's shape -------------------------------------------------------


def test_a_confident_present_pair_populates_both_sides(index):
    t = _table([PAPER["fA"]], index)["fA"]
    assert t.exposure_keys and t.outcome_keys
    assert FA_KEY in t.exposure_keys
    assert PAPER["fA"]["outcomes"][0]["key"] in t.outcome_keys
    # the inventory names keys, so nothing here is ever handed to the retriever
    assert t.exposure_terms == ()


@pytest.mark.parametrize(("paper", "empty_side", "populated_side"), [
    ("fB", "outcome_keys", "exposure_keys"),   # outcome reachable only by analogue
    ("fC", "outcome_keys", "exposure_keys"),   # outcome absent from the instrument
])
def test_a_modality_or_absent_side_yields_an_empty_tuple(index, paper, empty_side,
                                                         populated_side):
    t = _table([PAPER[paper]], index)[paper]
    assert getattr(t, empty_side) == (), f"{paper}: {empty_side} must be empty"
    assert getattr(t, populated_side), f"{paper}: {populated_side} must survive"


def test_a_paper_reachable_on_neither_side_yields_nothing_and_is_not_dropped(index):
    t = _table([PAPER["fD"]], index)
    assert set(t) == {"fD"}, "an unmatchable paper stays in the table"
    assert t["fD"].exposure_keys == () and t["fD"].outcome_keys == ()


def test_the_whole_fixture_keeps_every_paper_in_input_order(index):
    got = key_table_from_inventory(FAKE["papers"], HARNESS, index=index)
    assert [k.pmid for k in got] == [p["paper"] for p in FAKE["papers"]]


# --- rule 3: excluded, and counted -------------------------------------------


def test_every_row_is_counted_in_exactly_one_partition_cell(index):
    """No row may leave uncounted; that is what makes rule 3 checkable."""
    counts = side_exclusions(FAKE["papers"], index)
    for side in ("exposures", "outcomes"):
        rows = sum(len(p.get(side, [])) for p in FAKE["papers"])
        assert counts[side].rows_sum == rows, side
        assert counts[side].papers == len(FAKE["papers"])
        assert (counts[side].matchable_sides
                + counts[side].excluded_sides) == counts[side].papers


def test_a_not_confident_side_is_excluded_and_counted_never_dropped(index):
    """The fixture's fE carries an analogue key nobody could pin.

    It is excluded twice over -- a modality row never matches, and its
    `confident` is false -- and it must appear in BOTH counts, because a
    reader asking "how much did the reader's uncertainty cost" and a reader
    asking "how much did the modality rule cost" are asking different
    questions.
    """
    counts = side_exclusions([PAPER["fE"]], index)["outcomes"]
    assert _table([PAPER["fE"]], index)["fE"].outcome_keys == ()
    assert counts.rows_modality == 1
    assert counts.rows_not_confident_any_status == 1
    assert counts.excluded_sides == 1 and counts.matchable_sides == 0


def test_a_confident_false_present_row_is_counted_apart_from_an_absent_one(index):
    """Unsure is not absent.

    The partition must keep "the reader was unsure" apart from "not in the
    instrument". Binning both as absent would report a reader's hesitancy as
    an instrument gap.
    """
    unsure = [{"status": "present", "key": FA_KEY, "confident": False}]
    absent = [{"status": "absent", "key": None, "confident": True}]
    paper = {"paper": "fX", "exposures": unsure, "outcomes": absent}
    counts = side_exclusions([paper], index)
    assert counts["exposures"].rows_present_not_confident == 1
    assert counts["exposures"].rows_absent == 0
    assert counts["outcomes"].rows_absent == 1
    assert counts["outcomes"].rows_present_not_confident == 0
    assert _table([paper], index)["fX"].exposure_keys == ()


def test_a_key_the_build_does_not_hold_is_counted_as_unresolvable(index):
    """A key that names nothing is not an ordinary miss.

    It is a defect in the inventory or a moved build, and scoring it as a miss
    hides both.
    """
    paper = {"paper": "fY",
             "exposures": [{"status": "present", "key": "m9:Q99.9",
                            "confident": True}],
             "outcomes": [{"status": "present", "key": None, "confident": True}]}
    counts = side_exclusions([paper], index)
    assert counts["exposures"].rows_unresolvable == 1
    assert counts["outcomes"].rows_unresolvable == 1
    assert counts["exposures"].rows_absent == 0
    assert _table([paper], index)["fY"].exposure_keys == ()


def test_side_counts_add_up_across_papers(index):
    """Anti-vacuity: the totals are the papers summed, not a first paper's."""
    one = side_exclusions([PAPER["fA"]], index)
    two = side_exclusions([PAPER["fA"], PAPER["fA"]], index)
    for side in ("exposures", "outcomes"):
        assert two[side] == SideCounts(*(2 * v for v in one[side]))


# --- the schema pin ----------------------------------------------------------
#
# Verified against the schema FILE where the tree holds one. This clone bars
# `inventory/`, so a test that needs the pin to bite supplies its own file --
# the technique tests/test_tiered_score.py uses for the same reason.


def _schema(tmp_path) -> tuple[Path, str]:
    f = tmp_path / "schema.py"
    f.write_text("# a schema this test owns\n")
    return f, f"{f.as_posix()}@{git_blob_hash(f.read_bytes())[:12]}"


def test_a_matching_schema_pin_reads_the_rows(tmp_path, index):
    f, pin = _schema(tmp_path)
    got = key_table_from_inventory([PAPER["fA"]], {**HARNESS, "schema_version": pin},
                                   index=index, schema_path=f)
    assert got[0].exposure_keys


def test_a_changed_schema_version_string_fails_loudly(tmp_path, index):
    f, pin = _schema(tmp_path)
    moved = pin[:-1] + ("0" if pin[-1] != "0" else "1")
    with pytest.raises(HandoffMismatch, match="schema_version"):
        key_table_from_inventory([PAPER["fA"]], {**HARNESS, "schema_version": moved},
                                 index=index, schema_path=f)


def test_a_harness_naming_no_schema_is_refused_not_defaulted(index):
    for bad in ({}, {"schema_version": ""}):
        with pytest.raises(HandoffMismatch, match="names no schema_version"):
            key_table_from_inventory([PAPER["fA"]], bad, index=index)


def test_the_module_records_no_second_copy_of_the_pin():
    """One pin, computed.

    A `path@blob` literal here would restore the dual role that let a schema
    drift through `tiered_score` unnoticed: a live config value doubling as a
    historical record.
    """
    src = Path("benchmark/inventory_key.py").read_text()
    assert not re.findall(r"schema\.py@[0-9a-f]{6,}", src)
