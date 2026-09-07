"""The tiered harness's declared shape.

Every acceptance here is against synthetic fixtures: the real tiers derive
from the inventory and `inventory/case_map.json`, neither of which may be in
this clone, so nothing here may assert against the real `tier_counts`.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from benchmark import tiered_score
from benchmark.tiered_score import (
    MATRIX,
    RECORD_DIRECTIONS,
    SCOREABLE_CELLS,
    TIERS,
    Anchor,
    Cell,
    HandoffMismatch,
    Refusal,
    SideState,
    UnclassifiablePaper,
    analogue_scores,
    anchor_scores,
    built_dictionary_hash,
    covariate_score,
    direction_scores,
    direction_summary,
    directions_by_case,
    load_handoff,
    main,
    margin_score,
    modal_covariates,
    modal_size_disagreement,
    refusal_scores,
    scorable_covariates,
    self_check,
    side_state,
    tier_of,
    tiers_of,
)
from env.tools import resolve_variable
from generate.funnel import load_constructs
from pipeline.pose import construct_index


def test_the_declared_matrix_is_consistent():
    assert self_check() == []


def test_every_component_has_one_cell_per_tier():
    for row in MATRIX:
        assert len(row.cells) == len(TIERS), row.name


def test_the_half_available_row_names_what_blocks_it_and_keeps_its_row():
    # A missing row reads as "not applicable" when it means "not yet built",
    # so the blocked component stays in the matrix with its blocker named.
    half = [row for row in MATRIX if Cell.HALF in row.cells]
    assert [row.name for row in half] == ["modality analogue resolution"]
    assert "16-19" in half[0].blocked


def test_a_dropped_row_is_caught_rather_than_shortening_the_report():
    # Seeded failure for the pin: the scoreable-cell count is what notices a
    # component that quietly leaves the report.
    dropped = MATRIX[:-1]
    scoreable = sum(1 for row in dropped for c in row.cells if c is not Cell.NA)
    assert scoreable != SCOREABLE_CELLS


def test_the_self_check_cli_exits_zero(capsys):
    assert main(["--self-check"]) == 0
    assert "0 problems" in capsys.readouterr().out


# --- item 2: the synthetic tiered inventory -------------------------------
# The real inventory and inventory/case_map.json may never be in this clone,
# so every tier assertion in this file is against these five invented papers.

FAKE = json.loads(Path("tests/fake_tiered_inventory.json").read_text())
HANDOFF = json.loads(Path("handoff/for_harness.json").read_text())
PAPERS = FAKE["papers"]


def _rows(paper: dict) -> list[dict]:
    return [*paper["exposures"], *paper["outcomes"], *paper["covariates"]]


def test_the_fixture_says_it_is_synthetic():
    # A number scored against a synthetic inventory is a rehearsal, not a
    # measurement, and the fixture has to say so where a reader will see it.
    assert FAKE["synthetic"] is True
    assert "SYNTHETIC" in FAKE["notes"]


def test_one_paper_per_tier_plus_the_predicate_exerciser():
    assert [p["paper"] for p in PAPERS] == ["fA", "fB", "fC", "fD", "fE"]
    assert {p["intended_tier"] for p in PAPERS} == {"A", "B", "C", "D"}
    assert len(PAPERS) == 5


def test_the_exerciser_is_the_only_paper_the_two_readings_disagree_on():
    # 2a: without this shape the tier_rule assertion is never tested, because
    # confident_anchor and the bare-status reading agree on every other paper
    # and a mismatch would be silent.
    disagree = [p["paper"] for p in PAPERS
                if p["intended_tier"] != p["intended_tier_bare_status"]]
    assert disagree == ["fE"]
    fe = next(p for p in PAPERS if p["paper"] == "fE")
    (outcome,) = fe["outcomes"]
    assert outcome["status"] == "modality"
    assert outcome["analogue_key"] is not None
    assert outcome["confident"] is False
    assert (fe["intended_tier"], fe["intended_tier_bare_status"]) == ("D", "C")


def test_the_fixture_speaks_the_handoffs_vocabulary():
    # Taken from handoff/for_harness.json at run time, never restated here:
    # a vocabulary this file spelled out again would not notice the real one moving.
    statuses = set(HANDOFF["status_values"])
    modalities = set(HANDOFF["modality_values"])
    for paper in PAPERS:
        for row in _rows(paper):
            assert row["status"] in statuses, (paper["paper"], row)
            if row["status"] == "modality":
                assert row["modality"] in modalities, (paper["paper"], row)
                assert row["analogue_key"] is not None
            if row["status"] == "absent":
                assert row["key"] is None and row["analogue_key"] is None


def test_every_fixture_key_names_a_real_variable():
    # The labels are invented; the keys are real, so resolution, recall and the
    # modal set run against the built dictionary rather than against nothing.
    for paper in PAPERS:
        for row in _rows(paper):
            for key in (row["key"], row["analogue_key"]):
                if key is not None:
                    assert resolve_variable(key)["outcome"] == "unique", key


def test_the_fixture_carries_no_pmid_shaped_id():
    # fA..fE, never a pmid: the paper identity is what the opaque case ids exist
    # to withhold, and a fixture is an easy place to smuggle one back in.
    assert not re.search(r"\b\d{8}\b", json.dumps(FAKE))


def test_pair_counts_are_unbalanced_so_weighting_has_something_to_bite_on():
    # 11a: one real paper holds 23 of 95 triples, so an unweighted rate measures
    # that paper. The fixture reproduces the shape at small scale.
    counts = {p["paper"]: len(p["pairs"]) for p in PAPERS}
    assert counts == {"fA": 1, "fB": 2, "fC": 6, "fD": 1, "fE": 2}
    assert max(counts.values()) * 2 == sum(counts.values())
    ids = [pair["case_id"] for p in PAPERS for pair in p["pairs"]]
    assert len(set(ids)) == len(ids)


# --- item 4: the handoff header -------------------------------------------


def _handoff_at(tmp_path: Path, **overrides: object) -> Path:
    raw = dict(HANDOFF)
    raw.update(overrides)
    path = tmp_path / "for_harness.json"
    path.write_text(json.dumps(raw))
    return path


def test_the_handoff_loads_and_carries_the_vocabulary(tmp_path):
    h = load_handoff(_handoff_at(tmp_path))
    assert h.status_values == ("present", "modality", "absent")
    assert h.modality_values[0] == "self_report"
    assert h.modal_covariate_set_size == HANDOFF["modal_covariate_set_size"]
    assert h.raw == HANDOFF


def test_the_tree_holds_the_build_the_handoff_names():
    # Not a restated constant: read from the build's own version.json, so a
    # rebuild that moves the dictionary under the harness is caught.
    assert load_handoff().dictionary_version_hash == built_dictionary_hash()


@pytest.mark.parametrize(
    ("field", "value"),
    [("dictionary_version_hash", "deadbeefcafe"),
     ("schema_version", "inventory/schema.py@0000000000ff"),
     ("tier_rule", "bare_status")])
def test_each_pinned_field_raises_rather_than_warning(tmp_path, field, value):
    # 4a: all three are silent failures otherwise. The bare-status reading in
    # particular gives C=8 D=5 against C=7 D=6, and both sum to 16.
    with pytest.raises(HandoffMismatch) as e:
        load_handoff(_handoff_at(tmp_path, **{field: value}))
    assert field in str(e.value)


def test_a_missing_required_field_is_a_mismatch_not_a_default(tmp_path):
    raw = {k: v for k, v in HANDOFF.items() if k != "modal_covariate_set_size"}
    path = tmp_path / "for_harness.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(HandoffMismatch, match="modal_covariate_set_size"):
        load_handoff(path)


def test_an_absent_handoff_names_the_operator_step(tmp_path):
    with pytest.raises(HandoffMismatch, match="handoff-public"):
        load_handoff(tmp_path / "nothing.json")


def test_the_self_check_fails_when_the_handoff_disagrees(monkeypatch, tmp_path):
    monkeypatch.setattr(tiered_score, "HANDOFF_PATH", tmp_path / "gone.json")
    assert any("absent" in p for p in self_check())


def test_nothing_here_asserts_against_the_real_tier_counts():
    # 5a: tiers derive from the inventory and case_map.json, neither of which
    # may be in this clone. The counts are carried for the scoring clone and
    # are not an acceptance here.
    # An AST walk, not a substring scan: prose about the rule is not a
    # violation of it, and only an assert statement can smuggle one in.
    source = Path("tests/test_tiered_score.py").read_text()
    tree = ast.parse(source)
    here = "test_nothing_here_asserts_against_the_real_tier_counts"
    offenders = [
        ast.get_source_segment(source, node)
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and fn.name != here
        for node in ast.walk(fn)
        if isinstance(node, ast.Assert)
        and "tier_counts" in (ast.get_source_segment(source, node) or "")
    ]
    assert offenders == []


# --- item 5: tier assignment, against the fakes only ----------------------


def test_the_predicate_places_all_five_fakes_as_intended():
    assert tiers_of(PAPERS) == {p["paper"]: p["intended_tier"] for p in PAPERS}


def test_the_default_reading_is_confident_anchor_on_every_entry_point():
    # A first seeding flipped tier_of's own default and nothing went red:
    # tiers_of forwards require_confident explicitly, so the tests that go
    # through it masked the change. Each entry point is pinned on its own.
    by_id = {p["paper"]: p for p in PAPERS}
    assert tier_of(by_id["fE"]) == "D"
    assert tiers_of(PAPERS)["fE"] == "D"
    assert side_state(by_id["fE"]["outcomes"]) is SideState.UNREACHABLE


def test_dropping_the_confident_conjunct_moves_exactly_the_exerciser():
    # The assertion that the rule is confident_anchor and not bare status is
    # only worth anything if the two readings differ somewhere: on the real
    # inventory they differ on one paper, and fE is that shape.
    strict = tiers_of(PAPERS)
    bare = tiers_of(PAPERS, require_confident=False)
    moved = {k: (strict[k], bare[k]) for k in strict if strict[k] != bare[k]}
    assert moved == {"fE": ("D", "C")}
    assert bare == {p["paper"]: p["intended_tier_bare_status"] for p in PAPERS}


def test_each_side_is_classified_from_its_own_rows():
    by_id = {p["paper"]: p for p in PAPERS}
    assert side_state(by_id["fA"]["outcomes"]) is SideState.PRESENT
    assert side_state(by_id["fB"]["outcomes"]) is SideState.MODALITY
    assert side_state(by_id["fC"]["outcomes"]) is SideState.UNREACHABLE
    assert side_state(by_id["fE"]["outcomes"]) is SideState.UNREACHABLE
    bare = side_state(by_id["fE"]["outcomes"], require_confident=False)
    assert bare is SideState.MODALITY


def test_a_present_row_that_lost_its_key_is_not_reachable():
    # The keyed conjunct never discriminates on the real inventory; it is kept
    # because a row without a key names nothing a hypothesis could resolve to.
    row = {"status": "present", "key": None, "analogue_key": None,
           "modality": None, "confident": True}
    assert side_state([row]) is SideState.UNREACHABLE


def test_a_shape_the_rule_does_not_place_raises_rather_than_being_binned():
    both_modality = {
        "paper": "fX",
        "exposures": [{"status": "modality", "key": None, "analogue_key": "m1:Q5.4",
                       "modality": "measured", "confident": True}],
        "outcomes": [{"status": "modality", "key": None, "analogue_key": "m2:Q5.8",
                      "modality": "measured", "confident": True}]}
    with pytest.raises(UnclassifiablePaper, match="not placed by the tier rule"):
        tier_of(both_modality)


# --- item 6: anchor resolution --------------------------------------------


@pytest.fixture(scope="module")
def construct_of():
    # The inventory names variable keys and a run resolves to constructs, so
    # the comparison needs the build's own key -> construct map.
    try:
        C, _ = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    idx = construct_index(C)
    return lambda key: idx[key].construct_key if key in idx else None


def _case(case_id: str, exposure: str | None, outcome: str | None) -> dict:
    def side(ck: str | None) -> dict:
        return {"term": "synthetic term", "abstained": ck is None,
                "best_cos": 0.9 if ck else 0.1,
                "nearest_key": ck or "m9:Q0", "construct_key": ck}
    return {"case_id": case_id, "state": "emitted", "artefact": "a.json",
            "note": "", "exposure": side(exposure), "outcome": side(outcome)}


def test_a_side_that_lands_on_its_own_key_scores_a_hit(construct_of):
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    e_key = fa["exposures"][0]["key"]
    o_key = fa["outcomes"][0]["key"]
    case = _case("f001", construct_of(e_key), construct_of(o_key))
    (score,) = anchor_scores([case], {"f001": fa}, construct_of)
    assert (score.exposure, score.outcome) == (Anchor.KEY, Anchor.KEY)
    assert score.hits == 2 and score.scoreable == 2


def test_a_side_that_lands_elsewhere_is_not_a_hit_and_is_not_an_abstention(
        construct_of):
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    case = _case("f001", construct_of("m1:Q5.4"), construct_of(fa["outcomes"][0]["key"]))
    (score,) = anchor_scores([case], {"f001": fa}, construct_of)
    assert score.exposure is Anchor.ELSEWHERE
    assert score.hits == 1 and score.scoreable == 2


def test_an_abstention_is_its_own_verdict(construct_of):
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    case = _case("f001", None, construct_of(fa["outcomes"][0]["key"]))
    (score,) = anchor_scores([case], {"f001": fa}, construct_of)
    assert score.exposure is Anchor.ABSTAINED
    assert score.hits == 1


def test_a_modality_or_absent_side_is_not_scored_here(construct_of):
    # The matrix gives anchor resolution one side in tier C and nothing in D:
    # a side with no present key has no key to resolve to, and scoring it here
    # would double-count what items 7 and 8 score.
    fb = next(p for p in PAPERS if p["paper"] == "fB")
    fd = next(p for p in PAPERS if p["paper"] == "fD")
    (b,) = anchor_scores([_case("f002", construct_of("m2:Q9.69"), "m2:Q5.8")],
                         {"f002": fb}, construct_of)
    assert b.outcome is Anchor.NOT_SCOREABLE and b.scoreable == 1
    (d,) = anchor_scores([_case("f010", None, None)], {"f010": fd}, construct_of)
    assert (d.exposure, d.outcome) == (Anchor.NOT_SCOREABLE,) * 2
    assert d.scoreable == 0


def test_a_case_with_no_paper_is_dropped_rather_than_scored_against_nothing(
        construct_of):
    assert anchor_scores([_case("f999", "m2:Q5.8", "m2:Q5.8")], {}, construct_of) == []


def test_a_variable_key_is_never_compared_with_a_construct_key(construct_of):
    # The inventory's m2:Q9.105 sits in a construct with a different key on
    # this build; comparing the two strings directly would score a correct
    # resolution as a miss.
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    key = fa["exposures"][0]["key"]
    assert construct_of(key) is not None and construct_of(key) != key, (
        "the fixture must hold a member key, or this test passes vacuously")
    case = _case("f001", construct_of(key), construct_of(fa["outcomes"][0]["key"]))
    (score,) = anchor_scores([case], {"f001": fa}, construct_of)
    assert score.exposure is Anchor.KEY


# --- item 7: refusal on an unreachable anchor -----------------------------


def _state(case: dict, state: str) -> dict:
    return {**case, "state": state}


def test_an_abstention_on_an_absent_anchor_is_a_refusal():
    fd = next(p for p in PAPERS if p["paper"] == "fD")
    case = _state(_case("f010", None, None), "unresolved_anchor")
    (score,) = refusal_scores([case], {"f010": fd})
    assert (score.exposure, score.outcome) == (Refusal.AT_RETRIEVAL,) * 2
    assert score.refused == 2 and score.scoreable == 2 and score.approximated == 0


def test_a_record_built_on_an_absent_anchor_is_an_approximation():
    # The failure this component exists to count: the instrument has no
    # variable for the side and the pipeline produced a protocol anyway.
    fd = next(p for p in PAPERS if p["paper"] == "fD")
    case = _state(_case("f010", "m1:Q5.4", "m2:Q5.8"), "emitted")
    (score,) = refusal_scores([case], {"f010": fd})
    assert (score.exposure, score.outcome) == (Refusal.APPROXIMATED,) * 2
    assert score.refused == 0 and score.approximated == 2


def test_a_specifier_refusal_counts_separately_from_an_abstention():
    fd = next(p for p in PAPERS if p["paper"] == "fD")
    case = _state(_case("f010", "m1:Q5.4", "m2:Q5.8"), "refused")
    (score,) = refusal_scores([case], {"f010": fd})
    assert (score.exposure, score.outcome) == (Refusal.BY_SPECIFIER,) * 2
    assert score.refused == 2


def test_only_the_unreachable_side_of_a_tier_c_case_is_scored():
    # The matrix: refusal has one side in tier C and both in D. The reachable
    # side is item 6's, and counting it here would double-count the case.
    fc = next(p for p in PAPERS if p["paper"] == "fC")
    case = _state(_case("f004", "m2:Q9.105", None), "unresolved_anchor")
    (score,) = refusal_scores([case], {"f004": fc})
    assert score.exposure is Refusal.NOT_SCOREABLE
    assert score.outcome is Refusal.AT_RETRIEVAL
    assert score.scoreable == 1


def test_an_unpinned_modality_side_is_an_unreachable_anchor_too():
    # fE's outcome is a modality row with an analogue but confident=false.
    # Under the tier rule that side is unreachable, so refusal is the correct
    # behaviour there and the component scores it.
    fe = next(p for p in PAPERS if p["paper"] == "fE")
    case = _state(_case("f011", None, None), "unresolved_anchor")
    (score,) = refusal_scores([case], {"f011": fe})
    assert score.scoreable == 2 and score.refused == 2


def test_a_reachable_case_contributes_nothing_to_the_refusal_denominator():
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    case = _state(_case("f001", "m3:Q16.1", "m2:Q5.19"), "emitted")
    (score,) = refusal_scores([case], {"f001": fa})
    assert score.scoreable == 0 and score.refused == 0


# --- item 8: modality analogue resolution, the half that exists -----------


def test_a_modality_side_that_lands_on_the_analogue_scores_a_hit(construct_of):
    fb = next(p for p in PAPERS if p["paper"] == "fB")
    analogue = fb["outcomes"][0]["analogue_key"]
    case = _case("f002", "m2:Q9.69", construct_of(analogue))
    (score,) = analogue_scores([case], {"f002": fb}, construct_of)
    assert score.outcome is Anchor.KEY
    assert score.exposure is Anchor.NOT_SCOREABLE, "the present side is item 6's"
    assert score.scoreable == 1 and score.hits == 1


def test_a_modality_side_that_lands_elsewhere_is_not_a_hit(construct_of):
    fb = next(p for p in PAPERS if p["paper"] == "fB")
    case = _case("f002", "m2:Q9.69", construct_of("m1:Q5.4"))
    (score,) = analogue_scores([case], {"f002": fb}, construct_of)
    assert score.outcome is Anchor.ELSEWHERE and score.hits == 0


def test_an_unpinned_modality_side_is_not_this_components_either(construct_of):
    # fE's outcome carries an analogue but confident=false, so the tier rule
    # calls it unreachable: it is item 7's refusal case, not an analogue to hit.
    fe = next(p for p in PAPERS if p["paper"] == "fE")
    case = _case("f011", None, construct_of("m2:Q5.8"))
    (score,) = analogue_scores([case], {"f011": fe}, construct_of)
    assert score.scoreable == 0


def test_the_unbuilt_half_reports_unknown_and_never_false(construct_of):
    # None, not False: False would read as "the pipeline failed to flag the
    # substitution", which is a claim about the pipeline nobody has measured.
    fb = next(p for p in PAPERS if p["paper"] == "fB")
    case = _case("f002", "m2:Q9.69", construct_of("m2:Q5.8"))
    (score,) = analogue_scores([case], {"f002": fb}, construct_of)
    assert score.mismatch_flagged is None
    assert tiered_score.MODALITY_MISMATCH_AVAILABLE is False
    assert "16-19" in tiered_score.MODALITY_MISMATCH_BLOCKER


def test_turning_the_blocked_half_on_without_wiring_it_raises(monkeypatch,
                                                              construct_of):
    monkeypatch.setattr(tiered_score, "MODALITY_MISMATCH_AVAILABLE", True)
    with pytest.raises(NotImplementedError, match="16-19"):
        analogue_scores([], {}, construct_of)
    assert any("half available" in p for p in self_check())


def test_the_matrix_keeps_the_row_the_blocked_half_belongs_to():
    (row,) = [r for r in MATRIX if Cell.HALF in r.cells]
    assert row.name == "modality analogue resolution"
    assert row.cells[TIERS.index("B")] is Cell.HALF
    assert row.cells[TIERS.index("C")] is Cell.HALF


# --- item 9: covariate recall, raw ----------------------------------------


def test_recall_is_over_the_recoverable_rows_and_says_what_it_left_out():
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    # fA has four covariate rows; the unpinned one is not scorable.
    score = covariate_score("f001", fa, ["m1:Q5.4", "m2:Q5.6", "m2:Q9.201"])
    assert score.recoverable == 3 and score.paper_covariates == 4
    assert score.excluded == {"not_confident": 1}
    assert score.hits == 2 and score.recall == pytest.approx(2 / 3)
    assert score.precision == pytest.approx(2 / 3)


def test_a_paper_with_nothing_recoverable_reports_none_not_zero():
    # 0.0 reads as a measured zero; None says the question could not be asked.
    empty = {"paper": "fZ", "covariates": []}
    score = covariate_score("f999", empty, ["m1:Q5.4"])
    assert score.recall is None and score.recoverable == 0
    assert score.precision == 0.0


def test_an_empty_adjustment_set_has_no_precision_but_a_real_recall():
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    score = covariate_score("f001", fa, [])
    assert score.precision is None
    assert score.recall == 0.0 and score.recoverable == 3


def test_covariates_are_compared_variable_key_to_variable_key():
    # Both sides are variable keys, unlike the anchors, whose retrieval side is
    # a construct. A record adjusting for a sibling of the paper's covariate is
    # not a hit, and the harness must not quietly widen to the construct.
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    assert "m1:Q5.4" in scorable_covariates(fa)
    assert covariate_score("f001", fa, ["m1:Q5.4_2"]).hits == 0


def test_an_absent_or_unkeyed_row_is_excluded_by_its_own_reason():
    paper = {"paper": "fY", "covariates": [
        {"status": "absent", "key": None, "analogue_key": None,
         "modality": None, "confident": True},
        {"status": "modality", "key": None, "analogue_key": "m1:Q5.4",
         "modality": "measured", "confident": True},
        {"status": "present", "key": "m2:Q5.6", "analogue_key": None,
         "modality": None, "confident": False}]}
    score = covariate_score("f999", paper, [])
    assert score.excluded == {"absent": 1, "modality": 1, "not_confident": 1}
    assert score.recoverable == 0 and score.paper_covariates == 3


# --- item 10: the margin over the modal set -------------------------------


def test_the_modal_set_is_computed_from_the_inventory_not_written_down():
    # 10a: for_harness.json ships only modal_covariate_set_size, so no covariate
    # term or key crosses into this clone; the set itself is computed.
    modal = modal_covariates(PAPERS)
    assert modal == {"m1:Q5.4", "m2:Q5.6"}
    # m2:Q9.1 is in two of the five papers, below the majority threshold.
    assert "m2:Q9.1" not in modal


def test_this_module_holds_no_variable_key_literal():
    # The rule 10a states, enforced: a hardcoded modal set would be a covariate
    # term crossing the boundary, and it would also stop being a measurement.
    source = Path("benchmark/tiered_score.py").read_text()
    assert not re.search(r"\bm[123]:Q\d", source)


def test_the_margin_is_recall_minus_what_convention_alone_would_have_scored():
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    modal = modal_covariates(PAPERS)
    # fA's recoverable covariates are income, diabetes and menarche; the modal
    # set holds the first two, so convention alone recovers two of three.
    score = covariate_score("f001", fa, ["m1:Q5.4", "m2:Q5.6", "m2:Q9.1"])
    margin = margin_score(score, fa, modal)
    assert margin.recall == 1.0
    assert margin.modal_recall == pytest.approx(2 / 3)
    assert margin.margin == pytest.approx(1 / 3)
    assert margin.modal_size == 2


def test_a_record_that_only_reproduces_convention_has_a_zero_margin():
    # The raw number is not the result: this record scores 2/3 recall and adds
    # nothing over the set a specifier could propose without reading anything.
    fa = next(p for p in PAPERS if p["paper"] == "fA")
    modal = modal_covariates(PAPERS)
    score = covariate_score("f001", fa, sorted(modal))
    margin = margin_score(score, fa, modal)
    assert margin.recall == pytest.approx(2 / 3)
    assert margin.margin == 0.0


def test_an_unscoreable_paper_has_no_margin_rather_than_a_zero_one():
    empty = {"paper": "fZ", "covariates": []}
    margin = margin_score(covariate_score("f999", empty, ["m1:Q5.4"]), empty,
                          modal_covariates(PAPERS))
    assert margin.recall is None and margin.modal_recall is None
    assert margin.margin is None


def test_the_modal_size_is_cross_checked_against_the_handoff_and_reported():
    # Against the fakes a disagreement is expected and must not raise: the
    # published size is a fact about the real inventory. In the scoring clone
    # the same call is a real cross-check.
    msg = modal_size_disagreement(modal_covariates(PAPERS), load_handoff())
    assert msg is not None and "synthetic" in msg
    assert modal_size_disagreement(frozenset("abcdef"), load_handoff()) is None


# --- item 11: direction agreement, weighted per paper ---------------------


def _all_agree_but_fc() -> dict[str, str | None]:
    # Every case matches its paper's direction except fC's six, which are all
    # wrong: fC holds half the fixture's pairs, the shape 11a describes.
    out: dict[str, str | None] = {}
    for case_id, (paper, direction) in directions_by_case(PAPERS).items():
        wrong = "decrease" if direction != "decrease" else "increase"
        out[case_id] = wrong if paper == "fC" else direction
    return out


def test_one_dominant_paper_moves_the_unweighted_rate_and_not_the_weighted_one():
    # 11a: fC holds 6 of the 12 fixture pairs. Unweighted, its six wrong cases
    # halve the rate; weighted per paper, it is one of five papers.
    rows = direction_scores(_all_agree_but_fc(), PAPERS)
    s = direction_summary(rows)
    assert s.scored == 12 and s.papers == 5
    assert s.per_pair == pytest.approx(6 / 12)
    assert s.per_paper == pytest.approx(4 / 5)
    assert s.largest_paper_share == pytest.approx(0.5)


def test_the_base_rate_is_reported_so_a_rate_can_be_read_against_it():
    # A specifier that always guessed the majority direction would score this;
    # without it, agreement has nothing to be better than.
    rows = direction_scores({c: d for c, (_, d) in directions_by_case(PAPERS).items()},
                            PAPERS)
    s = direction_summary(rows)
    assert s.per_pair == 1.0 and s.per_paper == 1.0
    assert s.base_direction == "increase"
    assert s.base_rate == pytest.approx(6 / 12)


def test_a_case_with_no_record_is_carried_unscored_not_counted_as_a_miss():
    specified = dict.fromkeys(directions_by_case(PAPERS))
    rows = direction_scores(specified, PAPERS)
    assert all(r.agree is None for r in rows)
    s = direction_summary(rows)
    assert s.scored == 0 and s.unscored == 12
    assert s.per_pair is None and s.per_paper is None, "unmeasured, not zero"


def test_a_direction_outside_the_record_vocabulary_is_not_a_disagreement():
    papers = [{"paper": "fM", "pairs": [{"case_id": "x1", "direction": "mixed"}]}]
    (row,) = direction_scores({"x1": "increase"}, papers)
    assert row.agree is None
    assert direction_summary([row]).unscored == 1


def test_every_fixture_direction_is_one_a_record_can_hold():
    # The fixture cannot exercise agreement with a vocabulary the record has
    # no member for; only the deliberate "mixed" case above does that.
    assert {d for _, d in directions_by_case(PAPERS).values()} <= set(RECORD_DIRECTIONS)
