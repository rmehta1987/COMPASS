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
    INVENTORY_UNSCOREABLE,
    MATRIX,
    NEAR_MISS_BAND,
    RECORD_DIRECTIONS,
    RESIDUAL_LIMITATION,
    SCOREABLE_CELLS,
    SPECIFICATION_COMPONENTS,
    TIER_RULE_PROBE,
    TIERS,
    Anchor,
    CaseReport,
    Cell,
    DirectionState,
    HandoffMismatch,
    Refusal,
    SideState,
    UnclassifiablePaper,
    _carried,
    analogue_scores,
    anchor_scores,
    attach_pairs,
    attrition_causes,
    built_dictionary_hash,
    component_rates,
    covariate_score,
    direction_scores,
    direction_summary,
    directions_by_case,
    git_blob_hash,
    implemented_tier_rule,
    load_handoff,
    load_papers,
    main,
    margin_score,
    modal_covariates,
    modal_size_disagreement,
    normalise_papers,
    read_case_map,
    refusal_scores,
    render_attrition,
    render_case_studies,
    render_rates,
    render_report,
    render_specification_case_studies,
    render_targets,
    schema_version_of,
    scorable_covariates,
    self_check,
    side_state,
    tier_of,
    tiers_of,
    wilson,
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
    #
    # The schema is supplied here rather than taken from the tree, because
    # `schema_version` is now computed from the file: a clone without
    # `inventory/` would otherwise make this case unfalsifiable, which is the
    # defect the computation was added to remove.
    schema = tmp_path / "schema.py"
    schema.write_text("# a schema this test controls\n")
    good = f"{schema.as_posix()}@{git_blob_hash(schema.read_bytes())[:12]}"
    path = _handoff_at(tmp_path, **{"schema_version": good, field: value})
    with pytest.raises(HandoffMismatch) as e:
        load_handoff(path, schema_path=schema)
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


# --- item 12: tiers A and B as case studies -------------------------------


def _report(construct_of, paper_id: str, case_id: str, tier: str,
            adjustment: list[str] | None = None) -> CaseReport:
    paper = next(p for p in PAPERS if p["paper"] == paper_id)
    case = _case(case_id, construct_of(paper["exposures"][0].get("key") or "m1:Q5.4"),
                 construct_of(paper["outcomes"][0].get("key") or "m1:Q5.4"))
    cov = (None if adjustment is None
           else covariate_score(case_id, paper, adjustment))
    modal = modal_covariates(PAPERS)
    (direction,) = [d for d in direction_scores(
        {case_id: "increase"}, [paper]) if d.case_id == case_id] or [None]
    return CaseReport(
        case_id=case_id, paper=paper_id, tier=tier, state="emitted",
        anchor=anchor_scores([case], {case_id: paper}, construct_of)[0],
        analogue=analogue_scores([case], {case_id: paper}, construct_of)[0],
        refusal=refusal_scores([case], {case_id: paper})[0],
        covariate=cov,
        margin=None if cov is None else margin_score(cov, paper, modal),
        direction=direction)


def test_a_case_study_prints_counts_and_never_a_rate(construct_of):
    out = render_case_studies(
        [_report(construct_of, "fA", "f001", "A", ["m1:Q5.4", "m2:Q5.6"])], "A")
    assert "%" not in out
    assert not re.search(r"\d\.\d", out), "a ratio in a tier of one case is a rate"
    assert "2 of 3 recovered" in out
    assert "fA / f001" in out


def test_a_case_study_names_every_component_including_the_empty_ones(construct_of):
    out = render_case_studies([_report(construct_of, "fA", "f001", "A", [])], "A")
    for name in ("anchor resolution", "modality analogue",
                 "refusal on absent anchor", "covariate recall",
                 "margin over modal", "direction"):
        assert name in out, name
    # A missing row reads as "not applicable" when it means "not yet built".
    assert "mismatch flag UNAVAILABLE" in out


def test_a_case_with_no_record_says_so_rather_than_scoring_zero(construct_of):
    out = render_case_studies([_report(construct_of, "fA", "f001", "A", None)], "A")
    assert "no record emitted" in out
    assert "0 of" not in out


def test_an_empty_tier_reads_unmeasured_and_not_zero_per_cent():
    # 14a: tier A is one paper with one posed pair. At the pipeline's observed
    # discard rate that case can vanish, and the column must then say so.
    out = render_case_studies([], "A")
    assert "UNMEASURED" in out and "%" not in out
    assert "not a rate of zero" in out.lower()
    assert not re.search(r"\d", out.split("UNMEASURED")[1])


def test_the_margin_is_shown_as_counts_in_a_small_tier(construct_of):
    out = render_case_studies(
        [_report(construct_of, "fA", "f001", "A", ["m1:Q5.4", "m2:Q5.6", "m2:Q9.1"])],
        "A")
    assert "record 3 of 3, the modal set alone 2 of 3" in out


# --- item 13: tiers C and D as rates --------------------------------------


def test_the_wilson_interval_matches_the_projects_own_formula():
    # The same 95% interval src/char_strata.py computes; checked against a
    # hand calculation so the two cannot drift silently.
    assert wilson(6, 7) == (0.487, 0.974)
    assert wilson(0, 6) == (0.0, 0.39)
    assert wilson(0, 0) == (None, None), "no trials is no interval, not a wide one"


def test_every_printed_figure_carries_its_n(construct_of):
    """Every RATE line carries its n.

    render_rates now prints two sections: the retrieval components as rates,
    then the three specification components as case studies (they are never a
    rate, at any tier). The n invariant belongs to the first section; the
    second is checked by the two tests below.
    """
    reports = [_report(construct_of, "fC", f"f00{i}", "C", ["m1:Q5.4"])
               for i in (4, 5, 6)]
    out = render_rates(reports, "C")
    rates, _, _ = out.partition("SPECIFICATION COMPONENTS")
    body = [line for line in rates.splitlines()[1:] if line.strip()]
    assert body, "the rate section printed nothing"
    for line in body:
        assert "n=" in line, line


def test_the_specification_components_are_never_a_rate(construct_of):
    """Tier C and D print covariate recall, the margin and direction per case.

    The specification arm is scored only where a record was emitted, which
    needs both anchors to resolve; that denominator is small and selected by
    the retriever, so a percentage over it would be a number about retrieval
    wearing the specifier's name.
    """
    reports = [_report(construct_of, "fC", f"f00{i}", "C", ["m1:Q5.4"])
               for i in (4, 5, 6)]
    out = render_rates(reports, "C")
    rates, marker, studies = out.partition("SPECIFICATION COMPONENTS")
    assert marker, "the specification section is missing from a tier C render"
    for name in SPECIFICATION_COMPONENTS:
        assert name not in rates, f"{name} was printed as a rate"
    assert not re.search(r"\[\d\.\d{3}, \d\.\d{3}\]", studies), (
        "a specification case study printed a confidence interval")


def test_an_empty_specification_section_reads_unmeasured(construct_of):
    """A tier where nothing was emitted says so, and never 0%."""
    reports = [_report(construct_of, "fD", "f007", "D", [])]
    out = render_specification_case_studies(
        [r._replace(covariate=None, margin=None) for r in reports])
    assert "UNMEASURED" in out
    assert "0%" not in out and "0.000" not in out


def test_a_rate_is_printed_with_its_interval(construct_of):
    reports = [_report(construct_of, "fC", f"f00{i}", "C", ["m1:Q5.4"])
               for i in (4, 5, 6)]
    out = render_rates(reports, "C")
    assert re.search(r"\[\d\.\d{3}, \d\.\d{3}\]", out)
    assert "Wilson" in out


def test_a_component_that_scored_nothing_says_unmeasured_and_keeps_its_row(
        construct_of):
    # Tier D has no present anchor, so anchor resolution has n=0 there. It
    # keeps its row and says so: a dropped row reads as inapplicable.
    reports = [_report(construct_of, "fD", "f010", "D", ["m1:Q5.4"])]
    out = render_rates(reports, "D")
    assert "anchor resolution" in out
    assert "n=0" in out and "UNMEASURED" in out
    rates = {r.name: r for r in component_rates(reports)}
    assert rates["anchor resolution"].rate is None, "not a rate of zero"


def test_an_empty_tier_is_unmeasured_rather_than_a_rate_of_zero():
    out = render_rates([], "C")
    assert "UNMEASURED" in out
    assert not re.search(r"\d\.\d", out)


def test_the_margin_row_is_marked_as_not_a_proportion(construct_of):
    reports = [_report(construct_of, "fC", "f004", "C", ["m1:Q5.4", "m2:Q5.6"])]
    (row,) = [r for r in component_rates(reports) if "margin" in r.name]
    assert row.low is None and row.high is None
    assert "not a proportion" in row.note
    assert "margin " in row.note


def test_the_direction_row_carries_the_weighting_and_the_base_rate(construct_of):
    reports = [_report(construct_of, "fC", f"f00{i}", "C", ["m1:Q5.4"])
               for i in (4, 5, 6)]
    (row,) = [r for r in component_rates(reports) if "direction" in r.name]
    assert "weighted per paper" in row.note
    assert "base rate" in row.note and "largest paper" in row.note


# --- item 14: the report, targets before numbers --------------------------


def test_the_targets_are_recorded_with_the_handoffs_own_fixture_sizes():
    out = render_targets(load_handoff())
    assert "refusal 118" in out and "flag 25" in out
    assert ">= 0.90" in out and "< 0.75" in out
    # Said out loud so a reader does not invent one.
    assert "NO target is set on" in out
    assert "0.643" in out and "52%" in out


def test_the_report_puts_provenance_and_targets_before_every_number(construct_of):
    reports = [_report(construct_of, "fA", "f001", "A", ["m1:Q5.4"])]
    out = render_report(reports, handoff=load_handoff(),
                        inventory="tests/fake_tiered_inventory.json",
                        synthetic=True, run_id="t-1")
    assert out.index("LIMITATION") < out.index("TARGETS")
    assert out.index("TARGETS") < out.index("TIER A")
    # A band read off a number is not a target.
    assert out.index(">= 0.90") < out.index("TIER A")


def test_a_synthetic_inventory_is_announced_in_the_first_lines(construct_of):
    out = render_report([], handoff=load_handoff(), inventory="fake",
                        synthetic=True, run_id="t-1")
    assert "SYNTHETIC" in out.splitlines()[1]
    assert RESIDUAL_LIMITATION in out


def test_every_tier_appears_even_when_it_holds_nothing(construct_of):
    out = render_report([], handoff=load_handoff(), inventory="fake",
                        synthetic=True, run_id="t-1")
    for tier in TIERS:
        assert f"TIER {tier}" in out
    # 14a: a tier that lost all its cases is unmeasured, never zero.
    assert out.count("UNMEASURED") == len(TIERS)
    assert "%" not in out.split("TIER A")[1]


def test_the_blocked_half_is_marked_in_the_report_not_omitted(construct_of):
    reports = [_report(construct_of, "fB", "f002", "B", ["m1:Q5.4"]),
               _report(construct_of, "fC", "f004", "C", ["m1:Q5.4"])]
    out = render_report(reports, handoff=load_handoff(), inventory="fake",
                        synthetic=True, run_id="t-1")
    assert out.count("modality analogue") >= 2
    assert "UNAVAILABLE" in out and "16-19" in out


def test_design_agreement_is_declared_absent_rather_than_silently_missing():
    out = render_report([], handoff=load_handoff(), inventory="fake",
                        synthetic=True, run_id="t-1")
    assert "design agreement is NOT a component" in out
    assert "design: false" in out


# --- item 16: attrition, by cause -----------------------------------------


def _index_row(case_id: str, state: str, e_cos: float, o_cos: float,
               e_ck: str | None, o_ck: str | None) -> dict:
    def side(cos: float, ck: str | None) -> dict:
        return {"term": "t", "abstained": ck is None, "best_cos": cos,
                "nearest_key": "m9:Q0", "construct_key": ck}
    return {"case_id": case_id, "state": state, "artefact": None, "note": "",
            "exposure": side(e_cos, e_ck), "outcome": side(o_cos, o_ck)}


def test_attrition_splits_an_unresolved_anchor_by_which_side_went():
    # An exposure the instrument does not hold and an outcome it does not hold
    # are different findings about the instrument, not one "no record" bucket.
    rows = [_index_row("c1", "unresolved_anchor", 0.4, 0.9, None, "m2:Q5.8"),
            _index_row("c2", "unresolved_anchor", 0.9, 0.4, "m3:Q16.1", None),
            _index_row("c3", "unresolved_anchor", 0.4, 0.4, None, None),
            _index_row("c4", "emitted", 0.9, 0.9, "m3:Q16.1", "m2:Q5.8")]
    causes = attrition_causes(rows)
    assert causes == {"emitted": 1,
                      "unresolved_anchor: both sides": 1,
                      "unresolved_anchor: exposure only": 1,
                      "unresolved_anchor: outcome only": 1}


def test_a_near_miss_is_counted_against_a_stated_band():
    tau = 0.729476
    rows = [_index_row("c1", "unresolved_anchor", 0.728, 0.9, None, "m2:Q5.8"),
            _index_row("c2", "unresolved_anchor", 0.31, 0.9, None, "m2:Q5.8")]
    causes = attrition_causes(rows, min_cos=tau)
    assert causes[tiered_score.NEAR_MISS_ROW] == 1
    # The near-miss row counts SIDES; every other row counts cases.
    assert "SIDES" in tiered_score.NEAR_MISS_ROW
    out = render_attrition(rows, min_cos=tau)
    assert "0.729476" in out and str(NEAR_MISS_BAND) in out


def test_attrition_states_its_denominator():
    # An unstated denominator is not a number.
    out = render_attrition([_index_row("c1", "emitted", 0.9, 0.9, "a", "b")])
    assert "Denominator" in out and "1 rows" in out


def test_the_report_carries_attrition_between_the_targets_and_the_tiers(
        construct_of):
    rows = [_index_row("c1", "unresolved_anchor", 0.4, 0.9, None, "m2:Q5.8")]
    out = render_report([], handoff=load_handoff(), inventory="fake",
                        synthetic=True, run_id="t-1", cases=rows)
    assert out.index("TARGETS") < out.index("ATTRITION") < out.index("TIER A")


# --- the scoring clone's command line -------------------------------------


def test_the_fixture_and_a_directory_of_papers_both_load(tmp_path):
    # The fixture here is one file with a papers list; the real inventory in
    # the scoring clone is one file per paper. Both are read as data.
    papers, synthetic = load_papers(Path("tests/fake_tiered_inventory.json"))
    assert len(papers) == 5 and synthetic is True
    for paper in papers[:2]:
        (tmp_path / f"{paper['paper']}.json").write_text(json.dumps(paper))
    (tmp_path / "case_map.json").write_text(json.dumps({"f001": "fA"}))
    from_dir, synthetic_dir = load_papers(tmp_path)
    assert [p["paper"] for p in from_dir] == ["fA", "fB"]
    assert synthetic_dir is False


def test_the_case_map_is_never_read_as_a_paper(tmp_path):
    # inventory/case_map.json is the answer key's join table. It is passed in
    # deliberately with --case-map or not at all; it is never picked up by the
    # glob that reads the papers.
    (tmp_path / "case_map.json").write_text(json.dumps({"f001": "fA"}))
    assert load_papers(tmp_path) == ([], False)


def test_a_run_without_an_inventory_is_refused_rather_than_half_scored(capsys):
    with pytest.raises(SystemExit):
        main(["--run", "artefacts/nowhere"])
    assert "go together" in capsys.readouterr().err


def test_the_margin_row_says_unmeasured_when_nothing_was_recoverable(construct_of):
    # It is built directly rather than through _rate, so it needs the sentence
    # in its own hand; without it the row reads as withheld, not unmeasured.
    reports = [_report(construct_of, "fD", "f010", "D", None)]
    (row,) = [r for r in component_rates(reports) if "margin" in r.name]
    assert row.n == 0 and "UNMEASURED" in row.note
    assert "not a margin of zero" in row.note


# --- defect 4: the direction vocabularies are disjoint --------------------
#
# Every one of run tiered-20260906's 95 cases came back `agree=None`, which
# read as the `mixed` escape hatch and was in fact 91 rows the record
# vocabulary cannot express at all. `agree is None` cannot tell those apart;
# `state` can, and these pin that it must.


def test_an_out_of_vocabulary_direction_is_unmapped_not_the_mixed_hatch():
    """Drift must not be able to hide inside the exemption built for `mixed`."""
    papers = [{"paper": "p", "pairs": [{"case_id": "x1", "direction": "positive"}]}]
    (row,) = direction_scores({"x1": "increase"}, papers)
    assert row.agree is None
    assert row.state is DirectionState.UNMAPPED


def test_mixed_is_still_the_declared_escape_hatch():
    """`mixed` is unscoreable by design and must not be reported as drift."""
    papers = [{"paper": "p", "pairs": [{"case_id": "x1", "direction": "mixed"}]}]
    (row,) = direction_scores({"x1": "increase"}, papers)
    assert row.agree is None
    assert row.state is DirectionState.MIXED


def test_a_case_with_no_record_is_distinguishable_from_a_vocabulary_mismatch():
    """The two reasons a row is unscored must never collapse into one count."""
    papers = [{"paper": "p", "pairs": [{"case_id": "x1", "direction": "increase"}]}]
    (row,) = direction_scores({"x1": None}, papers)
    assert row.state is DirectionState.NO_RECORD


def test_the_summary_splits_unscored_by_reason():
    """A summary that only totals `unscored` cannot report a broken component."""
    papers = [{"paper": "p", "pairs": [
        {"case_id": "a", "direction": "positive"},   # unmapped
        {"case_id": "b", "direction": "mixed"},      # declared hatch
        {"case_id": "c", "direction": "increase"},   # no record
    ]}]
    s = direction_summary(direction_scores({"a": "increase", "c": None}, papers))
    assert s.scored == 0
    assert (s.unscored, s.unmapped, s.mixed, s.no_record) == (3, 1, 1, 1)


def test_an_unmapped_row_says_the_vocabularies_are_disjoint_not_that_it_disagreed():
    """The rendered note must name the mismatch; silence reads as a result."""
    papers = [{"paper": "p", "pairs": [{"case_id": "a", "direction": "positive"}]}]
    note = _carried(direction_summary(direction_scores({"a": "increase"}, papers)))
    assert "UNMAPPED" in note
    assert "vocabulary mismatch" in note
    assert "NOT a pipeline result" in note


def test_the_escape_hatch_never_overlaps_the_record_vocabulary():
    """If a record direction were also 'unscoreable', real verdicts would vanish."""
    assert not set(INVENTORY_UNSCOREABLE) & set(RECORD_DIRECTIONS)


# --- defect 5: the three renames, read in the scorer not in a helper ------
#
# These were bridged by an out-of-tree `phase3_adapt.py` that had to be run
# first. The join in `attach_pairs` is the one that can score the wrong pair's
# answer, so its assertion is pinned here rather than left to a passing run.


REAL_SHAPE_PAPER = {
    "pmid": "111", "exposures": [{"term": "E0"}, {"term": "E1"}],
    "outcomes": [{"term": "O0"}], "directions": [["E1", "O0", "positive"]],
}
REAL_SHAPE_CASES = {"c001": {"pmid": "111", "exposure_row": "exposures[1]",
                             "outcome_row": "outcomes[0]",
                             "direction_row": "directions[0]"}}


def test_pmid_is_read_as_the_paper_id():
    """Rename 1: the fixture says `paper`, the real inventory says `pmid`."""
    (p,) = normalise_papers([REAL_SHAPE_PAPER])
    assert p["paper"] == "111"


def test_an_existing_paper_id_is_never_overwritten():
    """The synthetic fixture must survive the rename untouched."""
    (p,) = normalise_papers([{"paper": "fA", "pmid": "999"}])
    assert p["paper"] == "fA"


def test_both_case_map_shapes_are_read(tmp_path):
    """Rename 2: a flat map and the real header-plus-`cases` map."""
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps({"c001": "fA"}))
    assert read_case_map(flat) == ({"c001": "fA"}, {})
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"n_cases": 1, "cases": REAL_SHAPE_CASES}))
    mapping, cases = read_case_map(real)
    assert mapping == {"c001": "111"}
    assert cases["c001"]["direction_row"] == "directions[0]"


def test_pairs_are_projected_from_the_direction_triples():
    """Rename 3: `directions` triples carry no case ids; the join supplies them."""
    (p,) = attach_pairs(normalise_papers([REAL_SHAPE_PAPER]), REAL_SHAPE_CASES)
    assert p["pairs"] == [{"case_id": "c001", "direction": "positive"}]


def test_a_direction_triple_naming_other_terms_is_refused():
    """A wrong join scores one pair's answer against another's, silently."""
    bad = {"c001": {**REAL_SHAPE_CASES["c001"], "exposure_row": "exposures[0]"}}
    with pytest.raises(ValueError, match="but the row addresses give"):
        attach_pairs(normalise_papers([REAL_SHAPE_PAPER]), bad)


# --- the schema pin: computed from the file, and only one of it --------------
#
# It used to be `raw["schema_version"] != EXPECT_SCHEMA_VERSION`: two recorded
# strings, neither read from `inventory/schema.py`. The schema gained a
# validated `Direction` enum on 2026-09-07, its blob moved off `292571ccc682`,
# and nothing went red -- while the mismatch message claimed a moved schema was
# exactly what it caught.


def test_the_blob_hash_is_gits_own():
    """Comparable with `git hash-object`, or the pin is not the thing it names."""
    # git hash-object of an empty file, a value git itself will not change.
    assert git_blob_hash(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert git_blob_hash(b"x\n") == "587be6b4c3f93f93c489c0111bba5596147a26cb"


def test_the_schema_pin_is_read_from_the_file(tmp_path):
    """The identity must be a function of the bytes, not of a constant."""
    schema = tmp_path / "schema.py"
    schema.write_text("# one\n")
    first = schema_version_of(schema)
    assert first == f"{schema.as_posix()}@{git_blob_hash(schema.read_bytes())[:12]}"
    schema.write_text("# two\n")
    assert schema_version_of(schema) != first


def test_a_schema_that_is_not_in_this_tree_is_unverifiable_not_passing(tmp_path):
    """A missing file must never read as a pin that matched."""
    assert schema_version_of(tmp_path / "absent.py") is None
    h = load_handoff(_handoff_at(tmp_path), schema_path=tmp_path / "absent.py")
    assert h.schema_verified is False


def test_a_schema_that_is_present_and_matching_is_recorded_as_verified(tmp_path):
    """The report must be able to say which pins were actually checked."""
    schema = tmp_path / "schema.py"
    schema.write_text("# a schema this test controls\n")
    good = f"{schema.as_posix()}@{git_blob_hash(schema.read_bytes())[:12]}"
    h = load_handoff(_handoff_at(tmp_path, schema_version=good), schema_path=schema)
    assert h.schema_verified is True


def test_the_tree_holds_the_schema_the_handoff_names(tmp_path):
    """The live pin, against the live file. Red means one of them moved.

    Guarded on which clone this is, because only ONE branch can ever run in a
    given tree and an unguarded comparison is red in half of them. `f80a2f9`
    asserted equality unconditionally and was red in every generation clone from
    the moment it landed: `schema_version_of` returns None there, by design and
    by its own docstring ("None means UNVERIFIABLE HERE, never 'matches'"),
    because `inventory/` is barred from this clone -- `check.sh` step 11 says so.
    The commit's message already stated the intended behaviour, "a clone with no
    inventory/ records schema_verified=False rather than passing"; this asserts
    that instead of comparing a pin against None.

    UNVERIFIABLE is not the same as absent, so the no-inventory branch still
    demands the handoff NAME a schema and record that it was not verified. A
    handoff that quietly dropped the field would be red here too.
    """
    live = schema_version_of()
    handoff = load_handoff()
    if live is not None:
        assert handoff.schema_version == live
        assert handoff.schema_verified
    else:
        assert handoff.schema_version, (
            "the handoff must still name the schema it was built against, even "
            "where this tree cannot check it")
        assert not handoff.schema_verified, (
            "no inventory/ in this tree, so nothing verified the pin; recording "
            "schema_verified=True here would be a pin that checked nothing")

    # Runs in EVERY clone, so the branch that cannot execute above is still
    # exercised: the computation itself, over a file this test owns.
    f = tmp_path / "schema.py"
    f.write_text("x = 1\n")
    assert schema_version_of(f) == f"{f.as_posix()}@{git_blob_hash(f.read_bytes())[:12]}"
    f.write_text("x = 2\n")
    assert schema_version_of(f).endswith(f"@{git_blob_hash(f.read_bytes())[:12]}")
    assert schema_version_of(tmp_path / "absent.py") is None


def test_there_is_no_second_recorded_copy_of_the_schema_pin():
    """One pin, live and computed.

    A constant carrying a `path@blob` would restore the dual role that let the
    drift through: a live config value doubling as a historical record. The run
    identity belongs in that run's own report, which is immutable.
    """
    src = Path("benchmark/tiered_score.py").read_text()
    literals = [n.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and re.search(r"schema\.py@[0-9a-f]{6,}", n.value)]
    assert literals == [], f"a second recorded schema pin is back: {literals}"


# --- the tier rule: probed from behaviour, not restated -----------------------
#
# It used to be `raw["tier_rule"] != EXPECT_TIER_RULE`, a word against a word.
# Flipping `side_state`'s default left `--self-check` at 0 problems and the
# report header still printing `confident_anchor`, so the provenance line was
# not evidence that the harness implemented the rule it named.


def test_the_probe_is_the_shape_the_two_readings_disagree_on():
    """A probe both readings answer alike would make the pin unfalsifiable."""
    probe = list(TIER_RULE_PROBE)
    assert side_state(probe, require_confident=True) is SideState.UNREACHABLE
    assert side_state(probe, require_confident=False) is SideState.MODALITY


def test_the_tier_rule_is_read_from_side_state():
    """The label must be a function of the code, not a second copy of the word."""
    assert implemented_tier_rule() == "confident_anchor"


def test_the_tree_implements_the_tier_rule_the_handoff_names():
    """The live pin against the live behaviour. Red means one of them moved."""
    assert load_handoff().tier_rule == implemented_tier_rule()


def test_no_module_level_constant_restates_a_tier_rule():
    """A recorded copy would restore the word-against-word compare.

    The literal is allowed inside `implemented_tier_rule`, which computes it.
    What may not come back is a module-level constant holding it, because that
    is the thing the handoff would then be compared against.
    """
    tree = ast.parse(Path("benchmark/tiered_score.py").read_text())
    named = [t.id for node in tree.body if isinstance(node, ast.Assign)
             for t in node.targets if isinstance(t, ast.Name)
             if isinstance(node.value, ast.Constant)
             and node.value.value in ("confident_anchor", "bare_status")]
    assert named == [], f"a recorded tier-rule constant is back: {named}"
