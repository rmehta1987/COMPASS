"""The inventory-backed key table, and the pre-registration it is bound by.

Everything here runs against `tests/fake_tiered_inventory.json`. The real
inventory is on the key side and may never be in this clone, so nothing below
asserts against a real row, a real pmid or a real tier count.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from benchmark import baseline_score as B
from benchmark.cohort_papers import COHORT_PAPERS
from benchmark.inventory_key import (
    InventoryShape,
    SideAgreement,
    SideCounts,
    agreement,
    analogue_only,
    fold,
    in_frame,
    inventory_input,
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
        rows = sum(len(p[side]) for p in FAKE["papers"])
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


# --- task 2: the frame gate, on the fakes ------------------------------------


def test_a_papers_frame_membership_is_decided_on_folded_constructs(index):
    """The fixture's fA has a member key for an exposure; a frame names constructs.

    A frame test that compared the inventory's key against the frame's
    construct key would put every paper out of frame and read as "the run
    could reach nothing", which is the same wrong answer the old exposure rule
    gives for a different reason.
    """
    table = _table(FAKE["papers"], index)
    fa = table["fA"]
    exposure = index[FA_KEY].construct_key
    outcome = index[PAPER["fA"]["outcomes"][0]["key"]].construct_key

    assert in_frame(fa, [(exposure, outcome)], index)
    assert not in_frame(fa, [(outcome, exposure)], index), "the pair is ORDERED"
    assert not in_frame(fa, [], index)
    # a paper with an empty side can be in no frame, however rich the frame is
    assert not in_frame(table["fD"], [(exposure, outcome)], index)


def test_inventory_input_gates_the_frame_and_counts_the_rest(index):
    exposure = index[FA_KEY].construct_key
    outcome = index[PAPER["fA"]["outcomes"][0]["key"]].construct_key
    prepared = inventory_input(FAKE["papers"], HARNESS, index=index,
                               frame_pairs=[(exposure, outcome)])
    assert prepared.in_frame == frozenset({"fA"})
    assert len(prepared.table) == len(FAKE["papers"])
    assert set(prepared.excluded_sides) == {"exposures", "outcomes"}
    assert prepared.synthetic is False, "load_papers sets it; this call cannot"

    unknown = inventory_input(FAKE["papers"], HARNESS, index=index)
    assert unknown.in_frame is None, "no frame given is UNKNOWN, never empty"


def test_the_frame_is_enumerated_from_the_funnel_not_written_down():
    """Rule 4, asserted on the call node rather than on a substring.

    `pipeline.run.narrow_frame` is the frame `--frame-only` prints its count
    from. A hand-typed pair list would drift from it silently, so the wiring
    is what is pinned.
    """
    src = Path("benchmark/baseline_score.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "frame_pairs")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "narrow_frame" in called, called


def test_the_cli_needs_the_harness_whenever_it_is_given_an_inventory():
    """A harness guessed at is a pin that checks nothing."""
    for argv in (["a.json", "--sha", "x", "--inventory", "inv/"],
                 ["a.json", "--sha", "x", "--harness", "h.json"]):
        with pytest.raises(SystemExit) as e:
            B.main(argv)
        assert e.value.code == 2


# --- task S's dependency: the second reader's agreement ---------------------
#
# A hand-written key has no reliability estimate, and that number bounds every
# figure the inventory scores. The function is written here; the reading it
# compares is the operator's step in the scoring clone, and nothing below
# touches a real paper.


def _row(label, status="present", key=None, confident=True, field="label") -> dict:
    return {field: label, "status": status, "key": key, "analogue_key": None,
            "confident": confident}


def _paper(pid, exposures, outcomes) -> dict:
    return {"paper": pid, "exposures": exposures, "outcomes": outcomes}


def test_two_identical_readings_agree_on_every_shared_row(index):
    a = [_paper("fA", [_row("smoking", key=FA_KEY)], [_row("bp", key="m2:Q5.19")])]
    got = agreement(a, [dict(p) for p in a], index)
    assert got.per_paper["fA"]["exposures"] == SideAgreement(
        labels_both=1, labels_a_only=0, labels_b_only=0, labels_repeated=0,
        status_agree=1, status_compared=1, key_agree=1, key_compared=1)
    assert got.pooled["outcomes"].status_agree == 1


def test_a_member_and_its_construct_are_not_a_disagreement(index):
    """A member and its construct name the same variable.

    Two readers who picked one each did not disagree, and scoring it as a miss
    would inflate the disagreement the operator has to adjudicate.
    """
    construct = index[FA_KEY].construct_key
    a = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    b = [_paper("fA", [_row("smoking", key=construct)], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.key_agree == 1 and side.key_compared == 1


def test_two_readers_who_typed_the_same_unheld_key_agree(index):
    """String identity first, folding second.

    Both readers typed the same key and the build no longer holds it -- an
    older build, a superseded item, a typo copied from one source. Folding
    alone gives two empty sets, whose intersection is empty, so two readers
    who literally agree would be counted as disagreeing.
    """
    a = [_paper("fA", [_row("smoking", key="m9:Q99.9")], [])]
    b = [_paper("fA", [_row("smoking", key="m9:Q99.9")], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.key_agree == 1 and side.key_compared == 1


def test_a_real_key_disagreement_is_counted_as_one(index):
    a = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    b = [_paper("fA", [_row("smoking", key="m2:Q5.19")], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.status_agree == 1, "both still called it present"
    assert side.key_agree == 0 and side.key_compared == 1


def test_a_status_disagreement_is_not_compared_on_keys(index):
    """Key agreement is taken only over rows BOTH readers called present.

    Comparing keys where one reader said absent would count a row twice, once
    as a status disagreement and once as a key one.
    """
    a = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    b = [_paper("fA", [_row("smoking", status="absent")], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.status_agree == 0 and side.status_compared == 1
    assert side.key_compared == 0, "no shared present row, so no key denominator"


def test_a_missing_status_on_both_sides_is_not_agreement(index):
    """`None == None` would report a renamed field as a perfect reading."""
    a = [_paper("fA", [{"label": "smoking", "key": FA_KEY}], [])]
    b = [_paper("fA", [{"label": "smoking", "key": FA_KEY}], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.labels_both == 1, "the row is still joined"
    assert side.status_compared == 0, "nothing carried a status to compare"
    assert side.status_agree == 0


def test_rows_named_term_rather_than_label_are_joined(index):
    """The real inventory's anchor rows are read as `term`.

    tiered_score::attach_pairs, the only code here that touches the real
    rows, reads paper["exposures"][i]["term"]; the fixture spells it `label`
    and carries no `term` at all. Reading one and not the other returns a
    clean table of zeros, which looks like a finished comparison.
    """
    a = [_paper("fA", [_row("smoking", key=FA_KEY, field="term")], [])]
    b = [_paper("fA", [_row("smoking", key=FA_KEY, field="label")], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.labels_both == 1 and side.key_agree == 1


def test_a_side_whose_rows_carry_no_name_is_refused_not_scored_zero(index):
    a = [_paper("fA", [{"status": "present", "key": FA_KEY}], [])]
    b = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    with pytest.raises(InventoryShape, match="not one carries a name"):
        agreement(a, b, index)


def test_a_label_a_reader_listed_twice_is_counted_not_merged(index):
    a = [_paper("fA", [_row("smoking", key=FA_KEY),
                       _row("smoking", status="absent")], [])]
    b = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert side.labels_repeated == 1, "the second row is an adjudication item"
    assert side.labels_both == 1


def test_a_variable_only_one_reader_listed_has_no_denominator(index):
    a = [_paper("fA", [_row("smoking", key=FA_KEY), _row("alcohol", key="m2:Q5.19")],
                [])]
    b = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    side = agreement(a, b, index).per_paper["fA"]["exposures"]
    assert (side.labels_both, side.labels_a_only, side.labels_b_only) == (1, 1, 0)
    assert side.status_compared == 1, "the unshared row is not a comparison"


def test_a_paper_only_one_reader_covered_is_counted_apart_not_scored(index):
    a = [_paper("fA", [_row("smoking", key=FA_KEY)], []),
         _paper("fB", [_row("x", key=FA_KEY)], [])]
    b = [_paper("fA", [_row("smoking", key=FA_KEY)], [])]
    got = agreement(a, b, index)
    assert set(got.per_paper) == {"fA"}, "coverage is not reliability"
    assert got.papers_a_only == 1 and got.papers_b_only == 0


def test_the_pooled_figures_are_the_papers_summed_and_kept_apart(index):
    one = _paper("fA", [_row("smoking", key=FA_KEY)], [])
    two = _paper("fB", [_row("smoking", key=FA_KEY)], [])
    got = agreement([one, two], [dict(one), dict(two)], index)
    assert got.pooled["exposures"].status_compared == 2
    assert got.pooled["exposures"].key_compared == 2
    # the pooled row does not share a namespace with the paper ids
    assert "__pooled__" not in got.per_paper
    assert len(got.per_paper) == 2, "len() is the papers compared, exactly"
    assert all(isinstance(v, int) for v in got.pooled["exposures"])


def test_one_reader_carrying_a_paper_twice_is_refused(index):
    one = _paper("fA", [_row("smoking", key=FA_KEY)], [])
    with pytest.raises(InventoryShape, match="carries fA twice"):
        agreement([one, dict(one)], [dict(one)], index)


def test_agreement_pins_the_schema_when_it_is_given_a_harness(tmp_path, index):
    f, pin = _schema(tmp_path)
    one = _paper("fA", [_row("smoking", key=FA_KEY)], [])
    moved = pin[:-1] + ("0" if pin[-1] != "0" else "1")
    with pytest.raises(HandoffMismatch, match="schema_version"):
        agreement([one], [dict(one)], index, {**HARNESS, "schema_version": moved},
                  schema_path=f)


# --- the shapes that used to be published as findings about the instrument ---


def test_a_missing_anchor_side_is_refused_not_read_as_an_instrument_gap(index):
    """An absent side is not an empty one.

    `paper.get(side, [])` counted a side the document does not carry as an
    excluded side, indistinguishable from a variable the instrument lacks.
    """
    paper = {"paper": "fX", "exposures": [_row("smoking", key=FA_KEY)]}
    with pytest.raises(InventoryShape, match="no 'outcomes' in this paper"):
        key_table_from_inventory([paper], HARNESS, index=index)
    with pytest.raises(InventoryShape, match="no 'outcomes' in this paper"):
        side_exclusions([paper], index)


def test_an_unrecognised_status_is_refused_not_binned_as_absent(index):
    """An unrecognised status must not become an instrument claim.

    `rows_absent` is a catch-all `else` and its documented meaning is a claim
    about the INSTRUMENT. A respelling of `present` would empty every side and
    the report would print that as a finding.
    """
    paper = _paper("fX", [_row("smoking", "Present", key=FA_KEY)],
                   [_row("bp", key="m2:Q5.19")])
    with pytest.raises(InventoryShape, match="status 'Present' is not one of"):
        key_table_from_inventory([paper], HARNESS, index=index)


def test_a_harness_whose_vocabulary_lacks_present_is_refused(index):
    paper = _paper("fX", [_row("smoking", key=FA_KEY)], [])
    bad = {**HARNESS, "status_values": ["seen", "modality", "absent"]}
    with pytest.raises(HandoffMismatch, match="do not contain 'present'"):
        key_table_from_inventory([paper], bad, index=index)


def test_a_paper_id_appearing_twice_is_refused(index):
    paper = _paper("fA", [_row("smoking", key=FA_KEY)], [])
    with pytest.raises(InventoryShape, match="fA appears twice"):
        key_table_from_inventory([paper, dict(paper)], HARNESS, index=index)


def test_a_paper_with_no_id_at_all_is_refused_by_name(index):
    paper = {"exposures": [], "outcomes": []}
    with pytest.raises(InventoryShape, match="neither `paper` nor `pmid`"):
        key_table_from_inventory([paper], HARNESS, index=index)


def test_the_rows_own_schema_version_is_pinned_against_the_harness(index):
    """The rows are pinned too, not just the harness.

    The pin used to check the harness against the tree and the rows against
    nothing. The fixture in this repository declares an OLDER schema than the
    harness does, and that went unnoticed until a hostile review said so.
    """
    assert FAKE["schema_version"] != HARNESS["schema_version"], "the premise"
    with pytest.raises(HandoffMismatch, match="rows were written under"):
        key_table_from_inventory(FAKE["papers"], HARNESS, index=index,
                                 rows_schema_version=FAKE["schema_version"])
    # matching versions read normally
    got = key_table_from_inventory(
        FAKE["papers"], {**HARNESS, "schema_version": FAKE["schema_version"]},
        index=index, rows_schema_version=FAKE["schema_version"])
    assert len(got) == len(FAKE["papers"])


def test_an_analogue_key_the_build_does_not_hold_is_not_reachable(index):
    """A key naming nothing is not a measurement.

    `analogue_only` asserts the instrument carries another measurement, so the
    analogue key is resolved exactly as a present key is.
    """
    real = _paper("fX", [_row("e", "modality", key=None)],
                  [_row("o", "modality", key=None)])
    for side in ("exposures", "outcomes"):
        real[side][0]["analogue_key"] = "m2:Q5.19"
    assert analogue_only(real, index)
    stale = _paper("fY", [_row("e", "modality", key=None)],
                   [_row("o", "modality", key=None)])
    for side in ("exposures", "outcomes"):
        stale[side][0]["analogue_key"] = "m9:Q99.9"
    assert not analogue_only(stale, index), "a key naming nothing is not a measurement"


def test_in_frame_does_not_consume_the_pairs_it_is_given(index):
    """A one-shot iterator is refused rather than quietly half-read.

    in_frame is called once per paper and `any` short-circuits, so a shared
    generator would be consumed by the first paper and every later one would
    read as out of frame -- and if that lands on zero the report prints "no
    matchable paper was in the frame", a false structural conclusion.
    Materialising inside the function does NOT fix this: the generator is
    already exhausted by the time the second call arrives.
    """
    exposure = index[FA_KEY].construct_key
    outcome = index[PAPER["fA"]["outcomes"][0]["key"]].construct_key
    table = _table(FAKE["papers"], index)
    pairs = ((e, o) for e, o in [(exposure, outcome)])
    with pytest.raises(InventoryShape, match="one-shot"):
        in_frame(table["fA"], pairs, index)
    # the same pairs as a list answer the same way for every paper, twice over
    materialised = [(exposure, outcome)]
    assert in_frame(table["fA"], materialised, index)
    assert in_frame(table["fA"], materialised, index)


def test_the_partition_is_checked_against_an_independently_counted_total(index):
    """rows_seen is counted at the top of the loop, before any branch."""
    counts = side_exclusions(FAKE["papers"], index, HARNESS["status_values"])
    for side in ("exposures", "outcomes"):
        rows = sum(len(p[side]) for p in FAKE["papers"])
        assert counts[side].rows_seen == rows, side
        assert counts[side].partition_holds, side
        assert counts[side].rows_sum == rows
