"""C18's scorer, pinned against fixtures that need no live call.

Every fixture below is AUTHORED HERE, not drawn from any publication or from any
model output about this cohort, and none of them states a design this project
believes to be correct. They exist to make the four rubric elements individually
falsifiable: each test removes exactly one and asserts the verdict flips.

The load-bearing pair is `test_a_complete_design_in_running_prose_scores_specifiable`
plus `test_headings_without_content_score_not_specifiable`. Together they pin the
one property the brief for this task singled out: the scorer reads DESIGN
CONTENT, not output format. A response with every heading and nothing under it
fails; a response with no headings at all and the four commitments in running
prose passes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from benchmark.unaided_specifiability import (
    ADJUST_BLOCK_LINES,
    ADJUST_CUES,
    CONTRAST_WORDS,
    DIRECTION_WORDS,
    MIN_COVARIATES,
    MODEL_FORMS,
    NEGATIVE_CONTROL,
    NOT_SPECIFIABLE,
    PROMPT,
    REQUIRED_PROVENANCE,
    RUBRIC,
    SPECIFIABLE,
    WITHHOLDING_PROBE,
    PairSpec,
    aided_argv,
    controls_hold,
    covariates_in,
    frame_pairs,
    pair_verdict,
    partition,
    positive_control,
    provenance,
    rescore,
    rubric_hash,
    score_response,
    unaided_argv,
    unaided_prompt,
)

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------- #
# fixtures: one sentence per rubric element, plus a weakened version of each
# --------------------------------------------------------------------------- #

ROLES = ("I would treat the neighbourhood safety rating as the exposure and the "
         "reported diagnosis as the outcome, and I expect a positive association.")
ROLES_NO_SIGN = ("I would treat the neighbourhood safety rating as the exposure "
                 "and the reported diagnosis as the outcome.")

CONTRAST = ("The exposure enters as the highest tertile set against the lowest "
            "tertile of the summed score.")
CONTRAST_NONE = "The exposure enters the analysis as it was collected."

ADJUSTMENT = ("I would hold fixed age, sex, educational attainment, household "
              "income, smoking status.")
ADJUSTMENT_VAGUE = ("I would adjust for the usual confounders that the "
                    "literature suggests here.")

MODEL = ("The estimator is a modified Poisson regression with the individual as "
         "the unit of analysis.")
MODEL_VAGUE = "I would fit an appropriate multivariable specification."

REFUSAL = ("I cannot write an analysis for this pair. Neither identifier carries "
           "any wording and I do not know what either one measures.")

HEADINGS_ONLY = "ROLES AND SIGN\n\nCONTRAST\n\nADJUSTMENT\n\nMODEL\n"


def compose(*parts: str) -> str:
    """Join fixture sentences into a response, one paragraph each.

    Blank lines between them are not cosmetic: `covariates_in` stops reading at
    the first blank line after the adjustment cue, so a fixture written as one
    run-on paragraph would let the model sentence's words be counted as
    covariates and the tests would pass for the wrong reason.

    Args:
        parts: Fixture sentences.

    Returns:
        The composed response text.
    """
    return "\n\n".join(parts) + "\n"


FULL = compose(ROLES, CONTRAST, ADJUSTMENT, MODEL)


# --------------------------------------------------------------------------- #
# the rubric: four elements, each individually necessary
# --------------------------------------------------------------------------- #

def test_a_complete_design_in_running_prose_scores_specifiable():
    v = score_response(FULL)
    assert v.verdict == SPECIFIABLE, v.elements
    assert all(v.elements.values()), v.elements
    assert len(v.covariates) >= 3, v.covariates
    assert v.model_forms


def test_headings_without_content_score_not_specifiable():
    """Format is not the signal: the four headings, filled with nothing."""
    v = score_response(HEADINGS_ONLY)
    assert v.verdict == NOT_SPECIFIABLE
    assert not any(v.elements.values()), v.elements


@pytest.mark.parametrize(("dropped", "text"), [
    ("directed_pairing", compose(ROLES_NO_SIGN, CONTRAST, ADJUSTMENT, MODEL)),
    ("contrast", compose(ROLES, CONTRAST_NONE, ADJUSTMENT, MODEL)),
    ("adjustment_set", compose(ROLES, CONTRAST, ADJUSTMENT_VAGUE, MODEL)),
    ("model_form", compose(ROLES, CONTRAST, ADJUSTMENT, MODEL_VAGUE)),
])
def test_every_rubric_element_is_individually_required(dropped, text):
    """Weaken exactly one element and the verdict must flip.

    This is what stops the scorer degenerating into "the model wrote prose".
    """
    v = score_response(text)
    assert v.elements[dropped] is False, (
        f"{dropped} still scored True on a response written without it: "
        f"{v.elements}")
    assert v.verdict == NOT_SPECIFIABLE
    others = {k: val for k, val in v.elements.items() if k != dropped}
    assert all(others.values()), (
        f"weakening {dropped} also knocked out {others} — the fixture is "
        f"testing more than one element and proves nothing about {dropped}")


def test_a_refusal_scores_not_specifiable():
    v = score_response(REFUSAL)
    assert v.verdict == NOT_SPECIFIABLE
    assert not any(v.elements.values()), v.elements


def test_a_statement_of_intent_is_not_an_adjustment_set():
    """"Adjust for confounders" commits the analyst to nothing checkable."""
    assert len(covariates_in(ADJUSTMENT_VAGUE)) < 3
    assert len(covariates_in(ADJUSTMENT)) >= 3


def test_a_bulleted_adjustment_block_is_read_as_items():
    """Formatting must not decide the count: bullets score like a comma list."""
    bulleted = ("I would adjust for the following:\n"
                "- age\n- sex\n- educational attainment\n- household income\n")
    assert len(covariates_in(bulleted)) >= 3


def test_the_cue_word_is_not_counted_as_a_covariate():
    """"Covariates: age, sex, income" is three, not four.

    The second assertion is bare headings, which the block reader now walks past
    a blank line to reach — so it may pick up the NEXT heading as a stray word.
    What must hold is that no cue word survives as an item and that a response
    with no covariates in it cannot reach `MIN_COVARIATES`.
    """
    assert covariates_in("Covariates: age, sex, household income.") == [
        "age", "sex", "household income"]
    stray = covariates_in("ADJUSTMENT\n\nMODEL")
    assert not any(c in " ".join(ADJUST_CUES) for c in stray), stray
    assert len(stray) < MIN_COVARIATES


# --------------------------------------------------------------------------- #
# two false negatives found on the FIRST live probe, 2026-08-30, on a response
# that visibly contained the element the scorer said was absent. Both are pinned
# here in the shape the model actually produced.
# --------------------------------------------------------------------------- #

MARKDOWN_ADJUSTMENT = (
    "**ADJUSTMENT**\n"
    "\n"
    "Hold fixed: age, sex, race/ethnicity, household income, body mass index, "
    "smoking status.\n"
    "\n"
    "**MODEL**\n")

SPLIT_PAIRING = (
    "Treat the first construct as the exposure and the second as the outcome.\n"
    "The expected association is positive: more of the first would mean higher "
    "odds of the second.")


def test_a_markdown_heading_does_not_end_the_adjustment_block():
    """The cue matched the heading and the blank line below it ate the list.

    A response naming six covariates scored zero. A blank line may only end the
    block once the block has content.
    """
    assert len(covariates_in(MARKDOWN_ADJUSTMENT)) >= 3
    assert "hold fixed" not in covariates_in(MARKDOWN_ADJUSTMENT)


def test_the_role_assignment_and_the_sign_may_sit_in_adjacent_sentences():
    """Prose splits these two commitments more often than it joins them."""
    assert score_response(SPLIT_PAIRING).elements["directed_pairing"] is True


def test_the_window_does_not_stretch_across_a_whole_response():
    """Two sentences, not the whole text: an echo far away must not score."""
    far = ("The exposure is the first construct and the outcome is the second.\n"
           "\n" + "Some unrelated sentence about the survey. " * 6 + "\n\n"
           "Rates were higher in that unrelated setting.")
    assert score_response(far).elements["directed_pairing"] is False


def test_a_blank_line_ends_the_adjustment_block_once_it_has_content():
    """A long tail after the block must not be counted as covariates."""
    text = compose(ADJUSTMENT_VAGUE,
                   "Separately, the record would name age, sex, income, "
                   "education, and insurance status somewhere else entirely.")
    assert len(covariates_in(text)) < 3


def test_the_adjustment_block_is_bounded_even_with_no_blank_line():
    """An unterminated list may not swallow the rest of the response.

    The bound is a LITERAL, not `ADJUST_BLOCK_LINES`. Written against the
    constant this test passed while the cap was raised to 100, because raising
    the cap raised the assertion with it — a check that moves when the thing it
    checks moves is not a check.
    """
    text = ("I would adjust for the following:\n"
            + "".join(f"- item number {i}\n" for i in range(40)))
    assert ADJUST_BLOCK_LINES <= 20, "raise the literal below before the cap"
    assert len(covariates_in(text)) <= 20


def test_schema_conformance_is_not_the_signal():
    """A design the pipeline schema would reject still scores specifiable.

    The fixture names no variable key, quotes no wording, states no analytic n,
    no falsifier threshold and no blocker, and is not JSON. Every one of those
    is a schema requirement supplied by the instrument, and the instrument is
    what this probe withholds — so scoring on them would measure the ablation
    rather than the model.
    """
    import re
    assert not re.search(r"\b(?:m[123]|clinical|lab|linked|ehr):[A-Za-z0-9_.]", FULL)
    with pytest.raises(json.JSONDecodeError):
        json.loads(FULL)
    assert score_response(FULL).verdict == SPECIFIABLE


def test_rubric_text_names_every_element_the_code_scores():
    """The written rubric and the scored elements may not drift apart.

    Matched as an INDENTED HEADING, not as a substring. A substring check
    passed while the rubric's `contrast` heading had been renamed, because the
    word still appeared in the prose underneath — a rubric that no longer
    defines an element the code scores, and a check that could not tell.
    """
    import re
    scored = set(score_response(FULL).elements)
    assert scored == {"directed_pairing", "contrast", "adjustment_set",
                      "model_form"}
    for name in scored:
        # Anchored at the heading's own indent and requiring the column gap.
        # `^ +` passed while the `contrast` heading had been renamed, because a
        # continuation line twenty columns in happened to begin "contrast is
        # not yet a design" — the check matched the prose it was supposed to
        # look past.
        assert re.search(rf"^  {re.escape(name)}\s\s+\S", RUBRIC, re.M), (
            f"{name} is scored but has no heading of its own in RUBRIC")
    assert len(rubric_hash()) == 16


# --------------------------------------------------------------------------- #
# the prompt may not hand the model the detectors
# --------------------------------------------------------------------------- #

def test_the_prompt_supplies_no_scored_vocabulary():
    """A probe that names the answer cannot detect the answer.

    `agent/sealed.py`'s probe 1 had to be rewritten for exactly this. Role words
    are exempt and must be: the pair cannot be stated without them, which is why
    `directed_pairing` requires a DIRECTION term as well.
    """
    low = PROMPT.lower()
    import re

    def hits(words: tuple[str, ...]) -> list[str]:
        return [w for w in words
                if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low)]
    assert not hits(DIRECTION_WORDS), hits(DIRECTION_WORDS)
    assert not hits(CONTRAST_WORDS), hits(CONTRAST_WORDS)
    assert not hits(MODEL_FORMS), hits(MODEL_FORMS)


def test_the_prompt_states_the_pair_and_withholds_everything_else():
    p = unaided_prompt("m3:Q16.3", "a stem", "m2:Q5.2", "another stem")
    assert "m3:Q16.3" in p and "m2:Q5.2" in p
    assert "a stem" in p and "another stem" in p
    assert "no tools" in p.lower()


def test_a_construct_with_no_wording_is_not_given_an_invented_stem():
    p = unaided_prompt("lab:assay_17", "", "clinical:measure_23", "")
    assert "(no wording available)" in p


# --------------------------------------------------------------------------- #
# the instrument is withheld by the argv, and that is checked
# --------------------------------------------------------------------------- #

class _FakeWorktree:
    """A stand-in for SealedWorktree that returns a fixed argv."""

    def __init__(self, argv: list[str]) -> None:
        self._argv = argv

    def base_argv(self, model: str) -> list[str]:
        return [*self._argv, "--model", model]


def test_unaided_argv_attaches_no_instrument():
    """No MCP server, no allow-list, every built-in denied."""
    from agent.sealed import DENY_TOOLS, SealedWorktree
    wt = SealedWorktree(mode="benchmark")
    try:
        argv = unaided_argv(wt, "claude-haiku-4-5", "hello")
    finally:
        wt.__exit__()
    assert "--mcp-config" not in argv
    assert "--allowed-tools" not in argv
    assert "--strict-mcp-config" in argv
    denied = argv[argv.index("--disallowed-tools") + 1].split(",")
    assert set(DENY_TOOLS) <= set(denied)
    assert argv[-1] == "hello", "the prompt must be the last positional argument"


def test_the_withholding_control_differs_from_the_probe_in_exactly_the_right_flags():
    """The positive control must actually attach what the probe withholds.

    A control built from the same argv as the thing it controls would log zero
    calls too, and the zero in every unaided log would still mean nothing.
    """
    from agent.sealed import SealedWorktree
    wt = SealedWorktree(mode="benchmark")
    try:
        aided = aided_argv(wt, "claude-haiku-4-5", "hello")
        bare = unaided_argv(wt, "claude-haiku-4-5", "hello")
    finally:
        wt.__exit__()
    assert "--mcp-config" in aided and "--mcp-config" not in bare
    assert "--allowed-tools" in aided and "--allowed-tools" not in bare
    allowed = aided[aided.index("--allowed-tools") + 1].split(",")
    assert allowed and all(a.startswith("mcp__compass__") for a in allowed)
    assert aided[-1] == "hello"


def test_the_withholding_probe_asks_for_a_tool_call_and_nothing_else():
    """It must not smuggle design content into the control."""
    v = score_response(WITHHOLDING_PROBE)
    assert v.verdict == NOT_SPECIFIABLE
    assert not any(v.elements.values()), v.elements


def test_unaided_argv_refuses_an_argv_that_reattaches_the_instrument():
    """If the seal ever starts attaching a server, every verdict is void."""
    wt = _FakeWorktree(["claude", "-p", "--mcp-config", "/tmp/x.json"])
    with pytest.raises(RuntimeError, match="instrument is NOT"):
        unaided_argv(wt, "claude-haiku-4-5", "hello")


def test_importing_the_scorer_does_not_load_the_seal_or_a_backend():
    """Module-scope imports only: scoring a saved record must cost no model.

    Every `agent.*` import in this module is function-local on purpose, so a
    reader who imports it to re-score records never spawns a worktree.
    """
    src = (ROOT / "benchmark" / "unaided_specifiability.py").read_text()
    tree = ast.parse(src)
    top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    names = [getattr(n, "module", "") or "" for n in top]
    names += [a.name for n in top if isinstance(n, ast.Import) for a in n.names]
    offenders = [m for m in names if m.startswith(("agent", "generate", "mcp"))]
    assert not offenders, (
        f"module-scope import of {offenders}: importing the scorer must not "
        f"load the seal, a backend or the funnel")


# --------------------------------------------------------------------------- #
# aggregation, provenance, controls
# --------------------------------------------------------------------------- #

def _scored(*verdicts: bool) -> list:
    return [score_response(FULL if v else REFUSAL) for v in verdicts]


def test_one_specifiable_response_in_k_flags_the_pair():
    """Conservative by design: the errors of a subtraction filter are not equal."""
    assert pair_verdict(_scored(False, False, False, False, True)) == SPECIFIABLE
    assert pair_verdict(_scored(False, False, False, False, False)) == NOT_SPECIFIABLE


def test_a_higher_threshold_can_be_applied_without_a_new_run():
    rs = _scored(False, False, False, False, True)
    assert pair_verdict(rs, min_specifiable=2) == NOT_SPECIFIABLE


def test_a_pair_with_no_responses_has_no_verdict():
    """An unprobed pair must not slip into C6's arm pool as `not_specifiable`."""
    with pytest.raises(ValueError, match="no responses"):
        pair_verdict([])


def _record(pair_id: str, verdict: str, role: str = "pilot",
            prov: dict | None = None) -> dict:
    return {"pair_id": pair_id, "verdict": verdict, "role": role,
            "n_specifiable": 5 if verdict == SPECIFIABLE else 0, "k": 5,
            "min_specifiable": 1,
            "provenance": prov if prov is not None else {
                "model_id": "claude-haiku-4-5", "seal_hash": "deadbeefdeadbeef",
                "date": "2026-08-30", "rubric_hash": rubric_hash(),
                "dictionary_version": "6fcd02755bf3"}}


def test_partition_halves_are_disjoint_and_cover_every_probed_pair():
    recs = [_record("a -> b", SPECIFIABLE), _record("c -> d", NOT_SPECIFIABLE)]
    part = partition(recs)
    assert part["counts"] == {"probed": 2, "flagged": 1, "unflagged": 1,
                              "arm_pool": 1}
    flagged = {r["pair_id"] for r in part["flagged"]}
    unflagged = {r["pair_id"] for r in part["unflagged"]}
    assert not flagged & unflagged
    assert flagged | unflagged == {"a -> b", "c -> d"}


def test_a_persisted_record_can_be_rescored_without_a_model_call():
    """The threshold and the rubric stay revisable because the text is kept.

    Written as a comment first and enforced nowhere. Here the same record is
    re-scored at two thresholds and the verdict flips, with no worktree, no
    argv and no call.
    """
    rec = {"schema": "unaided_specifiability/1", "pair_id": "a -> b",
           "role": "pilot", "k": 5, "n_specifiable": 1, "min_specifiable": 1,
           "verdict": SPECIFIABLE,
           "exposure": {"construct_key": "m3:Q16.1", "stem_text": ""},
           "outcome": {"construct_key": "m2:Q5.8", "stem_text": ""},
           "provenance": _record("a -> b", SPECIFIABLE)["provenance"],
           "responses": [{"index": i, "text": t, "verdict": "stale",
                          "elements": {}, "covariates_found": [],
                          "model_forms_found": [], "invocation_error": ""}
                         for i, t in enumerate([REFUSAL, REFUSAL, REFUSAL,
                                                REFUSAL, FULL])]}
    at_one = rescore(rec, min_specifiable=1)
    at_two = rescore(rec, min_specifiable=2)
    assert at_one["verdict"] == SPECIFIABLE
    assert at_two["verdict"] == NOT_SPECIFIABLE
    assert at_one["n_specifiable"] == 1
    assert at_one["responses"][4]["verdict"] == SPECIFIABLE
    assert at_one["responses"][0]["verdict"] == NOT_SPECIFIABLE
    assert at_one["provenance"]["rubric_hash"] == rubric_hash()
    # The calls are not re-attributed: the model and the seal describe the run
    # that produced the text, and re-scoring produced none.
    assert at_one["provenance"]["model_id"] == rec["provenance"]["model_id"]
    assert at_one["provenance"]["seal_hash"] == rec["provenance"]["seal_hash"]


def test_the_negative_control_never_enters_c6s_arm_pool():
    """It is a fabricated pair in empty registries: unflagged by construction.

    It stays in `unflagged`, because dropping a measurement would hide the
    control, and out of `arm_pool`, because an arm drawn from it would be a
    benchmark item with no instrument behind it.
    """
    part = partition([
        _record("neg", NOT_SPECIFIABLE, role="negative_control"),
        _record("a -> b", NOT_SPECIFIABLE),
        _record("c -> d", SPECIFIABLE)])
    assert "neg" in {r["pair_id"] for r in part["unflagged"]}
    assert "neg" not in {r["pair_id"] for r in part["arm_pool"]}
    assert {r["pair_id"] for r in part["arm_pool"]} == {"a -> b"}
    assert part["counts"]["arm_pool"] == 1


@pytest.mark.parametrize("field", REQUIRED_PROVENANCE)
def test_partition_refuses_a_record_missing_any_provenance_field(field):
    """A flagged set with no provenance is unusable the day the model changes."""
    prov = _record("a -> b", SPECIFIABLE)["provenance"]
    prov.pop(field)
    with pytest.raises(ValueError, match=field):
        partition([_record("a -> b", SPECIFIABLE, prov=prov)])


def test_controls_hold_reports_a_control_that_landed_on_the_wrong_side():
    part = partition([
        _record("neg", SPECIFIABLE, role="negative_control"),
        _record("pos", SPECIFIABLE, role="positive_control")])
    ok, bad = controls_hold(part)
    assert not ok
    assert any("negative_control" in b for b in bad)


def test_controls_hold_accepts_both_controls_on_the_right_side():
    part = partition([
        _record("neg", NOT_SPECIFIABLE, role="negative_control"),
        _record("pos", SPECIFIABLE, role="positive_control")])
    assert controls_hold(part) == (True, [])


def test_controls_hold_reports_a_control_that_was_never_run():
    ok, bad = controls_hold(partition([_record("a -> b", SPECIFIABLE)]))
    assert not ok
    assert len(bad) == 2


def test_provenance_carries_every_required_field():
    from agent.sealed import SealedWorktree
    wt = SealedWorktree(mode="benchmark")
    try:
        prov = provenance(wt, "claude-haiku-4-5", "0123456789abcdef")
    finally:
        wt.__exit__()
    assert all(prov.get(f) for f in REQUIRED_PROVENANCE), prov
    assert prov["instrument"] == "withheld"


# --------------------------------------------------------------------------- #
# the control pairs
# --------------------------------------------------------------------------- #

def test_the_negative_control_sits_in_declared_and_empty_registries():
    """There must be no design to recall, or the control proves nothing."""
    from env import tools as T
    cov = T.registry_coverage()["registries"]
    for key in (NEGATIVE_CONTROL.exposure_key, NEGATIVE_CONTROL.outcome_key):
        prefix = key.split(":")[0]
        assert cov[prefix]["coverage"] == "none", f"{key} is in a populated registry"
        assert T.resolve_variable(key=key)["outcome"] == "not_found"
    assert NEGATIVE_CONTROL.exposure_stem == ""
    assert NEGATIVE_CONTROL.outcome_stem == ""


def test_the_positive_control_is_selected_from_the_frame_not_authored():
    p = positive_control()
    assert p.role == "positive_control"
    assert p.pair_id in {q.pair_id for q in frame_pairs()}
    assert p.exposure_stem and p.outcome_stem


def test_the_positive_control_has_no_grid_battery_on_either_side():
    """A battery stem is not a question, so a battery cannot be the control.

    Found live 2026-08-30: the first mechanically chosen control was a battery
    and the model refused it correctly, which would have condemned a working
    scorer.
    """
    p = positive_control()
    assert p.requires_derivation is False
    live = {q.pair_id: q for q in frame_pairs()}
    assert live[p.pair_id].requires_derivation is False


def test_pair_slug_is_a_usable_filename():
    s = PairSpec("m3:Q16.1", "a", "m2:Q5.8", "b").slug
    assert "/" not in s and ":" not in s and " " not in s
    assert s.startswith("m3") and s.endswith("Q5.8")
