"""The retrieval adapter, against a fake retriever.

The real bundle is exercised by `python -m pipeline.retrieve --reproduce`
(check.sh); these tests pin the adapter's own logic without loading torch.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from pipeline import retrieve as R

TAU = 0.729476


class FakeRetriever:
    """Three targets; `search` orders the first len(cos) by cosine, descending.

    Ties keep declaration order, which is NOT id order: target 3 is declared
    before target 2, so a tie between them is returned 3-then-2.
    """

    min_cos = TAU
    manifest: ClassVar[dict[str, Any]] = {"dictionary_version_hash": "3dc8415eccfe"}
    targets: ClassVar[list[dict[str, Any]]] = [
        {"target_id": 1, "canonical_key": "m2:Q9.95", "construct_key": "m2:Q9.95",
         "module": "2", "stem": "ever used hormone therapy for menopause", "option": "O",
         "fold_size": 1, "siblings": [], "members": ["m2:Q9.95"]},
        {"target_id": 3, "canonical_key": "m1:Q5.4~dup", "construct_key": "m1:Q5.4",
         "module": "1", "stem": "total household income", "option": "O",
         "fold_size": 1, "siblings": [1], "members": ["m1:Q5.4~dup"]},
        {"target_id": 2, "canonical_key": "m1:Q5.4", "construct_key": "m1:Q5.4",
         "module": "1", "stem": "total household income", "option": "O",
         "fold_size": 2, "siblings": [1], "members": ["m1:Q5.4", "m1:Q5.4_1"]},
    ]

    def __init__(self, cos: tuple[float, ...]) -> None:
        """Cosines for the targets in declaration order (1, 3, 2)."""
        self.cos = cos
        self.queries: list[str] = []

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        self.queries.append(query)
        out = []
        for t, c in zip(self.targets[:len(self.cos)], self.cos, strict=True):
            out.append({"target_id": t["target_id"], "key": t["canonical_key"],
                        "construct_key": t["construct_key"], "module": t["module"],
                        "stem": t["stem"], "option": t["option"],
                        "fold_size": t["fold_size"], "n_siblings": len(t["siblings"]),
                        "members": t["members"], "cos": round(c, 6)})
        out.sort(key=lambda h: -h["cos"])       # stable: ties keep declaration order
        return out[:k]


def _req(**kw: Any) -> Any:
    tpl = R.load_template()
    kw.setdefault("role", tpl.VariableRole.EXPOSURE)
    return tpl.RetrievalRequest(**kw)


def test_resolved_record_carries_the_shipped_query_and_threshold():
    r = FakeRetriever((0.81, 0.77))
    rec = R.retrieve(r, _req(construct="hormone medication", instances=("estrogen",)))
    assert not rec.abstained and rec.hit is not None
    assert rec.query == "hormone medication: estrogen" == r.queries[0]
    assert rec.min_cos == TAU and rec.best_cos == 0.81
    assert rec.margin == pytest.approx(0.81 - TAU)
    assert rec.margin_12 == pytest.approx(0.04)
    assert rec.hit.key == rec.nearest_key == "m2:Q9.95"
    # stratum from the committed classifier; unmeasured because the fake target
    # set folds none of the real gold keys, so every stratum has zero rows
    assert rec.hit.stratum == "reproductive_hormonal" and rec.hit.unmeasured_stratum
    assert rec.request.population is None and rec.request.role == "exposure"
    assert rec.dictionary_hash == "3dc8415eccfe"


def test_abstention_is_an_outcome_with_the_nearest_target_still_named():
    r = FakeRetriever((0.61, 0.60))
    rec = R.retrieve(r, _req(construct="ambient PM2.5 exposure"))
    assert rec.abstained and rec.hit is None and rec.margin_12 is None
    assert rec.nearest_key == "m2:Q9.95"
    assert rec.margin == pytest.approx(0.61 - TAU) and rec.margin < 0


def test_caller_threshold_overrides_the_manifest_one():
    r = FakeRetriever((0.61, 0.60))
    rec = R.retrieve(r, _req(construct="x"), min_cos=0.5)
    assert not rec.abstained and rec.min_cos == 0.5


def test_search_is_asked_for_enough_hits_to_resolve_a_tie():
    class Counting(FakeRetriever):
        def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
            assert k == R.TIE_K >= 2
            return super().search(query, k)
    R.retrieve(Counting((0.9, 0.1)), _req(construct="x"))


def test_an_exact_tie_resolves_to_the_lowest_target_id_like_the_acceptance_test():
    # targets 3 and 2 tie; the fake returns 3 first; the adapter must pick 2
    rec = R.retrieve(FakeRetriever((0.5, 0.9, 0.9)), _req(construct="x"))
    assert rec.hit is not None and rec.hit.target_id == 2
    assert rec.nearest_key == "m1:Q5.4" and rec.margin_12 == 0.0


def test_a_tie_below_the_top_does_not_disturb_the_winner():
    rec = R.retrieve(FakeRetriever((0.95, 0.9, 0.9)), _req(construct="x"))
    assert rec.hit is not None and rec.hit.target_id == 1


def test_precomputed_strata_are_used_when_given():
    from pipeline.strata import Strata
    r = FakeRetriever((0.81, 0.77))
    strata = Strata.from_targets(r.targets, ["m2:Q9.95"])   # one row in that stratum
    rec = R.retrieve(r, _req(construct="x"), strata=strata)
    assert rec.hit is not None and rec.hit.unmeasured_stratum is False


def test_the_record_round_trips_after_a_real_adapter_call():
    rec = R.retrieve(FakeRetriever((0.81, 0.77)), _req(construct="x", instances=("a",)))
    assert R.RetrievalRecord.from_json(rec.to_json()) == rec


def test_reproduce_uses_the_gold_rule_by_target_membership(tmp_path):
    # target 2 is nearest (0.9). Row a's gold is a non-canonical member of
    # target 2 -> correct by membership; row b's gold is target 1 -> wrong.
    prereg = tmp_path / "p.json"
    prereg.write_text('{"positives": ['
                      '{"query": "a", "instances": [], "gold_key": "m1:Q5.4_1"},'
                      '{"query": "b", "instances": ["z"], "gold_key": "m2:Q9.95"}]}')
    got = R.reproduce(FakeRetriever((0.5, 0.2, 0.9)), prereg)
    assert got == {"n": 2, "rank1": 1, "R@1": 0.5, "abstained": 0}


def test_shipped_expectation_is_read_from_the_smoke_test():
    assert R.shipped_expectation() == 0.643


def test_no_gold_field_reader_is_imported():
    # fields_from_target() reads the gold target's matrix_col: a fixture stand-in
    # for a specifier, never the pipeline's input.
    import ast
    tree = ast.parse((R.ROOT / "pipeline" / "retrieve.py").read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "fields_from_target" not in names | attrs
    froms = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(m.startswith("src") for m in froms)
