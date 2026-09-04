"""The canary evaluator, without the bundle.

`python -m pipeline.canary` (check.sh) runs the real requests; these pin that a
changed outcome is reported rather than swallowed, and that the three canaries
the brief names are present with the shape it describes.
"""

from __future__ import annotations

from pipeline import canary as C
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


def _rec(*, abstained: bool, key: str = "m1:Q5.4", cos: float = 0.731576,
         stratum: str = "ses_employment", unmeasured: bool = True) -> RetrievalRecord:
    hit = None if abstained else Hit(
        key=key, construct_key=key, module="1", target_id=5, fold_size=1,
        n_siblings=0, members=(key,), stratum=stratum, unmeasured_stratum=unmeasured)
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="x", role="exposure"), query="x",
        dictionary_hash="h", min_cos=TAU, best_cos=cos, margin=cos - TAU,
        margin_12=None if abstained else 0.01, abstained=abstained,
        nearest_key=key, hit=hit)


C3 = next(c for c in C.CANARIES if c.name == "C3")


def test_the_current_c3_behaviour_evaluates_clean():
    assert C.evaluate(C3, _rec(abstained=False)) == []


def test_an_abstention_on_c3_is_reported_as_a_change_not_hidden():
    bad = C.evaluate(C3, _rec(abstained=True, cos=0.70))
    assert any("abstained=True" in b for b in bad)
    assert any("margin=" in b for b in bad)        # the margin is recorded either way


def test_a_different_key_or_stratum_or_margin_is_reported():
    assert any("key=" in b for b in C.evaluate(C3, _rec(abstained=False, key="m1:Q5.5")))
    assert any("stratum=" in b for b in
               C.evaluate(C3, _rec(abstained=False, stratum="demographics")))
    assert any("unmeasured_stratum=" in b for b in
               C.evaluate(C3, _rec(abstained=False, unmeasured=False)))
    assert any("margin=" in b for b in C.evaluate(C3, _rec(abstained=False, cos=0.80)))


def test_the_brief_s_three_canaries_are_present_with_their_shape():
    names = [c.name for c in C.CANARIES]
    assert names[0] == "C1" and names[-1] == "C3"
    c1 = C.CANARIES[0]
    assert c1.stratum == "chronic_condition" and c1.unmeasured is False
    assert not c1.abstained
    c2 = [c for c in C.CANARIES if c.name.startswith("C2")]
    assert len(c2) == 5 and all(c.abstained for c in c2)
    assert C3.instances == ("median household income",) and C3.margin_4dp == 0.0021
    assert C3.key == "m1:Q5.4" and C3.unmeasured is True


def test_canaries_never_carry_a_population():
    # shipped contract: instances only
    assert all(not hasattr(c, "population") for c in C.CANARIES)
