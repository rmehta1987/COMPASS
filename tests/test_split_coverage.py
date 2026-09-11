"""C29-C's measurement: the split arm is scored end to end, and its harm beside it.

Every test here drives `benchmark/split_coverage.py::score_requests` with a
stand-in pool function, so none needs the deployed encoder. The route's own
`_split_pools` and `_union_pools` still run: the stand-in replaces retrieval,
not the code that turns a split into pools.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent import prompt_contract as PC
from benchmark import split_coverage as SC

REQ = "Does smoking raise high blood pressure?"

#: What a stand-in retrieval returns for each query text. `m3:Q4.2` is the
#: exposure's item, `m2:Q5.8` the outcome's; `m3:Q2.1` is neither.
POOLS = {REQ: ["m3:Q2.1", "m2:Q5.8"], "smoking": ["m3:Q4.2"],
         "high blood pressure": ["m2:Q5.8"], "blood": ["m3:Q2.1"]}

#: Two keys on one target stand for a roster member and its representative.
TARGET_OF = {"m3:Q4.2": 1, "m3:Q4.2~member": 1, "m2:Q5.8": 2, "m3:Q2.1": 3}


def _pool(_state: object, text: str, _role: str, _k: int) -> dict[str, Any]:
    ks = POOLS[text]
    return {"cands": PC.candidates_from_keys(ks), "cos": dict.fromkeys(ks, 0.5),
            "skipped": [], "rendered": text}


def _row(exposure_key: str | None, outcome_key: str | None = "m2:Q5.8",
         rid: str = "1x1-000") -> dict[str, Any]:
    return {"request_id": rid, "request": REQ,
            "shape": {"exposures": 1, "outcomes": 1},
            "slots": [{"role": "exposure", "phrase": "smoking", "key": exposure_key},
                      {"role": "outcome", "phrase": "high blood pressure",
                       "key": outcome_key}]}


def _split(exposures: list[str], outcomes: list[str]) -> str:
    return json.dumps({"exposures": exposures, "outcomes": outcomes})


def _score(rows: list[dict], replies: dict[str, str]) -> dict[str, Any]:
    return SC.score_requests({"requests": rows},
                             {"model": "scripted", "replies": replies},
                             state=None, pool_fn=_pool, target_of=TARGET_OF)


@pytest.fixture(autouse=True)
def _route_uses_the_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_split_pools` calls the route's own `_role_candidates`; point it here."""
    from serve import api

    monkeypatch.setattr(api, "_role_candidates", _pool)


def test_a_split_that_carries_what_the_shared_pool_dropped_counts_as_a_gain() -> None:
    """The shared pool misses the exposure's item; the split's own pool has it."""
    rep = _score([_row("m3:Q4.2")], {"1x1-000": _split(["smoking"],
                                                       ["high blood pressure"])})
    row = rep["rows"][0]
    assert (row["shared"], row["split"], row["oracle"]) == (False, True, True)
    assert rep["split_gain"] == 1 and rep["wrong_split_harm"] == 0
    assert rep["split_status"] == {"used": 1}


def test_a_split_that_loses_what_the_shared_pool_had_counts_as_harm() -> None:
    """Harm is reported beside coverage, never folded into it."""
    # The shared pool happens to hold this exposure's item, and the split's own
    # exposure pool does not.
    rows = [_row("m3:Q2.1")]
    rep = _score(rows, {"1x1-000": _split(["smoking"], ["high blood pressure"])})
    assert rep["rows"][0]["shared"] is True and rep["rows"][0]["split"] is False
    assert rep["wrong_split_harm"] == 1 and rep["split_gain"] == 0


def test_a_refused_split_falls_back_to_the_shared_pool_as_the_route_does() -> None:
    """A split that adds a word is scored as the shared pool, and counted."""
    rep = _score([_row("m3:Q4.2")], {"1x1-000": _split(["tobacco"],
                                                       ["high blood pressure"])})
    row = rep["rows"][0]
    assert row["split_status"] == "fallback"
    assert row["split"] == row["shared"] is False
    # Both arms missed: that is neither harm nor gain. Harm is what the split
    # LOST against the shared pool, not every miss the split made.
    assert rep["wrong_split_harm"] == 0 and rep["split_gain"] == 0


def test_a_gold_offered_only_to_the_other_role_is_not_covered() -> None:
    """`_pair` asks each role of its own pool, so coverage is role-aware."""
    pools = {"exposure": _pool(None, "high blood pressure", "outcome", 20),
             "outcome": _pool(None, "smoking", "exposure", 20)}
    golds = {"exposure": ["m3:Q4.2"], "outcome": ["m2:Q5.8"]}
    assert not SC.offers_every_gold(pools, golds, TARGET_OF)
    swapped = {"exposure": pools["outcome"], "outcome": pools["exposure"]}
    assert SC.offers_every_gold(swapped, golds, TARGET_OF)


def test_a_gold_is_matched_by_target_not_by_key() -> None:
    """Another member of the same target is the same item."""
    pools = {"exposure": _pool(None, "smoking", "exposure", 20),
             "outcome": _pool(None, "high blood pressure", "outcome", 20)}
    golds = {"exposure": ["m3:Q4.2~member"], "outcome": ["m2:Q5.8"]}
    assert SC.offers_every_gold(pools, golds, TARGET_OF)


def test_a_phrase_the_instrument_lacks_leaves_the_denominator() -> None:
    """A null gold makes 'every construct covered' undefined, not a miss."""
    assert SC.gold_by_role(_row(None)) is None
    assert SC.gold_by_role(_row("m3:Q4.2")) == {"exposure": ["m3:Q4.2"],
                                                "outcome": ["m2:Q5.8"]}
    rep = _score([_row(None), _row("m3:Q4.2", rid="1x1-001")],
                 {"1x1-001": _split(["smoking"], ["high blood pressure"])})
    assert rep["gold_excluded"] == ["1x1-000"]
    assert rep["n_scored"] == 1
