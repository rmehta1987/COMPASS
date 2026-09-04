"""Item 14: DAG validators emit typed critiques.

A mediator under a cross-sectional design is rejected, and every check has a
seeded violation.
"""

from __future__ import annotations

import pytest

from agent.schema import ProtocolSpecification
from generate.funnel import Construct, load_constructs
from generate.run_specifier import fixture
from pipeline import causal_structure as CS
from pipeline import hypothesis as H
from pipeline import resolved_pair as RP
from pipeline import validators as V
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


def _rec(role: str, key: str, ck: str, members: tuple[str, ...]) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="t", role=role), query="t",
        dictionary_hash="h", min_cos=TAU, best_cos=0.9, margin=0.9 - TAU,
        margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=members,
                stratum="x", unmeasured_stratum=False))


@pytest.fixture(scope="module")
def built():
    try:
        C, version = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    p = ProtocolSpecification.model_validate_json(fixture(version, 384))
    e = C["m3:Q16.1"]
    pair = RP.from_records(_rec("exposure", e.member_keys[0], e.construct_key,
                                tuple(e.member_keys)),
                           _rec("outcome", "m2:Q5.8", "m2:Q5.8", ("m2:Q5.8",)),
                           C, estimability="blocked_no_metadata")
    return H.build(p, pair), pair


def _with_structure(rec: H.HypothesisRecord, **update: object) -> H.HypothesisRecord:
    return rec.model_copy(update={"structure": rec.structure.model_copy(update=update)})


# ----------------------------------------------------------------- temporality

def test_a_mediator_under_a_cross_sectional_design_is_rejected(built):
    rec, pair = built
    assert rec.structure.design == CS.CROSS_SECTIONAL
    crits = V.temporality(rec, pair)
    med = [c for c in crits if c.grounding_key == "m3:Q16.3"]
    assert len(med) == 1 and med[0].severity == "blocking"
    assert med[0].source == "validator:temporality"
    assert med[0].category == "identification" and "mediate" in med[0].statement
    assert V.blocking(crits)
    # the confounder-or-mediator is a major, not blocking, temporal claim
    cm = [c for c in crits if c.grounding_key == "m1:Q4.1"]
    assert len(cm) == 1 and cm[0].severity == "major"


def test_the_same_mediator_passes_under_repeated_measures(built):
    rec, pair = built
    rm = _with_structure(rec, design=CS.REPEATED_MEASURES, unit_of_analysis="visit")
    assert V.temporality(rm, pair) == ()


# ------------------------------------------------------------- dag_consistency

def test_the_derived_graph_is_consistent(built):
    rec, pair = built
    assert V.dag_consistency(rec, pair) == ()


def test_seeded_violations_are_caught(built):
    rec, pair = built
    s = rec.structure
    # 1. the hypothesised edge removed
    no_edge = _with_structure(rec, edges=tuple(e for e in s.edges
                                              if e.relation != "hypothesised"))
    assert any("under test is absent" in c.statement
               for c in V.dag_consistency(no_edge, pair))
    # 2. an adjusted node placed on the X -> Y path
    on_path = _with_structure(rec, edges=(
        *s.edges, CS.Edge(source=s.exposure, target="m1:Q5.5", relation="causes")))
    hits = [c for c in V.dag_consistency(on_path, pair) if c.grounding_key == "m1:Q5.5"]
    assert hits and hits[0].severity == "blocking"
    assert "directed path" in hits[0].statement
    # 3. a cycle
    cyc = _with_structure(rec, edges=(
        *s.edges, CS.Edge(source=s.outcome, target=s.exposure, relation="causes")))
    assert any("cycle" in c.statement for c in V.dag_consistency(cyc, pair))
    # 4. an adjusted node touching neither anchor
    lonely = _with_structure(rec, edges=tuple(e for e in s.edges
                                             if "m1:Q5.5" not in (e.source, e.target)))
    assert any(c.grounding_key == "m1:Q5.5" and "neither anchor" in c.statement
               for c in V.dag_consistency(lonely, pair))


# ----------------------------------------------------------------- cell_counts

def test_cell_counts_is_silent_without_an_n_and_blocks_below_the_floor(built):
    rec, pair = built
    assert V.cell_counts(rec, pair) == ()             # analytic_n is None today
    proto = dict(rec.artefact.protocol)
    est = dict(proto["estimability"])
    est["analytic_n"] = 40
    est["smallest_detectable_effect"] = dict(est["smallest_detectable_effect"] or {},
                                             at_n=200)
    proto["estimability"] = est
    small = rec.model_copy(update={"artefact": rec.artefact.model_copy(
        update={"protocol": proto})})
    crits = V.cell_counts(small, pair)
    assert len(crits) == 1 and crits[0].severity == "blocking"
    assert crits[0].category == "feasibility"
    est["analytic_n"] = 200
    ok = rec.model_copy(update={"artefact": rec.artefact.model_copy(
        update={"protocol": proto})})
    assert V.cell_counts(ok, pair) == ()


# ----------------------------------------------------------- measurement_level

def test_measurement_level_accepts_a_derivation_over_a_grid_battery(built):
    rec, pair = built
    assert pair.exposure.is_group and rec.structure.nodes[0].kind == "derivation"
    assert V.measurement_level(rec, pair) == ()


def test_measurement_level_rejects_a_bare_grid_anchor_and_free_text(built):
    rec, pair = built
    bare = _with_structure(rec, nodes=(
        rec.structure.nodes[0].model_copy(update={"kind": "variable"}),
        *rec.structure.nodes[1:]))
    crits = V.measurement_level(bare, pair)
    assert len(crits) == 1 and "signed derivation" in crits[0].statement
    free = Construct(construct_key="m2:Q5.8", module="2", base_id="Q5.8", stem_text="s",
                     member_keys=["m2:Q5.8"], is_group=False, is_free_text=True,
                     roster_instances=0)
    pair_ft = RP.ResolvedPair(exposure=pair.exposure, outcome=free,
                              retrieval=pair.retrieval)
    crits = V.measurement_level(rec, pair_ft)
    assert len(crits) == 1 and "free text" in crits[0].statement


# ---------------------------------------------------------------- apply / wire

def test_apply_attaches_critiques_through_the_seam_without_a_revision(built):
    rec, pair = built
    out = V.apply(rec, pair)
    assert rec.critiques == () and out.revision == 0
    assert out.critiques == V.validate(rec, pair)
    assert all(c.source.startswith("validator:") for c in out.critiques)
    assert V.blocking(out.critiques)                      # the mediator
    assert V.rejected_note(out.critiques) == "validator:temporality"
    assert H.HypothesisRecord.from_json(out.to_json()) == out


def test_a_resolved_blocking_critique_no_longer_blocks(built):
    rec, pair = built
    crits = tuple(c.model_copy(update={"resolved": True}) for c in V.validate(rec, pair))
    assert not V.blocking(crits) and V.rejected_note(crits) == ""
