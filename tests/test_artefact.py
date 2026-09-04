"""The Specifier's artefact: every named variable traced, wording redactable.

Uses the worked-example fixture record from generate/run_specifier.py and real
constructs from the built dictionary, so it skips where build/ is withheld.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

import pytest

from agent.schema import ProtocolSpecification
from generate.funnel import load_constructs
from generate.run_specifier import fixture
from pipeline import artefact as A
from pipeline import resolved_pair as RP
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


def _rec(role: str, key: str, ck: str, members: tuple[str, ...],
         source: str) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text=f"typed {role}", role=role, source=source),
        query=f"typed {role}", dictionary_hash="h", min_cos=TAU, best_cos=0.9,
        margin=0.9 - TAU, margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=members,
                stratum="x", unmeasured_stratum=False))


def _wordings(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "quoted_wording" and isinstance(v, str):
                yield v
            else:
                yield from _wordings(v)
    elif isinstance(node, list):
        for x in node:
            yield from _wordings(x)


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k != "quoted_wording"}
    if isinstance(node, list):
        return [_strip(x) for x in node]
    return node


@pytest.fixture(scope="module")
def built() -> tuple[ProtocolSpecification, RP.ResolvedPair, A.SpecifierArtefact]:
    try:
        C, version = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    p = ProtocolSpecification.model_validate_json(fixture(version, 384))
    e_key = C["m3:Q16.1"].member_keys[0]
    rec_e = _rec("exposure", e_key, "m3:Q16.1", tuple(C["m3:Q16.1"].member_keys),
                 "instrument")
    rec_o = _rec("outcome", "m2:Q5.8", "m2:Q5.8", ("m2:Q5.8",), "user")
    pair = RP.from_records(rec_e, rec_o, C, estimability="blocked_no_metadata")
    return p, pair, A.emit(p, pair)


def test_every_named_variable_has_a_provenance_line(built):
    p, _, art = built
    named = A.named_variables(p)
    assert [(v.key, v.where, v.kind) for v in art.variables] == named
    assert named[0][1] == "exposure" and named[1][1] == "outcome"
    assert len(named) >= 6                      # two anchors + four covariates


def test_anchors_carry_their_full_records_and_covariates_say_so(built):
    p, pair, art = built
    by_where: dict[str, list[A.VariableProvenance]] = {}
    for v in art.variables:
        by_where.setdefault(v.where, []).append(v)
    assert by_where["exposure"][0].retrieval == pair.retrieval[0]
    assert by_where["outcome"][0].retrieval == pair.retrieval[1]
    assert by_where["exposure"][0].kind == "derivation"     # the fixture's exposure
    for v in by_where["adjusted"]:
        assert v.source == "specifier_tool" and v.retrieval is None
    assert art.retrieval == {"exposure": pair.retrieval[0], "outcome": pair.retrieval[1]}
    assert art.estimability == "blocked_no_metadata"
    assert art.record_hash == p.record_hash() and art.pair_id == pair.pair_id


def test_the_artefact_round_trips_and_carries_the_whole_record(built):
    p, _, art = built
    back = A.SpecifierArtefact.from_json(art.to_json())
    assert back == art
    assert ProtocolSpecification.model_validate(back.protocol) == p


def test_a_record_for_another_pair_is_refused(built):
    p, pair, _ = built
    other = RP.ResolvedPair(exposure=pair.outcome, outcome=pair.exposure,
                            retrieval=(pair.retrieval[1], pair.retrieval[0]))
    with pytest.raises(ValueError, match="not in the pair's outcome construct"):
        A.emit(p, other)


def test_redaction_removes_every_piece_of_instrument_wording(built):
    _, _, art = built
    red = A.redact(art)
    assert red.redacted and not art.redacted
    text = red.to_json()
    originals = list(_wordings(art.protocol))
    assert originals
    for w in originals:
        assert w not in text
        assert "sha256:" + hashlib.sha256(w.encode()).hexdigest() in text
    # the instrument-sourced exposure record is digested; the user-typed
    # outcome record keeps its text
    assert red.retrieval["exposure"].query.startswith("sha256:")
    assert red.retrieval["exposure"].request.construct_text.startswith("sha256:")
    assert red.retrieval["outcome"].query == "typed outcome"
    assert A.redact(red) == red                             # idempotent
    assert A.SpecifierArtefact.from_json(text) == red       # still a valid artefact


def test_redaction_touches_nothing_else(built):
    _, _, art = built
    a = json.loads(art.to_json())
    b = json.loads(A.redact(art).to_json())
    assert _strip(a["protocol"]) == _strip(b["protocol"])
    assert a["variables"][1] == b["variables"][1]           # user-sourced outcome
    assert a["record_hash"] == b["record_hash"] and a["pair_id"] == b["pair_id"]
