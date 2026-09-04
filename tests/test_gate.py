"""The estimability gate: zero pairs pass today, and the bypass leaves a marker.

`python -m pipeline.gate` (check.sh step 9) runs it on the worked-example
frame against the built dictionary; these pin the logic on small pairs and
that the export names are the ones env/tools.py::estimate_n itself uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from env.tools import estimate_n
from pipeline import gate as G


@dataclass
class Con:
    construct_key: str
    member_keys: list[str]
    module: str


@dataclass
class Cand:
    exposure: Con
    outcome: Con
    state: str = "live"
    tags: dict = field(default_factory=dict)

    @property
    def pair_id(self) -> str:
        return f"{self.exposure.construct_key} -> {self.outcome.construct_key}"


CROSS = Cand(Con("m3:Q16.1", ["m3:Q16.1_1", "m3:Q16.1_2"], "3"),
             Con("m2:Q5.8", ["m2:Q5.8"], "2"))
SAME = Cand(Con("m2:Q5.7", ["m2:Q5.7"], "2"), Con("m2:Q5.8", ["m2:Q5.8"], "2"))
PRUNED = Cand(Con("m2:Q5.7", ["m2:Q5.7"], "2"), Con("m2:Q5.7", ["m2:Q5.7"], "2"),
              state="pruned")


def test_the_export_names_are_estimate_n_s_own():
    # cross-module: estimate_n names the co-completion counts outright
    r = estimate_n(["m3:Q16.1_1", "m2:Q5.8"])
    assert r["n_source"] == "unknown" and r["blocked_on"] == G.MODULE_CO_COMPLETION
    # single-module: no blocked_on key, but the log names the per-item counts
    r = estimate_n(["m2:Q5.7", "m2:Q5.8"])
    assert r["n_source"] == "unknown" and "blocked_on" not in r
    assert G.PER_ITEM_NON_MISSING in r["log"]


def test_without_the_flag_zero_pairs_pass_and_both_exports_are_named():
    res = G.gate([CROSS, SAME, PRUNED])
    assert res.passed == () and len(res.blocked) == 2          # pruned is not judged
    assert set(res.missing_exports) == set(G.MISSING_EXPORTS)
    by = {v.pair_id: v for v in res.verdicts}
    assert by[CROSS.pair_id].blocked_on == G.MISSING_EXPORTS
    assert by[SAME.pair_id].blocked_on == (G.PER_ITEM_NON_MISSING,)
    assert all(v.estimability == G.BLOCKED and v.n_source == "unknown"
               for v in res.verdicts)


def test_the_bypass_passes_every_pair_and_every_one_carries_the_marker():
    res = G.gate([CROSS, SAME], allow_unestimable=True)
    assert len(res.passed) == 2 and res.blocked == ()
    assert all(v.estimability == G.BLOCKED for v in res.passed)
    assert all(v.blocked_on for v in res.passed)                # the exports travel too
    assert res.allow_unestimable is True


def test_there_is_no_unmarked_bypass():
    # a pair passes either because it is estimable or because the flag is set
    # and it is marked; no verdict can be passed, blocked-on-something and
    # labelled estimable at once
    for flag in (False, True):
        for v in G.gate([CROSS, SAME], allow_unestimable=flag).verdicts:
            assert v.passed == (v.estimability == G.ESTIMABLE or flag)
            assert (v.estimability == G.ESTIMABLE) == (v.blocked_on == ())


def test_an_estimable_pair_would_pass_without_the_flag(monkeypatch):
    # the day estimate_n computes n, the gate opens on its own; nothing else changes
    computed = {"n_source": "computed_from_counts", "analytic_n": 1}
    monkeypatch.setattr(G, "estimate_n", lambda keys: computed)
    res = G.gate([CROSS])
    assert len(res.passed) == 1 and res.passed[0].estimability == G.ESTIMABLE
    assert res.missing_exports == ()
