"""The resolver benchmark: its fixture, its answer rule, and what it refuses.

The defects these pin are not hypothetical. Every one of them was MEASURED in the
browser harness `benchmark/resolver_eval.py` was ported from, on 2026-09-01,
against build 6fcd02755bf3: 8 of its 46 gold answers named an id two different
questions share, one pool listed a single id twice meaning two different
questions, 94 of its 508 candidate wordings were not what the instrument says,
and a run at n=1 scored with the critic's only evidence structurally absent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from benchmark import resolver_eval as R
from env import labels, tools

FX = R.load_fixture()
ROWS = FX.queries
ENTRIES = tools._load()["entries"]
BY_KEY = {e["key"]: e for e in ENTRIES}


def _keys(row: R.ResolverQuery) -> list[str]:
    out = list(row.pool) + list(row.gold) + list(row.accept_keys)
    if row.narrowing is not None and row.narrowing.gold:
        out.append(row.narrowing.gold)
    return out


ALL_FIXTURE_KEYS = [k for r in ROWS for k in _keys(r)]


# --------------------------------------------------------------------------- #
# the fixture addresses items by key, which is what the port was for
# --------------------------------------------------------------------------- #


def test_every_fixture_key_is_in_the_built_dictionary():
    missing = sorted({k for k in ALL_FIXTURE_KEYS if k not in BY_KEY})
    assert not missing, (
        f"{len(missing)} fixture key(s) are in no registry: {missing[:5]}. A row "
        f"pointing at a key the dictionary no longer holds is a stale fixture, "
        f"not a resolver error.")


def test_the_fixture_names_no_item_by_a_qid_two_questions_share():
    """The port's whole reason: `qid` is not unique, `key` is.

    Anti-vacuity is the second assertion. If the instrument ever stopped
    renumbering across modules there would be no colliding qid left, this test
    would pass by describing nothing, and the guarantee would be gone silently.
    """
    shared: dict[str, set[str]] = {}
    for e in ENTRIES:
        shared.setdefault(e["qid"], set()).add(e["key"])
    ambiguous = {q for q, ks in shared.items() if len(ks) > 1}
    assert len(ambiguous) >= 100, (
        f"only {len(ambiguous)} qid(s) are shared by two questions; this test "
        f"was written against 121 and is now describing a different instrument.")

    exposed = sorted({k for k in ALL_FIXTURE_KEYS
                      if BY_KEY[k]["qid"] in ambiguous})
    assert exposed, (
        "no fixture key names a shared qid, so this test proves nothing about "
        "the fixture. It was written when 77 of 508 candidates did.")
    for key in exposed:
        assert len(shared[BY_KEY[key]["qid"]]) > 1
        assert key.startswith(f"m{BY_KEY[key]['module']}:"), (
            f"{key} does not carry its module, so it does not say which of "
            f"{sorted(shared[BY_KEY[key]['qid']])} it means.")


def test_no_pool_lists_one_item_twice():
    for row in ROWS:
        assert len(set(row.pool)) == len(row.pool), (
            f"{row.id} lists a key twice. In the harness this was `Q9.2` "
            f"appearing as both the menstrual-cycle item and the tobacco-pipe "
            f"item, which the bare-qid space could not tell apart.")


def test_every_row_with_a_gold_answer_shows_it_in_its_own_pool():
    for row in ROWS:
        if not row.gold:
            continue
        assert set(row.gold) & set(row.pool), (
            f"{row.id}'s pool contains none of its gold keys, so the row scores "
            f"a resolver on an answer it was never shown.")


def test_the_fixture_states_the_rule_the_scorer_implements():
    assert " ".join(FX.answer_rule.split()) == R.ANSWER_RULE


def test_the_fixture_covers_every_tier_and_every_kind():
    assert {r.tier for r in ROWS} == {1, 2, 3, 4, 5}
    assert {r.kind for r in ROWS} == {"exact", "family", "derive", "abstain"}
    # A floor per partition, one-sided: rows may be added, never quietly lost.
    for kind, floor in (("exact", 11), ("family", 2), ("derive", 5),
                        ("abstain", 4)):
        assert sum(1 for r in ROWS if r.kind == kind) >= floor


def test_one_narrowing_row_supplies_a_clarification_that_must_not_resolve():
    """Without it, "narrowing helped" is unfalsifiable."""
    controls = [r for r in ROWS
                if r.narrowing is not None and r.narrowing.gold is None]
    assert controls, (
        "every narrowing row supplies a clarification that resolves, so the "
        "narrowing arm can only ever report success.")


# --------------------------------------------------------------------------- #
# wording reaches the model as the instrument wrote it
# --------------------------------------------------------------------------- #


def test_every_candidate_line_carries_the_dictionary_wording_uncollapsed():
    """The 94-of-508 defect: frozen text drifts, cited text cannot.

    Whitespace is collapsed for rendering and nothing else is — the same
    difference `agent/schema.py::_wording_is_verbatim` forgives.
    """
    for key in sorted(set(ALL_FIXTURE_KEYS)):
        line = R.candidate_line(key)
        want = labels._flat(BY_KEY[key]["question_text"])
        assert want in line, (
            f"{key}: the rendered line does not carry this item's wording.\n"
            f"  line:   {line[:160]!r}\n  wording: {want[:160]!r}")


def test_no_candidate_line_truncates_its_wording():
    """The harness cut every wording at 170 characters, mid-sentence."""
    longest = sorted(set(ALL_FIXTURE_KEYS),
                     key=lambda k: -len(BY_KEY[k]["question_text"]))[:20]
    assert len(labels._flat(BY_KEY[longest[0]]["question_text"])) > 170, (
        "the longest fixture wording is under the harness's cutoff, so this "
        "test cannot see truncation.")
    for key in longest:
        assert labels._flat(BY_KEY[key]["question_text"]) in R.candidate_line(key)


def test_a_candidate_line_states_the_module_it_came_from():
    for key in sorted(set(ALL_FIXTURE_KEYS)):
        assert f"module {BY_KEY[key]['module']}" in R.candidate_line(key)


def test_a_wording_printed_in_two_modules_says_so_on_its_line():
    dupes = [k for k in set(ALL_FIXTURE_KEYS)
             if R._duplicate_text_modules()[
                 labels._flat(BY_KEY[k]["question_text"])] > 1]
    assert dupes, (
        "no fixture candidate shares its wording with another module, so this "
        "test proves nothing; GQ021 was written because 'Do you currently work "
        "for pay?' is printed in all three.")
    for key in dupes:
        assert "modules" in R.candidate_line(key)


# --------------------------------------------------------------------------- #
# the roster family
# --------------------------------------------------------------------------- #


def test_a_roster_family_is_the_question_asked_of_each_member():
    fam = R.family_of("m1:1_Q6.3")
    assert len(fam) == 15
    assert len({BY_KEY[k]["roster_row"] for k in fam}) == 15
    assert len({BY_KEY[k]["construct_key"] for k in fam}) == 1


def test_a_grid_family_is_one_column_and_not_the_whole_grid():
    """The distinction the harness carried by hand as a prose note.

    `m2:Q16.8` is 20 roster members by 22 columns. The family a request for one
    column spans is the 20, and returning the 440 would be a different answer.
    """
    fam = R.family_of("m2:1_Q16.8#1_3")
    assert len(fam) == 20
    whole = [e["key"] for e in ENTRIES if e["construct_key"] == "m2:Q16.8"]
    assert len(whole) == 440
    assert set(fam) < set(whole)
    assert len({BY_KEY[k]["subitem_text"] for k in fam}) == 1


def test_a_question_asked_once_is_its_own_family():
    assert R.family_of("m2:Q9.1") == ("m2:Q9.1",)


def test_family_of_refuses_a_key_the_dictionary_does_not_hold():
    with pytest.raises(KeyError, match="is not in build"):
        R.family_of("m9:Q0.0")


# --------------------------------------------------------------------------- #
# what the module refuses
# --------------------------------------------------------------------------- #


def test_a_run_at_one_sample_is_refused():
    """AGENTS.md: a prose resolver refuses to start unconfirmed at n=1.

    The harness admitted it — `min(2, nSamples)` — so a single shortlist scored
    with the critic's only evidence of underdetermination structurally absent.
    """
    with pytest.raises(ValueError, match="cannot disagree"):
        R.evaluate(lambda _: "{}", n_samples=1)


def test_a_report_cannot_be_built_without_the_bias_notice():
    with pytest.raises(ValueError, match="known_bias"):
        R.PoolReport(arm="frozen", fixture_path="x", dictionary_version="y",
                     known_bias="   ", results=())


def test_a_report_cannot_publish_a_rule_the_scorer_does_not_apply():
    with pytest.raises(ValueError, match="answer rule"):
        R.ResolverReport(
            arm="frozen", prompt_arm="unaided", model_name="m", n_samples=3,
            fixture_path="x",
            dictionary_version="y", known_bias="b",
            answer_rule="whatever the model says is correct", results=(),
            sampling_note="n")


# --------------------------------------------------------------------------- #
# the answer rule
# --------------------------------------------------------------------------- #

BY_ID = {r.id: r for r in ROWS}


def _item(key: str, wording: str | None = None) -> R.ResolvedItem:
    return R.ResolvedItem(
        key=key,
        wording=labels.cite(key).wording if wording is None else wording)


def _verdict(kind: str, *keys: str, **kw: Any) -> R.CriticVerdict:
    return R.CriticVerdict(verdict=kind, items=tuple(_item(k) for k in keys),
                           **kw)


@pytest.mark.parametrize(("row_id", "verdict", "keys", "expected"), [
    # An exact request. The last of these is the deviation from the harness:
    # naming the wrong item is not the same failure as failing to name one.
    ("GQ001", "resolved", ("m3:Q2.1",), "correct"),
    ("GQ001", "resolved", ("m3:Q3.21",), "confident_wrong"),
    ("GQ001", "ambiguous", (), "over_abstained"),
    ("GQ001", "absent", (), "over_abstained"),
    ("GQ001", "derive", (), "wrong"),
    ("GQ001", "family", ("m3:Q2.1",), "wrong"),
    # A family request. Any member is the answer; one member alone is not.
    ("GQ013", "family", ("m1:7_Q6.3",), "correct"),
    ("GQ013", "family", ("m1:1_Q6.3",), "correct"),
    ("GQ013", "resolved", ("m1:1_Q6.3",), "confident_wrong"),
    ("GQ013", "family", (), "wrong"),
    ("GQ013", "ambiguous", (), "wrong"),
    # The secondary family the key calls defensible, scored apart from both.
    ("GQ012", "family", ("m2:1_Q16.8#1_3",), "correct"),
    ("GQ012", "family", ("m2:1_Q16.11",), "arguable"),
    ("GQ012", "resolved", ("m2:1_Q16.8#1_3",), "confident_wrong"),
    # A request no item measures.
    ("GQ014", "derive", (), "correct"),
    ("GQ014", "resolved", ("m1:1_Q6.3",), "confident_wrong"),
    ("GQ014", "ambiguous", (), "wrong"),
    # A request the codebook cannot pin down.
    ("GQ019", "ambiguous", (), "correct"),
    ("GQ019", "absent", (), "correct"),
    ("GQ019", "resolved", ("m3:Q2.8",), "confident_wrong"),
    ("GQ019", "derive", (), "wrong"),
])
def test_the_answer_rule(row_id, verdict, keys, expected):
    row = BY_ID[row_id]
    assert R.score_query(row, _verdict(verdict, *keys), row.pool) == expected


def test_naming_an_item_outside_the_pool_is_malformed_not_wrong():
    row = BY_ID["GQ001"]
    outside = next(k for k in BY_KEY if k not in row.pool)
    assert R.score_query(row, _verdict("resolved", outside), row.pool) == \
        "malformed"


def test_a_real_key_under_someone_elses_wording_is_malformed():
    """The failure a key-only answer cannot express, which is why it carries one."""
    row = BY_ID["GQ001"]
    bad = R.CriticVerdict(
        verdict="resolved",
        items=(R.ResolvedItem(key="m3:Q2.1",
                              wording=BY_KEY["m3:Q3.21"]["question_text"]),))
    assert R.score_query(row, bad, row.pool) == "malformed"


def test_wording_that_differs_only_in_whitespace_is_not_malformed():
    """The codebooks break lines inside phrases; a rewrap is not a paraphrase."""
    key = next(k for k in BY_ID["GQ001"].pool
               if "\n" in BY_KEY[k]["question_text"])
    row = BY_ID["GQ001"]
    v = R.CriticVerdict(verdict="resolved", items=(
        _item(key, labels._flat(BY_KEY[key]["question_text"])),))
    assert R.score_query(row, v, row.pool) != "malformed"


def test_an_abstention_is_never_scored_malformed_for_naming_nothing():
    row = BY_ID["GQ019"]
    assert R.score_query(row, _verdict("ambiguous"), row.pool) == "correct"


@pytest.mark.parametrize(("row_id", "verdict", "keys", "expected"), [
    ("GQ019", "resolved", ("m2:Q737",), "narrow_resolved"),
    ("GQ019", "resolved", ("m3:Q2.8",), "narrow_wrong_key"),
    ("GQ019", "ambiguous", (), "narrow_still_stuck"),
    # GQ022's clarification cannot resolve: the item's wording is missing from
    # the codebook. Resolving anyway is the failure this control exists to see.
    ("GQ022", "resolved", ("m1:Q3.1",), "narrow_false_resolve"),
    ("GQ022", "ambiguous", (), "narrow_correctly_stuck"),
])
def test_the_narrowing_rule(row_id, verdict, keys, expected):
    assert R.score_narrowing(BY_ID[row_id], _verdict(verdict, *keys)) == expected


def test_a_row_with_no_narrowing_arm_scores_none():
    assert R.score_narrowing(BY_ID["GQ001"], _verdict("resolved")) is None


# --------------------------------------------------------------------------- #
# what the pool arms reach, before any model is asked
# --------------------------------------------------------------------------- #

#: Rows whose answer the shipped lexical search reaches at the frozen pools'
#: budget. A FLOOR: it may only rise. Measured 2026-09-01, build 6fcd02755bf3.
SEARCHED_REACHABLE_FLOOR = 13


def test_a_frozen_pool_always_contains_its_own_answer():
    report = R.evaluate_pools("frozen")
    assert report.reachable == len(report.scored)


def test_the_lexical_arm_reaches_the_answer_at_least_as_often_as_before():
    report = R.evaluate_pools("searched")
    assert report.reachable >= SEARCHED_REACHABLE_FLOOR, (
        f"the lexical control arm reaches {report.reachable} of "
        f"{len(report.scored)} answers, below the floor of "
        f"{SEARCHED_REACHABLE_FLOOR}. Recall floors only rise.")


def test_rows_with_no_gold_key_leave_the_denominator_rather_than_missing():
    report = R.evaluate_pools("frozen")
    assert len(report.results) == len(ROWS)
    assert len(report.scored) == sum(1 for r in ROWS if r.gold)
    assert all(r.reachable is None for r in report.results
               if r.kind in ("derive", "abstain"))


def test_the_frozen_pools_rank_the_answer_first_more_often_than_search_does():
    """A finding, pinned so it cannot be forgotten and then quoted.

    The harness never recorded how its pools were assembled. Measured
    2026-09-01: 9 of 13 frozen pools list the gold answer at rank 1, against 6
    for the lexical arm on the same requests. That is what `KNOWN_BIAS` is
    about, and it is why frozen-pool figures are an upper bound rather than a
    baseline.
    """
    frozen = R.evaluate_pools("frozen")
    searched = R.evaluate_pools("searched")
    first = sum(1 for r in frozen.scored if r.rank == 1)
    assert first >= 9, (
        f"{first} of {len(frozen.scored)} frozen pools open with the answer; "
        f"this test was written against 9. Re-derive the bias notice.")
    assert first > sum(1 for r in searched.scored if r.rank == 1)


def test_the_pool_report_names_its_arm():
    for arm in ("frozen", "searched"):
        assert R.evaluate_pools(arm).scope.count(arm) >= 1


def test_a_pool_arm_takes_its_input_from_the_request_alone():
    """No oracle in the measurement (`AGENTS.md` §Testing Patterns).

    Every arm is called with the row and must reach the same answer when the
    row's gold and expected answer are stripped out of it.
    """
    for row in ROWS:
        blinded = row.model_copy(update={"gold": (), "accept_keys": (),
                                         "expected": "", "note": ""})
        assert R.pool_searched(blinded) == R.pool_searched(row)


# --------------------------------------------------------------------------- #
# end to end, against a scripted model
# --------------------------------------------------------------------------- #


def _fixture_of(*ids: str) -> R.ResolverFixture:
    return FX.model_copy(update={"queries": tuple(BY_ID[i] for i in ids)})


class ScriptedModel:
    """A model whose answers are written in advance, so a run is deterministic.

    Attributes:
        shortlist: Keys every shortlist returns, in order.
        critic: The verdicts to return, one per critic call, cycling on the last.
        prompts: Every prompt it was handed, for tests that read the surface.
    """

    def __init__(self, shortlist: Sequence[str],
                 critic: Sequence[dict[str, Any]]) -> None:
        """Record the answers this model will give, in order.

        Args:
            shortlist: Keys every shortlist returns.
            critic: The verdicts to return, cycling on the last.
        """
        self.shortlist = shortlist
        self.critic = list(critic)
        self.prompts: list[str] = []
        self._critic_calls = 0

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Decide what kind of answer" in prompt:
            i = min(self._critic_calls, len(self.critic) - 1)
            self._critic_calls += 1
            return json.dumps(self.critic[i])
        return json.dumps({"items": [
            {"key": k, "wording": labels.cite(k).wording}
            for k in self.shortlist], "note": "scripted"})


def _resolved(key: str) -> dict[str, Any]:
    return {"verdict": "resolved", "reason": "scripted",
            "items": [{"key": key, "wording": labels.cite(key).wording}]}


def test_a_run_that_answers_correctly_scores_correct():
    model = ScriptedModel(["m3:Q2.1", "m3:Q3.21"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=3,
                        model_name="scripted", sampling_note="scripted")
    assert report.tally()["correct"] == 1
    assert report.blocked == ()
    assert report.failed_calls == 0
    assert report.results[0].agreed.on_key == 3


def test_a_model_that_returns_no_json_blocks_the_row_rather_than_scoring_it():
    report = R.evaluate(lambda _: "I cannot answer that.",
                        fixture=_fixture_of("GQ001"), n_samples=3,
                        sampling_note="scripted")
    assert report.scored == ()
    assert len(report.blocked) == 1
    assert report.failed_calls == 3
    assert "only 0 of 3 shortlists returned" in report.blocked[0].blocked
    assert sum(report.tally().values()) == 0


def test_one_surviving_shortlist_is_not_enough_to_judge():
    """The n=1 refusal, reached from the other side: samples that failed."""
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        if "Decide what kind of answer" in prompt:
            return json.dumps(_resolved("m3:Q2.1"))
        calls["n"] += 1
        if calls["n"] > 1:
            return "no."
        return json.dumps({"items": [{"key": "m3:Q2.1",
                                      "wording": labels.cite("m3:Q2.1").wording}]})

    report = R.evaluate(flaky, fixture=_fixture_of("GQ001"), n_samples=3,
                        sampling_note="scripted")
    assert len(report.blocked) == 1
    assert "only 1 of 3" in report.blocked[0].blocked
    assert report.scored == ()


def test_a_repaired_verdict_is_reported_and_not_absorbed():
    bad = {"verdict": "resolved", "reason": "invented",
           "items": [{"key": "module 3", "wording": "module 3"}]}
    model = ScriptedModel(["m3:Q2.1"], [bad, _resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2,
                        sampling_note="scripted")
    assert report.repairs == 1
    assert report.results[0].repaired is True
    assert report.tally()["correct"] == 1
    assert "second attempt" in R.format_report(report)


def test_a_verdict_that_stays_unusable_scores_malformed():
    bad = {"verdict": "resolved", "reason": "invented",
           "items": [{"key": "module 3", "wording": "module 3"}]}
    model = ScriptedModel(["m3:Q2.1"], [bad])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2,
                        sampling_note="scripted")
    assert report.tally()["malformed"] == 1


def test_the_narrowing_arm_runs_only_when_the_critic_says_ambiguous():
    model = ScriptedModel(["m2:Q737"],
                          [{"verdict": "ambiguous", "missing_dimension": "route",
                            "items": []},
                           _resolved("m2:Q737")])
    report = R.evaluate(model, fixture=_fixture_of("GQ019"), n_samples=2,
                        sampling_note="scripted")
    assert report.tally()["correct"] == 1
    assert report.narrow_tally()["narrow_resolved"] == 1
    assert "clarified" in model.prompts[-1]


def test_a_resolved_verdict_never_reaches_the_narrowing_arm():
    model = ScriptedModel(["m2:Q737"], [_resolved("m2:Q737")])
    report = R.evaluate(model, fixture=_fixture_of("GQ019"), n_samples=2,
                        sampling_note="scripted")
    assert report.narrow_tally()["narrow_resolved"] == 0
    assert report.results[0].narrow_outcome is None


def test_a_run_carries_how_its_samples_were_drawn():
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2)
    assert "UNCONTROLLED" in report.sampling_note
    assert report.sampling_note in report.scope


def test_the_bias_notice_precedes_the_first_figure():
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    text = R.format_report(R.evaluate(model, fixture=_fixture_of("GQ001"),
                                      n_samples=2, sampling_note="scripted"))
    # Against the FIGURE, not the word: the scope block above the banner
    # prints the answer rule, and that sentence contains "correct" too.
    assert text.index(R.BIAS_BANNER) < text.index("/1  correct")
    pool = R.format_pool_report(R.evaluate_pools("frozen"))
    assert pool.index(R.BIAS_BANNER) < pool.index("answer reachable")


def test_a_tally_reports_its_zeros():
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2,
                        sampling_note="scripted")
    assert set(report.tally()) == set(R.OUTCOME_MEANING)
    assert set(report.narrow_tally()) == set(R.NARROW_MEANING)


def test_measuring_leaves_no_trace_in_the_shared_tool_log():
    """A sweep must not read, in a live run's audit trail, as the model's calls."""
    depth = len(tools.LOG.calls)
    R.evaluate_pools("searched")
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    R.evaluate(model, arm="searched", fixture=_fixture_of("GQ001"), n_samples=2,
               sampling_note="scripted")
    assert len(tools.LOG.calls) == depth


def test_a_prompt_shows_the_model_every_candidate_it_may_choose_from():
    row = BY_ID["GQ001"]
    prompt = R.shortlist_prompt(row, row.pool)
    for key in row.pool:
        assert key in prompt
    assert json.loads(json.dumps(R.Shortlist.model_json_schema()))


def test_the_critic_prompt_states_the_agreement_it_is_reasoning_from():
    row = BY_ID["GQ001"]
    samples = (R.Shortlist(items=(_item("m3:Q2.1"),)),
               R.Shortlist(items=(_item("m3:Q3.21"),)))
    agreed = R.agreement(samples, 2)
    assert agreed.on_key == 1
    prompt = R.critic_prompt(row, samples, agreed)
    assert "1 of 2 named the same item" in prompt
    assert "m3:Q2.1" in prompt and "m3:Q3.21" in prompt


def test_agreement_on_a_family_is_never_below_agreement_on_a_key():
    samples = (R.Shortlist(items=(_item("m1:1_Q6.3"),)),
               R.Shortlist(items=(_item("m1:9_Q6.3"),)))
    agreed = R.agreement(samples, 2)
    assert agreed.on_key == 1
    assert agreed.on_family == 2


# --------------------------------------------------------------------------- #
# the critic may ask for more evidence; the harness decides whether it gets any
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("asked", "drawn", "already", "granted"), [
    (0, 3, False, 0),          # no request
    (-2, 3, False, 0),         # a negative is not a request
    (3, 3, False, 3),          # the ordinary case
    (99, 3, False, R.MAX_SAMPLES - 3),   # clipped to the cap, never refused flat
    (3, R.MAX_SAMPLES, False, 0),        # already at the cap
    (3, 3, True, 0),           # this row has had its grant
])
def test_the_grant_rule_is_a_pure_function_of_the_run(asked, drawn, already,
                                                      granted):
    assert R.grant_samples(asked, drawn, already) == granted


def test_the_grant_rule_never_reads_the_reason_it_was_given():
    """The asymmetry: the model may ask, and may not decide.

    `grant_samples` takes three integers-and-a-flag and no text, so there is no
    argument through which a persuasive `more_samples_reason` could buy a grant
    a terse one would not. This is the signature, checked, not a promise.
    """
    import inspect

    params = set(inspect.signature(R.grant_samples).parameters)
    assert params == {"asked_for", "drawn", "already_granted"}


def test_three_shortlists_cannot_show_a_family_of_twenty():
    """The measurement behind the rule the critic is given.

    A shortlist shows `SHORTLIST_SIZE` items, so three of them surface at most
    fifteen distinct keys and GQ012's answer is a family of twenty: the union
    the critic reasons over CANNOT hold that family whole.
    """
    family = R.family_of(BY_ID["GQ012"].gold[0])
    assert len(family) == 20
    assert 3 * R.SHORTLIST_SIZE < len(family)


def test_a_candidate_line_states_a_family_size_the_shortlists_cannot_show():
    """What keeps that truncation from being blindness.

    The rule tells the critic to read the line before asking, so the line has to
    carry it: a member of the twenty is labelled twenty on its own line, however
    few of its siblings the shortlists happened to surface.
    """
    line = R.candidate_line(BY_ID["GQ012"].gold[0])
    assert "asked of each of 20 roster members" in line


def test_the_critic_is_told_it_may_ask_and_told_who_decides():
    row = BY_ID["GQ012"]
    prompt = R.critic_prompt(row, (R.Shortlist(items=(_item(row.pool[0]),)),),
                             R.agreement((), 3))
    # Against a sentence only the RULE carries. The schema is rendered into
    # this same prompt and its field descriptions say "more_samples_requested"
    # and "granted by rule" too, so asserting on those passed with the rule
    # deleted — caught by seeding exactly that deletion.
    assert "you may ask for more of them" in prompt
    assert "at most once and up to a fixed total" in prompt
    # And that asking is not a way to avoid answering.
    assert "a verdict is required in this reply" in prompt
    # The rule tells the critic to read the line before asking about a family,
    # so the line has to be the cheaper answer.
    assert "each one states how many roster members" in prompt


def _asks(n: int) -> dict[str, Any]:
    return {"verdict": "ambiguous", "items": [], "more_samples_requested": n,
            "more_samples_reason": "the family is larger than the shortlists",
            "reason": "scripted"}


def test_a_granted_request_draws_more_and_the_second_verdict_is_the_scored_one():
    model = ScriptedModel(["m1:1_Q6.3"],
                          [_asks(3), {"verdict": "family", "reason": "scripted",
                                    "items": [{"key": "m1:1_Q6.3",
                                               "wording": labels.cite(
                                                   "m1:1_Q6.3").wording}]}])
    report = R.evaluate(model, fixture=_fixture_of("GQ013"), n_samples=3,
                        sampling_note="scripted")
    row = report.results[0]
    assert row.extra_requested == 3
    assert row.extra_granted == 3
    assert row.samples_drawn == 6
    assert row.agreed.n == 6
    # The first verdict asked and did not decide; the scored one is the second.
    assert report.tally()["correct"] == 1
    assert report.shortlists_drawn == 6


def test_a_row_is_granted_extras_at_most_once():
    model = ScriptedModel(["m1:1_Q6.3"], [_asks(3)])
    report = R.evaluate(model, fixture=_fixture_of("GQ013"), n_samples=3,
                        sampling_note="scripted")
    row = report.results[0]
    assert row.samples_drawn == 6, (
        "a critic that asks on every reply walked the cap up one call at a time")
    assert row.extra_granted == 3
    shortlists = [p for p in model.prompts if "Shortlist the" in p]
    assert len(shortlists) == 6


def test_a_request_refused_at_the_cap_is_still_reported():
    model = ScriptedModel(["m1:1_Q6.3"], [_asks(4)])
    report = R.evaluate(model, fixture=_fixture_of("GQ013"),
                        n_samples=R.MAX_SAMPLES, sampling_note="scripted")
    row = report.results[0]
    assert row.extra_requested == 4
    assert row.extra_granted == 0
    assert report.extra_requests == 1
    assert report.extra_grants == 0
    assert "1 granted" not in R.format_report(report)
    assert "1 refused at the cap" in R.format_report(report)


def test_a_run_reports_the_shortlists_it_actually_drew():
    """The run's real size is what it drew, not what it asked for.

    `n_samples` is the first-pass number; a figure quoted "at k samples" is
    wrong the moment a single extra is granted.
    """
    model = ScriptedModel(["m1:1_Q6.3"], [_asks(2)])
    report = R.evaluate(model, fixture=_fixture_of("GQ013"), n_samples=3,
                        sampling_note="scripted")
    assert report.n_samples == 3
    assert report.shortlists_drawn == 5
    assert "5 shortlists over 1 rows" in report.scope


# --------------------------------------------------------------------------- #
# the live backend is wired to the sealed, toolless path
# --------------------------------------------------------------------------- #


def test_the_live_model_goes_through_the_sealed_transduce_path():
    """AST, not a source substring (`AGENTS.md` §Testing Patterns).

    What matters is not that `live_model` mentions the backend but that it CALLS
    `.transduce`: that is the path with an empty `mkdtemp` cwd and every
    built-in denied, and a resolver that could `cat` the dictionary would answer
    from the file rather than from the pool it was shown.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(R.live_model)))
    attrs = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "transduce" in attrs, (
        "live_model does not call transduce; a resolver reached the model "
        "through some other path, and the seal is not on that path")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "ClaudeCliBackend" in names


def test_the_default_resolver_model_is_named_and_not_the_specifier_pin():
    """`TASKS.md` C17: the Haiku pin covers the Specifier, not a resolver.

    A record whose resolver differs from its specifier is legitimate; one that
    hides which model resolved is not. So every report names it.
    """
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2,
                        model_name="claude-sonnet-5", sampling_note="scripted")
    assert "claude-sonnet-5" in report.scope


# --------------------------------------------------------------------------- #
# the row table and the false-positive split
# --------------------------------------------------------------------------- #


def test_naming_one_item_where_none_is_right_is_a_false_positive():
    """The distinction `confident_wrong` alone cannot make.

    On a derive or abstain row it asserts the instrument holds a variable it
    does not; on an exact row it is a wrong pick from a set where one was right.
    Both are confidently wrong. Only the first is a false positive.
    """
    # GQ014 has no key answer at all, so naming one asserts the instrument
    # holds a variable it does not. GQ001 has one, and this names another.
    model = ScriptedModel(["m1:1_Q6.3"],
                          [_resolved("m1:1_Q6.3"), _resolved("m3:Q3.21")])
    report = R.evaluate(model, fixture=_fixture_of("GQ014", "GQ001"),
                        n_samples=2, sampling_note="scripted")
    assert report.tally()["confident_wrong"] == 2
    assert [r.id for r in report.false_resolutions] == ["GQ014"]
    assert [r.id for r in report.misidentifications] == ["GQ001"]


def test_a_row_carries_the_answer_it_was_scored_against():
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001", "GQ013", "GQ014"),
                        n_samples=2, sampling_note="scripted")
    by_id = {r.id: r.answer for r in report.results}
    assert by_id["GQ001"] == "m3:Q2.1"
    assert by_id["GQ013"] == "family of 15, e.g. m1:1_Q6.3"
    assert by_id["GQ014"] == BY_ID["GQ014"].expected


def test_every_model_call_a_row_makes_is_counted():
    """Counted at the callable, so a repair on a superseded pass still counts."""
    bad = {"verdict": "resolved", "reason": "invented",
           "items": [{"key": "module 3", "wording": "module 3"}]}
    model = ScriptedModel(["m3:Q2.1"], [bad, _resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=3,
                        sampling_note="scripted")
    # 3 shortlists + 1 critic + 1 repair, and the repair is the one a count
    # derived from samples_drawn and the verdict fields would have lost.
    assert report.results[0].model_calls == 5
    assert report.model_calls == len(model.prompts) == 5


def test_the_table_reports_agreement_over_the_shortlists_that_returned():
    """Agreement is over the shortlists that returned, not those asked for.

    A partly failed run would otherwise report agreement diluted by calls that
    produced no opinion, which reads as disagreement.
    """
    calls = {"n": 0}

    def flaky(prompt: str) -> str:
        if "Decide what kind of answer" in prompt:
            return json.dumps(_resolved("m3:Q2.1"))
        calls["n"] += 1
        if calls["n"] == 3:
            return "no."
        return json.dumps({"items": [{"key": "m3:Q2.1",
                                      "wording": labels.cite("m3:Q2.1").wording}]})

    report = R.evaluate(flaky, fixture=_fixture_of("GQ001"), n_samples=3,
                        sampling_note="scripted")
    row = report.results[0]
    assert row.agreed.returned == 2 and row.agreed.n == 3
    assert "2/2" in R.format_row_table(report)


def test_the_table_marks_a_refused_request():
    model = ScriptedModel(["m1:1_Q6.3"], [_asks(4)])
    report = R.evaluate(model, fixture=_fixture_of("GQ013"),
                        n_samples=R.MAX_SAMPLES, sampling_note="scripted")
    table = R.format_row_table(report)
    assert "4!" in table, "a request refused at the cap is not marked"


def test_the_table_has_a_line_per_row_and_a_legend():
    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    report = R.evaluate(model, fixture=_fixture_of("GQ001", "GQ014"),
                        n_samples=2, sampling_note="scripted")
    table = R.format_row_table(report)
    assert table.count("\n") > 2
    for row in report.results:
        assert any(line.startswith(row.id) for line in table.splitlines())
    for legend in ("calls ", "smp ", "asked ", "agree ", "FP "):
        assert legend in table


def test_no_variable_key_contains_whitespace():
    """What makes the copy rule exact rather than nearly right.

    The rule tells the model a key is the first run of non-space characters on
    its line. That is only true if no key has a space in it, and it is checked
    against the build rather than assumed: an instrument that started issuing
    keys with spaces would make the rule wrong on every roster line at once.
    """
    keys = [str(e["key"]) for e in ENTRIES]
    assert keys and not [k for k in keys if any(c.isspace() for c in k)]


def test_the_copy_rule_excludes_the_roster_tag_the_renderer_appends():
    """Regression: GQ012, claude-haiku-4-5, 2026-09-01.

    `Cited.render` prints `m2:1_Q16.8#1_3 [roster row 1] | ...`. Under the
    earlier rule — "the key is the text before the first ' | '" — the model
    returned the tag as part of the key, obeying the instruction exactly, and
    scored `malformed` on a verdict whose reasoning was right. The eval was
    moving with its own wording.
    """
    line = R.candidate_line("m2:1_Q16.8#1_3")
    assert line.startswith("m2:1_Q16.8#1_3 [roster row 1] | ")
    assert "[roster row 1]" in R._COPY_RULE
    assert "NOT part of it" in R._COPY_RULE
    # And the rule reaches the model on both calls, not just one.
    row = BY_ID["GQ012"]
    assert R._COPY_RULE in R.shortlist_prompt(row, row.pool)
    for arm in R.RESOLVER_PROMPT_ARMS:
        assert R._COPY_RULE in R.critic_prompt(
            row, (R.Shortlist(items=(_item(row.pool[0]),)),), R.agreement((), 3),
            arm=arm)


def test_a_key_with_the_roster_tag_glued_on_is_still_unusable():
    """The scorer is unchanged: the fix was to the instruction, not the check.

    Accepting the tagged form would have been fixing the fixture rather than the
    rule, and it would let a resolver return a string that resolves to nothing.
    """
    row = BY_ID["GQ012"]
    tagged = R.CriticVerdict(verdict="family", items=(R.ResolvedItem(
        key="m2:1_Q16.8#1_3 [roster row 1]",
        wording=labels.cite("m2:1_Q16.8#1_3").wording),))
    assert R.score_query(row, tagged, row.pool) == "malformed"


# --------------------------------------------------------------------------- #
# the line grammar, and the family rule as a named arm
# --------------------------------------------------------------------------- #


def test_the_copy_rule_states_where_a_wording_ends_not_only_where_a_key_starts():
    """Regression: GQ012, claude-opus-5, 2026-09-01.

    The rule that fixed the key boundary never said where a wording ENDS, so
    opus returned `... - 1 - Breast cancer (module 2; asked of each of 20 roster
    members)` — the fact clause copied into the wording — and scored malformed
    on four keys, with the verdict and the reasoning right. Haiku and sonnet
    guessed the boundary correctly on the same line. A rule three models read
    three ways is not an instruction.
    """
    assert "is NOT part of the wording" in R._COPY_RULE
    assert "parenthesised clause" in R._COPY_RULE
    # Both boundaries, in one grammar rather than two prohibitions.
    assert "KEY [optional roster tag] | WORDING" in R._COPY_RULE


def test_the_fact_clause_copied_into_a_wording_is_unusable():
    """The scorer is unchanged; the instruction is what was wrong.

    Accepting the line-with-facts as a wording would let a resolver quote text
    the instrument does not contain, which is what `Cited` exists to prevent.
    """
    row = BY_ID["GQ012"]
    key = row.gold[0]
    v = R.CriticVerdict(verdict="family", items=(
        _item(key, R.candidate_line(key).split(" | ", 1)[1]),))
    assert R.score_query(row, v, row.pool) == "malformed"


def test_a_wording_copied_between_the_bars_and_the_facts_is_usable():
    """The grammar the rule now states, applied literally, must validate."""
    row = BY_ID["GQ012"]
    key = row.gold[0]
    line = R.candidate_line(key)
    wording = line.split(" | ", 1)[1].rsplit("  (", 1)[0]
    v = R.CriticVerdict(verdict="family",
                        items=(_item(key, wording),), family_size=20)
    assert R.score_query(row, v, row.pool) == "correct"


def test_the_family_rule_is_an_arm_and_every_report_names_which_one():
    row = BY_ID["GQ012"]
    s1 = (R.Shortlist(items=(_item(row.pool[0]),)),)
    with_rule = R.critic_prompt(row, s1, R.agreement(s1, 3),
                                arm="with_family_rule")
    without = R.critic_prompt(row, s1, R.agreement(s1, 3), arm="unaided")
    assert R._FAMILY_RULE in with_rule
    assert R._FAMILY_RULE not in without
    # Everything else is the same prompt: the arm is one block, not a rewrite.
    assert len(without) < len(with_rule)
    assert R._COPY_RULE in without and R._MORE_SAMPLES_RULE in without

    model = ScriptedModel(["m3:Q2.1"], [_resolved("m3:Q2.1")])
    for arm in R.RESOLVER_PROMPT_ARMS:
        rep = R.evaluate(model, fixture=_fixture_of("GQ001"), n_samples=2,
                         sampling_note="scripted", prompt_arm=arm)
        assert f"prompt arm      {arm}" in rep.scope


def test_an_unknown_prompt_arm_is_refused_rather_than_defaulted():
    """A typo must not put two prompts behind one label."""
    row = BY_ID["GQ012"]
    with pytest.raises(ValueError, match="is not a prompt arm"):
        R.critic_prompt(row, (), R.agreement((), 3), arm="with_famly_rule")


def test_the_family_rule_asks_for_one_member_and_its_size():
    """Enumerating members is the failure mode it removes.

    Members differ only at an index buried mid-wording, so returning N of them
    means transcribing N near-identical strings: sonnet returned five and got
    all five right, opus returned four and mis-transcribed all four.
    """
    assert "EXACTLY ONE member key" in R._FAMILY_RULE
    assert "family_size" in R._FAMILY_RULE
    assert "SAME family" in R._FAMILY_RULE
    assert "family_size" in json.dumps(R.CriticVerdict.model_json_schema())


def test_one_member_of_the_right_family_scores_correct_however_many_are_named():
    """What makes asking for one member safe: the rule was already member-blind."""
    row = BY_ID["GQ012"]
    one = R.CriticVerdict(verdict="family", family_size=20,
                          items=(_item("m2:1_Q16.8#1_3"),))
    other = R.CriticVerdict(verdict="family", family_size=20,
                            items=(_item("m2:7_Q16.8#1_3"),))
    assert R.score_query(row, one, row.pool) == "correct"
    assert R.score_query(row, other, row.pool) == "correct"


# --------------------------------------------------------------------------- #
# the structured arm
# --------------------------------------------------------------------------- #


def test_the_structured_arm_shows_the_model_no_key_on_either_call():
    """The failure class removed, on both stages rather than one."""
    row = BY_ID["GQ012"]
    shortlist = R.structured_shortlist_contract(row, row.pool)
    critic = R.structured_critic_contract(row, row.pool[:6])
    for rendered in (shortlist.render(), critic.render()):
        for key in row.pool:
            assert key not in rendered
        assert "Select by `index`" in rendered


def test_each_structured_stage_asks_its_own_question():
    """A shortlist is a ranking call, not a verdict call.

    Reusing the critic's task for both put "decide what kind of answer this
    request has" in front of a call that only ranks.
    """
    row = BY_ID["GQ012"]
    shortlist = R.structured_shortlist_contract(row, row.pool).task
    critic = R.structured_critic_contract(row, row.pool).task
    assert "Shortlist the" in shortlist
    assert "Decide what kind of answer" not in shortlist
    assert "Decide what kind of answer" in critic


def test_the_critic_reindexes_over_the_union_not_the_pool():
    """The critic's indices are its own, not the shortlist's.

    An index meaning one item in one call and another in the next is the
    failure this representation removes, reintroduced between two calls.
    """
    row = BY_ID["GQ012"]
    union = list(row.pool[5:8])
    critic = R.structured_critic_contract(row, union)
    assert [c.index for c in critic.candidates] == [1, 2, 3]
    assert critic.resolve(1).key == union[0]
    assert R.structured_shortlist_contract(row, row.pool).resolve(6).key == union[0]


def test_a_structured_candidate_carries_the_grid_column_as_a_field():
    """The discriminator the line format buried at character 99."""
    facts = R.candidate_facts("m2:1_Q16.8#1_3")
    assert facts["grid_column"] == "Breast cancer"
    assert facts["roster_family_size"] == 20
    assert facts["roster_row"] == 1
    assert facts["module"] == "2"


def test_a_structured_answer_can_never_be_malformed():
    """An index resolves or it does not; it cannot resolve to a wrong string.

    The line arm's `malformed` outcome exists because a returned key could name
    nothing. Here the worst an out-of-range index can do is leave nothing to
    score.
    """
    row = BY_ID["GQ012"]
    surface = R.structured_critic_contract(row, row.pool)
    items = R._items_from_indices(surface, (1, 2, 9999, -3, 0))
    assert len(items) == 2
    assert R._unusable(items, row.pool) == ()


def test_an_unresolvable_index_is_dropped_rather_than_raised_on():
    row = BY_ID["GQ012"]
    surface = R.structured_critic_contract(row, row.pool[:2])
    assert R._items_from_indices(surface, (7,)) == ()


def test_the_structured_shortlist_can_decline_where_the_line_arm_could_not():
    """A shortlist can decline, which the line arm had no way to express.

    GQ015 returned an empty list three times and was BLOCKED as three failed
    calls; for a request no single item measures that may be the right answer,
    so declining is a value here.
    """
    assert "absent" in R.VariableShortlist.model_fields["outcome"].annotation.__args__
    row = BY_ID["GQ015"]
    assert "'absent'" in R.structured_shortlist_contract(row, row.pool).render()


def test_the_structured_arm_runs_end_to_end_against_a_scripted_model():
    row = BY_ID["GQ012"]
    gold_index = row.pool.index(row.gold[0]) + 1

    def model(prompt: str) -> str:
        if "Shortlist the" in prompt:
            return json.dumps({"outcome": "shortlisted",
                               "indices": [gold_index], "note": "scripted"})
        return json.dumps({"verdict": "family", "indices": [1],
                           "reason": "scripted"})

    report = R.evaluate(model, arm="frozen", fixture=_fixture_of("GQ012"),
                        n_samples=2, sampling_note="scripted",
                        prompt_arm="structured")
    assert report.tally()["correct"] == 1
    assert report.results[0].repaired is False
    assert "prompt arm      structured" in report.scope


def test_the_structured_arm_cannot_request_more_samples_and_says_so():
    """A named difference between arms, not a silent one.

    `VariableSelection` carries no `more_samples_requested` field, so
    `extra_requested` is 0 by construction here rather than by choice.
    """
    from agent import prompt_contract as PC
    assert "more_samples_requested" not in PC.VariableSelection.model_fields
    assert "more_samples_requested" in R.CriticVerdict.model_fields

    def model(prompt: str) -> str:
        if "Shortlist the" in prompt:
            return json.dumps({"outcome": "shortlisted", "indices": [1]})
        return json.dumps({"verdict": "family", "indices": [1]})

    report = R.evaluate(model, fixture=_fixture_of("GQ013"), n_samples=2,
                        sampling_note="scripted", prompt_arm="structured")
    assert report.extra_requests == 0
    assert report.results[0].samples_drawn == 2
