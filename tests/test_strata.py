"""Strata: which parts of the instrument the retrieval benchmark never measured.

The rule is `src/char_strata.py`'s, reused by path. The fake tests pin the
mechanics; the bundle test pins the four unmeasured strata the brief names and
their size, on the frozen bundle (hash pinned in tests/test_dictionary.py) and
the tracked pre-registration file.
"""

from __future__ import annotations

import pytest

from pipeline import strata as S

FAKE_TARGETS = [
    {"target_id": 1, "construct_key": "c1", "members": ["k1", "k1b"],
     "stem": "how old were you when you were first told that you had asthma"},
    {"target_id": 2, "construct_key": "c2", "members": ["k2"],
     "stem": "what is your total household income"},
    {"target_id": 3, "construct_key": "c2", "members": ["k3"],
     "stem": "what is your total household income"},
    {"target_id": 4, "construct_key": "c4", "members": ["k4"],
     "stem": "please pick a contact preference"},
]


def test_strata_are_the_committed_classifiers():
    st = S.Strata.from_targets(FAKE_TARGETS, ["k1b"])
    assert st.stratum_of == {1: "chronic_condition", 2: "ses_employment",
                             3: "ses_employment", 4: "unclassified"}
    assert st.targets_per_stratum == {"chronic_condition": 1, "ses_employment": 2,
                                      "unclassified": 1}
    assert st.constructs_per_stratum == {"chronic_condition": 1, "ses_employment": 1,
                                         "unclassified": 1}


def test_a_gold_key_counts_through_target_membership_not_canonical_key():
    st = S.Strata.from_targets(FAKE_TARGETS, ["k1b", "k1b", "nope"])
    assert st.rows_per_stratum == {"chronic_condition": 2}   # unknown key ignored


def test_unmeasured_is_zero_rows_and_of_reports_it():
    st = S.Strata.from_targets(FAKE_TARGETS, ["k1"])
    assert st.unmeasured() == {"ses_employment", "unclassified"}
    assert st.of(1) == ("chronic_condition", False)
    assert st.of(2) == ("ses_employment", True)
    assert st.of(4) == ("unclassified", True)


@pytest.fixture(scope="module")
def bundle_strata():
    import json
    targets = S.ROOT / "deploy" / "targets.json"
    if not targets.exists():
        pytest.skip("deploy/targets.json is withheld from the public tree")
    T = json.loads(targets.read_text())["targets"]
    return S.Strata.from_targets(T, S.gold_keys())


def test_the_four_named_strata_are_unmeasured_on_the_frozen_bundle(bundle_strata):
    named = {"ses_employment", "insurance_access", "cancer_screening", "demographics"}
    assert named <= bundle_strata.unmeasured()
    # survey admin has no gold rows either; its quality is just as unknown
    assert "unclassified" in bundle_strata.unmeasured()
    # and nothing the fixture does cover is flagged
    assert not ({"chronic_condition", "medication", "reproductive_hormonal",
                 "cancer_history", "tobacco"} & bundle_strata.unmeasured())


def test_the_named_gap_is_61_targets_across_51_constructs(bundle_strata):
    # CHARACTERISATION.md section 4, reproduced 2026-09-04 from the bundle and
    # out/qx_preregistration.json. Both inputs are frozen (dictionary hash
    # pinned; the pre-registration is tracked), so this is a pin on frozen
    # data, not on today's corpus. If it moves, the bundle or the fixture did.
    named = ("ses_employment", "insurance_access", "cancer_screening", "demographics")
    assert sum(bundle_strata.targets_per_stratum[s] for s in named) == 61
    assert sum(bundle_strata.constructs_per_stratum[s] for s in named) == 51


def test_chronic_condition_is_measured_and_an_ses_target_is_not(bundle_strata):
    # item 5's acceptance, by stratum rather than by a hand-picked id
    st = bundle_strata
    chronic = next(i for i, s in st.stratum_of.items() if s == "chronic_condition")
    ses = next(i for i, s in st.stratum_of.items() if s == "ses_employment")
    assert st.of(chronic)[1] is False
    assert st.of(ses)[1] is True
