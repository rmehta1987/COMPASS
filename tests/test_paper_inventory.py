"""The inventory schema catches the failure modes a hand-written key has."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmark import paper_inventory as PI

ROOT = Path(__file__).resolve().parents[1]


def _v(**kw: object) -> PI.InventoryVariable:
    base: dict[str, object] = {"role": "covariate", "label": "x", "keys": ("m1:Q5.4",),
                               "instrument_region": "m1:Q5 household",
                               "covariate_role": "confounder"}
    base.update(kw)
    return PI.InventoryVariable(**base)  # type: ignore[arg-type]


def _paper(**kw: object) -> PI.PaperInventory:
    base: dict[str, object] = {
        "pmid": "36702470", "design": "cross_sectional", "expected_direction": "increase",
        "unit_of_analysis": "participant", "read_on": "2026-09-04",
        "variables": (_v(role="exposure", label="e", keys=("m2:Q9.105",),
                         instrument_region="m2:Q9 female medical history",
                         covariate_role=None),
                      _v(role="outcome", label="o", keys=("m2:Q5.19",),
                         instrument_region="m2:Q5 diagnosed conditions",
                         covariate_role=None),
                      _v(label="c1"),
                      _v(label="c2", keys=(), instrument_region="linked spatial, not in "
                                                                 "the instrument"))}
    base.update(kw)
    return PI.PaperInventory(**base)  # type: ignore[arg-type]


def test_a_well_formed_paper_validates_and_reports_its_keys_by_role():
    p = _paper()
    assert p.posable
    assert p.keys_by_role("exposure") == {"m2:Q9.105"}
    assert p.keys_by_role("covariate") == {"m1:Q5.4"}
    assert [v.in_instrument for v in p.variables] == [True, True, True, False]


@pytest.mark.parametrize(("kw", "phrase"), [
    ({"keys": ("Q5.4",)}, "not an instrument key"),
    ({"keys": ()}, "no keys are named"),
    ({"instrument_region": "not in the instrument"}, "says not in the instrument"),
    ({"covariate_role": "important"}, "covariate_role must be one of"),
    ({"role": "exposure", "covariate_role": "confounder"}, "only a covariate"),
])
def test_a_variable_that_contradicts_itself_is_rejected(kw, phrase):
    with pytest.raises(ValidationError, match=phrase):
        _v(**kw)


def test_a_paper_needs_both_anchors_and_distinct_labels():
    with pytest.raises(ValidationError, match="no outcome variable"):
        _paper(variables=(_v(role="exposure", label="e", covariate_role=None), _v()))
    with pytest.raises(ValidationError, match="duplicate variable labels"):
        _paper(variables=(_v(role="exposure", label="e", covariate_role=None),
                          _v(role="outcome", label="e", covariate_role=None)))
    with pytest.raises(ValidationError):
        _paper(design="case_control")
    with pytest.raises(ValidationError):
        _paper(expected_direction="positive")


def test_the_inventory_must_match_the_bibliography():
    p = _paper()
    assert PI.validate_inventory([p], known_pmids=["36702470"]) == (p,)
    with pytest.raises(ValueError, match="appears twice"):
        PI.validate_inventory([p, p], known_pmids=["36702470"])
    with pytest.raises(ValueError, match="not in the bibliography"):
        PI.validate_inventory([p], known_pmids=["1"])
    # the real bibliography carries this pmid
    assert PI.validate_inventory([p])


def test_keys_are_checked_against_the_resolver_not_trusted():
    verdicts = {"m2:Q9.105": "unique", "m2:Q5.19": "construct", "m1:Q5.4": "not_found"}
    bad = PI.validate_against_dictionary([_paper()],
                                         lambda k: {"outcome": verdicts.get(k)})
    assert len(bad) == 2
    assert any("names a construct" in b for b in bad)
    assert any("does not resolve" in b for b in bad)
    ok = PI.validate_against_dictionary([_paper()], lambda k: {"outcome": "unique"})
    assert ok == []


def test_posed_pairs_are_the_anchor_product_and_skip_unposable_papers():
    two_out = _paper(variables=(
        *_paper().variables,
        _v(role="outcome", label="o2", keys=("m2:Q5.2",),
           instrument_region="m2:Q5 diagnosed conditions", covariate_role=None)))
    absent = _paper(pmid="32938600", variables=(
        _v(role="exposure", label="e", keys=(), instrument_region="linked, not in the "
                                                                   "instrument",
           covariate_role=None),
        _v(role="outcome", label="o", keys=("m2:Q5.19",),
           instrument_region="m2:Q5 diagnosed conditions", covariate_role=None)))
    assert not absent.posable
    rows = PI.posed_pairs([two_out, absent])
    assert rows == [
        {"pmid": "36702470", "exposure_key": "m2:Q9.105", "outcome_key": "m2:Q5.19"},
        {"pmid": "36702470", "exposure_key": "m2:Q9.105", "outcome_key": "m2:Q5.2"}]


def test_the_template_validates_as_written(tmp_path, monkeypatch):
    src = PI.template()
    ns: dict[str, object] = {}
    exec(compile(src, "paper_inventory_key.py", "exec"), ns)
    inv = ns["INVENTORY"]
    assert isinstance(inv, tuple) and len(inv) == 1
    # the synthetic pmid is not in the bibliography, which is the point of it
    with pytest.raises(ValueError, match="not in the bibliography"):
        PI.validate_inventory(inv)


def test_the_key_is_unreachable_here_and_named_in_the_holdout_registry():
    with pytest.raises(ImportError):
        PI.load_inventory()
    assert not (ROOT / "benchmark" / "paper_inventory_key.py").exists()
    src = (ROOT / "benchmark" / "contamination_check.py").read_text()
    tree = ast.parse(src)
    names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
             and isinstance(n.value, str)}
    assert "paper_inventory_key.py" in names
    # and this schema module never imports the key at module level
    mine = ast.parse((ROOT / "benchmark" / "paper_inventory.py").read_text())
    top = {n.module for n in mine.body if isinstance(n, ast.ImportFrom)}
    assert PI.KEY_MODULE not in top
