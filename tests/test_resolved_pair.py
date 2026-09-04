"""ResolvedPair: two RetrievalRecords become a pair the Specifier takes.

Acceptance for item 10: the Specifier's signature names PairLike, a
ResolvedPair renders the byte-identical prompt to the funnel Candidate for the
same anchors, and it travels through specify_once's real path.
"""

from __future__ import annotations

import inspect

import pytest

from agent import specifier as SP
from agent.backends import Reply, ScriptedBackend
from generate.funnel import Candidate, Construct
from generate.run_specifier import ANALYSIS, REASON_CALLS_A
from pipeline import resolved_pair as RP
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


def _con(key: str, module: str, stem: str, members: list[str],
         is_group: bool = False) -> Construct:
    return Construct(construct_key=key, module=module, base_id=key.split(":")[1],
                     stem_text=stem, member_keys=members, is_group=is_group,
                     is_free_text=False, roster_instances=0)


CONSTRUCTS = {
    "m3:Q16.1": _con("m3:Q16.1", "3", "neighborhood cohesion", ["m3:Q16.1_1"], True),
    "m2:Q5.8": _con("m2:Q5.8", "2", "high blood pressure", ["m2:Q5.8"]),
}


def _rec(role: str, key: str, ck: str, *, abstained: bool = False,
         source: str = "user") -> RetrievalRecord:
    hit = None if abstained else Hit(
        key=key, construct_key=ck, dict_construct_key=ck, module=ck[1], target_id=1,
        fold_size=1, n_siblings=0, members=(key,), stratum="x", unmeasured_stratum=False)
    cos = 0.6 if abstained else 0.9
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="q", role=role, source=source),
        query="q", dictionary_hash="h", min_cos=TAU, best_cos=cos, margin=cos - TAU,
        margin_12=None if abstained else 0.1, abstained=abstained,
        nearest_key=key, hit=hit)


E = _rec("exposure", "m3:Q16.1_1", "m3:Q16.1")
OUT = _rec("outcome", "m2:Q5.8", "m2:Q5.8")


def test_the_specifier_signature_names_pairlike():
    for fn in (SP.specify, SP.specify_once, SP.user_prompt):
        assert inspect.signature(fn).parameters["pair"].annotation == "PairLike"


def test_a_resolved_pair_renders_the_byte_identical_prompt_to_a_candidate():
    rp = RP.from_records(E, OUT, CONSTRUCTS, estimability="blocked_no_metadata")
    cand = Candidate(exposure=CONSTRUCTS["m3:Q16.1"], outcome=CONSTRUCTS["m2:Q5.8"],
                     estimability="blocked_no_metadata", requires_derivation=True)
    assert SP.user_prompt(rp) == SP.user_prompt(cand)
    assert rp.pair_id == cand.pair_id == "m3:Q16.1 -> m2:Q5.8"


def test_the_records_ride_along_and_derivation_follows_the_funnel_rule():
    rp = RP.from_records(E, OUT, CONSTRUCTS)
    assert rp.retrieval == (E, OUT)
    assert rp.requires_derivation is True          # m3:Q16.1 is a grid battery
    assert rp.estimability is None                 # not gated yet


@pytest.mark.parametrize("bad, why", [
    ((_rec("exposure", "m3:Q16.1_1", "m3:Q16.1", abstained=True), OUT), "abstained"),
    ((E, _rec("outcome", "m2:Q9.99", "m2:Q9.99")), "does not hold"),
    ((OUT, E), "carries role"),                       # sides swapped
])
def test_a_hole_refuses_to_become_a_pair(bad, why):
    with pytest.raises(RP.Unresolved, match=why):
        RP.from_records(bad[0], bad[1], CONSTRUCTS)


def test_a_resolved_pair_goes_through_specify_once_s_real_path():
    # same script and same gate outcome as the Candidate test in test_specifier:
    # the Specifier does not know which implementation it was handed
    rp = RP.from_records(E, OUT, CONSTRUCTS, estimability="blocked_no_metadata")
    backend = ScriptedBackend([Reply(tool_calls=REASON_CALLS_A), Reply(content=ANALYSIS)])
    a = SP.specify_once(backend, rp, seed=0)
    assert a.gate == "missing_calls" and a.protocol is None


def test_from_pair_resolution_requires_both_sides():
    from pipeline.auto_intake import PairResolution
    ok = PairResolution("m3:Q16.1 -> m2:Q5.8", E, OUT, True, True)
    assert RP.from_pair_resolution(ok, CONSTRUCTS).pair_id == "m3:Q16.1 -> m2:Q5.8"
    half = PairResolution("m3:Q16.1 -> m2:Q5.8", E, OUT, True, False)
    with pytest.raises(RP.Unresolved):
        RP.from_pair_resolution(half, CONSTRUCTS)
