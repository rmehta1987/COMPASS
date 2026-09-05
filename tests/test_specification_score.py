"""Harness mode 2 on the synthetic inventory; the real key never loads here."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark import specification_score as S
from benchmark.baseline_score import Refused
from pipeline import ledger as L
from pipeline import pose
from pipeline.artefact import SpecifierArtefact, VariableProvenance
from pipeline.causal_structure import CausalStructure, Edge, Node
from pipeline.generation_env import GenerationEnv
from pipeline.hypothesis import HypothesisRecord
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord
from tests.fake_inventory import FAKE_INVENTORY
from tests.test_baseline_score import HASH, OK, SHA, FakeRetriever

TAU = 0.729476
CLEAN = GenerationEnv(key_present=False, key_fetchable=False, tree_sha=SHA,
                      tree_clean=True, branch="ralph-loop")


def _rec(role: str, key: str) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="sha256:x", role=role,
                                source="instrument"),
        query="sha256:x", dictionary_hash=HASH, min_cos=TAU, best_cos=0.9,
        margin=0.9 - TAU, margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=key, dict_construct_key=key, module=key[1],
                target_id=1, fold_size=1, n_siblings=0, members=(key,),
                stratum="chronic_condition", unmeasured_stratum=False))


def _record(exposure: str, outcome: str, adjusted: tuple[str, ...], *,
            direction: str = "increase", posed: bool = True,
            pid: str = "p") -> HypothesisRecord:
    e, o = _rec("exposure", exposure), _rec("outcome", outcome)
    sel = {"selection_mode": "externally_posed" if posed else "enumerated_screen",
           "screened_from": 0 if posed else 18540}
    art = SpecifierArtefact(
        protocol_id=pid, record_hash="r", pair_id=f"{exposure}->{outcome}",
        estimability="blocked_no_metadata",
        protocol={"selection_rationale": sel, "question": "q"},
        retrieval={"exposure": e, "outcome": o},
        variables=(VariableProvenance(key=exposure, where="exposure", kind="variable",
                                      source="retrieval", retrieval=e),
                   VariableProvenance(key=outcome, where="outcome", kind="variable",
                                      source="retrieval", retrieval=o)),
        redacted=True)
    nodes = [Node(key=exposure, kind="variable", position="exposure"),
             Node(key=outcome, kind="variable", position="outcome")]
    nodes += [Node(key=k, kind="variable", position="covariate", role="confounder",
                   decision="adjusted") for k in adjusted]
    edges = [Edge(source=exposure, target=outcome, relation="hypothesised")]
    edges += [Edge(source=k, target=outcome, relation="causes") for k in adjusted]
    st = CausalStructure(design="cross_sectional", unit_of_analysis="participant",
                         exposure=exposure, outcome=outcome, expected_direction=direction,
                         nodes=tuple(nodes), edges=tuple(edges), adjustment_set=adjusted)
    return HypothesisRecord(artefact=art, structure=st, generation=CLEAN)


def _run(tmp_path: Path, records: dict[str, HypothesisRecord], *,
         provenance: bool = True, synthetic: bool = True) -> list[Path]:
    d = tmp_path / "posed-x"
    d.mkdir(parents=True)
    led = L.Ledger(d, "posed-x")
    common = {"exposure_stratum": "s", "outcome_stratum": "s",
              "estimability": "blocked_no_metadata"}
    for name, rec in records.items():
        (d / name).write_text(rec.to_json() + "\n")
        led.append(pair_id=rec.artefact.pair_id, exposure_key=rec.structure.exposure,
                   outcome_key=rec.structure.outcome, outcome="emitted",
                   protocol_id=rec.artefact.protocol_id, record_hash="r", artefact=name,
                   **common)
    led.append(pair_id="m2:Q9.105 -> m2:Q5.8", exposure_key="m2:Q9.105",
               outcome_key="m2:Q5.8", outcome="discarded", note="validator:temporality",
               **common)
    led.write_summary()
    if provenance:
        pose.write_provenance(d, "tests/fake_inventory.py", synthetic, 3)
    return [d / n for n in records]


def _two(tmp_path: Path, **kw: object) -> list[Path]:
    return _run(tmp_path, {
        "a.json": _record("m2:Q9.105", "m2:Q5.19",
                          ("m1:Q5.4", "m2:Q5.6", "m2:Q9.108", "m1:Q3.10")),
        "b.json": _record("m2:Q9.69", "m2:Q5.8", ("m1:Q5.4",), pid="q"),
    }, **kw)  # type: ignore[arg-type]


def test_recall_precision_modal_and_margin_by_hand(tmp_path):
    paths = _two(tmp_path)
    s = S.score(paths, inventory=FAKE_INVENTORY, retriever=FakeRetriever(), verdicts=OK,
                require_sha=SHA[:12])
    assert s.synthetic and s.provenance["inventory"] == "tests/fake_inventory.py"
    assert (s.papers_in_inventory, s.papers_posable, s.papers_unreproducible,
            s.papers_without_record, s.n) == (4, 3, 1, 1, 2)
    assert s.modal_set == ("m1:Q5.4", "m2:Q5.6", "m2:Q9.1")
    a, b = s.rows
    # paper 36065817: scorable covariates {m1:Q5.4, m2:Q5.6, m2:Q9.1}; the record
    # adjusted for 4, hit 2 (m2:Q9.108 was found by search, so it is not in P)
    assert (a.pmid, a.paper_covariates, a.adjusted, a.hits) == ("36065817", 3, 4, 2)
    assert a.recall == pytest.approx(2 / 3) and a.precision == 0.5
    assert a.modal_hits == 3 and a.modal_recall == 1.0 and a.modal_precision == 1.0
    assert a.margin_recall == pytest.approx(-1 / 3) and a.margin_precision == -0.5
    assert a.design_agree is True and a.direction_agree is True
    assert a.excluded == {"found_by_search": 1, "absent": 1} and a.recoverable == (3, 5)
    # paper 37252073: P = {m1:Q5.4, m2:Q5.6} (m2:Q9.7 not confident); direction decrease
    assert (b.pmid, b.paper_covariates, b.adjusted, b.hits) == ("37252073", 2, 1, 1)
    assert b.recall == 0.5 and b.precision == 1.0
    assert b.modal_hits == 2 and b.modal_recall == 1.0
    assert b.modal_precision == pytest.approx(2 / 3)
    assert b.margin_recall == -0.5 and b.margin_precision == pytest.approx(1 / 3)
    assert b.direction_agree is False and b.excluded == {"not_confident": 1}
    p = s.pooled
    assert (p.n, p.hits, p.paper_covariates, p.adjusted) == (2, 3, 5, 5)
    assert p.recall == 0.6 and p.precision == 0.6
    assert p.modal_hits == 5 and p.modal_size_total == 6
    assert p.modal_recall == 1.0 and p.modal_precision == pytest.approx(5 / 6)
    assert p.margin_recall == pytest.approx(-0.4)
    assert p.margin_precision == pytest.approx(0.6 - 5 / 6)
    assert s.recoverable == (5, 8) and s.excluded_rows == {"found_by_search": 1,
                                                          "absent": 2, "not_confident": 1}
    assert s.denominator == 3 and s.by_outcome == {"emitted": 2, "discarded": 1}


def test_design_and_direction_carry_their_base_rates(tmp_path):
    s = S.score(_two(tmp_path), inventory=FAKE_INVENTORY, retriever=FakeRetriever(),
                verdicts=OK)
    d = s.design
    assert d.omitted is None and (d.n, d.agree, d.rate) == (2, 2, 1.0)
    assert d.majority == ("cross-sectional", 0.75) and d.majority_agreement == 1.0
    x = s.direction
    assert (x.n, x.agree, x.rate) == (2, 1, 0.5)
    assert x.majority == ("increase", pytest.approx(2 / 3))
    assert x.majority_agreement == 0.5
    assert not s.degeneracy.design_degenerate
    # a degenerate inventory drops design agreement and says why
    same = tuple(p.model_copy(update={"design": "cross-sectional"})
                 for p in FAKE_INVENTORY)
    s2 = S.score(_two(tmp_path / "d"), inventory=same, retriever=FakeRetriever(),
                 verdicts=OK)
    assert s2.design.omitted and "not a metric" in s2.design.omitted
    assert s2.design.rate is None and s2.rows[0].design_agree is None
    text = S.render(s2)
    assert "design agreement: OMITTED" in text


def test_refusals_of_mode_two(tmp_path):
    with pytest.raises(Refused, match="no inventory provenance"):
        S.score(_two(tmp_path, provenance=False), inventory=FAKE_INVENTORY,
                retriever=FakeRetriever(), verdicts=OK)
    screened = _run(tmp_path / "s", {"a.json": _record("m2:Q9.105", "m2:Q5.19", (),
                                                       posed=False)})
    with pytest.raises(Refused, match="selection_mode='enumerated_screen'"):
        S.score(screened, inventory=FAKE_INVENTORY, retriever=FakeRetriever(),
                verdicts=OK)
    stray = _run(tmp_path / "t", {"a.json": _record("m1:Q5.4", "m2:Q5.19", ())})
    with pytest.raises(Refused, match="hit no paper"):
        S.score(stray, inventory=FAKE_INVENTORY, retriever=FakeRetriever(), verdicts=OK)
    with pytest.raises(Refused, match="halting verdict"):
        S.score(_two(tmp_path / "h"), inventory=FAKE_INVENTORY, retriever=FakeRetriever(),
                verdicts={**OK, "input_leakage": "FAIL (2 leaks)"})
    with pytest.raises(Refused, match="stamped at aaaa"):
        S.score(_two(tmp_path / "v"), inventory=FAKE_INVENTORY, retriever=FakeRetriever(),
                verdicts=OK, require_sha="b" * 12)


def test_the_report_leads_with_provenance_and_keeps_discovery_apart(tmp_path):
    disc = {"run_id": "b3", "matched": 0, "scored": 28, "rate": 0.0, "denominator": 48,
            "ceiling": {"max_rate": 0.0}}
    s = S.score(_two(tmp_path), inventory=FAKE_INVENTORY, retriever=FakeRetriever(),
                verdicts=OK, discovery=disc)
    text = S.render(s)
    lines = text.splitlines()
    assert lines[2].startswith("**Inventory: tests/fake_inventory.py — SYNTHETIC")
    assert "Nothing below is a measurement" in lines[2]
    assert "never pooled" in text
    assert "| recall | 0.600 | 1.000 | -0.400 | 2 rows, 5 covariates |" in text
    assert "| precision | 0.600 | 0.833 | -0.233 | 2 rows, 5 adjusted |" in text
    assert "run b3: matched 0 / scored 28, rate 0.000, denominator 48" in text
    assert "recall is over recoverable covariates only, 5 of 8" in text
    assert "1 unreproducible" in text and "1 posable but no record emitted" in text
    # a real inventory reads differently, and the JSON round-trips
    real = S.score(_two(tmp_path / "r", synthetic=False), inventory=FAKE_INVENTORY,
                   retriever=FakeRetriever(), verdicts=OK)
    assert "SYNTHETIC" not in S.render(real).splitlines()[2]
    assert S.Specification.model_validate_json(s.model_dump_json()) == s
    assert json.loads(s.model_dump_json())["synthetic"] is True
