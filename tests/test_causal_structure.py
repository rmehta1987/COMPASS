"""CausalStructure: the record's roles as a typed graph, and HypothesisRecord."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent.schema import CausalRole, ProtocolSpecification
from generate.funnel import load_constructs
from generate.run_specifier import fixture
from pipeline import causal_structure as CS
from pipeline import hypothesis as H
from pipeline import resolved_pair as RP
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476
PROSE_FIELDS = {"question", "mechanism", "justification", "falsifier", "log"}


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
    return p, pair, CS.derive(p)


def test_anchors_first_and_the_hypothesised_edge_first(built):
    p, _, s = built
    assert s.nodes[0].position == "exposure" and s.nodes[1].position == "outcome"
    assert s.exposure == "derivation:social_cohesion_scale" and s.outcome == "m2:Q5.8"
    assert s.edges[0] == CS.Edge(source=s.exposure, target=s.outcome,
                                 relation="hypothesised")
    assert s.expected_direction == p.expected_direction.direction.value


def test_every_role_lays_out_its_edges(built):
    _, _, s = built
    roles = s.roles("adjusted")
    assert roles == {"m1:Q3.11": "confounder", "m1:Q5.4": "confounder",
                     "m1:Q5.5": "precision", "m1:Q3.10": "proxy"}
    out = {k: [(e.target, e.relation) for e in s.edges if e.source == k] for k in roles}
    assert sorted(out["m1:Q3.11"]) == [(s.exposure, "causes"), (s.outcome, "causes")]
    assert out["m1:Q5.5"] == [(s.outcome, "causes")]
    assert sorted(out["m1:Q3.10"]) == [(s.exposure, "proxies"), (s.outcome, "proxies")]
    assert s.adjustment_set == ("m1:Q3.11", "m1:Q5.4", "m1:Q5.5", "m1:Q3.10")


def test_design_comes_from_the_unit_of_analysis(built):
    p, _, s = built
    assert s.unit_of_analysis == p.model_spec.unit_of_analysis.value
    assert s.design == CS.design_of(s.unit_of_analysis)
    assert CS.design_of("participant") == CS.CROSS_SECTIONAL
    assert CS.design_of("visit") == CS.REPEATED_MEASURES
    assert CS.design_of("participant-year") == CS.REPEATED_MEASURES


def test_the_structure_is_typed_not_prose(built):
    _, _, s = built
    d = json.loads(s.model_dump_json())
    keys: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            keys.update(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(d)
    assert not (keys & PROSE_FIELDS)
    with pytest.raises(ValidationError):
        CS.Node(key="k", kind="variable", position="covariate", decision="kept")
    with pytest.raises(ValidationError):
        CS.Edge(source="a", target="b", relation="maybe")


def test_every_role_in_the_vocabulary_has_a_defined_edge_set_or_none():
    # a role the edge table forgets would silently become an isolated node
    for role in CausalRole:
        edges = CS.EDGES_BY_ROLE.get(role.value, ())
        if role in (CausalRole.not_a_cause_of_either, CausalRole.confounder_or_mediator,
                    CausalRole.unadjudicated, CausalRole.unreliable_coding):
            assert edges == ()
        else:
            assert edges
    assert set(CS.EDGES_BY_ROLE) <= {r.value for r in CausalRole}


def test_hypothesis_record_round_trips_and_redacts(built):
    p, pair, s = built
    h = H.build(p, pair)
    assert h.structure == s and h.artefact.record_hash == p.record_hash()
    assert H.HypothesisRecord.from_json(h.to_json()) == h
    r = h.redacted()
    assert r.artefact.redacted and r.structure == s
    assert set(json.loads(h.to_json())) == {"artefact", "structure"}
