"""agent/specifier.py — the one agent that reasons.

    LLM        reasoning + tool calling      (this file's two model calls)
    Python     orchestration                 (this file's control flow)

That split is the finding, not a style preference. The largest measured
architectural gains in the reviewed corpus come from deterministic orchestration
of narrow model calls, and the one system that gave its LLM the orchestrator role
deleted it after observing that it "almost always called tools in the same
order." So the model here never chooses which pair to work on, how many samples
to draw, when to stop, or which record wins. It is handed a stated pair and asked
to specify a design for it, which is the operation this model class is
comparatively reliable at.

FLOW — two model calls, never one:

    handed a pair
      |
      +-- call 1: REASON.  Unconstrained prose. Tools available. Loops until the
      |           model stops calling tools or MAX_STEPS. This is where the
      |           thinking happens and where every fact enters.
      |
      +-- gate:   MECHANICAL, no model. Did the research log actually contain the
      |           calls a defensible record requires? A model that skipped
      |           check_access does not get to assert an access decision.
      |
      +-- call 2: TRANSDUCE. Constrained by the Pydantic JSON schema. Sees its
      |           own reasoning and the tool log; adds no new facts. Field order
      |           in the schema is load-bearing: mechanism and justification are
      |           emitted before role, so a grammar cannot commit to a verdict
      |           before generating the reasoning that supports it.
      |
      +-- authority: MECHANICAL, no model. agent/tool_authority.py replaces every
      |           field the environment computed with the environment's own value
      |           and rejects a verdict that contradicts the log. Runs before
      |           validation, because a null smallest_detectable_effect has to be
      |           filled before the falsifier check reads it.
      |
      +-- validate, up to MAX_TRANSDUCE_ATTEMPTS drafts, each re-prompted with
      |           the rejected object AND the error. Raised from 2 to 4 on
      |           2026-08-27: pydantic raises on the FIRST failing validator, so
      |           five measured runs produced five different single-validator
      |           rejections and zero records. Formatting only — no new facts.
      |
      k=5 samples -> dedup by record_hash -> deterministic selection -> parked/

REFUSAL — the second outlet, added 2026-08-28. Until it existed the output space
was "valid protocol or nothing", so for a pair whose exposure resolves nowhere
the only well-formed record was one that invented a key. Two things make it a
measurement rather than an escape hatch, and neither is a vote:

    adjudicate()  MECHANICAL, no model, and it runs BEFORE call 1. It asks the
                  environment whether this pair's anchors resolve at all. Its
                  answer is a property of the pair and the dictionary, so it is
                  the same for every one of the k samples and cannot be moved by
                  any of them.

    _refusal_gate MECHANICAL, no model. Symmetric with REQUIRED_CALLS: a
                  protocol must show the calls that support its assertions, and
                  a refusal must show the calls that force it. Which calls those
                  are is read from agent/schema.py's REFUSAL_EVIDENCE, never
                  restated here.

The four outcomes are settled by the environment against the model's own
declaration, never by which of them more samples produced:

    environment forces a refusal, sample refused   -> refusal, reason stamped
    environment forces a refusal, sample specified -> specified_the_unspecifiable
    pair is specifiable,          sample refused   -> unearned_refusal
    pair is specifiable,          sample specified -> the protocol path above
"""

from __future__ import annotations

import hashlib
import json
import string
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, ConfigDict, ValidationError

from agent.backends import Backend, Reply
from agent.registry import build_registry
from agent.schema import (
    REFUSAL_EVIDENCE,
    NotSpecifiable,
    ProtocolSpecification,
    RefusalEvidence,
    RefusalReason,
    Status,
)
from agent.tool_authority import (
    GateMismatch,
    RunIdentity,
    apply_record_identity,
    apply_tool_authority,
)
from env.tools import ToolLog


# THE PROMPT CONTRACT. Every prompt below is rendered through PromptTemplate,
# and a template's variables are PARSED OUT OF ITS BODY — there is deliberately
# nowhere to write them down a second time.
#
# WHY DERIVED AND NEVER DECLARED. langchain's PromptTemplate takes
# `input_variables=[...]` alongside the body, and a hand-kept list beside the
# thing it describes drifts. Counted by the orchestrator on 2026-09-01 against
# the one prior-art system read at implementation level
# (`references/PRIOR_ART_CONTAMINATION.md` §Read status) and NOT re-fetched
# here: five of its six templates disagree with their own bodies. Three declare
# variables the body no longer uses, which `str.format` accepts and discards in
# silence, and three interpolate a context variable declared nowhere. Neither
# direction raised. So the list is computed here by the same `string.Formatter`
# that `str.format` itself consumes the body with, which makes the two
# impossible to disagree rather than merely discouraged from it — AGENTS.md
# §Testing Patterns, a guarantee enforced nowhere is this codebase's signature
# failure, and the enforcement that cannot be skipped is the one nobody has to
# remember.


class PromptContractError(ValueError):
    """A render call and its template body disagree about the variables."""


def _slots(name: str, body: str) -> frozenset[str]:
    """Derive the variables a template body requires, from the body alone.

    Args:
        name: The template's name, for the message.
        body: The prompt text. `{x}` is a slot; `{{` and `}}` are literal
            braces, which the JSON these prompts quote depends on.

    Returns:
        Every name `str.format` would consume from this body, once each.

    Raises:
        PromptContractError: On unbalanced braces, or on a field that no
            keyword can supply — `{0}`, `{a.b}`, `{a[0]}`.
    """
    try:
        parsed = list(string.Formatter().parse(body))
    except ValueError as exc:  # unbalanced braces: a defect, not a slot
        raise PromptContractError(f"prompt {name} does not parse: {exc}") from exc
    out: set[str] = set()
    for _, field_name, _, _ in parsed:
        if field_name is None:
            continue
        if not field_name.isidentifier():
            raise PromptContractError(
                f"prompt {name} uses the field {field_name!r}, which is not a "
                f"plain name. A positional, dotted or indexed field cannot be "
                f"compared with the keywords render() is handed, and this type "
                f"is only worth having while that comparison is total")
        out.add(field_name)
    return frozenset(out)


class PromptTemplate(BaseModel):
    """One prompt body, plus the variable contract computed from it.

    Attributes:
        name: How this template is named in an error message.
        body: The prompt text, with `{slot}` wherever a value goes.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    body: str

    @property
    def variables(self) -> frozenset[str]:
        """The variables this template requires.

        Returns:
            The names parsed out of `body`, derived on every access and stored
            nowhere, so no copy exists to go stale.
        """
        return _slots(self.name, self.body)

    def render(self, **values: object) -> str:
        """Fill the body, refusing any disagreement about the variables.

        Args:
            **values: One keyword per slot in the body. Exactly the slots:
                no more and no fewer.

        Returns:
            The prompt text a model will read.

        Raises:
            PromptContractError: When a slot has no value, or a value has no
                slot; the message names every offending variable.

        The second half is the one that is easy to leave out and the reason
        this method exists rather than a bare `.format`: `str.format` accepts an
        argument the body does not use and drops it without a word, which is
        how four templates in the prior-art system above went on declaring
        variables their bodies had stopped mentioning. An unused argument is not
        a harmless extra — it is a value someone computed and believes the model
        was shown.
        """
        wanted = self.variables
        missing = sorted(wanted - set(values))
        unused = sorted(set(values) - wanted)
        if missing or unused:
            said = ([f"no value for {missing}"] if missing else []) + (
                [f"no slot for {unused}"] if unused else [])
            raise PromptContractError(
                f"prompt {self.name}: {', and '.join(said)}. "
                f"The body's slots are {sorted(wanted)}")
        return self.body.format(**values)


def _template(name: str) -> PromptTemplate:
    """The named prompt body as a template, read from this module at call time.

    Args:
        name: A module-level name in this file holding prompt text.

    Returns:
        A template over whatever that name holds NOW.

    Raises:
        PromptContractError: When that name holds no prompt text.

    Read through the module global rather than captured once at import, for the
    reason `benchmark/contamination_check.py::_second_call_surface` gives for
    doing the same: two marker tests plant a marker with
    `monkeypatch.setattr(SP, "REPAIR", ...)` and then assert the scan finds it,
    which holds only while the text sent is the text the module holds. A
    template bound at import is a copy, and a scan over a copy scans something
    the model never reads.
    """
    body = globals().get(name)
    if not isinstance(body, str):
        raise PromptContractError(f"{name} is not prompt text in this module")
    return PromptTemplate(name=name, body=body)


MAX_STEPS = 14  # In-process tool-loop bound. The comment here read "enough for 11
                # tools plus retries" until 2026-08-31; the registry has carried 12
                # since browse_variables landed, so the stated headroom was wrong by
                # one. The VALUE is unchanged because nothing measures it: the saved
                # logs record tool CALLS, not loop steps (22-109 calls across the 27
                # logs under run/, measured 2026-08-31), no saved record carries a
                # step count, and a call count is not a step count. Raise it on a
                # measurement of steps, not on an argument from the tool count.

#: Transduction attempts per sample, the first plus its repairs. Bounded, and the
#: bound is a measurement rather than a preference: at 2 (one repair) five live
#: Haiku runs on 2026-08-27 produced zero valid records and failed on five
#: DIFFERENT single validators — a key in two lists, a key in no registry, a
#: paraphrased unit, a stale estimate_n key set, a null at_n. pydantic raises on
#: the FIRST failing model_validator, so an attempt that repairs the error it was
#: shown can still surface the next one, and a record with ~20 validators over it
#: does not converge in one pass. This is formatting, not reasoning: no repair
#: adds a fact, the tool log and the analysis are fixed, and control flow stays
#: in Python. Raising it does not make the gate weaker — every attempt faces the
#: same validators.
MAX_TRANSDUCE_ATTEMPTS = 4
REQUIRED_CALLS = {"resolve_variable", "estimate_n", "check_access",
                  "estimate_detectability"}

#: The one shape call 1 may use to declare a refusal. A sentinel and not a
#: keyword search: "this pair may not be specifiable" is a sentence a model
#: writes on its way to specifying it, and a detector firing on prose would turn
#: hedging into abstention and then report the difference as calibration. Named
#: here because the prompt is generated from it and `claimed_refusal` parses it —
#: a literal in both places is a shape the model is told one way and read another.
REFUSAL_SENTINEL = "NOT SPECIFIABLE:"

#: The reasons the environment can settle from the PAIR ALONE, which is what
#: makes them adjudicable before the model is called and identical across k. This
#: set is the menu the system prompt offers, so the model is never invited to
#: state a reason nothing can uphold.
#:
#: The other three RefusalReason members are design-dependent, not
#: pair-dependent, and are deliberately absent. `no_signed_derivation` does not
#: follow from a grid anchor: env/tools.py's own group log offers naming a
#: sub-item as the alternative, so a battery with no derivation is still
#: specifiable and forcing a refusal would be over-refusal. `no_contrast_definable`
#: and `access_gate_refused` depend on the key set the model chose rather than on
#: the pair — and MEASURED 2026-08-28, neither is reachable from this environment
#: at all: get_contrast_convention has no branch that fails to return a contrast,
#: and check_access returns only `pass` or `refer`, never a refusing decision. A
#: reason no return value can produce cannot be earned. Reported rather than
#: silently patched: env/tools.py belongs to another lane.
PAIR_ADJUDICABLE = frozenset({
    RefusalReason.anchors_are_the_same_construct,
    RefusalReason.registry_empty,
    RefusalReason.exposure_unresolvable,
    RefusalReason.outcome_unresolvable,
    RefusalReason.free_text_anchor,
})


# CLAUSE (d) OF C24, PAID FOR IN THE SAME EDIT. The `sought_covariates` sentence
# in rule 6 replaced "Excluding a variable is a first-class act ... not omitted
# silently": 155 characters out, 142 in, leaving SYSTEM 13 SHORTER than before
# (5681 -> 5668). Nothing was lost. The mediator -> `excluded` routing that
# sentence stated is already in the {roles} table generated below, in this same
# prompt, from the sets the validator actually uses; "with its mechanism" is
# rule 7; and "not omitted silently" is the rationale rule 6 still gives two
# sentences later. A prompt that only ever grows stops being read, so a sentence
# added here is a sentence found and removed there.
SYSTEM_TEMPLATE = PromptTemplate(name="SYSTEM", body="""\
You are a study-design specifier for COMPASS, the ChicagO Multiethnic Prevention \
And Surveillance Study.

You are handed ONE exposure-outcome pair that a deterministic enumeration already \
produced. You do not choose it, judge whether it is interesting, or propose a \
different one. Your job is to specify a design for the pair you were given.

No participant data exists in this system and none will. You never run an \
analysis and you never report a result. You produce a PROTOCOL: a design that \
could be executed later, stating exactly what is known, what is assumed, and what \
is missing.

HARD RULES
1. Every variable key you name must come back from resolve_variable. If a key \
does not resolve, say so and set a blocker. Never substitute a similar-sounding \
item — a key that resolves while naming the wrong construct is the one failure \
with no automated detector.
2. Quote question wording verbatim from resolve_variable. Do not paraphrase it.
3. You may not state a variable's response scale, coding or missing codes. The \
codebooks have two columns and none of that exists. This is checked, and a \
record that names a code is rejected: write "highest versus lowest category", \
never "1-5 Likert, 1=strongly disagree". If the design cannot be specified \
without knowing the coding, that is an admitted gap and not a licence to supply \
one — set the response_coding blocker and say so.
4. Never invent a sample size. If estimate_n returns unknown, the record says \
unknown and names the blocker.
5. A multi-item scale enters only by naming a signed derivation from \
list_derivations. Inline recipes are forbidden.
6. Covariates go in exactly one of three lists: adjusted, excluded, undetermined. \
A construct you searched for and could not bind to any key goes in none of them: \
record it in `sought_covariates` with the phrases you tried. \
`undetermined` is honest abstention and is not a failure. `adjusted` and \
`excluded` must each name AT LEAST ONE variable: a record with an empty \
`excluded` list is rejected, because an omitted-by-accident variable and an \
omitted-on-purpose one are indistinguishable unless the exclusions are written \
down. If you can name nothing you deliberately left out, you have not finished \
the design.
7. For each covariate, state the MECHANISM first — how it connects exposure and \
outcome — then the justification, then the role. Reason toward the role; do not \
start from it. Each list accepts only certain roles, and a role in the wrong \
list is rejected:
{roles}

IF THE PAIR CANNOT BE SPECIFIED, SAY SO. That is a legitimate outcome and it is \
not counted as a failure. It is the correct output when the instrument does not \
contain an anchor the design needs, and inventing a key that merely looks \
well-formed is the failure it exists to prevent. To take it, end your analysis \
with a line of exactly this shape and write nothing after it:

  {sentinel} <reason>

Use one of these reasons and no other, and only once the lookups beside it are \
in your research log — the log is checked, and a reason whose lookups are \
missing is rejected the same way a missing check_access is. This list is what \
the environment can currently establish for itself; a difficulty it cannot check \
is not on it, and is not a reason to refuse:
{refusals}

The environment settles this against its own lookups, not against what you \
state. A refusal on a pair whose anchors do resolve is discarded exactly as a \
fabricated key is. If you refuse, the four calls below are NOT required — they \
are the calls a protocol needs, and there is no protocol.

Call tools freely. Facts you did not get from a tool do not belong in the record.

BEFORE YOU CONCLUDE, these calls MUST appear in your research log. A record that
asserts an access decision, a sample size or a detectable effect that was never
looked up is rejected mechanically, and the whole sample is discarded:
{required}

Run each one as soon as you have a key set you intend to keep. A run that spends
its turns on covariate discovery and never calls check_access is discarded whole,
and covariate discovery is worth less than a record that passes.

THEN, WHEN YOUR COVARIATE LISTS ARE FINAL, CALL estimate_n AND check_access ONE
MORE TIME, BOTH OF THEM, WITH THE SAME COMPLETE KEY SET. Both are checked
against the key set your record actually names, and a key you add after the last
call is a key the environment never saw. Found live: a run added one covariate after its
final estimate_n, re-ran check_access alone, and lost the whole sample. If you
add or remove a key, the pair of calls is stale — run both again.\
""")


# Found live 2026-08-26: Haiku passed the derivation id "social_cohesion_scale"
# into estimate_n and check_access. estimate_n dropped it silently and reported
# modules m1+m2 for a design that spans m3; check_access flagged it
# origin_unknown and returned `refer`, which the record then overwrote with
# `pass`. Both tools take VARIABLE keys and neither prompt line said so.
#
# Two instances of the same hole, one found in the repo and one found live on
# 2026-08-27. In the scripted fixture both calls named 6 keys while the record
# they justify names 11, and the environment's verdict was stamped on anyway. In
# a live Haiku run the model called estimate_n with 9 keys, found a 10th
# covariate afterwards, re-ran check_access alone, and left estimate_n stale.
# Both calls are now bound to the record's own key set, so the checklist has to
# say which keys that is and when to run them.
_KEY_SET = ("the exposure, the outcome, every adjusted covariate and every "
            "undetermined covariate — a derivation enters as its component "
            "keys, never as its id. Deliberately excluded variables are left "
            "out: they consume no budget and constrain no n")
_WHY = {
    "resolve_variable": "every key you name, before you name it",
    "estimate_n": f"TOGETHER WITH check_access, LAST. {_KEY_SET}",
    # Named as the BOUND, not "the curve". Round 3: the check moved off the
    # caller-asserted curve onto sde_by_n_worst_case_prevalence, and a checklist
    # line still pointing at "the curve" would send the model to the wrong one.
    "estimate_detectability": ("to find the bound your falsifier is checked "
                               "against: sde_by_n_worst_case_prevalence, NOT "
                               "sde_by_n"),
    "check_access": ("TOGETHER WITH estimate_n, LAST. Same key set. A key it "
                     "cannot place returns refer"),
}
# GENERATED FROM THE SETS THE VALIDATOR USES, never restated by hand. The
# role-to-list mapping is enforced by ProtocolSpecification._roles_match_their_
# lists and appeared in no prompt, so a live run on 2026-08-27 spent all four
# transductions being told "role=unadjudicated cannot appear in
# excluded_variables" with nothing anywhere to say where it does belong.
# Generating it means a role added to one of those sets cannot silently fail to
# reach the model — the same reason the required-call checklist is generated
# from REQUIRED_CALLS.
def _role_table() -> str:
    """Render the role-to-list mapping the validator enforces.

    Returns:
        One line per covariate list, naming the roles it accepts.
    """
    from agent.schema import ADJUSTED_ROLES, EXCLUDED_ROLES, UNDETERMINED_ROLES
    return "\n".join(
        f"  {name:14} {', '.join(sorted(r.value for r in roles))}"
        for name, roles in (("adjusted", ADJUSTED_ROLES),
                            ("excluded", EXCLUDED_ROLES),
                            ("undetermined", UNDETERMINED_ROLES)))


# GENERATED FROM agent/schema.py's REFUSAL_EVIDENCE, for the same reason the role
# table above is generated from the validator's own sets: a reason added to the
# enum without reaching this prompt is a reason the model cannot state, and a
# reason whose required lookups change here but not in the gate is a refusal the
# model is told to earn one way and judged on another.
def _refusal_table() -> str:
    """Render the refusal menu, with the lookups the gate will demand for each.

    Returns:
        One line per reason the environment can uphold, naming the lookups that
        must appear in the research log before that reason may be stated.
    """
    return "\n".join(
        f"  {r.value:32} needs {', '.join(sorted(REFUSAL_EVIDENCE[r]))}"
        for r in RefusalReason if r in PAIR_ADJUDICABLE)


SYSTEM = SYSTEM_TEMPLATE.render(
    required="\n".join(f"  - {n}: {_WHY[n]}" for n in sorted(REQUIRED_CALLS)),
    roles=_role_table(),
    sentinel=REFUSAL_SENTINEL,
    refusals=_refusal_table())


USER_PROMPT_TEMPLATE = PromptTemplate(name="user_prompt", body="""\
PAIR {pair_id}

  exposure construct  {exposure_key}
    stem              {exposure_stem}
    member keys       {exposure_members}
    is a grid battery {exposure_is_group}

  outcome construct   {outcome_key}
    stem              {outcome_stem}
    member keys       {outcome_members}

  funnel estimability {estimability}
  requires derivation {requires_derivation}
  screened from       enumerated candidate set

Research this pair with the tools, then state in prose:
  - the causal question, and the direction you expect
  - the exposure: which key or which signed derivation, and its contrast
  - the outcome key and its verbatim wording
  - every covariate, with its mechanism, split across adjusted / excluded / \
undetermined
  - the model form, unit of analysis, and clustering
  - a falsifier with a numeric threshold, AND the candidate n you claim it is \
detectable at. estimate_detectability returns a CURVE, not one number, because \
the analytic n of this design is unknown; the smallest detectable effect \
therefore has no single value and the record carries the whole curve. Name one \
n ON that curve. Naming a larger n is not a looser test — it is a larger claim \
about what this study must reach, it is written into the record for a reviewer \
to see, and while the analytic n is unknown the record stays draft and must \
name its blocker. The grid is a set of n to EVALUATE at, never a cohort size \
this study is known to reach, so do not copy one into analytic_n.
    YOUR THRESHOLD IS CHECKED AGAINST `sde_by_n_worst_case_prevalence`, NOT \
AGAINST `sde_by_n`. The `baseline_prevalence` you pass to estimate_detectability \
is your own assumption — no tool here returns an outcome frequency for this \
cohort, so nothing in this environment can confirm or refute the number you \
choose — and the smallest detectable effect shrinks as that assumption moves \
away from the value that maximises it. A threshold checked against `sde_by_n` \
would therefore be checked against a floor you set yourself, which is not a \
check. `sde_by_n_worst_case_prevalence` is the same formula at the frequency \
that MAXIMISES the floor; no caller can move it, and a threshold clearing it is \
detectable whatever the true frequency turns out to be. So: read \
`sde_by_n_worst_case_prevalence` at the n you named, and state a threshold at \
or above THAT value. It is never the smaller of the two numbers — it is equal \
to `sde_by_n` only if you assumed the maximising frequency exactly, and larger \
otherwise. Your \
`baseline_prevalence` is still recorded, as a labelled assumption and not as a \
yardstick, and because nothing here can confirm it the record also carries the \
blocker `outcome_prevalence_unconfirmed` and cannot leave draft on it.
    estimate_detectability computes a RISK DIFFERENCE in percentage points and \
nothing else, so a numeric threshold must be a difference in percentage points \
to be checkable at all. If your falsifier is naturally a ratio — an odds ratio, \
a risk ratio — or a model comparison, then state it in the falsifier PROSE and \
leave the numeric threshold out. An unstated threshold is honest; one in a unit \
that cannot be compared to the curve is a check that never runs.
  - what is missing and what it blocks

Do not emit JSON. Prose only. A separate step will format it.""")


def user_prompt(pair: PairLike) -> str:
    """Render call 1's user message: the pair, and what to state about it.

    Args:
        pair: The pair this run was handed; see `PairLike`.

    Returns:
        The prompt text naming the pair.
    """
    e, o = pair.exposure, pair.outcome
    return USER_PROMPT_TEMPLATE.render(
        pair_id=pair.pair_id,
        exposure_key=e.construct_key,
        exposure_stem=e.stem_text,
        exposure_members=', '.join(e.member_keys),
        exposure_is_group=e.is_group,
        outcome_key=o.construct_key,
        outcome_stem=o.stem_text,
        outcome_members=', '.join(o.member_keys),
        estimability=pair.estimability,
        requires_derivation=pair.requires_derivation)


TRANSDUCE = """\
Convert the analysis below into one JSON object matching the required schema.

Add NOTHING. Every key, wording, number and blocker must already appear in the \
analysis or the tool log. If the analysis did not establish a field, use the \
schema's null or unknown value — do not fill a gap with a plausible value.

For each covariate emit mechanism and justification BEFORE role.

`access` and `estimability` are checked against the tool log after you emit \
them. `smallest_detectable_effect.curve`, `.worst_case_curve` and \
`.asserted_baseline_prevalence` are all written from estimate_detectability's \
own return value — emit them empty or null and they will be filled; what you \
must supply is `at_n`, the candidate n you claim the falsifier is detectable \
at. Your falsifier threshold is compared against `worst_case_curve` at that n, \
never against `curve`. `access.decision`, `estimability.n_source` and \
`estimability.analytic_n` must be exactly what check_access and estimate_n \
returned — a record that \
restates them from memory is rejected. Read the tool's own `decision` and \
`n_source` keys: every tool also returns `outcome`, which says only that the \
call succeeded and is never the verdict. The remaining numbers in those two \
blocks are replaced with the tool's values, so an approximate transcription \
costs nothing and an invented one is visible.

--- ANALYSIS ---
{analysis}

--- TOOL LOG ---
{toollog}
"""


TRANSDUCE_REFUSAL = """\
The analysis below concluded that this pair cannot be specified, and the \
environment agrees. Convert it into one JSON object matching the required schema.

Add NOTHING. `pair_id`, `dictionary_version`, `reason`, `blocked_on` and every \
entry of `evidence` are written over by the environment after you emit them, so \
transcribe them from THE ENVIRONMENT'S FINDING below and invent nothing. What \
you supply is `statement` and `what_would_unblock`, and a reader must be able to \
check both against that evidence without rerunning anything.

Emit no design. There is no covariate, model form, direction, threshold or \
sample-size field in this schema, and adding one is rejected.

--- THE ENVIRONMENT'S FINDING ---
{finding}

--- ANALYSIS ---
{analysis}

--- TOOL LOG ---
{toollog}
"""


def prompt_hash(pair: PairLike) -> str:
    """Hash the exact prompt text a run sends, for provenance.

    Args:
        pair: The funnel candidate this run was handed.

    Returns:
        The first 16 hex characters of the SHA-256 of the four prompt bodies.

    Every provenance field in the one live record was the empty string, and
    prompt_hash's job is to let an ablation tell "the component changed" from
    "someone edited a prompt and forgot". A literal "fixture" or "unset" does
    that job no better than "". All FOUR bodies are hashed, not just SYSTEM,
    because the transduction prompts and the pair rendering are prompt text the
    model reads too. TRANSDUCE_REFUSAL joined them on 2026-08-28: it is sent
    only on the refusal path, but a hash that omitted it would report two runs
    as identically prompted while one of them could refuse and the other could
    not, which is the one comparison this field exists to make.
    """
    body = "\x00".join((SYSTEM, user_prompt(pair), TRANSDUCE, TRANSDUCE_REFUSAL))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


REPAIR = """\

--- YOUR PREVIOUS ATTEMPT ---
{attempt}

--- IT WAS REJECTED ---
{err}

Re-emit the WHOLE object with exactly one thing changed: what the error names. \
Copy every other field through unchanged.

The change the error asks for may be a DELETION, and deleting is allowed — what \
you may not do is invent a fact the analysis does not contain. If the error says \
a key appears in two lists, delete that key's entry from one of them and keep \
the other; leaving it in both is not an option, and the analysis being ambiguous \
about which list it belongs in is not a reason to leave it. If the error says a \
field must be non-null, fill it from the tool log above.\
"""


@dataclass
class Attempt:
    """One sample's outcome: at most one record, plus how it got there."""

    protocol: ProtocolSpecification | None = None
    #: The refusal this sample produced, if the environment upheld one. A
    #: SECOND field rather than a widened `protocol`, so that no caller can read
    #: one as the other and no ordering function can be handed both — see
    #: `_rank`, which must never learn to compare them.
    refusal: NotSpecifiable | None = None
    #: What the model itself declared at the end of call 1, before the
    #: environment ruled on it. Kept even when the environment overrules it,
    #: because "did the model reach for the refusal" and "was the refusal
    #: correct" are two different measurements and only this field carries the
    #: first one.
    claimed_reason: RefusalReason | None = None
    analysis: str = ""
    tool_names: list[str] = field(default_factory=list)
    # pass                       -> a valid protocol
    # refused                    -> a valid refusal the environment upheld
    # missing_calls              -> the log lacks calls the record needed
    # invalid_record             -> transduction never produced a valid protocol
    # invalid_refusal            -> transduction never produced a valid refusal
    # gate_field_mismatch        -> a verdict field contradicted its own tool
    # unearned_refusal           -> refused a pair whose anchors resolve
    # specified_the_unspecifiable-> wrote a protocol for a pair that has none
    gate: str = "unrun"
    error: str | None = None
    seed: int | None = None
    steps: int = 0
    # The log file THIS sample wrote. Carried on the attempt because
    # run/tool_log.jsonl used to be one path truncated per sample, so the only
    # surviving log belonged to the last sample of the last run and no saved
    # record could be audited against the calls that produced it.
    tool_log_path: str | None = None
    #: Transduction attempts spent, and the raw object the last one emitted.
    attempts: int = 0
    rejected: str | None = None

    @property
    def ok(self) -> bool:
        """Whether this sample produced a valid PROTOCOL.

        Deliberately still false for a refusal. Every caller of `ok` — dedup,
        `all_valid`, `_rank`'s input — is asking for records that can be ordered
        against each other, and a refusal cannot be. `refused` is the separate
        question.
        """
        return self.protocol is not None and self.gate == "pass"

    @property
    def refused(self) -> bool:
        """Whether this sample produced a refusal the environment upheld.

        A refusal is an OUTCOME, not a gate failure: `specify` counts it on its
        own line and never in the failure count.
        """
        return self.refusal is not None and self.gate == "refused"


# --------------------------------------------------------------------------- #
# call 1: reason, with tools
# --------------------------------------------------------------------------- #

def _unfence(text: str) -> str:
    """Strip a markdown fence. Needed only on backends without grammar
    enforcement — a constrained decoder cannot emit one.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _reason(backend: Backend, pair, callables, schemas, seed, temperature):
    """Call 1, and the authentic record of what the environment returned.

    Returns the analysis prose, the in-memory ToolLog the gate reads, the step
    count, and the RAW log records. The raw records are separate from ToolLog
    because ToolCall in env/tools.py carries no `result` field — that file
    belongs to another lane — and without the return values there is nothing for
    agent/tool_authority.py to be authoritative with.
    """
    raw: list[dict] = []
    if getattr(backend, "drives_own_tool_loop", False):
        # The CLI/MCP path runs the request -> tool -> response cycle itself. We
        # recover the call log from the file OUR mcp server wrote, so the gate
        # still inspects executed calls rather than anything the model claimed.
        r = backend.reason(SYSTEM, user_prompt(pair), list(callables))
        log = ToolLog()
        raw = backend.read_tool_log()
        for rec in raw:
            log.record(rec["tool"], rec.get("args", {}), rec.get("outcome", "ok"),
                       rec.get("ms", 0.0))
        return r.content, log, len(log.calls), raw

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(pair)}]
    log = ToolLog()
    steps = 0

    for steps in range(1, MAX_STEPS + 1):
        r: Reply = backend.chat(messages, tools=schemas, temperature=temperature,
                                seed=seed, max_tokens=2048)
        if not r.tool_calls:
            return r.content, log, steps, raw

        messages.append({"role": "assistant", "content": r.content or None,
                         "tool_calls": r.tool_calls})
        for tc in r.tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                out = {"outcome": "error", "log": f"arguments were not valid JSON: {exc}"}
                args = {}
            else:
                fn = callables.get(name)
                out = (fn(**args) if fn else
                       {"outcome": "error",
                        "log": f"No tool named {name!r}. Available: {sorted(callables)}"})
            log.record(name, args, out.get("outcome", "ok"), 0.0)
            # Captured here rather than in ToolLog so the in-process loop gives
            # tool_authority the same evidence the MCP server writes to disk:
            # the environment's actual return value, at the function boundary.
            raw.append({"tool": name, "args": args,
                        "outcome": out.get("outcome", "ok"), "ms": 0.0,
                        "result": out})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "name": name, "content": json.dumps(out)[:6000]})

    # Bounded, and the bound is reported rather than silently truncating.
    return ("[tool loop hit MAX_STEPS without a final answer]", log, steps, raw)


# --------------------------------------------------------------------------- #
# the gate: mechanical, no model
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# adjudication: the environment decides, before the model is called
# --------------------------------------------------------------------------- #

#: resolve_variable outcomes that mean the key names something real. `ambiguous`
#: is absent on purpose — env/tools.py calls it a FAILURE in its own log, and a
#: bare qid resolving to 20 variables is not an anchor.
_RESOLVED = frozenset({"unique", "group", "construct"})


class _Anchor(Protocol):
    """The half of a pair the adjudicator reads.

    Structural, so agent/ does not import generate/ to type one attribute.
    """

    construct_key: str
    member_keys: list[str]
    is_free_text: bool
    stem_text: str
    is_group: bool


class PairLike(Protocol):
    """What the Specifier reads from a pair, and nothing more.

    The funnel's `Candidate` satisfies it, and so does
    `pipeline.resolved_pair.ResolvedPair`, which builds the same two anchors
    from a pair of `RetrievalRecord`s. Naming the interface is what lets a
    request-sourced pair reach the Specifier through the same call path as an
    enumerated one, with the prompt byte-identical for the same anchors.
    `pair_id` is read-only because both implementations derive it.
    """

    @property
    def estimability(self) -> str | None:
        """The funnel's or the gate's verdict, rendered into the prompt."""
        ...

    @property
    def requires_derivation(self) -> bool:
        """True when an anchor is a grid battery."""
        ...

    @property
    def exposure(self) -> _Anchor:
        """The exposure anchor. Read-only so a narrower concrete type fits."""
        ...

    @property
    def outcome(self) -> _Anchor:
        """The outcome anchor."""
        ...

    @property
    def pair_id(self) -> str:
        """`<exposure construct key> -> <outcome construct key>`."""
        ...


#: The adjudicator's name for the same interface.
_Pair = PairLike


#: Per required tool, the `outcome` values that mean the call did its job.
#: `resolve_variable` reuses `_RESOLVED` rather than restating it: `ambiguous` is
#: a FAILURE there — `env/tools.py` says so in its own log, and a bare qid
#: resolving to 20 variables is not an anchor — and a second copy of that
#: judgement would drift from the first.
_GATE_SUCCESS: dict[str, frozenset[str]] = {
    "resolve_variable": _RESOLVED,
    "estimate_n": frozenset({"ok"}),
    "check_access": frozenset({"ok"}),
    "estimate_detectability": frozenset({"ok"}),
}

#: Required tools whose arguments cannot name the pair, so the relevance half of
#: the gate does not apply to them. `estimate_detectability(baseline_prevalence,
#: alpha, power)` takes no key at all; demanding one would fail every honest run.
#: Listed rather than inferred from a signature, because a tool that GAINED a key
#: argument should start being checked, and a signature test would start
#: exempting it silently.
_GATE_NO_KEY_ARGS = frozenset({"estimate_detectability"})


def _pair_keys(pair: _Pair) -> frozenset[str]:
    """Every key that names this pair, either side, container or member.

    The same set `_lookup_anchor` walks, for the same reason: a model may
    legitimately reach an anchor through its construct key or through any one of
    its members, and a gate that accepted only one of those would reject the
    other as work on a different pair.

    Args:
        pair: The pair under specification.

    Returns:
        Every key naming either anchor.
    """
    return frozenset(
        k for anchor in (pair.exposure, pair.outcome)
        for k in (anchor.construct_key, *anchor.member_keys))


def _referenced_keys(args: dict) -> frozenset[str]:
    """Every string one call's arguments carry, flattened one level.

    Deliberately shape-agnostic: `resolve_variable` takes `key: str` and both
    `estimate_n` and `check_access` take `keys: list[str]`, and a gate that
    hard-coded those two shapes would silently stop checking a tool whose
    signature changed.

    Args:
        args: The recorded keyword arguments of one call.

    Returns:
        The string values, including strings inside a list or tuple argument.
    """
    out: set[str] = set()
    for value in args.values():
        if isinstance(value, str):
            out.add(value)
        elif isinstance(value, (list, tuple)):
            out.update(v for v in value if isinstance(v, str))
    return frozenset(out)


def _gate(log: ToolLog, pair: _Pair) -> tuple[bool, str]:
    """Did the research log show the work a defensible record requires?

    THREE FAILURES, NOT ONE. Until 2026-09-01 this was a set difference over
    tool NAMES — `REQUIRED_CALLS - log.distinct()` — so a model that called
    `check_access` with malformed arguments, received an error, and then asserted
    an access decision passed. The log already carried what was needed to catch
    that: `env/tools.py::ToolCall` records `outcome` (set to `error` when the
    tool raised) and `args`, and neither was read.

    So a required call now counts only when it BOTH returned a success outcome
    for its own tool AND named a key belonging to this pair. The second half is
    what separates a model that looked up its own anchors from one that looked up
    something else and asserted anyway; `_GATE_NO_KEY_ARGS` exempts the one
    required tool whose arguments carry no key.

    `pair` is required rather than defaulted. A gate whose strictness depends on
    whether a caller passed an optional argument is a guarantee that reads as
    enforced and is not, which is this codebase's recurring defect.

    Args:
        log: The tool log for this sample.
        pair: The pair under specification.

    Returns:
        `(passed, why)`. `why` is empty when it passed, and otherwise names
        every failing tool and which of the three ways it failed.
    """
    pair_keys = _pair_keys(pair)
    never: list[str] = []
    errored: list[str] = []
    elsewhere: list[str] = []

    for name in sorted(REQUIRED_CALLS):
        calls = [c for c in log.calls if c.name == name]
        if not calls:
            never.append(name)
            continue
        succeeded = [c for c in calls if c.outcome in _GATE_SUCCESS[name]]
        if not succeeded:
            errored.append(
                f"{name} (returned {sorted({c.outcome for c in calls})})")
            continue
        if name in _GATE_NO_KEY_ARGS:
            continue
        if not any(_referenced_keys(c.args) & pair_keys for c in succeeded):
            elsewhere.append(name)

    if not (never or errored or elsewhere):
        return True, ""

    parts: list[str] = []
    if never:
        parts.append(f"never called: {sorted(never)}")
    if errored:
        parts.append(f"called but never succeeded: {errored}")
    if elsewhere:
        parts.append(f"succeeded only on other variables: {sorted(elsewhere)}")
    return False, (
        "the research log does not support this record — "
        + "; ".join(parts)
        + ". A record cannot assert an access decision, a sample size or a "
          "detectable effect that was never looked up, that errored when it "
          "was, or that was looked up for a different pair.")



@dataclass(frozen=True)
class Adjudication:
    """The environment's verdict on whether a pair can be specified at all.

    Attributes:
        reason: The reason the environment forces, or None when both anchors
            resolve and a protocol is the only legal output.
        evidence: The lookups that force it, built from the environment's own
            return values rather than transcribed by the model.
        blocked_on: Blockers the environment names, e.g. the artifact that would
            populate an empty registry.
        finding: One line a reader can check the record against.
    """

    reason: RefusalReason | None = None
    evidence: tuple[RefusalEvidence, ...] = ()
    blocked_on: tuple[str, ...] = ()
    finding: str = "both anchors resolve against the instrument"


def _lookup_anchor(resolve: Callable[..., dict],
                   anchor: _Anchor) -> tuple[bool, list[RefusalEvidence], bool]:
    """Ask the environment whether one anchor names anything real.

    Args:
        resolve: The registry's own `resolve_variable`.
        anchor: One side of the pair.

    Returns:
        `(resolves, evidence, is_free_text)`. Evidence is collected only while
        the anchor is still unresolved: a resolving pair produces no refusal, so
        a long member list costs nothing.
    """
    ev: list[RefusalEvidence] = []
    free_text = False
    for key in dict.fromkeys([anchor.construct_key, *anchor.member_keys]):
        out = resolve(key=key)
        outcome = str(out.get("outcome"))
        if outcome in _RESOLVED:
            # is_free_text is only present on a unique resolution; a group or
            # construct hit is a container and carries none.
            free_text = free_text or bool(out.get("is_free_text"))
            return True, [RefusalEvidence(tool="resolve_variable", argument=key,
                                          outcome=outcome)], free_text
        ev.append(RefusalEvidence(tool="resolve_variable", argument=key,
                                  outcome=outcome))
    return False, ev, free_text


def adjudicate(pair: _Pair, callables: dict[str, Callable[..., dict]]) -> Adjudication:
    """Decide, from the environment alone, whether this pair has any protocol.

    MECHANICAL, NEVER BY VOTE, and it runs before call 1. If the exposure does
    not resolve, a protocol naming one is invalid however many of the k samples
    produced it; if it does resolve, a refusal citing `exposure_unresolvable` is
    false however many produced that. The verdict is a function of the pair and
    the built dictionary, so it is identical for every sample and no sample can
    move it.

    Args:
        pair: The enumerated pair, chosen by the funnel and never by the model.
        callables: The registry for this run's mode. `resolve_variable` and
            `registry_coverage` are the environment's own, not a copy.

    Returns:
        The environment's verdict. `reason=None` means a protocol is the only
        legal output for this pair.
    """
    resolve = callables["resolve_variable"]
    coverage = callables["registry_coverage"]

    if pair.exposure.construct_key == pair.outcome.construct_key:
        ev = [RefusalEvidence(tool="resolve_variable",
                              argument=pair.exposure.construct_key,
                              outcome=str(resolve(key=pair.exposure.construct_key)
                                          .get("outcome")))]
        return Adjudication(
            RefusalReason.anchors_are_the_same_construct, tuple(ev), (),
            f"both anchors are {pair.exposure.construct_key}")

    for side, anchor, unresolvable in (
            ("exposure", pair.exposure, RefusalReason.exposure_unresolvable),
            ("outcome", pair.outcome, RefusalReason.outcome_unresolvable)):
        resolves, ev, free_text = _lookup_anchor(resolve, anchor)
        if resolves:
            if free_text or anchor.is_free_text:
                return Adjudication(
                    RefusalReason.free_text_anchor, tuple(ev), (),
                    f"the {side} anchor is free text and carries no coding")
            continue
        registries = coverage().get("registries", {})
        prefix = anchor.construct_key.split(":", 1)[0]
        declared = registries.get(prefix, {})
        blocker = declared.get("blocked_on")
        # `registry_empty` over the bare unresolvable reason, because it is the
        # one that converts into a request: an empty registry is a pending
        # inventory, not a permanent property of the study, and
        # NotSpecifiable._refusal_states_a_remedy makes the blocker mandatory
        # for exactly that reason. Which is also why an empty registry that
        # names NO remedy falls through to the plain reason instead: stamping
        # the literal "None" into blocked_on would fail BlockedOn's enum four
        # transductions in a row, and report an environment inconsistency as a
        # formatting failure by the model.
        if declared.get("coverage") == "none" and blocker:
            return Adjudication(
                RefusalReason.registry_empty,
                (RefusalEvidence(tool="registry_coverage", argument=prefix,
                                 outcome=f"{prefix}: coverage "
                                         f"{declared.get('coverage')}"),
                 *ev),
                (str(blocker),),
                f"the {side} anchor is in the {prefix} registry, "
                f"which is declared and empty")
        return Adjudication(unresolvable, tuple(ev), (),
                            f"the {side} anchor resolves to nothing in any registry")

    return Adjudication()


def claimed_refusal(analysis: str) -> RefusalReason | None:
    """Read the refusal the model declared at the end of call 1, if any.

    Args:
        analysis: The prose from call 1.

    Returns:
        The declared reason, or None. An unrecognised reason name reads as None:
        the sentinel is generated into the prompt from the enum, so a name that
        is not a member is not a reason this system has, and inventing a
        vocabulary is the behaviour the whole path exists to remove.
    """
    if REFUSAL_SENTINEL not in analysis:
        return None
    tail = analysis.rsplit(REFUSAL_SENTINEL, 1)[1]
    word = tail.strip().split()[0].strip(".,`'\"*") if tail.strip() else ""
    try:
        return RefusalReason(word)
    except ValueError:
        return None


def _refusal_gate(log: ToolLog, reason: RefusalReason) -> tuple[bool, str]:
    """The gate a refusal faces. Symmetric with `_gate`, by construction.

    `_gate` asks whether the research log holds the calls any defensible
    protocol requires; this asks whether it holds the calls this particular
    reason requires. Both read the EXECUTED log and neither reads the record —
    which is the split that matters, because a record citing evidence it never
    gathered has fabricated the evidence, and fabricated evidence is a gate
    failure rather than a formatting one. The record's own citations are checked
    separately by `NotSpecifiable._refusal_is_earned`, and both read the same
    declaration in agent/schema.py so they cannot drift apart.

    Args:
        log: The executed call log for this sample.
        reason: The reason the ENVIRONMENT settled on, not the model's claim —
            the environment's is the one that gets stamped into the record.

    Returns:
        `(passed, why)`.
    """
    missing = REFUSAL_EVIDENCE[reason] - log.distinct()
    if missing:
        return False, (f"the research log is missing the calls that earn "
                       f"reason={reason.value}: {sorted(missing)}. A refusal "
                       f"must show the lookups that force it, exactly as a "
                       f"protocol must show the calls that support it.")
    return True, ""


# --------------------------------------------------------------------------- #
# call 2: transduce, constrained
# --------------------------------------------------------------------------- #

#: Tools whose RETURN VALUE the record must transcribe rather than paraphrase,
#: and the fields of it that the record actually copies. Nothing else is
#: expanded: the other tools' values reach the record through the analysis prose
#: or through agent/tool_authority.py, which does not need the model's help.
#:
#: Projected rather than dumped whole. Inlining the full returns of one real
#: 56-call log rendered 28,905 characters beside a 20,201-character schema,
#: almost all of it `log` — a standing instruction repeated once per call, which
#: the model already read in full during call 1. Projecting the copied fields
#: brings the same log to a fraction of that. Showing the model LESS is also the
#: safe direction for contamination; the scan that must read a whole return
#: value is benchmark/contamination_check, not this.
_RESULT_BEARING: dict[str, tuple[str, ...]] = {
    "resolve_variable": ("outcome", "key", "quoted_wording", "stem_text",
                         "subitem_text", "group_key"),
    "get_derivation": ("derivation_id", "unit", "component_keys", "recipe",
                       "fitted_to_outcome"),
}


def _render_log(log: ToolLog, raw_log: list[dict] | None) -> str:
    """Render the research log for the transduction prompt.

    Args:
        log: The in-memory call log, names and arguments only.
        raw_log: The same calls with the environment's return values, when the
            backend captured them.

    Returns:
        One line per call; for the tools whose output the record must quote, the
        return value follows.

    TRANSDUCE has said since it was written that every key, wording and number
    "must already appear in the analysis or the tool log", and then handed over a
    log rendered as `name(args) -> outcome` with the return values stripped. The
    sentence was false about its own prompt. Two live failures came straight out
    of that gap — a paraphrased `quoted_wording` in the record of 2026-08-26, and
    `unit: "scale"` for a signed unit on 2026-08-27 — and both look like the
    model inventing a value when it had no way to read one.
    """
    if not raw_log:
        return "\n".join(f"{c.name}({json.dumps(c.args)[:160]}) -> {c.outcome}"
                         for c in log.calls)
    lines: list[str] = []
    seen: set[str] = set()
    for r in raw_log:
        name = str(r.get("tool"))
        args = json.dumps(r.get("args", {}), sort_keys=True)
        lines.append(f"{name}({args[:160]}) -> {r.get('outcome')}")
        fields = _RESULT_BEARING.get(name)
        result = r.get("result")
        # Once per distinct call. A model that resolves the same key twice gets
        # the wording once; repeating it is the bulk of a long log.
        if not fields or not isinstance(result, dict) or f"{name}{args}" in seen:
            continue
        seen.add(f"{name}{args}")
        shown = {k: result[k] for k in fields
                 if k in result and result[k] is not None}
        lines.append(f"    returned: {json.dumps(shown)[:700]}")
    return "\n".join(lines)


def _emit(backend: Backend, schema: dict, body: str, seed: int | None,
          build: Callable[[dict], Any], fail_kind: str = "invalid_record",
          ) -> tuple[Any, str, str, int, str]:
    """Run one constrained emission with its bounded repair loop.

    Shared by the protocol and the refusal transductions. Extracted rather than
    copied on 2026-08-28: every comment in this loop records a live failure, and
    a second copy of the loop is a second place for those failures to come back
    one at a time.

    Args:
        backend: The reasoning backend.
        schema: The JSON schema the output must match.
        body: The transduction prompt, before any repair.
        seed: Sample seed, where the backend has one.
        build: Turns the parsed object into a validated record, raising on
            anything it will not accept.
        fail_kind: The gate value to report when the whole budget is spent.

    Returns:
        `(record, error, kind, attempts_spent, last_rejected_text)`. `record` is
        None exactly when the budget was spent without a valid one.
    """
    msg = [{"role": "system",
            "content": "You emit JSON matching a schema. Nothing else."},
           {"role": "user", "content": body}]

    cli = getattr(backend, "drives_own_tool_loop", False)
    base = body + ("\n\n--- REQUIRED JSON SCHEMA ---\n"
                   + json.dumps(schema) if cli else "")
    prompt = base

    for attempt in range(MAX_TRANSDUCE_ATTEMPTS):
        if cli:
            r = backend.transduce(prompt)
            r = Reply(content=_unfence(r.content))
        else:
            r = backend.chat(msg, guided_json=schema, temperature=0.0, seed=seed,
                             max_tokens=4096)
        try:
            return build(json.loads(r.content)), "", "pass", attempt + 1, r.content
        except GateMismatch as exc:
            err, kind = str(exc)[:1800], "gate_field_mismatch"
        except (ValidationError, ValueError) as exc:
            err, kind = str(exc)[:1800], fail_kind
        if attempt == MAX_TRANSDUCE_ATTEMPTS - 1:
            # The object that was rejected, kept. Without it a failed live run
            # reports a validator name and nothing to read it against, and
            # diagnosing one costs another paid run.
            return None, err, kind, attempt + 1, r.content
        # THE PREVIOUS ATTEMPT ITSELF, not just the error. Found 2026-08-26 by
        # running the live driver twice: `claude -p` is a fresh session per call,
        # so on this branch the model was handed "your previous attempt was
        # rejected: m1:Q3.3 appears in both adjusted and excluded" with no
        # previous attempt anywhere in its context. It regenerated from the same
        # analysis, reproduced the same key in both lists, and both live runs
        # ended `gate=invalid_record` on the identical error. The in-process
        # branch above never had the bug — it appends the assistant turn to
        # `msg` — which is why the repair loop looked like it worked.
        # REBUILT FROM `base`, NEVER APPENDED TO THE LAST PROMPT. Appending grew
        # the prompt by a whole ~10 kB record per attempt, so by the fourth try
        # the model was reading three superseded drafts and three stale errors
        # ahead of the one it was asked to fix, on top of a 20 kB schema. It has
        # to see exactly one object and exactly one rejection: the current ones.
        prompt = base + _template("REPAIR").render(attempt=r.content,
                                                   err=err)
        msg = [*msg[:2], {"role": "assistant", "content": r.content},
               {"role": "user",
                "content": _template("REPAIR").render(attempt="(above)",
                                                      err=err)}]
    raise AssertionError("unreachable: the loop returns on its last pass")


def _transduce(backend: Backend, analysis: str, log: ToolLog, seed: int | None,
               raw_log: list[dict] | None = None,
               identity: RunIdentity | None = None) -> Attempt:
    """Call 2, then identity, then tool authority, then validation, with repairs.

    The order is deliberate. apply_tool_authority runs on the parsed object
    BEFORE ProtocolSpecification validates it, because a null
    smallest_detectable_effect.value is rejected by `_falsifier_is_detectable`
    and no prompt ever asked the model for that value — filling it afterwards
    would never get the chance. A GateMismatch is a ValueError, so it reaches the
    repair attempt on the same path a schema error does.

    apply_record_identity runs first because it never raises: the record is then
    complete in the fields the driver owns before anything inspects it, and a
    rejection is always about the design rather than about a blank the model was
    never asked to fill.

    Args:
        backend: The reasoning backend.
        analysis: Call 1's prose.
        log: The executed call log, names and arguments.
        seed: Sample seed, where the backend has one.
        raw_log: The same calls with the environment's return values.
        identity: The fields the driver owns, written over the record.

    Returns:
        The attempt, whether or not it produced a valid record.
    """
    def build(filled: dict) -> ProtocolSpecification:
        if identity is not None:
            filled = apply_record_identity(filled, identity)
        return ProtocolSpecification.model_validate(
            apply_tool_authority(filled, raw_log or []))

    schema = ProtocolSpecification.model_json_schema()
    body = _template("TRANSDUCE").render(
        analysis=analysis, toollog=_render_log(log, raw_log))
    rec, err, kind, spent, rejected = _emit(backend, schema, body, seed, build)
    if rec is None:
        return Attempt(analysis=analysis, tool_names=log.names, gate=kind,
                       error=err, seed=seed, attempts=spent, rejected=rejected)
    return Attempt(protocol=rec, analysis=analysis, tool_names=log.names,
                   gate="pass", seed=seed, attempts=spent)


def _transduce_refusal(backend: Backend, analysis: str, log: ToolLog,
                       seed: int | None, pair: _Pair, verdict: Adjudication,
                       raw_log: list[dict] | None = None,
                       identity: RunIdentity | None = None) -> Attempt:
    """Call 2 on the refusal path: the model writes prose, the environment the rest.

    `reason`, `evidence`, `blocked_on`, `pair_id` and `dictionary_version` are
    STAMPED from the adjudication, not transcribed. This is the same rule
    agent/tool_authority.py applies to a protocol's gate fields and for the same
    reason: a refusal whose evidence the model wrote is a refusal whose evidence
    the model could write, and the acceptance test for this path is that the
    cited lookups are the ones that actually ran. What the model supplies is
    `statement` and `what_would_unblock` — the two fields a reader needs and no
    tool can produce.

    Args:
        backend: The reasoning backend.
        analysis: Call 1's prose.
        log: The executed call log.
        seed: Sample seed, where the backend has one.
        pair: The enumerated pair, which owns `pair_id`.
        verdict: The environment's adjudication, stamped over the record.
        raw_log: The same calls with the environment's return values.
        identity: The fields the driver owns.

    Returns:
        The attempt, whether or not it produced a valid refusal.
    """
    def build(filled: dict) -> NotSpecifiable:
        if not isinstance(filled, dict):
            raise ValueError("the refusal must be one JSON object")
        filled = {**filled,
                  "pair_id": pair.pair_id,
                  "reason": verdict.reason.value if verdict.reason else None,
                  "evidence": [e.model_dump() for e in verdict.evidence],
                  "blocked_on": list(verdict.blocked_on)}
        if identity is not None:
            filled["dictionary_version"] = identity.dictionary_version
            prov = filled.get("provenance")
            filled["provenance"] = {
                **(prov if isinstance(prov, dict) else {}),
                "dictionary_version": identity.dictionary_version,
                "module_version": identity.module_version,
                "prompt_hash": identity.prompt_hash,
                "model_id": identity.model_id,
                **({"seed": identity.seed} if identity.seed is not None else {})}
        return NotSpecifiable.model_validate(filled)

    schema = NotSpecifiable.model_json_schema()
    body = _template("TRANSDUCE_REFUSAL").render(
        analysis=analysis, toollog=_render_log(log, raw_log),
        finding=json.dumps({
            "reason": verdict.reason.value if verdict.reason else None,
            "finding": verdict.finding,
            "blocked_on": list(verdict.blocked_on),
            "evidence": [e.model_dump() for e in verdict.evidence]}, indent=1))
    rec, err, kind, spent, rejected = _emit(backend, schema, body, seed, build,
                                            fail_kind="invalid_refusal")
    if rec is None:
        return Attempt(analysis=analysis, tool_names=log.names, gate=kind,
                       error=err, seed=seed, attempts=spent, rejected=rejected)
    return Attempt(refusal=rec, analysis=analysis, tool_names=log.names,
                   gate="refused", seed=seed, attempts=spent)


def specify_once(backend: Backend, pair: PairLike, *, mode="benchmark", seed=0,
                 temperature=0.0, identity: RunIdentity | None = None) -> Attempt:
    """One sample. The unit the k-fan-out repeats.

    Args:
        backend: The reasoning backend.
        pair: The enumerated pair, chosen by the funnel and never by the model.
        mode: Registry mode. No default anywhere it is constructed (§5 rule 4).
        seed: Sample seed, where the backend has one.
        temperature: Sampling temperature, where the backend has one.
        identity: What the driver knows — dictionary version, funnel
            denominator, model id, prompt hash. Written over the record before
            validation. None only on paths that construct their own record.

    Returns:
        The attempt: a protocol, a refusal, or neither, with the gate value that
        says which and why.
    """
    callables, schemas = build_registry(mode)
    # BEFORE call 1, so nothing the model does can move it and every one of the k
    # samples is handed the same verdict. Adjudicating afterwards would
    # adjudicate against a log the model wrote, which is the vote this must not
    # become.
    verdict = adjudicate(pair, callables)
    analysis, log, steps, raw = _reason(backend, pair, callables, schemas, seed,
                                        temperature)
    claimed = claimed_refusal(analysis)
    # Read after _reason, not before: the backend allocates a fresh log path per
    # reasoning call, so asking earlier would name the previous sample's file.
    log_path = getattr(backend, "tool_log", None)
    path = str(log_path) if log_path else None

    def failed(gate: str, why: str) -> Attempt:
        """Build the attempt for an outcome that produced no record.

        Args:
            gate: The gate value naming what went wrong.
            why: The message a reader diagnoses it from.

        Returns:
            The attempt, carrying the analysis and this sample's own log path.
        """
        return Attempt(analysis=analysis, tool_names=log.names, gate=gate,
                       error=why, seed=seed, steps=steps, tool_log_path=path,
                       claimed_reason=claimed)

    if verdict.reason is not None:
        if claimed is None:
            # Enforced rather than described: a protocol for a pair the
            # environment has ruled unspecifiable is invalid however many
            # samples produced one, so it never reaches transduction and never
            # reaches _rank.
            return failed("specified_the_unspecifiable",
                          f"the environment ruled this pair not specifiable "
                          f"({verdict.reason.value}: {verdict.finding}), and "
                          f"this sample did not refuse. Any protocol for it "
                          f"names an anchor that resolves nowhere.")
        passed, why = _refusal_gate(log, verdict.reason)
        if not passed:
            return failed("missing_calls", why)
        a = _transduce_refusal(backend, analysis, log, seed, pair, verdict, raw,
                               replace(identity, seed=seed) if identity else None)
    else:
        if claimed is not None:
            # The escape hatch, closed. Refusing is strictly easier than the
            # work, so it stands only where the environment forces it.
            return failed("unearned_refusal",
                          f"this sample declared {claimed.value}, but the "
                          f"environment finds that {verdict.finding}. A refusal "
                          f"the environment contradicts is discarded exactly as "
                          f"a fabricated key is.")
        passed, why = _gate(log, pair)
        if not passed:
            return failed("missing_calls", why)
        # The seed belongs to THIS sample, so it is stamped here rather than by
        # the caller: a provenance block that recorded the same seed for every
        # sample of a k-fan-out could not identify which sample it came from.
        a = _transduce(backend, analysis, log, seed, raw,
                       replace(identity, seed=seed) if identity else None)
    a.steps = steps
    a.tool_log_path = path
    a.claimed_reason = claimed
    return a


# --------------------------------------------------------------------------- #
# k samples, dedup, deterministic selection
# --------------------------------------------------------------------------- #

@dataclass
class Result:
    """The outcome of k samples on one pair.

    `selected` and `refusal` are two fields and not one, and that is the whole
    answer to "what does selected hold when the refusals were right": None. A
    refusal is not a protocol that won. Widening `selected` would push the
    discrimination onto every caller — `res.selected.protocol_id` is written in
    two drivers — and the only other way to fill it would be an ordering that
    compares a refusal against a protocol, which `_rank` may never learn.

    Attributes:
        selected: The winning protocol, or None. None whenever the environment
            ruled the pair unspecifiable, whatever the samples produced.
        parked: The other distinct valid protocols, in rank order.
        attempts: Every sample, valid or not.
        reason: The yield line and how selection went.
        refusal: The refusal the environment upheld, or None. All k refusals of
            one pair carry the same evidence, because the environment wrote it,
            so they dedup to one record by construction.
    """

    selected: ProtocolSpecification | None
    parked: list[ProtocolSpecification]
    attempts: list[Attempt]
    reason: str
    refusal: NotSpecifiable | None = None

    @property
    def distinct(self) -> int:
        """How many distinct valid protocols the k samples produced."""
        return len({p.record_hash() for p in self.all_valid})

    @property
    def all_valid(self) -> list[ProtocolSpecification]:
        """Every sample's valid protocol, duplicates included."""
        return [a.protocol for a in self.attempts if a.ok]

    @property
    def counts(self) -> tuple[int, int, int]:
        """Specified, refused and failed, in that order.

        A refusal is subtracted from the failure count rather than added to it.
        Counting one as a failure is what made "valid protocol or nothing" look
        like a yield problem instead of an output-space problem.
        """
        specified = sum(1 for a in self.attempts if a.ok)
        refused = sum(1 for a in self.attempts if a.refused)
        return specified, refused, len(self.attempts) - specified - refused

    @property
    def yield_line(self) -> str:
        """The yield, with refusals on their own line and not among the failures."""
        specified, refused, failed = self.counts
        return f"{specified} specified, {refused} refused, {failed} failed"


def _rank(p: ProtocolSpecification) -> tuple:
    """Selection order. Every term is a property of the RECORD.

    No term is a model score, a self-rating or a judge verdict: a model ranking
    its own outputs on soundness has no measured skill at it, and a same-family
    judge inflates the scores of models that share its mistakes. What orders these
    is whether the access gate passed, whether the design is estimable, and how
    much of the record is asserted rather than deferred.
    """
    from agent.schema import GateDecision, NSource
    return (
        0 if p.access.decision is GateDecision.pass_ else 1,
        0 if p.estimability.n_source is not NSource.unknown else 1,
        len(p.blocked_on),
        0 if p.status is Status.ready_for_review else 1,
        -(len(p.adjusted_covariates) + len(p.excluded_variables)),
        p.record_hash(),                      # total order, so ties are stable
    )


def _disclosure(p: ProtocolSpecification) -> int:
    """How much a record discloses that its `record_hash` cannot see.

    A pure function of the record, like every term of `_rank`, and used for the
    same reason: nothing the model says about its own output may order it.

    Args:
        p: A valid protocol.

    Returns:
        The number of sought-but-unresolved covariates recorded.
    """
    return len(p.sought_covariates)


def specify(backend: Backend, pair: PairLike, *, k: int = 5, mode: str = "benchmark",
            temperature: float = 0.7, parked_dir: Path | None = None,
            identity: RunIdentity | None = None) -> Result:
    """K samples of one pair. Deterministic everywhere except the sampling itself.

    Sampling is the only stochastic element and it is bounded: k fixed in code,
    seeds fixed in code, dedup by typed-record set equality rather than by string,
    so two records that differ only in covariate ORDER collapse to one. Selection
    reads the records, never the model.

    A mixed k is settled by the environment and never by the majority. The
    adjudication is a function of the pair, so it is the same for every sample:
    either no protocol here is valid, or no refusal here is. There is no case
    where both a protocol and a refusal survive and something has to choose
    between them, which is why `_rank` is never handed one of each.

    Args:
        backend: The reasoning backend.
        pair: The enumerated pair, chosen by the funnel and never by the model.
        k: Sample count, fixed by the caller and never by the model.
        mode: Registry mode.
        temperature: Sampling temperature, where the backend has one.
        parked_dir: Where the losing distinct protocols are written.
        identity: The fields the driver owns.

    Returns:
        The result, carrying at most one of a selected protocol and a refusal.
    """
    attempts = [specify_once(backend, pair, mode=mode, seed=s,
                             temperature=(0.0 if k == 1 else temperature),
                             identity=identity)
                for s in range(k)]

    refusals: dict[str, NotSpecifiable] = {}
    for a in attempts:
        if a.refused and a.refusal is not None:
            refusals.setdefault(a.refusal.record_hash(), a.refusal)
    if refusals:
        # Ordered by record_hash — a total order over a pure function of the
        # record, the same tie-breaker _rank ends on. It is very nearly moot:
        # pair_id, reason, dictionary_version and evidence are all stamped by
        # the environment, so k refusals of one pair hash identically and the
        # first sample's prose is the one that survives dedup.
        chosen = refusals[min(refusals)]
        res = Result(None, [], attempts, "", refusal=chosen)
        res.reason = (f"{res.yield_line}; the environment ruled this pair not "
                      f"specifiable ({chosen.reason.value}), so no protocol for "
                      f"it is valid and none was selected")
        return res

    # NOT `setdefault`. `sought_covariates` is outside `canonical_form` on
    # purpose (see schema::ProtocolSpecification.canonical_form), so a sample
    # that records a covariate gap and a sample that stays silent about the same
    # design hash IDENTICALLY. Under `setdefault` the first seed to arrive won
    # and the other was dropped before `ordered` was ever built — and `parked` is
    # `ordered[1:]`, over DISTINCT hashes, so the loser was not parked either. If
    # seed 0 was silent, the disclosing sample vanished from the run entirely,
    # recreating the exact silence C24 exists to end: 20 of 21 saved protocols
    # record no covariate gap. The tie-break is a pure function of the record.
    by_hash: dict[str, ProtocolSpecification] = {}
    for a in attempts:
        prot = a.protocol
        if not a.ok or prot is None:
            continue
        h = prot.record_hash()
        held = by_hash.get(h)
        if held is None or _disclosure(prot) > _disclosure(held):
            by_hash[h] = prot

    if not by_hash:
        why = "; ".join(sorted({f"{a.gate}" for a in attempts}))
        r = Result(None, [], attempts, "")
        r.reason = (f"{r.yield_line}; no sample produced a valid record ({why})")
        return r

    ordered = sorted(by_hash.values(), key=_rank)
    winner, parked = ordered[0], ordered[1:]

    if parked_dir:
        parked_dir.mkdir(parents=True, exist_ok=True)
        for p in parked:
            (parked_dir / f"{p.protocol_id}.{p.record_hash()}.json").write_text(
                p.model_dump_json(indent=2))

    res = Result(winner, parked, attempts, "")
    res.reason = (f"{res.yield_line}; {len(by_hash)} distinct of "
                  f"{sum(a.ok for a in attempts)} valid ({k} sampled); "
                  f"selected by gate status then estimability")
    return res
