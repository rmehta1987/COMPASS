"""Auto intake: a funnel pair to two requests, both resolved, on a fake bundle.

`python -m pipeline.auto_intake --pair m3:Q16.1 m2:Q5.8` and `--frame`
(check.sh step 8) are the acceptance against the real bundle and dictionary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from pipeline import auto_intake as A
from pipeline.retrieve import load_template


@dataclass
class Con:
    construct_key: str
    stem_text: str
    module: str = "2"


@dataclass
class Cand:
    exposure: Con
    outcome: Con

    @property
    def pair_id(self) -> str:
        return f"{self.exposure.construct_key} -> {self.outcome.construct_key}"


class Fake:
    """Two targets; cosines chosen per query text."""

    min_cos = 0.729476
    manifest: ClassVar[dict[str, Any]] = {"dictionary_version_hash": "h"}
    targets: ClassVar[list[dict[str, Any]]] = [
        {"target_id": 1, "canonical_key": "m3:Q16.1_2", "construct_key": "m3:Q16.1",
         "dict_construct_key": "m3:Q16.1", "module": "3", "stem": "neighborhood",
         "option": "O", "fold_size": 1, "siblings": [], "members": ["m3:Q16.1_2"]},
        {"target_id": 2, "canonical_key": "m2:Q5.8~x", "construct_key": "m2:Q5.8~x",
         "dict_construct_key": "m2:Q5.8", "module": "2", "stem": "blood pressure",
         "option": "O", "fold_size": 1, "siblings": [], "members": ["m2:Q5.8~x"]},
    ]

    def __init__(self, scores: dict[str, tuple[float, float]]) -> None:
        """Map query text to (cos target 1, cos target 2)."""
        self.scores = scores

    def search(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        c1, c2 = self.scores[query]
        out = []
        for t, c in zip(self.targets, (c1, c2), strict=True):
            out.append({"target_id": t["target_id"], "key": t["canonical_key"],
                        "construct_key": t["construct_key"], "module": t["module"],
                        "stem": t["stem"], "option": t["option"],
                        "fold_size": t["fold_size"], "n_siblings": 0,
                        "members": t["members"], "cos": c})
        out.sort(key=lambda h: -h["cos"])
        return out[:k]


CAND = Cand(Con("m3:Q16.1", "how safe the neighborhood feels", "3"),
            Con("m2:Q5.8", "told you had high blood pressure"))


def test_requests_carry_roles_no_instances_no_population():
    tpl = load_template()
    e, o = A.requests_for(CAND, tpl)
    assert e.role is tpl.VariableRole.EXPOSURE and o.role is tpl.VariableRole.OUTCOME
    assert e.construct == CAND.exposure.stem_text
    assert o.construct == CAND.outcome.stem_text
    assert e.instances == () == o.instances and e.population is None is o.population


def test_both_sides_resolve_by_dictionary_construct_not_target_construct():
    r = Fake({"how safe the neighborhood feels": (0.9, 0.3),
              "told you had high blood pressure": (0.2, 0.95)})
    pr = A.resolve_pair(r, CAND)
    assert pr.exposure_resolved and pr.outcome_resolved and pr.both_resolved
    # the outcome target's own construct_key differs from the dictionary's;
    # resolution compares the dictionary's
    assert pr.outcome.hit is not None
    assert pr.outcome.hit.construct_key == "m2:Q5.8~x"
    assert pr.outcome.hit.dict_construct_key == "m2:Q5.8"
    assert pr.pair_id == "m3:Q16.1 -> m2:Q5.8"


def test_records_are_marked_instrument_sourced():
    r = Fake({"how safe the neighborhood feels": (0.9, 0.3),
              "told you had high blood pressure": (0.2, 0.95)})
    pr = A.resolve_pair(r, CAND)
    assert pr.exposure.request.source == "instrument"
    assert pr.outcome.request.source == "instrument"
    assert pr.exposure.request.role == "exposure" and pr.outcome.request.role == "outcome"


def test_an_abstention_or_a_wrong_construct_does_not_resolve():
    r = Fake({"how safe the neighborhood feels": (0.5, 0.3),      # abstains
              "told you had high blood pressure": (0.95, 0.2)})   # lands on target 1
    pr = A.resolve_pair(r, CAND)
    assert not pr.exposure_resolved and not pr.outcome_resolved
    assert not pr.both_resolved
    assert pr.exposure.abstained and pr.outcome.hit is not None


def test_the_frame_floor_is_a_floor_below_its_live_count():
    assert 0 < A.FRAME_BOTH_FLOOR <= A.FRAME_LIVE
