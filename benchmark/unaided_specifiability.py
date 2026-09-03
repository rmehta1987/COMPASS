"""C18: subtract the pairs the model can already specify unaided.

The instrument is withheld and the model is asked for a design anyway.

WHY THIS EXISTS. This benchmark scores rediscovery. A pair the model can specify
WITHOUT the instrument therefore measures something other than instrument
reasoning, and no rediscovery score over that pair is interpretable. The prior
art names the move: CiteME removed every dataset instance GPT-4o could answer,
running each sample five times (`references/PRIOR_ART_CONTAMINATION.md`
§"Subtracting what the model already knows"). C6 — the one-shot recall probe —
must draw its arms from the UNFLAGGED remainder, which is why this lands first.

WHY NOT `agent/sealed.py::score`. That scorer asks whether a probe answer
VOLUNTEERS a held-out fact about this cohort. It is an answer key, matched
literally. This module asks a different question — can the model RECONSTRUCT A
DESIGN for a stated construct pair with no tools — for which there is no answer
key and no correct answer at all. Reusing the fact scorer here would measure
recall of specific strings and report it as design capability.

WHY NOT THE SCHEMA. The obvious naive scorer runs the pair through the real
Specifier with tools withheld and asks whether a `ProtocolSpecification`
validates. It will not, on nearly every pair, and for reasons that say nothing
about whether the model knows the design: with no tools it cannot resolve a
variable key, cannot quote wording verbatim, cannot name a signed derivation and
cannot read a detectability curve. Those failures are the ENVIRONMENT'S
authority working correctly. **Schema conformance is not the signal. Design
content is.** So this module puts the pair to the model in prose and scores the
prose for the four things that make a design usable, listed in `RUBRIC` below.

WHAT THIS MEASURES, STATED NARROWLY. `specifiable_unaided` means: given the two
question stems and nothing else, the model wrote a complete design. It does NOT
distinguish recall of a published analysis from ordinary epidemiological
competence, and it cannot: there is no ground-truth design to be correct about,
so unlike CiteME there is no "correctly answer" to filter on. For the purpose of
the subtraction the distinction does not matter — both are non-instrument routes
to a design, and a score over either is uninterpretable as instrument reasoning
— but any reading of the FLAG RATE as a contamination rate would be wrong.

NO ANSWER KEY LIVES HERE, and none may be added. This module names no study
design, no published exposure-outcome pairing, no adjustment set drawn from a
publication, no prevalence and no cohort figure. The two control pairs below are
constructed mechanically — one from declared-and-empty registries, one from the
frame — precisely so that nothing has to be written down about any paper.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "run" / "unaided"

#: The two per-response verdicts. Named rather than boolean because the flagged
#: set is read by C6 and a bare True is unreadable two sessions later.
SPECIFIABLE = "specifiable_unaided"
NOT_SPECIFIABLE = "not_specifiable_unaided"

#: The written rubric. It is a module constant, not a comment, for two reasons:
#: it is hashed into every record's provenance so a partition names the rubric it
#: was produced under, and `tests/test_unaided_specifiability.py::
#: test_rubric_text_names_every_element_the_code_scores` fails if the prose and
#: the code drift apart. A rubric stated in a docstring
#: and enforced nowhere is this codebase's signature failure.
RUBRIC = """\
A response is `specifiable_unaided` when ALL FOUR of the following are present,
and `not_specifiable_unaided` otherwise. Each is design content: it is a
commitment the analyst has to make before an analysis can be run, and none of
them is a property of the output's FORMAT.

  directed_pairing  One sentence both assigns the roles (which construct is the
                    exposure, which the outcome) and states the sign of the
                    association expected. The role words are supplied by the
                    prompt and are worth nothing on their own; the DIRECTION
                    term is not, and is what this element actually rests on. A
                    design with no expected direction states no hypothesis and
                    cannot be wrong, which is why this is required.

  contrast          The response says how the exposure enters the model: the
                    levels being contrasted, or the increment the effect is
                    expressed for. None of this vocabulary appears in the
                    prompt. Two analysts adjusting identically and contrasting
                    differently do not run the same study, so a design without a
                    contrast is not yet a design.

  adjustment_set    At least three covariates, NAMED INDIVIDUALLY, enumerated
                    where the response first says it is adjusting. "Adjust for
                    confounders" fails and is meant to: it is a statement of
                    intent, not an adjustment set, and it commits the analyst to
                    nothing that could later be checked.

  model_form        A named estimator. "Fit a model" fails; "logistic
                    regression" passes. The estimator decides what the
                    coefficient means, so a design without one has not said what
                    it would report.

NOT REQUIRED, DELIBERATELY, because each is supplied by the instrument and its
absence would only mean the tools were withheld — which is the condition of the
probe, not a finding about the model: a resolvable variable key, verbatim
question wording, a signed derivation, an analytic n, a detectability curve, a
falsifier threshold, a blocker, and JSON that validates against
`agent/schema.py`. A response consisting of well-formed prose that would be
REJECTED by the pipeline schema still scores `specifiable_unaided` when the four
elements above are present.

The four elements are scored on the whole response, without reference to
headings or to any output format. A response that supplies the headings and
fills them with nothing scores `not_specifiable_unaided`; a response that uses
no headings at all and states all four in running prose scores
`specifiable_unaided`.
"""


def rubric_hash() -> str:
    """Hash of `RUBRIC`, recorded on every record.

    Returns:
        The first 16 hex characters of the SHA-256 of the rubric text.
    """
    return hashlib.sha256(RUBRIC.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #

#: The pair is stated the way `agent/specifier.py::user_prompt` states it, minus
#: everything the instrument supplies, so this is an ablation of the tool surface
#: and not a different question. The four headings are a courtesy to the model;
#: the scorer never reads them (see RUBRIC, last paragraph).
#:
#: THE HEADINGS ARE WORDED TO SUPPLY NO SCORED VOCABULARY. An earlier draft said
#: "how the exposure is compared" and "the direction you expect", which hands the
#: model two of the four detectors for free — a probe that names the answer
#: cannot detect the answer, the same failure `agent/sealed.py`'s probe 1 was
#: rewritten for. `exposure` and `outcome` are unavoidable, because the pair
#: cannot be stated without them; that is why `directed_pairing` rests on the
#: direction term rather than on the role words.
PROMPT = """\
You have no tools in this task. There is no codebook, no variable registry, no \
data dictionary, no search and no design conventions available to you, and none \
will become available. Do not ask for them.

A pair of survey constructs is stated below by identifier and by the question \
stem each one is drawn from.

  exposure construct  {exposure_key}
    stem              {exposure_stem}

  outcome construct   {outcome_key}
    stem              {outcome_stem}

Write the analysis you would run for this pair, from what you already know. \
State all four of the following:

  ROLES AND SIGN   which of the two you treat as the exposure and which as the \
outcome, and the sign of the association you expect.
  CONTRAST         the levels of the exposure you would set against each other, \
or the increment the effect is stated for.
  ADJUSTMENT       the covariates you would hold fixed, named one by one.
  MODEL            the estimator you would fit, and the unit of analysis.

If you cannot write an analysis for this pair, say so in one line and stop. Do \
not invent an analysis for a construct whose meaning you do not have.

Prose only. No JSON. Do not invent variable keys or question wording beyond \
what is stated above."""


def unaided_prompt(exposure_key: str, exposure_stem: str,
                   outcome_key: str, outcome_stem: str) -> str:
    """Render the probe for one construct pair.

    Args:
        exposure_key: The exposure construct key, e.g. `m3:Q16.3`.
        exposure_stem: The exposure's question stem, or the empty string when
            the construct has no codebook row — which is what a key in a
            declared-and-empty registry has, and inventing a plausible sentence
            for it would hand the model the very description the environment
            cannot give it (`generate/live_specifier.py::stand_in`).
        outcome_key: The outcome construct key.
        outcome_stem: The outcome's question stem, or the empty string.

    Returns:
        The prompt text sent to the model.
    """
    return PROMPT.format(
        exposure_key=exposure_key,
        exposure_stem=exposure_stem or "(no wording available)",
        outcome_key=outcome_key,
        outcome_stem=outcome_stem or "(no wording available)")


def prompt_hash(text: str) -> str:
    """Hash one rendered prompt, for provenance.

    Args:
        text: The rendered prompt.

    Returns:
        The first 16 hex characters of the SHA-256 of the prompt.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# the scorer
# --------------------------------------------------------------------------- #

#: Role words. Supplied by the prompt, so their presence is worth nothing alone —
#: see `directed_pairing` in RUBRIC.
ROLE_WORDS = ("exposure", "outcome", "predictor", "dependent variable",
              "independent variable", "explanatory variable", "response variable")

#: Direction terms. NONE of these appears in `PROMPT`, so a match is the model's
#: own commitment.
DIRECTION_WORDS = ("positive", "positively", "negative", "negatively", "inverse",
                   "inversely", "increase", "increases", "increased", "increasing",
                   "decrease", "decreases", "decreased", "decreasing", "higher",
                   "lower", "greater", "reduced", "elevated", "protective",
                   "harmful", "raises", "lowers", "worse", "better")

#: How an exposure can enter a model. None of this vocabulary is in `PROMPT`.
CONTRAST_WORDS = ("per 1", "per one", "per unit", "per sd", "per point",
                  "per standard deviation", "per category", "per level",
                  "versus", "vs", "vs.", "compared to", "compared with",
                  "relative to", "tertile", "tertiles", "quartile", "quartiles",
                  "quintile", "quintiles", "median split", "dichotomous",
                  "dichotomise", "dichotomize", "dichotomised", "dichotomized",
                  "binary", "yes/no", "reference category", "reference group",
                  "reference level", "referent", "ever/never", "any/none",
                  "highest", "lowest", "ordinal", "continuous",
                  "categorical", "categorise", "categorize", "categorised",
                  "categorized", "dose-response", "one-unit", "1-unit",
                  "1-point", "one-point", "trichotom")

#: Named estimators. A closed list is right here and is NOT an answer key: model
#: forms are a small closed vocabulary that exists independently of this study,
#: and a miss lands in `not_specifiable_unaided`, which is the conservative
#: direction for a subtraction filter — it keeps a pair in the benchmark rather
#: than removing it.
MODEL_FORMS = ("logistic regression", "logistic model", "linear regression",
               "linear model", "poisson regression", "modified poisson",
               "log-binomial", "log binomial", "negative binomial",
               "cox regression", "cox proportional hazards", "cox model",
               "ordinal logistic", "proportional odds", "multinomial logistic",
               "probit", "generalized linear model", "generalised linear model",
               "glm", "mixed-effects", "mixed effects", "multilevel model",
               "multilevel logistic", "hierarchical model", "random-effects",
               "random effects", "generalized estimating equations",
               "generalised estimating equations", "gee", "propensity score",
               "inverse probability", "marginal structural", "survival analysis",
               "kaplan-meier", "structural equation", "difference in proportions",
               "chi-square", "chi-squared", "t-test", "anova", "ancova")

#: Where a response first says it is adjusting. The cue alone is not the element;
#: the enumerated items after it are.
ADJUST_CUES = ("adjust", "adjusted", "adjusting", "adjustment", "control for",
               "controlling for", "controlled for", "hold fixed", "holding fixed",
               "covariate", "covariates", "confounder", "confounders")

#: Minimum NAMED covariates for `adjustment_set`. Three, because two is a pair
#: and any epidemiological answer reaches age and sex without saying anything;
#: the third is the first one that carries information about this design.
MIN_COVARIATES = 3

#: How many lines after the adjustment cue are read. Bounded because a response
#: that never closes the block would otherwise let the MODEL section's prose
#: count as covariates.
ADJUST_BLOCK_LINES = 14

#: Longest fragment, in words, still readable as one covariate name. A longer
#: fragment is a sentence, and counting sentences as covariates is how
#: "we adjust for the usual demographic and socioeconomic factors that the
#: literature suggests" would score three.
MAX_COVARIATE_WORDS = 6

#: A cue word and the punctuation around it, at the head of a fragment. Applied
#: REPEATEDLY, because two cues can stack: the live response of 2026-08-30 put
#: "**ADJUSTMENT**" and "Hold fixed:" in the same fragment, and one pass left
#: "hold fixed" standing as though it were a covariate.
_CUE_PREFIX = re.compile(
    r"^[\W_]*(?:i (?:would |will )?)?"
    r"(?:adjust(?:ed|ing|ment|ments)?|control(?:led|ling)?|"
    r"hold(?:ing)? fixed|covariates?|confounders?)?"
    r"[\W_]*(?:for|on|are|include[sd]?|including|the following)?[\W_]*")

_BULLET = re.compile("^\\s*(?:[-*\u2022\u2013]|\\(?\\d+[.)])\\s+")

#: Sentence boundary: end punctuation followed by whitespace, or a blank line.
#: The same idiom as `agent/sealed.py::_answered_no`, and for a reason that
#: matters here — splitting on EVERY newline cuts a wrapped sentence in half, so
#: a model whose "I expect a positive association with the outcome" happened to
#: wrap between "positive" and "outcome" would score `directed_pairing` False.
#: For a subtraction filter a false negative keeps an uninterpretable pair in the
#: benchmark, which is the expensive direction.
_SENTENCE = re.compile(r"(?<=[.!?])\s|\n\s*\n")


def _token_in(text: str, phrase: str) -> bool:
    r"""Does `text` contain `phrase` as a standalone token?

    Lookarounds rather than `\b`, for the reason
    `benchmark/leak_facts.py::_mentions` gives: `\b` does not fire on a phrase
    ending in a non-word character, and `vs.` has to match `A vs. B`.

    Args:
        text: Already lower-cased haystack.
        phrase: Literal needle, lower-cased.

    Returns:
        True on a standalone match.
    """
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def _strip_cue(frag: str) -> str:
    """Remove every stacked adjustment cue from the head of one fragment.

    Args:
        frag: One split fragment of the adjustment block.

    Returns:
        The fragment with leading cue words, markup and connectives removed,
        stripped. Empty when the fragment was nothing but cues.
    """
    f, prev = frag.strip(), None
    while prev != f:
        prev = f
        f = _CUE_PREFIX.sub("", f).strip(" .*_#\u2013-\t")
    return f


def _any_token(text: str, phrases: tuple[str, ...]) -> list[str]:
    """Which of `phrases` appear in `text` as standalone tokens.

    Args:
        text: Already lower-cased haystack.
        phrases: Literal needles, lower-cased.

    Returns:
        The matching phrases, in declaration order.
    """
    return [p for p in phrases if _token_in(text, p)]


def has_directed_pairing(text: str) -> bool:
    """Does one sentence assign the roles AND state an expected direction?

    Scoped to a sentence rather than to the whole response because the role
    words come from the prompt: whole-text co-occurrence would score any
    response that echoed the pair statement and used the word "higher"
    anywhere.

    Args:
        text: The response, in full.

    Returns:
        True when some sentence carries both a role word and a direction term.
    """
    sents = [s for s in _SENTENCE.split(text.lower()) if s.strip()]
    # A WINDOW OF TWO, not one. MEASURED 2026-08-30 on the first live positive
    # control: "Treat <x> as the exposure and <y> as the outcome." followed by
    # "The expected association is positive: ... would have higher odds ..." —
    # both commitments made, one sentence apart, and single-sentence scoping
    # scored the element False. Prose splits the role assignment from the sign
    # far more often than it joins them, and for a subtraction filter a false
    # negative is the expensive error: it leaves an uninterpretable pair in the
    # benchmark. Two is still narrow enough that an echo of the pair statement
    # plus the word "higher" three paragraphs later does not score.
    windows = [" ".join(sents[i:i + 2]) for i in range(max(1, len(sents) - 1))]
    return any(_any_token(w, ROLE_WORDS) and _any_token(w, DIRECTION_WORDS)
               for w in windows)


def has_contrast(text: str) -> bool:
    """Does the response say how the exposure enters the model?

    Args:
        text: The response, in full.

    Returns:
        True when any contrast vocabulary appears.
    """
    return bool(_any_token(text.lower(), CONTRAST_WORDS))


def model_forms_in(text: str) -> list[str]:
    """Which named estimators the response commits to.

    Args:
        text: The response, in full.

    Returns:
        The estimator names found, in declaration order.
    """
    return _any_token(text.lower(), MODEL_FORMS)


def covariates_in(text: str) -> list[str]:
    """The covariates enumerated where the response first says it is adjusting.

    Bulleted items are read as items. Otherwise the block is split on commas,
    semicolons and `and`, and fragments longer than `MAX_COVARIATE_WORDS` are
    dropped — which is what makes "adjust for the usual confounders described in
    the literature" score zero rather than one, and is the whole difference
    between an adjustment set and a statement of intent.

    Args:
        text: The response, in full.

    Returns:
        The covariate fragments, lower-cased and stripped, in order. Empty when
        the response never says it is adjusting.
    """
    lines = text.lower().splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if _any_token(ln, ADJUST_CUES)), None)
    if start is None:
        return []
    # A BLANK LINE ONLY ENDS THE BLOCK ONCE THE BLOCK HAS CONTENT. MEASURED
    # 2026-08-30 on the first live positive control, whose adjustment section
    # was a markdown heading ("**ADJUSTMENT**"), a blank line, and then eleven
    # named covariates. The cue matched the HEADING, the blank line below it
    # ended the block, and a response naming eleven covariates scored zero.
    block: list[str] = []
    has_content = False
    for ln in lines[start:start + ADJUST_BLOCK_LINES]:
        stripped = ln.strip()
        if not stripped:
            if has_content:
                break
            continue
        block.append(ln)
        if len(_BULLET.sub("", stripped).split()) > 2:
            has_content = True

    bullets = [_BULLET.sub("", ln).strip() for ln in block if _BULLET.match(ln)]
    if len(bullets) >= 2:
        # A bulleted list is already itemised; splitting it again on "and" would
        # turn "smoking and alcohol use" into two covariates in one branch and
        # one in the other, which makes the count depend on formatting.
        raw = bullets
    else:
        joined = " ".join(ln.strip() for ln in block)
        # Cut everything before the cue: the sentence often opens with prose
        # ("The estimate would be biased, so I adjust for ...") that would
        # otherwise be split into fragments and counted.
        cue = min((joined.find(c) for c in ADJUST_CUES if c in joined),
                  default=0)
        raw = re.split(r"[,;:]|\band\b|\bplus\b", joined[cue:])

    out: list[str] = []
    for frag in raw:
        f = _strip_cue(frag)
        words = f.split()
        if not words or len(words) > MAX_COVARIATE_WORDS:
            continue
        if not re.search(r"[a-z]{3}", f):
            continue
        out.append(f)
    return out


class ResponseVerdict(NamedTuple):
    """One response, scored.

    Attributes:
        verdict: `SPECIFIABLE` or `NOT_SPECIFIABLE`.
        elements: The four rubric elements, each True or False.
        covariates: The covariate fragments `covariates_in` recovered, so a
            reader can see WHY `adjustment_set` scored as it did without
            rereading the response.
        model_forms: The estimators found, for the same reason.
    """

    verdict: str
    elements: dict[str, bool]
    covariates: list[str]
    model_forms: list[str]


def score_response(text: str) -> ResponseVerdict:
    """Score one response against `RUBRIC`. Deterministic, no model, no network.

    Args:
        text: The model's response, in full and untruncated.

    Returns:
        The verdict with the four element flags and the evidence behind two of
        them. `SPECIFIABLE` requires all four elements.
    """
    covs = covariates_in(text)
    forms = model_forms_in(text)
    elements = {
        "directed_pairing": has_directed_pairing(text),
        "contrast": has_contrast(text),
        "adjustment_set": len(covs) >= MIN_COVARIATES,
        "model_form": bool(forms),
    }
    verdict = SPECIFIABLE if all(elements.values()) else NOT_SPECIFIABLE
    return ResponseVerdict(verdict, elements, covs, forms)


#: How many of `k` responses must be `SPECIFIABLE` for the pair to be flagged.
#: ONE, deliberately. This is a subtraction filter, so its errors are asymmetric:
#: wrongly flagging a pair costs one benchmark item, wrongly keeping one puts an
#: uninterpretable score into the results. A pair the model can specify one time
#: in five is a pair whose score is uninterpretable one time in five. The
#: per-response verdicts are persisted, so raising this threshold later needs no
#: new model calls.
DEFAULT_MIN_SPECIFIABLE = 1

#: Responses per pair. CiteME's k, and adopted for CiteME's reason plus one of
#: our own: `agent/cli_backend.py`'s docstring records that the CLI exposes no
#: seed and no temperature, so k samples vary without being reproducible and a
#: single draw cannot separate "cannot" from "did not this time".
DEFAULT_K = 5


def pair_verdict(responses: list[ResponseVerdict],
                 min_specifiable: int = DEFAULT_MIN_SPECIFIABLE) -> str:
    """Aggregate k response verdicts into one pair verdict.

    Args:
        responses: The scored responses for one pair.
        min_specifiable: How many must be `SPECIFIABLE` to flag the pair.

    Returns:
        `SPECIFIABLE` when the pair is flagged, `NOT_SPECIFIABLE` otherwise.

    Raises:
        ValueError: If `responses` is empty. An unflagged pair with no evidence
            behind it would enter C6's arm pool as though it had been tested.
    """
    if not responses:
        raise ValueError("no responses: a pair with no probe cannot be given a "
                         "verdict, and an empty list would silently pass as "
                         "not_specifiable_unaided")
    n = sum(1 for r in responses if r.verdict == SPECIFIABLE)
    return SPECIFIABLE if n >= min_specifiable else NOT_SPECIFIABLE


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #

#: The in-pipeline Specifier, and the only model this probe may use. Substituting
#: a larger one would subtract pairs a model that never runs the benchmark can do
#: (AGENTS.md §Hard Constraints).
MODEL = "claude-haiku-4-5"


@dataclass
class PairSpec:
    """One construct pair to probe, and what it is for.

    Attributes:
        exposure_key: Exposure construct key.
        exposure_stem: Exposure question stem, empty when none exists.
        outcome_key: Outcome construct key.
        outcome_stem: Outcome question stem, empty when none exists.
        role: `pilot`, `negative_control` or `positive_control`.
        note: Why this pair is in the set, for a reader of the record.
        requires_derivation: True when either anchor is a grid battery. Carried
            because a battery's STEM is not a question — VERIFIED live
            2026-08-30, when the first mechanically chosen positive control was
            a battery and the model correctly refused it: "the exposure
            construct is stated only by stem, without the specific statements
            being rated". That is the environment's own rule
            (`env/tools.py::get_item_group`: sub-item text is only
            interpretable WITH the stem) reappearing on the unaided side, and a
            positive control that trips it tests nothing.
    """

    exposure_key: str
    exposure_stem: str
    outcome_key: str
    outcome_stem: str
    role: str = "pilot"
    note: str = ""
    requires_derivation: bool = False

    @property
    def pair_id(self) -> str:
        """The pair identifier, in `generate/funnel.py`'s spelling.

        Returns:
            `<exposure_key> -> <outcome_key>`.
        """
        return f"{self.exposure_key} -> {self.outcome_key}"

    @property
    def slug(self) -> str:
        """Filesystem-safe stem for this pair's record.

        Returns:
            The pair id with the characters a filename cannot carry replaced.
        """
        return re.sub(r"[^A-Za-z0-9.]+", "_", self.pair_id).strip("_")


def unaided_argv(worktree: Any, model: str, prompt: str) -> list[str]:
    """The command line for one unaided probe.

    THE INSTRUMENT IS WITHHELD BY WHAT IS NOT HERE. `SealedWorktree.base_argv`
    passes `--strict-mcp-config` and no `--mcp-config`, so no MCP server is
    attached at all and the environment is unreachable at the process boundary
    rather than by convention; `DENY_TOOLS` removes every built-in, so the model
    cannot read the project or search the web instead.
    `tests/test_unaided_specifiability.py::test_unaided_argv_attaches_no_instrument`
    pins both, because "the tools were withheld" asserted in a docstring and
    checked nowhere is the failure this codebase is named for.

    Args:
        worktree: A `SealedWorktree`.
        model: Model id.
        prompt: The rendered probe.

    Returns:
        The argv, prompt last.

    Raises:
        RuntimeError: If the sealed base argv ever starts attaching an MCP
            server or allow-listing tools, which would void every record this
            module has written.
    """
    argv = list(worktree.base_argv(model))
    for flag in ("--mcp-config", "--allowed-tools", "--allowedTools"):
        if flag in argv:
            raise RuntimeError(
                f"{flag} is in the sealed base argv: the instrument is NOT "
                f"withheld, and every unaided verdict produced under it is "
                f"void. Fix the harness, do not relax this check.")
    return [*argv, prompt]


#: The prompt for the withholding control. It asks for a tool call and nothing
#: else, so the number of logged calls is the whole result and no design content
#: is involved on either side.
WITHHOLDING_PROBE = ("Call the registry_coverage tool and report, in one line, "
                     "which registries it says are empty. If you have no tools, "
                     "say exactly: NO TOOLS AVAILABLE.")


def aided_argv(worktree: Any, model: str, prompt: str) -> list[str]:
    """The same invocation with the instrument ATTACHED. Positive control only.

    "No tool call was logged" is not evidence that tools were unreachable until
    something shows the counter can move. This builds the one invocation that
    differs from `unaided_argv` in exactly the flags that attach the
    environment, so `verify_withholding` can run both and compare.

    NEVER use this to score a pair. It exists so the zero in every unaided log
    means something.

    Args:
        worktree: A `SealedWorktree`.
        model: Model id.
        prompt: The prompt to send.

    Returns:
        The argv, prompt last, with the MCP server attached and this mode's
        registry tools allow-listed.
    """
    from agent.cli_backend import ClaudeCliBackend
    from agent.registry import build_registry
    # A worktree has no .venv of its own, so the sealed config's server command
    # has to be retargeted at the running interpreter or the server never spawns
    # and the control silently logs zero calls for the wrong reason.
    cfg = ClaudeCliBackend._retarget_mcp_config(worktree.mcp_config)
    callables, _schemas = build_registry(worktree.mode)
    allowed = ",".join(f"mcp__compass__{n}" for n in sorted(callables))
    return [*worktree.base_argv(model), "--mcp-config", str(cfg),
            "--allowed-tools", allowed, "--max-turns", "6", prompt]


def verify_withholding(worktree: Any, model: str = MODEL,
                       out_dir: Path = RUN_DIR) -> dict:
    """Run the same probe with the instrument withheld and then attached.

    Args:
        worktree: A `SealedWorktree`, already entered.
        model: Model id.
        out_dir: Where the control's log and record are written.

    Returns:
        `withheld_calls`, `attached_calls`, both answers, the two log paths and
        `ok`. `ok` is False when the attached arm logged no call — in which case
        the withheld arm's zero is uninformative and every record this module
        wrote under that harness is unverified, not verified.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "withholding_control.tool_log.jsonl"
    log.write_text("")
    os.environ["COMPASS_TOOL_LOG"] = str(log)

    withheld_text, withheld_line = probe_once(
        worktree, model, WITHHOLDING_PROBE, log, 0)

    before = _server_lines(log)
    argv = aided_argv(worktree, model, WITHHOLDING_PROBE)
    error, out = "", {}
    try:
        out = worktree.run(argv, timeout=300)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:800]
    attached_calls = _server_lines(log) - before
    attached_line = {
        "record": "invocation", "response_index": 1,
        "instrument": "attached", "mcp_servers_attached": ["compass"],
        "tool_calls_logged": attached_calls,
        "argv_flags": [a for a in argv if a.startswith("--")],
        "model": model, "num_turns": out.get("num_turns"),
        "total_cost_usd": out.get("total_cost_usd"),
        "is_error": bool(out.get("is_error")), "error": error,
    }
    with log.open("a") as f:
        f.write(json.dumps(attached_line) + "\n")

    result = {
        "schema": "withholding_control/1",
        "withheld_calls": withheld_line["tool_calls_logged"],
        "attached_calls": attached_calls,
        "withheld_answer": withheld_text[:600],
        "attached_answer": str(out.get("result", ""))[:600],
        "ok": withheld_line["tool_calls_logged"] == 0 and attached_calls > 0,
        "tool_log_path": str(log),
        "provenance": provenance(worktree, model, prompt_hash(WITHHOLDING_PROBE)),
    }
    rec = out_dir / "withholding_control.json"
    rec.write_text(json.dumps(result, indent=2))
    result["record_path"] = str(rec)
    return result


def _server_lines(path: Path) -> int:
    """How many MCP tool calls the environment server has logged to `path`.

    Args:
        path: The tool log this response is writing to.

    Returns:
        The number of lines carrying a `tool` key. Zero when the file does not
        exist, which is what an unaided run leaves behind.
    """
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        with contextlib.suppress(json.JSONDecodeError):
            n += 1 if "tool" in json.loads(line) else 0
    return n


def probe_once(worktree: Any, model: str, prompt: str,
               tool_log: Path, index: int) -> tuple[str, dict]:
    """Put one prompt to the model with the instrument withheld, once.

    The invocation is appended to `tool_log` beside whatever the environment
    server logged, so a record is auditable against ITS OWN log rather than
    against whichever log was written last — the failure
    `agent/cli_backend.py::_tool_log_path` records.

    Args:
        worktree: A `SealedWorktree`.
        model: Model id.
        prompt: The rendered probe.
        tool_log: Where this response's log line is appended. Also exported as
            `COMPASS_TOOL_LOG`, so that if an environment server were ever
            attached its calls would land in this same file and the
            `tool_calls_logged` count below would be non-zero.
        index: Zero-based response index within this pair.

    Returns:
        The response text and the log line that was written.
    """
    argv = unaided_argv(worktree, model, prompt)
    tool_log.parent.mkdir(parents=True, exist_ok=True)
    # Set on the parent's environ because SealedWorktree.run copies os.environ
    # and takes no extra env; this module may not edit agent/sealed.py.
    os.environ["COMPASS_TOOL_LOG"] = str(tool_log)
    before = _server_lines(tool_log)
    t0 = time.perf_counter()
    error = ""
    out: dict = {}
    try:
        out = worktree.run(argv, timeout=300)
    except Exception as exc:
        # Persisted rather than raised: a live run costs a model call, and
        # diagnosing why one failed must not cost a second one.
        error = f"{type(exc).__name__}: {exc}"[:800]
    text = str(out.get("result", "")).strip()
    line = {
        "record": "invocation",
        "response_index": index,
        "instrument": "withheld",
        "mcp_servers_attached": [],
        "tool_calls_logged": _server_lines(tool_log) - before,
        "denied_builtins": _deny_tools(),
        "argv_flags": [a for a in argv if a.startswith("--")],
        "model": model,
        "num_turns": out.get("num_turns"),
        "total_cost_usd": out.get("total_cost_usd"),
        "session_id": out.get("session_id"),
        "is_error": bool(out.get("is_error")),
        "duration_s": round(time.perf_counter() - t0, 2),
        "error": error,
    }
    with tool_log.open("a") as f:
        f.write(json.dumps(line) + "\n")
    return text, line


def _deny_tools() -> list[str]:
    """The built-in tools the seal denies.

    Returns:
        `agent/sealed.py::DENY_TOOLS`, read at call time so this module can
        never drift from the seal's own list.
    """
    from agent.sealed import DENY_TOOLS
    return list(DENY_TOOLS)


def probe_pair(worktree: Any, spec: PairSpec, *, model: str = MODEL,
               k: int = DEFAULT_K,
               min_specifiable: int = DEFAULT_MIN_SPECIFIABLE,
               out_dir: Path = RUN_DIR) -> dict:
    """Probe one pair k times, score it, and persist the record and its log.

    Args:
        worktree: A `SealedWorktree`, already entered.
        spec: The pair to probe.
        model: Model id. Defaults to the in-pipeline Specifier.
        k: Responses to draw.
        min_specifiable: Flag threshold over the k responses.
        out_dir: Directory for the record and the tool log.

    Returns:
        The persisted record as a dict, with `record_path` and `tool_log_path`
        added.
    """
    prompt = unaided_prompt(spec.exposure_key, spec.exposure_stem,
                            spec.outcome_key, spec.outcome_stem)
    p_hash = prompt_hash(prompt)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{spec.slug}.{p_hash}"
    tool_log = out_dir / f"{stem}.tool_log.jsonl"
    tool_log.write_text("")   # a NEW log per pair, never a truncate mid-run

    scored: list[ResponseVerdict] = []
    responses: list[dict] = []
    for i in range(k):
        text, line = probe_once(worktree, model, prompt, tool_log, i)
        v = score_response(text)
        scored.append(v)
        responses.append({
            "index": i,
            "verdict": v.verdict,
            "elements": v.elements,
            "covariates_found": v.covariates,
            "model_forms_found": v.model_forms,
            "invocation_error": line["error"],
            # Untruncated. The scorer read the whole text and a reader who wants
            # to overturn a verdict must be able to read exactly what it read.
            "text": text,
        })

    record = {
        "schema": "unaided_specifiability/1",
        "pair_id": spec.pair_id,
        "role": spec.role,
        "note": spec.note,
        "exposure": {"construct_key": spec.exposure_key,
                     "stem_text": spec.exposure_stem},
        "outcome": {"construct_key": spec.outcome_key,
                    "stem_text": spec.outcome_stem},
        "requires_derivation": spec.requires_derivation,
        "verdict": pair_verdict(scored, min_specifiable),
        "k": k,
        "n_specifiable": sum(1 for v in scored if v.verdict == SPECIFIABLE),
        "min_specifiable": min_specifiable,
        "provenance": provenance(worktree, model, p_hash),
        "responses": responses,
    }
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(record, indent=2))
    return {**record, "record_path": str(path), "tool_log_path": str(tool_log)}


def provenance(worktree: Any, model: str, p_hash: str) -> dict:
    """What a flagged set has to name to still be usable next month.

    Args:
        worktree: A `SealedWorktree`, for its seal manifest hash.
        model: Model id the verdicts were produced by.
        p_hash: Hash of the rendered prompt.

    Returns:
        Model id, seal hash, date, rubric hash, prompt hash and the dictionary
        version. A flagged set with no provenance is unusable the day the model
        changes, and this project has already lost time to a stale one.
    """
    return {
        "model_id": model,
        "seal_hash": worktree.manifest()["seal_hash"],
        "date": date.today().isoformat(),
        "rubric_hash": rubric_hash(),
        "prompt_hash": p_hash,
        "dictionary_version": _dictionary_version(),
        "instrument": "withheld",
    }


def _dictionary_version() -> str:
    """The built dictionary's version hash, or `unknown` when it is absent.

    Returns:
        `build/dictionary.json`'s `version_hash`.
    """
    f = ROOT / "build" / "dictionary.json"
    if not f.exists():
        return "unknown"
    return str(json.loads(f.read_text()).get("version_hash", "unknown"))


# --------------------------------------------------------------------------- #
# the partition C6 consumes
# --------------------------------------------------------------------------- #

#: Roles whose pairs are FABRICATED for the probe and are not benchmark
#: candidates. The negative control names two keys that exist in no registry, so
#: it is unflagged by construction and an arm drawn from it would be an item with
#: no instrument behind it.
SYNTHETIC_ROLES = ("negative_control",)

#: Every provenance field a partition must carry before C6 may draw arms from it.
REQUIRED_PROVENANCE = ("model_id", "seal_hash", "date", "rubric_hash",
                       "dictionary_version")


def partition(records: list[dict]) -> dict:
    """Split probed pairs into the flagged set and C6's arm pool.

    Args:
        records: Records returned by `probe_pair`.

    Returns:
        `flagged` (specifiable unaided; excluded from rediscovery scoring),
        `unflagged`, and `arm_pool` — the unflagged pairs C6 may actually draw
        from. The three differ, and the difference is load-bearing: the negative
        control is a FABRICATED pair in two declared-and-empty registries, it is
        unflagged by construction, and an arm drawn from it would be a benchmark
        item with no instrument behind it. It stays in `unflagged` because it is
        a real measurement and dropping it would hide the control; it is kept
        out of `arm_pool` because it is not a candidate.

    Raises:
        ValueError: If any record is missing a provenance field, or if a pair
            appears in both halves. Either would put an unusable set in front of
            C6 — the first because nobody can tell which model produced it, the
            second because an arm would be drawn from the excluded set.
    """
    for r in records:
        missing = [f for f in REQUIRED_PROVENANCE
                   if not r.get("provenance", {}).get(f)]
        if missing:
            raise ValueError(
                f"{r.get('pair_id')}: provenance is missing {missing}. A flagged "
                f"set that does not name the model, the seal and the date is "
                f"unusable the day any of them changes.")

    flagged = [r for r in records if r["verdict"] == SPECIFIABLE]
    unflagged = [r for r in records if r["verdict"] == NOT_SPECIFIABLE]
    overlap = {r["pair_id"] for r in flagged} & {r["pair_id"] for r in unflagged}
    if overlap:
        raise ValueError(f"pairs in both halves: {sorted(overlap)}")

    def row(r: dict) -> dict:
        return {"pair_id": r["pair_id"], "role": r["role"],
                "n_specifiable": r["n_specifiable"], "k": r["k"],
                "provenance": r["provenance"]}

    arm_pool = [r for r in unflagged if r["role"] not in SYNTHETIC_ROLES]

    return {
        "schema": "unaided_partition/1",
        "generated": date.today().isoformat(),
        "min_specifiable": records[0]["min_specifiable"] if records else None,
        "rubric_hash": rubric_hash(),
        "counts": {"probed": len(records), "flagged": len(flagged),
                   "unflagged": len(unflagged), "arm_pool": len(arm_pool)},
        "controls": {r["role"]: {"pair_id": r["pair_id"],
                                 "verdict": r["verdict"],
                                 "n_specifiable": r["n_specifiable"]}
                     for r in records if r["role"] != "pilot"},
        "flagged": [row(r) for r in flagged],
        "unflagged": [row(r) for r in unflagged],
        "arm_pool": [row(r) for r in arm_pool],
    }


def load_records(out_dir: Path = RUN_DIR) -> list[dict]:
    """Re-read every persisted pair record under `out_dir`.

    Args:
        out_dir: Directory `probe_pair` wrote to.

    Returns:
        The records, sorted by pair id. The partition and the withholding
        control are not pair records and are skipped.
    """
    out = []
    for f in sorted(out_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        if rec.get("schema") == "unaided_specifiability/1":
            out.append(rec)
    return sorted(out, key=lambda r: r["pair_id"])


def rescore(record: dict,
            min_specifiable: int = DEFAULT_MIN_SPECIFIABLE) -> dict:
    """Re-score a persisted record from its stored response texts. No model.

    This is what makes the threshold and the rubric revisable: every response is
    persisted untruncated, so raising `min_specifiable` or amending `RUBRIC`
    costs a re-read rather than another k model calls. The claim was written in
    a comment first and enforced nowhere, which is this codebase's signature
    failure; `tests/test_unaided_specifiability.py::
    test_a_persisted_record_can_be_rescored_without_a_model_call` is the
    enforcement.

    Args:
        record: A record `probe_pair` wrote.
        min_specifiable: The threshold to apply now.

    Returns:
        A new record with every response re-scored, the pair verdict recomputed,
        and `provenance.rubric_hash` set to the rubric that did the re-scoring.
        The model id, seal hash and date are left as they were, because they
        describe the calls that produced the text and re-scoring made none.
    """
    scored = [score_response(r["text"]) for r in record["responses"]]
    responses = [{**r, "verdict": v.verdict, "elements": v.elements,
                  "covariates_found": v.covariates,
                  "model_forms_found": v.model_forms}
                 for r, v in zip(record["responses"], scored, strict=True)]
    return {**record,
            "responses": responses,
            "verdict": pair_verdict(scored, min_specifiable),
            "n_specifiable": sum(1 for v in scored if v.verdict == SPECIFIABLE),
            "min_specifiable": min_specifiable,
            "provenance": {**record["provenance"],
                           "rubric_hash": rubric_hash(),
                           "rescored": date.today().isoformat()}}


def controls_hold(part: dict) -> tuple[bool, list[str]]:
    """Did both controls come back the way a working scorer requires?

    A partition whose controls failed is not a weaker result, it is no result:
    "could not detect a design" is never "no design is there" without a probe
    that shows the detector fires.

    Args:
        part: A `partition` return value.

    Returns:
        `(ok, complaints)`. `ok` is False when a control is missing or landed on
        the wrong side.
    """
    want = {"negative_control": NOT_SPECIFIABLE,
            "positive_control": SPECIFIABLE}
    bad: list[str] = []
    for role, expected in want.items():
        got = part.get("controls", {}).get(role)
        if got is None:
            bad.append(f"{role} was not run")
        elif got["verdict"] != expected:
            bad.append(f"{role} ({got['pair_id']}) came back {got['verdict']}, "
                       f"expected {expected}")
    return (not bad), bad


# --------------------------------------------------------------------------- #
# the control pairs, and the frame
# --------------------------------------------------------------------------- #

#: The negative control. Both anchors sit in registries `env/tools.py::
#: registry_coverage` declares EMPTY, so no codebook row exists, no wording can
#: be shown, and there is no design to recall or to reconstruct — the identifiers
#: below name nothing in this project or in any publication. If a scorer flags
#: this pair it is flagging the presence of prose, not the presence of a design.
NEGATIVE_CONTROL = PairSpec(
    exposure_key="lab:assay_17", exposure_stem="",
    outcome_key="clinical:measure_23", outcome_stem="",
    role="negative_control",
    note="both anchors in declared-and-empty registries; no wording exists, so "
         "the model has nothing to design from")


def frame_pairs() -> list[PairSpec]:
    """The 6x64 frame the live Specifier runs against, as probe specs.

    Returns:
        Every live pair from `generate/funnel.py` over the same exposure and
        outcome blocks `generate/live_specifier.py` uses, ordered as the funnel
        emits them.
    """
    sys.path.insert(0, str(ROOT))
    from generate.funnel import load_constructs, run
    c, _ = load_constructs()
    exposures = sorted([x for x in c.values()
                        if x.module == "3" and x.base_id.startswith("Q16.")],
                       key=lambda x: x.base_id)
    outcomes = sorted([x for x in c.values()
                       if x.module == "2" and x.base_id.startswith("Q5.")],
                      key=lambda x: x.base_id)
    cands, _counts = run(exposures, outcomes)
    return [PairSpec(x.exposure.construct_key, x.exposure.stem_text,
                     x.outcome.construct_key, x.outcome.stem_text,
                     requires_derivation=x.requires_derivation)
            for x in cands if x.state == "live"]


def positive_control() -> PairSpec:
    """A frame pair the model plainly can design for unaided.

    Chosen mechanically — the first live frame pair whose two stems are both
    plain, self-describing questions — rather than authored, so that no
    exposure-outcome pairing has to be written into this file. If the model
    cannot produce a design for two plainly worded questions with no tools, the
    probe is broken and every `not_specifiable_unaided` verdict it produced is
    uninterpretable.

    Returns:
        The control pair.

    Raises:
        RuntimeError: If the frame contains no such pair.
    """
    for p in frame_pairs():
        if (not p.requires_derivation
                and len(p.exposure_stem) > 40 and len(p.outcome_stem) > 40
                and "?" in p.exposure_stem and "?" in p.outcome_stem):
            return PairSpec(p.exposure_key, p.exposure_stem,
                            p.outcome_key, p.outcome_stem,
                            role="positive_control",
                            note="first live frame pair with no grid battery "
                                 "on either side and two plainly worded stems; "
                                 "selected mechanically, not authored")
    raise RuntimeError("no frame pair has two plainly worded stems")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _print_record(rec: dict) -> None:
    """Print one probed pair's verdict and the evidence behind it.

    Args:
        rec: A `probe_pair` return value.
    """
    print(f"\n  {rec['role'].upper():<18} {rec['pair_id']}")
    print(f"    verdict     {rec['verdict']}  "
          f"({rec['n_specifiable']}/{rec['k']} responses specifiable)")
    for r in rec["responses"]:
        on = ",".join(k for k, v in r["elements"].items() if v) or "none"
        print(f"    [{r['index']}] {r['verdict']:<26} elements: {on}")
        if r["invocation_error"]:
            print(f"        ERROR {r['invocation_error']}")
    print(f"    record      {rec['record_path']}")
    print(f"    tool log    {rec['tool_log_path']}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the run's arguments.

    Args:
        argv: The command line, without the program name.

    Returns:
        The parsed arguments.
    """
    ap = argparse.ArgumentParser(description="C18 unaided-specifiability probe")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--pilot", type=int, default=0,
                    help="probe this many frame pairs, evenly spaced")
    ap.add_argument("--controls", action="store_true",
                    help="probe the negative and positive controls")
    ap.add_argument("--repartition", action="store_true",
                    help="re-score the records already on disk and rewrite the "
                         "partition. Makes no model call.")
    ap.add_argument("--verify-withholding", action="store_true",
                    help="positive control on the harness: run the same probe "
                         "with the instrument withheld and then attached")
    ap.add_argument("--min-specifiable", type=int,
                    default=DEFAULT_MIN_SPECIFIABLE)
    ap.add_argument("--out", type=Path, default=RUN_DIR)
    return ap.parse_args(argv)


def _pilot_specs(n: int, exclude: tuple[str, ...] = ()) -> list[PairSpec]:
    """Evenly spaced frame pairs, so a pilot is not all one exposure block.

    Args:
        n: How many pairs.
        exclude: Pair ids already being probed as controls. Without this the
            positive control — the FIRST live frame pair — is drawn again as
            pilot pair 0, and the same pair appears twice in the partition.

    Returns:
        `n` pair specs drawn at a fixed stride from the live frame.
    """
    live = [p for p in frame_pairs() if p.pair_id not in exclude]
    if n <= 0 or not live:
        return []
    stride = max(1, len(live) // n)
    return [live[i * stride] for i in range(n) if i * stride < len(live)]


def main(argv: list[str] | None = None) -> int:
    """Run the probe and write the partition.

    Args:
        argv: Command line, without the program name.

    Returns:
        0 when every requested control held, 1 otherwise. A non-zero exit on a
        failed control is deliberate: a partition produced by a scorer whose
        controls did not hold must not be picked up by C6 by accident.
    """
    from agent.sealed import SealedWorktree
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.repartition:
        recs = [rescore(r, args.min_specifiable)
                for r in load_records(args.out)]
        if not recs:
            print(f"no records under {args.out}")
            return 1
        for r in recs:
            spec = PairSpec(r["exposure"]["construct_key"], "",
                            r["outcome"]["construct_key"], "")
            name = f"{spec.slug}.{r['provenance']['prompt_hash']}.json"
            (args.out / name).write_text(json.dumps(r, indent=2))
        part = partition(recs)
        (args.out / "partition.json").write_text(json.dumps(part, indent=2))
        ok, bad = controls_hold(part)
        print(f"  repartitioned {part['counts']} at threshold "
              f"{args.min_specifiable}   controls "
              f"{'HOLD' if ok else 'FAILED: ' + '; '.join(bad)}")
        return 0 if ok else 1

    if args.verify_withholding:
        with SealedWorktree(mode="benchmark") as wt:
            r = verify_withholding(wt, args.model, args.out)
        print(f"  withheld  tool calls logged: {r['withheld_calls']}")
        print(f"            answer: {r['withheld_answer'][:200]}")
        print(f"  attached  tool calls logged: {r['attached_calls']}")
        print(f"            answer: {r['attached_answer'][:200]}")
        print(f"  record    {r['record_path']}")
        print(f"  tool log  {r['tool_log_path']}")
        print(f"  {'OK' if r['ok'] else 'FAILED'}: the counter that reads zero "
              f"on every unaided probe "
              f"{'does' if r['ok'] else 'DOES NOT'} move when the instrument "
              f"is attached")
        if not r["ok"]:
            return 1

    specs: list[PairSpec] = []
    if args.controls:
        specs += [NEGATIVE_CONTROL, positive_control()]
    specs += _pilot_specs(args.pilot, tuple(s.pair_id for s in specs))
    if not specs:
        if args.verify_withholding:
            return 0
        print("nothing to probe: pass --controls, --pilot N or "
              "--verify-withholding")
        return 1

    bar = "=" * 74
    print(bar)
    print(f"UNAIDED SPECIFIABILITY (C18)   model={args.model}  k={args.k}  "
          f"pairs={len(specs)}")
    print(f"rubric {rubric_hash()}   threshold {args.min_specifiable}/{args.k}")
    print(bar)

    records = []
    with SealedWorktree(mode="benchmark") as wt:
        print(f"  seal {wt.manifest()['seal_hash']}   "
              f"CLAUDE.md reachable: {wt.manifest()['claude_md_found'] or 'none'}")
        for spec in specs:
            rec = probe_pair(wt, spec, model=args.model, k=args.k,
                             min_specifiable=args.min_specifiable,
                             out_dir=args.out)
            records.append(rec)
            _print_record(rec)

    part = partition(records)
    out = args.out / "partition.json"
    out.write_text(json.dumps(part, indent=2))
    print(f"\n{bar}")
    print(f"  flagged {part['counts']['flagged']} / probed "
          f"{part['counts']['probed']}   written {out}")

    if args.controls:
        ok, bad = controls_hold(part)
        print(f"  controls    {'HOLD' if ok else 'FAILED'}")
        for b in bad:
            print(f"    {b}")
        if not ok:
            print("  This partition is NOT usable by C6: a scorer whose "
                  "controls failed has measured nothing.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
