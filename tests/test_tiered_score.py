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
    SCOREABLE_CELLS,
    TIERS,
    Anchor,
    Cell,
    HandoffMismatch,
    SideState,
    UnclassifiablePaper,
    anchor_scores,
    built_dictionary_hash,
    load_handoff,
    main,
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
