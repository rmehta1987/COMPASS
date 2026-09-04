"""RetrievalRecord: the persisted outcome of one retrieval.

Pins the JSON round trip (item 2's acceptance), the abstention invariants, and
the two deliberate absences: no wording, no dataclass identity.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

REQ = RequestSnapshot(construct_text="use of anti-inflammatory medication",
                      role="exposure", population=None,
                      timeframe="past 12 months",
                      instances=("ibuprofen", "naproxen"))
HIT = Hit(key="m2:Q9.95", construct_key="m2:Q9.95", module="2", target_id=17,
          fold_size=1, n_siblings=0, members=("m2:Q9.95",),
          stratum="reproductive_hormonal", unmeasured_stratum=False)
RESOLVED = RetrievalRecord(request=REQ, query="use of anti-inflammatory medication "
                           "past 12 months: ibuprofen, naproxen",
                           dictionary_hash="3dc8415eccfe", min_cos=0.729476,
                           best_cos=0.812345, margin=0.812345 - 0.729476,
                           margin_12=0.031, abstained=False,
                           nearest_key="m2:Q9.95", hit=HIT)
PM25 = RequestSnapshot(construct_text="ambient PM2.5 exposure", role="exposure")
ABSTAINED = RetrievalRecord(request=PM25,
                            query="ambient PM2.5 exposure",
                            dictionary_hash="3dc8415eccfe", min_cos=0.729476,
                            best_cos=0.61, margin=0.61 - 0.729476, margin_12=None,
                            abstained=True, nearest_key="m2:Q3.5", hit=None)


@pytest.mark.parametrize("rec", [RESOLVED, ABSTAINED], ids=["resolved", "abstained"])
def test_json_round_trip_is_lossless(rec):
    back = RetrievalRecord.from_json(rec.to_json())
    assert back == rec
    assert back.to_json() == rec.to_json()
    # tuples survive as tuples, not lists, and None survives as None
    assert isinstance(back.request.instances, tuple)
    assert back.hit is None or isinstance(back.hit.members, tuple)


def test_the_wire_format_is_plain_json_with_no_wording_fields():
    d = json.loads(RESOLVED.to_json())
    assert set(d) == {"request", "query", "dictionary_hash", "min_cos", "best_cos",
                      "margin", "margin_12", "abstained", "nearest_key", "hit"}
    assert set(d["hit"]) == {"key", "construct_key", "module", "target_id",
                             "fold_size", "n_siblings", "members", "stratum",
                             "unmeasured_stratum"}
    for wording in ("stem", "option", "text", "question_text"):
        assert wording not in d["hit"]


def test_unknown_fields_are_refused():
    d = json.loads(RESOLVED.to_json())
    d["stem"] = "leaked"
    with pytest.raises(ValidationError):
        RetrievalRecord.model_validate(d)


@pytest.mark.parametrize("patch", [
    {"abstained": True},                       # abstained but carries a hit
    {"hit": None},                             # resolved but no hit
    {"best_cos": 0.5, "margin": 0.5 - 0.729476},  # resolved below threshold
    {"margin": 0.0},                           # margin disagrees with the cosines
    {"nearest_key": "m2:Q3.5"},                # selected hit is not the nearest
], ids=["abstained_with_hit", "resolved_without_hit", "resolved_below_tau",
        "margin_mismatch", "hit_not_nearest"])
def test_inconsistent_abstention_is_refused(patch):
    d = json.loads(RESOLVED.to_json())
    d.update(patch)
    with pytest.raises(ValidationError):
        RetrievalRecord.model_validate(d)


def test_abstained_record_may_not_carry_a_runner_up_margin():
    d = json.loads(ABSTAINED.to_json())
    d["margin_12"] = 0.01
    with pytest.raises(ValidationError):
        RetrievalRecord.model_validate(d)


def test_hit_from_retriever_dict_drops_wording():
    raw = {"target_id": 3, "key": "m1:Q5.4", "construct_key": "m1:Q5.4",
           "module": 1, "stem": "WORDING", "option": "WORDING", "fold_size": 2,
           "n_siblings": 4, "members": ["m1:Q5.4", "m1:Q5.4_1"], "cos": 0.73}
    h = Hit.from_hit(raw, stratum="ses_employment", unmeasured_stratum=True)
    assert h.key == "m1:Q5.4" and h.module == "1"
    assert h.stratum == "ses_employment" and h.unmeasured_stratum is True
    assert h.members == ("m1:Q5.4", "m1:Q5.4_1")
    assert "WORDING" not in h.model_dump_json()


def test_request_snapshot_takes_the_shipped_dataclass_by_duck_type():
    from deploy.template import RetrievalRequest, VariableRole
    req = RetrievalRequest(construct="hormone medication", role=VariableRole.OUTCOME,
                           instances=("estrogen",))
    snap = RequestSnapshot.from_request(req)
    assert snap.role == "outcome" and snap.instances == ("estrogen",)
    assert snap.construct_text == "hormone medication"
    assert snap.population is None and snap.timeframe is None
