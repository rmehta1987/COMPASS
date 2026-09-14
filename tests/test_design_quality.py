"""The groundedness dashboard: does each measure fire, and is its denominator stated?

Every test here builds its own corpus in `tmp_path`. None reads `run/`, on
purpose: `AGENTS.md` §Testing Patterns forbids pinning today's corpus, and a
dashboard test that asserts the numbers currently in `run/` would go red the
next time somebody runs the Specifier, which is progress and not a defect.

What IS pinned is that each measure fires on a seeded failure. A share that
cannot go down is not a measurement — `AGENTS.md` §Verification Discipline,
"could not detect X is never X is absent" — so every measure below has a
positive control that makes it move.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.schema import (
    NotSpecifiable,
    NSource,
    Provenance,
    RefusalEvidence,
    RefusalReason,
    Status,
    derive_status,
)
from agent.tool_authority import design_keys
from benchmark import design_quality as DQ

# The P-014 specimen, reused rather than copied. A second hand-built valid
# ProtocolSpecification would be seventy lines that drift from the schema the
# day a validator is added, and `AGENTS.md` §Efficiency and Commits says to say
# what is reused and why. `tests/test_schema.py` owns it; this file only varies
# it.
from tests.test_schema import DICT, p014

PROV = Provenance(dictionary_version=DICT["version_hash"], module_version="0.1",
                  prompt_hash="deadbeef", model_id="unset")


def ready() -> object:
    """A protocol that clears every clause of the status truth table."""
    est = p014().estimability.model_copy(
        update={"analytic_n": 1500, "n_source": NSource.synthetic_cohort})
    return p014(estimability=est, blocked_on=[], status=Status.ready_for_review)


def refusal(**over: object) -> NotSpecifiable:
    """A valid `registry_empty` refusal."""
    base = dict(
        pair_id="linked:neighborhood_disadvantage -> m3:Q16.2",
        dictionary_version=DICT["version_hash"],
        reason=RefusalReason.registry_empty,
        statement=("The linked registry holds no rows, so no area measure can "
                   "anchor the exposure side of this pair."),
        evidence=[
            RefusalEvidence(tool="registry_coverage", argument="linked",
                            outcome="linked: coverage none"),
            RefusalEvidence(tool="resolve_variable",
                            argument="linked:neighborhood_disadvantage",
                            outcome="not_found"),
        ],
        blocked_on=["area_measure_inventory"],
        what_would_unblock="an area measure inventory from the study team",
        provenance=PROV,
    )
    base.update(over)
    return NotSpecifiable(**base)


def write(d: Path, name: str, record, log: list[dict] | None = None) -> Path:
    """Write one record, and optionally the tool log beside it."""
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(record.model_dump_json(indent=1)
                 if hasattr(record, "model_dump_json") else json.dumps(record))
    if log is not None:
        f.with_suffix(".tool_log.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in log))
    return f


# --- the denominator --------------------------------------------------------- #

def test_the_corpus_listing_accounts_for_every_file_the_glob_matched(tmp_path):
    write(tmp_path, "good.json", p014())
    (tmp_path / "artifact.json").write_text(json.dumps({"recall_at_1": 0.56}))
    (tmp_path / "broken.json").write_text('{"protocol_id": "x", "exposure": 1}')
    (tmp_path / "notjson.json").write_text("{{{")
    c = DQ.load_corpus(tmp_path).as_dict()
    assert c["matched"] == 4
    assert sum(c["dispositions"].values()) == c["matched"], (
        "a matched file with no disposition is a file dropped silently, which "
        "is the denominator defect this listing exists to prevent")
    assert c["glob"] == "*.json"
    assert c["directory"] == str(tmp_path)


def test_a_non_record_json_file_is_classified_by_shape_not_validation(tmp_path):
    """`invalid` must mean "the schema rejects this record", never "other JSON"."""
    (tmp_path / "hybrid_pools.json").write_text(json.dumps({"arms": [1, 2]}))
    c = DQ.load_corpus(tmp_path)
    assert [f.path.name for f in c.of_kind(DQ.NOT_A_RECORD)] == ["hybrid_pools.json"]
    assert c.of_kind(DQ.INVALID) == []


def test_a_record_the_current_schema_rejects_is_reported_not_dropped(tmp_path):
    bad = json.loads(p014().model_dump_json())
    bad["protocol_id"] = ""
    (tmp_path / "rejected.json").write_text(json.dumps(bad))
    c = DQ.load_corpus(tmp_path).as_dict()
    assert c["dispositions"][DQ.INVALID] == 1
    assert c["invalid"][0]["file"] == "rejected.json"
    assert c["invalid"][0]["error"], "an invalid record must carry its reason"


def test_a_dotfile_record_is_counted_because_pathlib_glob_keeps_it(tmp_path):
    """A dotfile record is in the denominator.

    `run/` holds pinned failing records saved as dotfiles precisely so a SHELL
    `run/*.json` misses them. `pathlib.Path.glob` does not, so they are in the
    denominator and the listing has to name them.
    """
    write(tmp_path, ".pinned.json", p014())
    c = DQ.load_corpus(tmp_path)
    assert [f.path.name for f in c.of_kind(DQ.PROTOCOL)] == [".pinned.json"]
    assert c.as_dict()["glob_keeps_dotfiles"] is True


def test_a_share_over_nothing_is_not_zero_percent():
    assert DQ.Share(n=0, of=0, basis="nothing").fraction is None
    assert DQ.Share(n=0, of=3, basis="three").fraction == 0.0


def test_every_reported_share_states_what_its_denominator_counts(tmp_path):
    write(tmp_path, "a.json", p014())
    rep = DQ.report(tmp_path, unaided=None)
    shares = [v for v in rep.values()
              if isinstance(v, dict) and {"n", "of", "fraction"} <= set(v)]
    assert len(shares) >= 5
    for s in shares:
        assert s["basis"].strip(), s


# --- reaches ready_for_review, and why it does not --------------------------- #

def test_the_ready_share_moves_when_a_record_reaches_ready_for_review(tmp_path):
    write(tmp_path, "draft.json", p014())
    assert DQ.ready_share(DQ.load_corpus(tmp_path)).n == 0
    write(tmp_path, "ready.json", ready())
    s = DQ.ready_share(DQ.load_corpus(tmp_path))
    assert (s.n, s.of) == (1, 2)


def test_draft_reason_never_disagrees_with_the_status_truth_table():
    """Two copies of one truth table drift; this is what stops them.

    `draft_reason` walks `agent/schema.py::derive_status`'s clauses in the same
    order so the dashboard can say WHICH one held. It may never disagree about
    whether any clause held at all.
    """
    est = p014().estimability
    cases = [
        p014(),
        ready(),
        p014(estimability=est.model_copy(
            update={"analytic_n": 1500, "n_source": NSource.synthetic_cohort})),
    ]
    for p in cases:
        assert (DQ.draft_reason(p) is None) is (
            derive_status(p) is Status.ready_for_review), p.protocol_id


def test_draft_because_names_the_clause_that_is_holding_the_record(tmp_path):
    write(tmp_path, "draft.json", p014())
    assert DQ.draft_because(DQ.load_corpus(tmp_path)) == {DQ.N_UNKNOWN: 1}
    est = p014().estimability.model_copy(
        update={"analytic_n": 1500, "n_source": NSource.synthetic_cohort})
    write(tmp_path, "blocked.json", p014(estimability=est))
    assert DQ.draft_because(DQ.load_corpus(tmp_path)) == {
        DQ.N_UNKNOWN: 1, DQ.HAS_BLOCKERS: 1}


# --- asserted keys ----------------------------------------------------------- #

def test_asserted_keys_cover_a_derivation_s_components_and_an_exclusion():
    """The two key sets differ on purpose, and the difference is load-bearing.

    `agent/tool_authority.py::design_keys` builds what the access call must
    COVER and omits exclusions, because an excluded variable consumes no
    budget. This one is about what the record ASSERTS, so an exclusion counts.
    """
    p = p014()
    keys = DQ.asserted_keys(p)
    assert {"m3:Q2.33", "m3:Q2.62"} <= keys, "derivation components are asserted"
    excluded = {e.variable.key for e in p.excluded_variables}
    assert excluded <= keys
    covered = design_keys(json.loads(p.model_dump_json()))
    assert not (excluded & covered), (
        "design_keys must keep omitting exclusions; if it stops, this module's "
        "reason for having its own key walk is gone")


def test_resolves_live_says_no_to_a_key_that_matches_the_pattern_and_exists_nowhere():
    """The positive control for the key measure.

    `linked:household_poverty` satisfies `agent/schema.py::KEY_PATTERN` and is
    in no registry — the schema's own example of a well-formed invented key.
    Without this the 100% the dashboard reports could mean the probe never
    fires.
    """
    assert DQ.resolves_live("linked:household_poverty") is False
    assert DQ.resolves_live("m3:Q16.2") is True


def test_a_key_that_stops_resolving_is_counted_and_named(tmp_path, monkeypatch):
    write(tmp_path, "a.json", p014())
    before, unresolved = DQ.key_resolution(DQ.load_corpus(tmp_path))
    assert before.n == before.of > 0 and unresolved == {}

    real = DQ.resolves_live
    monkeypatch.setattr(DQ, "resolves_live",
                        lambda k: False if k == "m3:Q16.2" else real(k))
    after, unresolved = DQ.key_resolution(DQ.load_corpus(tmp_path))
    assert after.n == before.n - 1 and after.of == before.of
    assert unresolved == {"a.json": ["m3:Q16.2"]}


# --- refusals, against their own log ----------------------------------------- #

def test_citation_state_separates_a_call_that_never_ran_from_one_it_cannot_check():
    log = [{"tool": "resolve_variable", "outcome": "not_found"},
           {"tool": "registry_coverage", "outcome": "ok"}]
    assert DQ.citation_state("resolve_variable", "not_found", log) == DQ.OUTCOME_MATCHED
    assert DQ.citation_state("list_derivations", "ok", log) == DQ.ABSENT
    # The case that must NOT read as a failed citation: registry_coverage always
    # logs `ok` and the specifier stamps the emptiness it read out of the
    # payload. Presence is corroborated; the outcome is not checkable.
    assert DQ.citation_state("registry_coverage", "linked: coverage none",
                             log) == DQ.CALLED


def test_a_refusal_citing_a_lookup_that_never_ran_is_not_counted_as_grounded(tmp_path):
    ran = [{"tool": "resolve_variable", "outcome": "not_found"},
           {"tool": "registry_coverage", "outcome": "ok"}]
    write(tmp_path, "r.json", refusal(), log=ran)
    assert DQ.refusal_evidence_share(DQ.load_corpus(tmp_path)).n == 1

    # Seeded failure: the same record, with a log that never called the registry.
    write(tmp_path, "r.json", refusal(), log=ran[:1])
    s = DQ.refusal_evidence_share(DQ.load_corpus(tmp_path))
    assert (s.n, s.of) == (0, 1)


def test_the_required_tool_list_comes_from_the_reason_not_from_the_citations(tmp_path):
    """Padding the evidence list must not be able to raise the count."""
    padded = refusal(evidence=[
        RefusalEvidence(tool="registry_coverage", argument="linked",
                        outcome="linked: coverage none"),
        RefusalEvidence(tool="resolve_variable",
                        argument="linked:neighborhood_disadvantage",
                        outcome="not_found"),
        RefusalEvidence(tool="list_derivations", argument="", outcome="ok"),
    ])
    log = [{"tool": "list_derivations", "outcome": "ok"}]
    states = DQ.refusal_citations(padded, log)
    assert states.get(DQ.ABSENT) == 2, (
        "both REQUIRED lookups are missing from the log; the extra corroborated "
        "citation is not one of them")
    assert sum(states.values()) == 2, "one state per REQUIRED tool, no more"


def test_a_refusal_with_no_log_is_unmeasurable_and_not_a_failure(tmp_path):
    write(tmp_path, "r.json", refusal())          # no tool log beside it
    s = DQ.refusal_evidence_share(DQ.load_corpus(tmp_path))
    assert (s.n, s.of, s.unmeasurable) == (0, 0, 1)
    assert s.fraction is None, (
        "an unchecked citation is not a false one: it must not land as 0%")
    assert s.unmeasurable_why


def test_the_refusal_share_is_over_records_of_either_kind(tmp_path):
    write(tmp_path, "p.json", p014())
    write(tmp_path, "r.json", refusal())
    s = DQ.refusal_share(DQ.load_corpus(tmp_path))
    assert (s.n, s.of) == (1, 2)


# --- blockers ---------------------------------------------------------------- #

def test_blocker_disclosure_reports_the_distribution_beside_the_mean(tmp_path):
    write(tmp_path, "one.json", p014())
    write(tmp_path, "two.json", p014(blocked_on=["module_co_completion_counts",
                                                 "response_coding"]))
    b = DQ.blocker_disclosure(DQ.load_corpus(tmp_path))
    assert b["mean_len_blocked_on"] == 1.5
    assert b["by_member"] == {"module_co_completion_counts": 2,
                              "response_coding": 1}
    assert b["disclosing_at_least_one"]["n"] == 2


def test_the_mean_is_none_rather_than_zero_when_there_are_no_protocols(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    assert DQ.blocker_disclosure(DQ.load_corpus(tmp_path))["mean_len_blocked_on"] is None


# --- the numeric falsifier --------------------------------------------------- #

def test_the_falsifier_share_moves_when_a_record_carries_only_prose(tmp_path):
    write(tmp_path, "with.json", p014())
    assert DQ.numeric_falsifier(DQ.load_corpus(tmp_path)).n == 1
    write(tmp_path, "without.json", p014(falsifier_threshold=None))
    s = DQ.numeric_falsifier(DQ.load_corpus(tmp_path))
    assert (s.n, s.of) == (1, 2)


# --- the unaided split -------------------------------------------------------- #

def _unaided(pair: str, ex: str, out: str, verdict: str) -> dict:
    return {"schema": "unaided_specifiability/1", "pair_id": pair,
            "role": "pilot", "verdict": verdict,
            "exposure": {"construct_key": ex, "stem_text": ""},
            "outcome": {"construct_key": out, "stem_text": ""},
            "responses": [], "k": 0, "n_specifiable": 0, "min_specifiable": 1,
            "provenance": {}}


def test_the_unaided_split_reports_its_own_directory_and_probe_count(tmp_path):
    d = tmp_path / "unaided"
    d.mkdir()
    # Both anchors sit in registries `registry_coverage` declares EMPTY, so the
    # environment names a blocker and the pair is NO_COHERENT_DESIGN, not
    # NEEDS_INSTRUMENT. Same pair `unaided_specifiability.NEGATIVE_CONTROL` uses.
    (d / "neg.json").write_text(json.dumps(_unaided(
        "lab:assay_17 -> clinical:measure_23", "lab:assay_17",
        "clinical:measure_23", "not_specifiable_unaided")))
    (d / "pos.json").write_text(json.dumps(_unaided(
        "m3:Q16.2 -> m3:Q16.3", "m3:Q16.2", "m3:Q16.3",
        "specifiable_unaided")))
    split = DQ.instrument_split(d)
    assert split["probed"] == 2
    assert split["split"]["no_coherent_design"] == 1
    assert split["split"]["specifiable_unaided"] == 1
    assert split["directory"] == str(d)


def test_an_empty_unaided_directory_reports_no_split_not_zeroes(tmp_path):
    split = DQ.instrument_split(tmp_path)
    assert split["probed"] == 0 and split["split"] == {}


def test_skipping_the_unaided_split_is_reported_as_null_not_as_empty(tmp_path):
    write(tmp_path, "a.json", p014())
    assert DQ.report(tmp_path, unaided=None)["unaided_with_instrument"] is None


# --- the entry point ---------------------------------------------------------- #

def test_the_dashboard_refuses_to_look_clean_over_an_empty_corpus(tmp_path, capsys):
    assert DQ._main(["--dir", str(tmp_path), "--no-unaided"]) == 1
    assert "nothing was measured" in capsys.readouterr().out


def test_the_dashboard_renders_and_writes_its_json(tmp_path, capsys):
    write(tmp_path, "a.json", p014())
    out = tmp_path / "report.json"
    assert DQ._main(["--dir", str(tmp_path), "--no-unaided",
                     "--json", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "DESIGN QUALITY" in printed
    assert f"{tmp_path}/*.json" in printed, "the denominator is printed, not implied"
    assert json.loads(out.read_text())["schema"] == "design_quality/1"


@pytest.mark.parametrize("name", ["reaches_ready_for_review",
                                  "refuses_as_not_specifiable",
                                  "refusal_lookups_ran",
                                  "asserted_keys_resolve_live",
                                  "carries_numeric_falsifier"])
def test_the_report_carries_every_measure_the_dashboard_promises(tmp_path, name):
    write(tmp_path, "a.json", p014())
    assert name in DQ.report(tmp_path, unaided=None)
