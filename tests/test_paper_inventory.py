"""The inventory schema catches the failure modes a hand-written key has."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmark import paper_inventory as PI

ROOT = Path(__file__).resolve().parents[1]


def _v(**kw: object) -> PI.InventoryVariable:
    base: dict[str, object] = {"role": "covariate", "label": "x", "key": "m1:Q5.4",
                               "in_instrument": True, "resolution": "verified",
                               "confident": True}
    base.update(kw)
    return PI.InventoryVariable(**base)  # type: ignore[arg-type]


def _absent(**kw: object) -> PI.InventoryVariable:
    return _v(key=None, in_instrument=False, resolution="absent",
              absent_reason="linked spatial measure", **kw)


def _paper(**kw: object) -> PI.PaperInventory:
    base: dict[str, object] = {
        "pmid": "36702470", "design": "cross-sectional", "direction": "increase",
        "read_on": "2026-09-04",
        "exposures": (_v(role="exposure", label="e", key="m2:Q9.105"),),
        "outcomes": (_v(role="outcome", label="o", key="m2:Q5.19"),),
        "covariates": (_v(label="c1"),
                       _v(label="c2", key="m2:Q9.1", resolution="found_by_search",
                          confident=False),
                       _v(label="c3", key="m2:Q5.6", confident=False),
                       _absent(label="c4"))}
    base.update(kw)
    return PI.PaperInventory(**base)  # type: ignore[arg-type]


def test_a_well_formed_paper_validates_and_only_scorable_rows_count():
    p = _paper()
    assert p.posable and p.reproducible
    assert p.scorable_keys("exposure") == {"m2:Q9.105"}
    assert p.scorable_keys("covariate") == {"m1:Q5.4"}
    assert p.excluded() == {"found_by_search": 1, "not_confident": 1, "absent": 1}
    assert [v.exclusion for v in p.covariates] == [None, "found_by_search",
                                                   "not_confident", "absent"]


@pytest.mark.parametrize(("kw", "phrase"), [
    ({"key": "Q5.4"}, "not an instrument key"),
    ({"key": None}, "not an instrument key"),
    ({"resolution": "absent"}, "resolution is 'absent'"),
    ({"absent_reason": "somewhere"}, "absent_reason given"),
    ({"in_instrument": False, "resolution": "absent", "absent_reason": "x"},
     "named but in_instrument is False"),
    ({"key": None, "in_instrument": False, "resolution": "absent"}, "say where"),
    ({"key": None, "in_instrument": False, "absent_reason": "x"}, "must be 'absent'"),
    ({"resolution": "found_by_search"}, "never confident"),
    ({"role": "exposure", "covariate_role": "confounder"}, "only a covariate"),
    ({"covariate_role": "important"}, "covariate_role must be one of"),
])
def test_a_variable_that_contradicts_itself_is_rejected(kw, phrase):
    with pytest.raises(ValidationError, match=phrase):
        _v(**kw)


def test_a_paper_needs_anchors_matching_roles_and_known_vocabularies():
    with pytest.raises(ValidationError):
        _paper(outcomes=())
    with pytest.raises(ValidationError, match="sits in outcomes but carries role"):
        _paper(outcomes=(_v(role="covariate", label="o"),))
    with pytest.raises(ValidationError, match="duplicate variable labels"):
        _paper(covariates=(_v(label="e"),))
    with pytest.raises(ValidationError):
        _paper(design="cohort")
    with pytest.raises(ValidationError):
        _paper(direction="harmful")
    assert _paper(design="nested case-control", direction="mixed").direction == "mixed"


def test_an_absent_anchor_makes_a_paper_unreproducible_not_failed():
    p = _paper(exposures=(_absent(role="exposure", label="e"),))
    assert not p.reproducible and not p.posable
    assert PI.posed_pairs([p]) == []


def test_the_inventory_must_match_the_bibliography():
    p = _paper()
    assert PI.validate_inventory([p], known_pmids=["36702470"]) == (p,)
    with pytest.raises(ValueError, match="appears twice"):
        PI.validate_inventory([p, p], known_pmids=["36702470"])
    with pytest.raises(ValueError, match="not in the bibliography"):
        PI.validate_inventory([p], known_pmids=["1"])
    assert PI.validate_inventory([p])        # the real bibliography carries it


def test_keys_are_verified_against_the_resolver_not_trusted():
    verdicts = {"m2:Q9.105": "unique", "m2:Q5.19": "construct", "m1:Q5.4": "not_found",
                "m2:Q9.1": "unique", "m2:Q5.6": "unique"}
    bad = PI.validate_against_dictionary([_paper()],
                                         lambda k: {"outcome": verdicts.get(k)})
    assert len(bad) == 2
    assert any("names a construct" in b for b in bad)
    assert any("does not resolve" in b for b in bad)
    ok = PI.validate_against_dictionary([_paper()], lambda k: {"outcome": "unique"})
    assert ok == []


def test_posed_pairs_are_the_scorable_anchor_product():
    two = _paper(outcomes=(_v(role="outcome", label="o", key="m2:Q5.19"),
                           _v(role="outcome", label="o2", key="m2:Q5.2"),
                           _v(role="outcome", label="o3", key="m2:Q5.8",
                              confident=False)))
    assert PI.posed_pairs([two]) == [
        {"pmid": "36702470", "exposure_key": "m2:Q9.105", "outcome_key": "m2:Q5.19"},
        {"pmid": "36702470", "exposure_key": "m2:Q9.105", "outcome_key": "m2:Q5.2"}]


def test_the_modal_set_is_a_stated_majority_over_scorable_covariates():
    a = _paper(pmid="1" * 8, covariates=(_v(label="a", key="m1:Q5.4"),
                                          _v(label="b", key="m2:Q5.6")))
    b = _paper(pmid="2" * 8, covariates=(_v(label="a", key="m1:Q5.4"),
                                          _v(label="c", key="m2:Q9.1")))
    c = _paper(pmid="3" * 8, covariates=(_v(label="a", key="m1:Q5.4"),
                                          _v(label="b", key="m2:Q5.6"),
                                          _v(label="d", key="m2:Q5.8", confident=False)))
    none = _paper(pmid="4" * 8, covariates=(_absent(label="z"),))
    assert PI.covariate_counts([a, b, c, none]) == {"m1:Q5.4": 3, "m2:Q5.6": 2,
                                                    "m2:Q9.1": 1}
    # three papers carry a scorable covariate; majority = ceil(0.5 * 3) = 2
    assert PI.modal_covariates([a, b, c, none]) == {"m1:Q5.4", "m2:Q5.6"}
    assert PI.modal_covariates([a, b, c, none], share=1.0) == {"m1:Q5.4"}
    assert PI.modal_covariates([none]) == frozenset()


def test_degeneracy_reports_the_base_rates_before_a_metric_is_adopted():
    same = [_paper(pmid=str(i) * 8) for i in range(1, 4)]
    d = PI.degeneracy(same)
    assert d.design_degenerate and d.design_majority == ("cross-sectional", 1.0)
    assert d.direction_majority == ("increase", 1.0) and d.direction_scorable == 3
    varied = [_paper(pmid="1" * 8), _paper(pmid="2" * 8, design="prospective",
                                          direction="decrease"),
              _paper(pmid="3" * 8, direction="mixed")]
    d = PI.degeneracy(varied)
    assert not d.design_degenerate
    assert d.designs == {"cross-sectional": 2, "prospective": 1}
    assert d.design_majority == ("cross-sectional", pytest.approx(2 / 3))
    assert d.directions == {"increase": 1, "decrease": 1, "mixed": 1}
    assert d.direction_scorable == 2 and d.direction_majority[1] == 0.5
    assert PI.degeneracy([]).design_majority is None


def test_the_template_validates_as_written():
    ns: dict[str, object] = {}
    exec(compile(PI.template(), "paper_inventory_key.py", "exec"), ns)
    inv = ns["INVENTORY"]
    assert isinstance(inv, tuple) and len(inv) == 1
    assert inv[0].excluded() == {"found_by_search": 1, "absent": 1}
    with pytest.raises(ValueError, match="not in the bibliography"):
        PI.validate_inventory(inv)          # the synthetic pmid, on purpose


def test_the_key_is_unreachable_here_and_named_in_the_holdout_registry():
    with pytest.raises(ImportError):
        PI.load_inventory()
    assert not (ROOT / "benchmark" / "paper_inventory_key.py").exists()
    src = (ROOT / "benchmark" / "contamination_check.py").read_text()
    names = {n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant)
             and isinstance(n.value, str)}
    assert "paper_inventory_key.py" in names
    mine = ast.parse((ROOT / "benchmark" / "paper_inventory.py").read_text())
    top = {n.module for n in mine.body if isinstance(n, ast.ImportFrom)}
    assert PI.KEY_MODULE not in top


def test_the_guide_states_the_two_amendments():
    # collapse whitespace first: a phrase can span a line wrap
    raw = (ROOT / "benchmark" / "PAPER_INVENTORY_GUIDE.md").read_text()
    guide = re.sub(r"\s+", " ", raw)
    assert "found_by_search" in guide and "confident=False" in guide
    assert "cannot measure the retriever" in guide
    assert "covariate boundary has moved" in guide
    assert "never scored on the paper's result" in guide
