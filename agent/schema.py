"""agent/schema.py — the protocol record. Authoritative artifact.

Everything else is generated from these models: JSON Schema via
`ProtocolSpecification.model_json_schema()`, the guided-decoding grammar via the
serving backend's converter, diagrams as a doc build. Do not hand-maintain a
second copy of this shape anywhere.

Two enforcement layers, never to be confused:

    guided decoding (guided_json / GBNF)   shape, required, enum, const
    pydantic validator                     everything else, including every
                                           length floor and every comparison
                                           between two instance values

A grammar-level minLength cannot be violated, so it manufactures padding instead
of measuring it. Length floors therefore live here as validators with a
reject-and-regenerate path and a logged rejection rate. They are named
`min_length` because that is all they are: a floor against empty strings.

FIELD ORDER IS LOAD-BEARING. Pydantic emits JSON Schema properties in declaration
order, and the decoding grammar follows that order. Under a constrained grammar a
model must emit fields in the order given, so any field whose value is a verdict
is declared AFTER the fields that justify it. Put `role` before `mechanism` and
the grammar forces the model to commit to a causal role before it has written the
reasoning that would justify one. Do not reorder these classes casually.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- #
# namespace
# --------------------------------------------------------------------------- #

REGISTRY_PREFIXES = ("m1", "m2", "m3", "clinical", "lab", "linked", "ehr")

#: A variable key. Five registries; the survey ones are populated from the three
#: codebooks, the other four ship declared-but-empty so that a protocol naming
#: `linked:pm25_annual` fails resolution loudly with a named blocker rather than
#: being unrepresentable. `~N` disambiguates the one qid that repeats inside a
#: module (m2:Q785). A grid stem lives in the `group:` namespace and can never
#: appear here.
_WORDING_CACHE: dict[str, str] | None = None


def _norm(t: str) -> str:
    """Collapse whitespace. The codebooks carry hard newlines inside quoted
    fields, so newline-versus-space is a format difference, not a paraphrase.
    """
    return " ".join((t or "").split())


def _norm_construct(t: str) -> str:
    """Normalise a construct name for equality, punctuation included.

    Separate from `_norm` on purpose: `_norm` backs `_wording_is_verbatim`, which
    diffs a quoted item against the instrument, and there a dropped comma IS a
    difference. Here the comparison is between two things the model wrote, and
    the only question is whether they name the same construct.

    Args:
        t: A construct name as the model wrote it.

    Returns:
        The name casefolded, stripped of punctuation, with whitespace collapsed.
    """
    return _norm(re.sub(r"[^\w\s]", " ", t or "")).casefold()


def _dictionary_wording() -> dict[str, str]:
    global _WORDING_CACHE
    if _WORDING_CACHE is None:
        import json as _json
        from pathlib import Path as _Path
        p = _Path(__file__).resolve().parent.parent / "build" / "dictionary.json"
        _WORDING_CACHE = ({e["key"]: e["question_text"]
                           for e in _json.loads(p.read_text())["entries"]}
                          if p.exists() else {})
    return _WORDING_CACHE


_DERIVATION_CACHE: dict[str, dict] | None = None


def _signed_derivations() -> dict[str, dict]:
    """Load every signed derivation file, once.

    Returns:
        Mapping of derivation_id to the signed object. Empty when
        `curated/derivations/` is absent, which is the same degradation
        `_dictionary_wording` takes when there is no build.
    """
    global _DERIVATION_CACHE
    if _DERIVATION_CACHE is None:
        import json as _json
        from pathlib import Path as _Path
        d = _Path(__file__).resolve().parent.parent / "curated" / "derivations"
        _DERIVATION_CACHE = {
            f.stem: _json.loads(f.read_text()) for f in sorted(d.glob("*.json"))
        } if d.is_dir() else {}
    return _DERIVATION_CACHE


KEY_PATTERN = r"^(?:m[123]|clinical|lab|linked|ehr):[A-Za-z0-9._#-]+(?:~\d+)?$"
VariableKey = Annotated[str, Field(pattern=KEY_PATTERN)]

MIN_JUSTIFICATION = 25
MIN_MECHANISM = 20
#: Floors for the sought-but-unresolved covariate record. Same idiom and same
#: reason as the two above: a grammar-level minLength manufactures padding
#: instead of measuring it, so the floor lives in a validator with a
#: reject-and-regenerate path. `MIN_SEARCH_PHRASE` is deliberately tiny — real
#: search phrases are short — and exists only to stop a list of `[""]` or `["x"]`
#: satisfying `min_length=1` on the list itself.
MIN_CONSTRUCT = 12
MIN_SEARCH_PHRASE = 2
MIN_REJECTION = 25
MIN_BIAS_STATEMENT = 25


class Registry(str, Enum):
    survey_m1 = "m1"
    survey_m2 = "m2"
    survey_m3 = "m3"
    clinical = "clinical"
    lab = "lab"
    linked = "linked"
    ehr = "ehr"


# --------------------------------------------------------------------------- #
# references — a tagged union, never a bare VariableRef
# --------------------------------------------------------------------------- #

class VariableRef(BaseModel):
    """A single instrument variable, resolved by set membership in a registry.

    `quoted_wording` is verbatim dictionary text. At the grammar layer it is
    emitted as an enum keyed off `key`, which makes fabrication structurally
    impossible rather than detectable after the fact. The validator here is the
    fallback for ungrammared generation.

    The honest limit, stated so it is not mistaken for verification: comparing
    wording to the dictionary catches INVENTED quotes only. It cannot catch a
    correct quote attached to the wrong identifier — a verbatim paste scores
    perfectly while a correct plain-language construct label scores near zero, so
    it rewards pasting and punishes thinking. It is named
    `quote_fabrication_check` for that reason and never gates on similarity.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["variable"] = "variable"
    key: VariableKey
    quoted_wording: str = Field(description="verbatim dictionary text for `key`")

    @property
    def registry(self) -> str:
        return self.key.split(":", 1)[0]


class DerivationRef(BaseModel):
    """A combined variable. Inline recipes are forbidden.

    A derivation is a reviewable, signed, versioned object in
    curated/derivations/, and validate_protocol fails if the file is missing — so
    a recipe cannot be invented mid-protocol. This matters because there is no
    single "physical activity" item: there are 30 (m3:Q2.33-Q2.62), and hundreds
    of defensible ways to combine them. Search 200 recipes, keep the strongest
    association, and you find one whether or not it exists.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["derivation"] = "derivation"
    derivation_id: str = Field(description="filename stem in curated/derivations/")
    unit: str
    component_keys: list[VariableKey] = Field(min_length=1)

    @model_validator(mode="after")
    def _matches_the_signature_it_names(self) -> DerivationRef:
        """`component_keys` and `unit` must be the signed file's, not restated.

        Returns:
            The validated reference.

        Raises:
            ValueError: If no signed file of that id exists, or if either field
                differs from it.
        """
        # Nothing tied a reference to the file it named. The one live record's
        # excluded exposure carried 30 component_keys and the unit "MET-hours per
        # week" against a signed file declaring 2 keys and "MET-hours/week", and
        # its exposure restated a unit the signed file words differently — so
        # both anchors were inline recipes wearing a reference's clothes. §5 rule
        # 5's sibling: a derivation that does not match its signature is a recipe
        # invented mid-protocol, which is the one thing this class forbids.
        #
        # Three docstrings and two tool return values have said since they were
        # written that "validate_protocol fails if the file is missing". There
        # was no validate_protocol and no such check anywhere. It fails here now.
        signed = _signed_derivations()
        if not signed:
            # No curated/ in this tree; the same degradation _dictionary_wording
            # takes when there is no build.
            return self
        got = signed.get(self.derivation_id)
        if got is None:
            raise ValueError(
                f"no signed derivation {self.derivation_id!r} exists. Call "
                f"list_derivations and name one of {sorted(signed)}, or set a "
                f"blocker — a recipe cannot be invented mid-protocol.")
        want_keys, want_unit = list(got.get("component_keys", [])), got.get("unit")
        if set(self.component_keys) != set(want_keys):
            raise ValueError(
                f"derivation {self.derivation_id!r} declares component_keys "
                f"{want_keys}; this reference names {sorted(self.component_keys)}. "
                f"A reference restates the signed file, it does not redefine it. "
                f"Call get_derivation({self.derivation_id!r}) and copy the list.")
        # Unit exactly, not approximately: the falsifier threshold is compared to
        # the smallest detectable effect only when the two units are equal
        # strings, so a paraphrased unit silently switches that check off.
        if want_unit is not None and self.unit != want_unit:
            raise ValueError(
                f"derivation {self.derivation_id!r} declares unit {want_unit!r}; "
                f"this reference says {self.unit!r}. Copy the signed unit "
                f"verbatim.")
        return self


class AreaMeasureRef(BaseModel):
    """A linked place-based measure attached to a participant's area.

    CONTAMINATION NOTE — do not restore the earlier docstring. Pydantic copies
    class docstrings into `description` fields of model_json_schema(), and that
    schema (17,922 chars) is pasted verbatim into the transduction prompt. The
    previous text named specific pollutant exposures and "the eight benchmark
    papers", so every transduce call was telling the model both what the
    benchmark contains and which exposures the cohort's own published work
    used. Keep docstrings in this module free of study designs, exposures,
    outcomes and paper counts: anything written here is prompt text.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["area_measure"] = "area_measure"
    measure_id: str
    source: str
    grain: str = Field(description="tract, ZIP, community area, point")
    entity: str = Field(description="residence, workplace, school")
    years: str | None = None


Ref = Annotated[VariableRef | DerivationRef | AreaMeasureRef,
                Field(discriminator="kind")]


# --------------------------------------------------------------------------- #
# causal roles
# --------------------------------------------------------------------------- #

class CausalRole(str, Enum):
    """One shared vocabulary across all three covariate lists.

    `collider` is deliberately absent. Asserting it requires naming two parent
    constructs, one an ancestor of the exposure and one of the outcome, with
    evidence — an escalation, never a default. And no exclusion decision needs
    it: a true M-bias collider is neither a cause nor an effect of either anchor,
    so it lands in `not_a_cause_of_either` and is correctly excluded on evidence
    we actually have.

    `exposure` and `outcome` are also absent. They are positions in the design,
    not roles.
    """

    # -> adjusted
    confounder = "confounder"
    cause_of_exposure_only = "cause_of_exposure_only"
    precision = "precision"
    proxy = "proxy"
    # -> excluded
    mediator = "mediator"
    descendant_of_exposure = "descendant_of_exposure"
    descendant_of_outcome = "descendant_of_outcome"
    not_a_cause_of_either = "not_a_cause_of_either"
    # -> undetermined
    confounder_or_mediator = "confounder_or_mediator"
    unadjudicated = "unadjudicated"
    unreliable_coding = "unreliable_coding"


ADJUSTED_ROLES = {CausalRole.confounder, CausalRole.cause_of_exposure_only,
                  CausalRole.precision, CausalRole.proxy}
EXCLUDED_ROLES = {CausalRole.mediator, CausalRole.descendant_of_exposure,
                  CausalRole.descendant_of_outcome, CausalRole.not_a_cause_of_either}
UNDETERMINED_ROLES = {CausalRole.confounder_or_mediator, CausalRole.unadjudicated,
                      CausalRole.unreliable_coding}


class CausalAdjustment(BaseModel):
    """One covariate decision.

    Declaration order is the point: `mechanism` and `justification` are emitted
    BEFORE `role`, so a constrained grammar cannot let the model commit to a
    causal role before writing the reasoning for it.

    `mechanism` is one sentence naming intermediate constructs if the path is
    indirect. It is required, and a role asserted without one is coerced to
    `unadjudicated` rather than accepted — that coercion is the calibration guard
    that stops ancestor-level permissiveness collapsing into "adjust for
    everything".
    """

    model_config = ConfigDict(extra="forbid")

    variable: Ref
    mechanism: str = Field(description="one sentence; name intermediate constructs "
                                       "if the path is indirect")
    justification: str
    role: CausalRole
    proxy_for: str | None = Field(
        default=None,
        description="required when role is proxy; a short prose statement of the "
                    "thing being proxied. Race as a proxy for structural exposure "
                    "is a real case no type can express, and the claim belongs in "
                    "a field a reviewer can contest.")
    contestable: bool = Field(
        default=False,
        description="mark exclusions a reasonable methodologist would dispute")

    @model_validator(mode="after")
    def _floors_and_role_coherence(self) -> CausalAdjustment:
        if len(self.justification.strip()) < MIN_JUSTIFICATION:
            raise ValueError(
                f"justification below min_length ({MIN_JUSTIFICATION}); "
                "regenerate rather than pad")
        if len(self.mechanism.strip()) < MIN_MECHANISM:
            raise ValueError(
                f"mechanism below min_length ({MIN_MECHANISM}); a role asserted "
                "without a mechanism must be recorded as unadjudicated instead")
        if self.role is CausalRole.proxy and not (self.proxy_for or "").strip():
            raise ValueError("role=proxy requires proxy_for")
        if self.role is not CausalRole.proxy and self.proxy_for:
            raise ValueError("proxy_for is only meaningful when role=proxy")
        return self


# --------------------------------------------------------------------------- #
# the covariate that has no key
#
# WHY THIS IS A SEPARATE MODEL AND NOT A FOURTH `Ref`. Every member of `Ref`
# carries a resolvable identifier, and `_ref_key`, `_all_variable_refs`,
# `_no_covariate_repeats_an_anchor`, `_no_covariate_named_twice`,
# `canonical_form` and tool_authority::design_keys all assume a Ref yields one.
# A keyless Ref would produce empty-string keys in every one of them, silently:
# two unrelated gaps would collide in `_no_covariate_named_twice`, and
# `canonical_form` would dedup on "". So the gap gets its own shape, off the Ref
# path entirely.
#
# WHY IT EXISTS AT ALL. Measured on this repo 2026-08-31 over `run/*.json` plus
# `run/superseded/*.json`, excluding `mcp_config.json`: 21 saved records carry
# `adjusted_covariates`, and exactly ONE names a covariate whose wording is about
# the respondent's own age. It is in `run/superseded/`. In the other twenty the
# construct is absent and NOTHING IN THE RECORD SAYS SO — an omission and a
# considered rejection are indistinguishable, which is the same argument
# `excluded_variables` already makes for variables that do have keys. In at least
# one run the model searched, was returned an item measuring the construct for
# somebody other than the respondent, correctly refused it, and then had nowhere
# legal to write that down: `CausalAdjustment` requires a `Ref`, and it is
# `extra="forbid"`.
#
# DECLARATION ORDER, for the same reason `CausalAdjustment` puts `mechanism`
# before `role`: under a constrained grammar the model emits fields in the order
# given, so what was sought and what was tried are both on the page before the
# consequence is stated. Kept as a comment and out of the docstring because
# model_json_schema() copies docstrings into the transduction prompt, and this
# paragraph is for the next maintainer, not for the model.
#
# NOT CHECKED AGAINST THE TOOL LOG, DELIBERATELY. `search_phrases` says what the
# model searched with, and nothing here verifies it against the run's own log.
# Coupling the two was assessed and rejected: a repaired record legitimately
# carries values its log never returned, so the gate would reject honest records
# to catch a dishonesty nobody has observed. The guarantee this model makes is
# that the gap is EXPRESSIBLE and RECORDED, never that it was earned.
# --------------------------------------------------------------------------- #

class UnresolvedCovariate(BaseModel):
    """A construct that was looked for and could not be bound to any key."""

    model_config = ConfigDict(extra="forbid")

    construct_sought: str = Field(
        description="the covariate construct you looked for, in plain words. "
                    "Not a variable key — a construct that HAS a key belongs in "
                    "one of the three covariate lists instead of here")
    search_phrases: list[str] = Field(
        min_length=1,
        description="the phrases you actually searched with, as you sent them")
    why_rejected: str = Field(
        description="what came back and why it does not measure the construct. "
                    "Name the keys you looked at and turned down; 'nothing came "
                    "back' is also an answer")
    exposes_the_estimate_to: str = Field(
        description="what the estimate is exposed to with this construct absent "
                    "from the model")

    @model_validator(mode="after")
    def _floors_and_no_key_where_there_is_no_key(self) -> UnresolvedCovariate:
        # EVERY PROBLEM IN ONE MESSAGE, not the first one found. Transduction
        # allows exactly ONE repair, and this model has three new prose fields
        # each with its own floor -- so an entry that undershoots two of them
        # would spend the repair on the first, be told nothing about the second,
        # and die on the regenerated record. That is likeliest on the model's
        # FIRST use of the field, which is the case the whole change exists to
        # get right. Aggregating costs nothing: none of these checks depends on
        # another passing.
        problems: list[str] = []
        for text, floor, field in ((self.construct_sought, MIN_CONSTRUCT,
                                    "construct_sought"),
                                   (self.why_rejected, MIN_REJECTION,
                                    "why_rejected"),
                                   (self.exposes_the_estimate_to,
                                    MIN_BIAS_STATEMENT,
                                    "exposes_the_estimate_to")):
            if len(text.strip()) < floor:
                problems.append(
                    f"{field} below min_length ({floor}); regenerate rather "
                    f"than pad. A gap stated in a token records nothing a "
                    f"reader could act on.")
        for i, phrase in enumerate(self.search_phrases):
            if len(phrase.strip()) < MIN_SEARCH_PHRASE:
                problems.append(
                    f"search_phrases[{i}] is empty or a single character. List "
                    f"the phrases you searched with, or if you never searched, "
                    f"search before recording the construct as unfindable.")
        # THE FIELD IS FOR CONSTRUCTS WITH NO KEY. A key in `construct_sought`
        # means the thing resolved, and a resolved covariate belongs in one of
        # the three lists, where its role is adjudicated and its keys reach the
        # tools. Only `construct_sought` is checked: `why_rejected` NAMES the
        # keys it turned down, which is the honest half of the record and has to
        # stay legal.
        found = _KEY_TOKEN_IN_FREE_PROSE.search(self.construct_sought)
        if found:
            problems.append(
                f"construct_sought names the variable key {found.group(0)!r}, "
                f"so it resolved. sought_covariates is only for constructs "
                f"that bind "
                f"to no key at all. Move this to adjusted_covariates, "
                f"excluded_variables or undetermined_covariates and give it a "
                f"role; name rejected keys in why_rejected instead.")
        if problems:
            raise ValueError(
                " ".join(f"({i}) {t}" for i, t in enumerate(problems, 1))
                + " Fix every item listed above in ONE edit; there is no second "
                  "repair after this.")
        return self


# --------------------------------------------------------------------------- #
# design blocks
# --------------------------------------------------------------------------- #

class Direction(str, Enum):
    increase = "increase"
    decrease = "decrease"
    no_difference = "no_difference"
    non_monotonic = "non_monotonic"


class ExpectedDirection(BaseModel):
    """Direction is theory-derived and fabrication-free; magnitude is not. They
    do not share a field, and a magnitude without a source is refused.
    """

    model_config = ConfigDict(extra="forbid")

    direction: Direction
    magnitude: str | None = None
    magnitude_source: str | None = None

    @model_validator(mode="after")
    def _magnitude_needs_source(self) -> ExpectedDirection:
        if self.magnitude and not self.magnitude_source:
            raise ValueError("magnitude requires magnitude_source — an unsourced "
                             "effect size is the 'unsupported specificity' failure")
        return self


class Comparator(str, Enum):
    gte = ">="
    gt = ">"
    lte = "<="
    lt = "<"


class FalsifierThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    unit: str
    comparator: Comparator


class NSource(str, Enum):
    computed_from_counts = "computed_from_counts"
    synthetic_cohort = "synthetic_cohort"
    published_paper = "published_paper"
    unknown = "unknown"


class SdePoint(BaseModel):
    """One evaluated point of a detectability curve.

    Args:
        n: The candidate sample size the formula was evaluated at.
        sde_percentage_points: The smallest detectable effect there.
    """

    model_config = ConfigDict(extra="forbid")

    n: int
    sde_percentage_points: float


class SmallestDetectableEffect(BaseModel):
    """Structured so the falsifier comparison is actually computable.

    estimate_detectability returns a curve, not a scalar — smallest detectable
    effect at a set of candidate n values, with the assumption set recorded. That
    is what lets this field stay honest while n is unknown, and the record
    therefore carries the whole curve rather than one point off it. Collapsing an
    unknown-n design to a single floor forces a choice no one can defend: the
    lowest candidate makes every falsifier absurdly large, the highest makes the
    check vacuous, and both assert a sample size in a system whose first rule
    about sample sizes is never to invent one.

    `at_n` is the point this design commits to being falsifiable at. It is a
    disclosure, not a comparator the model may pick freely: it must be a point on
    `curve`, the whole curve sits beside it, and while the analytic n is unknown
    the record cannot leave draft.

    TWO CURVES, AND ONLY ONE OF THEM IS THE COMPARATOR. `curve` is computed under
    an outcome frequency the caller of estimate_detectability supplied, and this
    environment holds no data that could confirm or refute it. Because the
    detectable effect shrinks as that frequency moves away from the value that
    maximises it, a caller who understates it lowers the bar it is then judged
    against — the same "choose your own floor" hole that `at_n` and the candidate
    n grid were each closed for. `worst_case_curve` is the same formula at the
    frequency that MAXIMISES the detectable effect, which no caller can
    influence, so it is what the falsifier is checked against. `curve` stays in
    the record because it is the disclosed reasoning a reviewer needs to see; it
    is evidence, not a yardstick.
    """

    model_config = ConfigDict(extra="forbid")

    curve: list[SdePoint] = Field(
        default_factory=list,
        description="written from the tool's own return value, never by you")
    worst_case_curve: list[SdePoint] = Field(
        default_factory=list,
        description="the caller-independent bound your falsifier is actually "
                    "checked against, written from the tool's own return value, "
                    "never by you")
    asserted_baseline_prevalence: float | None = Field(
        default=None,
        description="ASSERTED, NOT MEASURED. The reference-arm outcome frequency "
                    "`curve` was computed under, recorded as the assumption it "
                    "is. No tool in this environment returns this quantity, so "
                    "nothing here can confirm it; a record that carries it must "
                    "name the matching blocker and cannot leave draft. Written "
                    "from the tool's own return value, never by you")
    value: float | None = None
    unit: str | None = None
    at_n: int | None = Field(
        default=None,
        description="the candidate n on `curve` at which you claim the falsifier "
                    "is detectable. Naming a larger one is a larger claim about "
                    "what this study must reach, not a looser test")
    assumptions: str


class Estimability(BaseModel):
    """A fabricated n is worse than an admitted gap.

    Cross-module pairs are the normal case here — diagnoses live in module 2 and
    behaviours in module 3 — and the co-completion counts do not exist, so
    `unknown` is the expected value on day one, not a defect.
    """

    model_config = ConfigDict(extra="forbid")

    analytic_n: int | None = None
    n_source: NSource
    modules_required: list[str] = Field(default_factory=list)
    exposure_contrast: str = Field(
        description="a stated design contrast from a convention document, e.g. "
                    "'per 5 MET-hours/week' or 'highest vs lowest Likert category'")
    collinearity_max: float | None = Field(
        default=None,
        description="null until per-item non-missing counts arrive; there is no "
                    "synthetic cohort to parameterise, and any number one "
                    "produced would be fabrication wearing a tool's credibility")
    smallest_detectable_effect: SmallestDetectableEffect

    @model_validator(mode="after")
    def _n_and_source_agree(self) -> Estimability:
        if self.analytic_n is not None and self.n_source is NSource.unknown:
            raise ValueError("analytic_n present but n_source=unknown")
        if self.analytic_n is None and self.n_source is not NSource.unknown:
            raise ValueError(f"n_source={self.n_source.value} but analytic_n is null")
        return self


class UnitOfAnalysis(str, Enum):
    participant = "participant"
    visit = "visit"
    participant_year = "participant-year"


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form: str
    unit_of_analysis: UnitOfAnalysis
    clustering: str


class GateDecision(str, Enum):
    pass_ = "pass"
    refer = "refer"
    fail = "fail"


class Access(BaseModel):
    """Returns its working, not just a verdict.

    Location precision is grouped by the place being located, the finest
    precision taken per place, then summed across places — because
    residence-tract plus residence-ZIP narrows to one area while residence-tract
    plus workplace-ZIP narrows to an area AND a building, and additive scoring
    calls those equal.

    Deliberately excluded variables must still resolve and have their wording
    checked, but consume no budget: penalising a protocol for stating its
    exclusions punishes the behaviour the schema exists to encourage.
    """

    model_config = ConfigDict(extra="forbid")

    decision: GateDecision
    reconstruction_load: int = Field(ge=0)
    budget: int = Field(ge=0, description="named config value, never a literal")
    location_bearing_keys: list[VariableKey] = Field(default_factory=list)
    per_place_working: str
    origin_unknown_keys: list[VariableKey] = Field(
        default_factory=list,
        description="origin_unknown is a distinct state, never a default — a "
                    "missing build step once made every variable read as "
                    "unknown-provenance and the gate referred everything: "
                    "correct-looking behaviour, wrong reason, no error")


class SelectionMode(str, Enum):
    enumerated_screen = "enumerated_screen"
    externally_posed = "externally_posed"
    hand_specified = "hand_specified"


class SelectionRationale(BaseModel):
    """Both `screened_from` and `selection_mode` are written by the wrapper from
    the funnel counter, never by the model — which has every incentive to keep
    the denominator small. Selection from a screened space is part of any
    eventual inference, and disclosure is what makes agnostic screening sound
    rather than suspect.
    """

    model_config = ConfigDict(extra="forbid")

    selection_mode: SelectionMode
    screened_from: int | None = None
    prior_work: str
    why_this_cohort: str

    @model_validator(mode="after")
    def _denominator_required_when_enumerated(self) -> SelectionRationale:
        if self.selection_mode is SelectionMode.enumerated_screen and self.screened_from is None:
            raise ValueError("screened_from is required when selection_mode="
                             "enumerated_screen")
        return self


class Provenance(BaseModel):
    """Without these an ablation cannot distinguish a component's effect from a
    prompt edit someone forgot about.

    All four required fields were the empty string in the one live record, which
    is the same as not having them: an ablation cannot tell two runs apart on a
    field that is "" in both. The driver knows every one of them before the model
    is called, so they are written by the wrapper and floored here.
    """

    model_config = ConfigDict(extra="forbid")

    dictionary_version: str = Field(min_length=1)
    module_version: str = Field(min_length=1)
    prompt_hash: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    weights_sha256: str | None = None
    seed: int | None = None
    sampling: dict = Field(default_factory=dict)
    tool_calls: list[str] = Field(default_factory=list)
    specifier_trace_sha256: str | None = Field(
        default=None,
        description="content hash of the freeform reasoning pass. Auditors "
                    "detected 55% of agent failures from the final artifact "
                    "alone and 82% with the trace, so the trace is published "
                    "beside the record — but it never enters the verdict path.")


class Status(str, Enum):
    draft = "draft"
    ready_for_review = "ready_for_review"


class BlockedOn(str, Enum):
    module_co_completion_counts = "module_co_completion_counts"
    per_item_non_missing_counts = "per_item_non_missing_counts"
    area_measure_inventory = "area_measure_inventory"
    response_coding = "response_coding"
    study_team_confirmation = "study_team_confirmation"
    #: The reference-arm outcome frequency the detectability curve was computed
    #: under was supplied by whoever called the tool, and no tool in this
    #: environment returns one to check it against. Same class of quantity as the
    #: analytic n, and admitted the same way. It is listed LAST on purpose: the
    #: n-gap check below refuses to let this blocker stand in for the n blocker,
    #: because a gap admitted about one quantity is not an admission about
    #: another.
    outcome_prevalence_unconfirmed = "outcome_prevalence_unconfirmed"
    #: The detectability curve assumes independent observations while
    #: curated/conventions/clustering_community_area.md instructs the model to
    #: cluster at the community area. Clustering INFLATES the true smallest
    #: detectable effect, so the floor is too low and errs toward accepting a
    #: falsifier the study could not falsify. The correction needs participants
    #: per cluster and an intracluster correlation; neither exists here, so the
    #: gap is admitted rather than estimated. Added at the lane-a/lane-b merge
    #: 2026-08-27: env/tools.py had begun telling the model to name this and
    #: the enum refused it, so a live run produced no record at all.
    design_effect_for_community_area_clustering = (
        "design_effect_for_community_area_clustering")

    # NO MEMBER FOR AN UNRESOLVED COVARIATE, and the omission is a decision.
    # `sought_covariates` records that gap instead. Every member above names a
    # PENDING ARTIFACT somebody could deliver — counts, an inventory, a coding, a
    # confirmation, a design effect — and `NotSpecifiable._refusal_states_a_remedy`
    # leans on exactly that. "The instrument appears not to carry this construct"
    # names no deliverable; it is a property of a fixed instrument, so it would be
    # the one member that never unblocks. Two mechanical reasons on top of the
    # definitional one. `specifier::_rank` orders on `len(p.blocked_on)` ASCENDING,
    # so a blocker tied to disclosure would rank an honest record strictly below
    # an otherwise identical silent one — a penalty on the behaviour this field
    # exists to elicit. And `_a_threshold_on_an_unknown_n_discloses_it` subtracts
    # a DENYLIST of one from blocked_on, so every member added here silently
    # gains standing as an admission about the analytic n, which this one is not.


# --------------------------------------------------------------------------- #
# HARD RULE 3 — a response coding the environment does not have
# --------------------------------------------------------------------------- #
#
# THE THIRD MECHANISM. Two other unknowable quantities already have guards and
# they use two different shapes. A variable key is checked against an
# authoritative source: every key must come back from resolve_variable, and
# _wording_is_verbatim diffs quoted wording against build/dictionary.json. A
# sample size is a field the environment owns: estimate_n returns null +
# `unknown` + a named blocker, _n_and_source_agree requires the record to agree
# with itself, and apply_tool_authority overwrites both from the run's own log.
# Response coding can use neither, because there is no authoritative value to
# compare against -- that is the whole problem. VERIFIED 2026-08-28 against
# build/dictionary.json 6fcd02755bf3: all 2,804 entries carry value_labels,
# response_options, value_type, missing_codes, measurement_level and
# branch_dependency, and every one of the six is null or empty on every entry.
# So the environment can assert the ABSENCE, and the question a gate can ask is
# not "is this coding right" but "does this record state a coding at all".
#
# WHY EVERY PATTERN REQUIRES A NUMERAL. The advisory detector at
# benchmark/unearned_assertions.py::SCALE_PATTERNS carries `coding_claim`,
# \bcod(?:ed|ing|es)\b, and it is not gateable: it fires on "reverse-coding
# items 4 and 5", which is copied verbatim from a signed derivation, and it
# produced exactly that false positive on run/m3q16.1_to_m2q5.8.
# 5ff7561afb90e529.json at selection_rationale.prior_work. The line drawn here
# instead: A CODING CLAIM THE ENVIRONMENT CANNOT SUPPLY IS ONE THAT NAMES A
# CODE. Prose about the absence of codes names none, so "the response coding is
# not in the public codebook" and "role=unreliable_coding" survive, while
# "1=strongly disagree" and "7/8/9 are missing codes" do not. That single rule
# is what lets the gate reject without needing a transcription exemption: the
# recipe, unit, construct_validity_basis and caveat of both files in
# curated/derivations/ are clean under every pattern below, MEASURED, while
# three of those eight strings fire `coding_claim`.
#
# A variable key is an identifier, not a code. `m3:Q16.1_5` and `m2:Q19.86_1`
# carry digits, so a sentence naming a key while disclosing the coding gap --
# "the response coding for m3:Q16.1_1 is unpublished" -- would otherwise trip
# the digit-proximity patterns and punish the disclosure the rule asks for.
_VARIABLE_KEY_TOKEN = re.compile(
    r"(?:m[123]|clinical|lab|linked|ehr):[A-Za-z0-9._#~-]+")

#: The same idea against a DIFFERENT THREAT MODEL, and the reason it is a second
#: pattern rather than a loosening of the one above.
#:
#: `_VARIABLE_KEY_TOKEN` STRIPS canonical keys out of text before the coding scan
#: reads it. That text is tool-returned, so the exact lowercase-module form is
#: guaranteed and anything looser would start eating prose the scan needs to see.
#: `_states_a_coding` depends on that and must NOT be given this pattern.
#:
#: `UnresolvedCovariate.construct_sought` is the opposite situation: MODEL-AUTHORED
#: FREE PROSE, scanned to REJECT it. There the strict form is evadable, and cheaply
#: — MEASURED 2026-08-31, all four accepted where the canonical form is rejected:
#:
#:     rejected  m1:Q2.15_3    (the canonical form, the control)
#:     ACCEPTED  M1:Q2.15_3    uppercase module
#:     ACCEPTED  m1: Q2.15_3   one space after the colon
#:     ACCEPTED  Q2.15_3       no module prefix
#:     ACCEPTED  m1:q2.15_3    lowercase q
#:
#: That matters because transduction allows ONE repair and the repair loop rewards
#: the SMALLEST edit that passes. A case-shift is smaller than moving the entry to
#: a covariate list and giving it a role, so the cheapest way past this validator
#: was to keep the resolved covariate here and dodge role adjudication — which is
#: the one thing the validator exists to stop.
#:
#: The bare-key branch requires `Q<digits>.<digits>`: a construct written in plain
#: words cannot trip it, and that shape is what every survey key in the three
#: modules looks like once the module prefix is dropped.
_KEY_TOKEN_IN_FREE_PROSE = re.compile(
    r"(?:m[123]|clinical|lab|linked|ehr)\s*:\s*[A-Za-z0-9._#~-]+"
    r"|(?<![A-Za-z0-9])Q\s*\d+(?:\.\d+)+(?:[_#~-][A-Za-z0-9.]+)*",
    re.I)

#: A digit bound to a label, an anchored range, a missing-code convention. Each
#: is narrower than its `SCALE_PATTERNS` counterpart and `coding_claim` has no
#: counterpart here at all. Calibrated 2026-08-28 against every string of all
#: 23 protocol records under run/ and run/superseded/: zero hits.
CODING_ASSERTION_PATTERNS: dict[str, str] = {
    "value_label_binding": r"\b\d+\s*=\s*[A-Za-z]{2}",
    # `\u2013` rather than a literal en dash: ruff flags the ambiguous glyph,
    # and a model writing "1\u20135" must still be caught.
    "anchored_scale_range":
        r"\b\d+\s*(?:-|\u2013|\bto\b)\s*\d+\s*(?:point|likert|scale)\b",
    # A trailing noun is REQUIRED. Without it this fires on "a 0.5-point
    # difference", which is a magnitude in the signed unit of
    # curated/derivations/social_cohesion_scale.json ("mean Likert score, 5
    # items") and states no coding at all.
    "n_point_scale":
        r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"[-\s]point\b[-\s]*(?:likert[-\s]*)?(?:scale|response|categor|item)",
    "scored_range":
        r"\bscor(?:ed|ing)\s+(?:from\s+)?\d+\s*(?:-|\u2013|\bto\b)\s*\d+",
    # Sentinels are spelled out rather than taken as any two-to-four digit
    # negative, because -25 is a plausible percentage-point threshold and -99 is
    # not a plausible anything else. "missing code" needs a code within the
    # sentence on one side or the other, so that naming the gap stays legal.
    "missing_code_convention":
        r"\bmissing\s+cod\w*[^.]{0,40}\d|\d[^.]{0,40}\bmissing\s+cod"
        r"|(?<![\w-])-(?:7{2,3}|8{2,3}|9{2,3})\b",
    "enumerated_response_options":
        r"\bresponse\s+(?:option|categor|code|scale)\w*[^.]{0,40}\d",
}

#: The fields where a stated coding changes what the study would estimate or
#: what it would be judged against. Everything else in the record stays with the
#: ADVISORY scanner, on the argument that a gate is only worth its false
#: positives where the claim is load-bearing.
#:
#: Four exclusions are not judgement calls and must not be "fixed" later:
#:
#:   quoted_wording          `_wording_is_verbatim` REQUIRES the instrument's
#:                           text. m2:Q19.86_1 reads "On average, how would you
#:                           rate your physical pain? 0 = Mild pain; 10 =
#:                           Extreme pain" -- one item in 2,804, and gating this
#:                           field would put two validators in direct
#:                           contradiction over it.
#:   smallest_detectable_    written by apply_tool_authority::_sde_from_curve
#:   effect.*, provenance.*  from the tool's own return value. Gating them
#:                           reports the environment to itself, which is why
#:                           SCAN_EXEMPT_PREFIXES already exempts
#:                           provenance.tool_calls.
#:   DerivationRef.unit      `_matches_the_signature_it_names` requires it to
#:                           equal the signed file verbatim. Same contradiction.
#:   CausalAdjustment.       `CausalRole.unreliable_coding` exists so a model
#:   mechanism/justification CAN say a variable's coding is unusable. Gating the
#:                           prose for that role would punish the schema's own
#:                           designated honest answer -- and these six lists are
#:                           the largest prose surface in the record.
CODING_GATED_FIELDS: tuple[str, ...] = (
    "question",
    "expected_direction.magnitude",
    "falsifier",
    "falsifier_threshold.unit",
    "model_spec.form",
    "estimability.exposure_contrast",
)


def _states_a_coding(text: str) -> str | None:
    """Which coding-assertion pattern this text trips, if any.

    Args:
        text: One free-text field value from a record.

    Returns:
        The name of the first pattern in `CODING_ASSERTION_PATTERNS` that
        matches, or None.
    """
    stripped = _VARIABLE_KEY_TOKEN.sub(" ", text or "")
    return next((name for name, pattern in CODING_ASSERTION_PATTERNS.items()
                 if re.search(pattern, stripped, re.I)), None)


# --------------------------------------------------------------------------- #
# the record
# --------------------------------------------------------------------------- #

class ProtocolSpecification(BaseModel):
    """A study design as a mechanically checkable record, not a prose hypothesis.

    Every field value — exposure, outcome, model form, and each adjusted,
    excluded or undetermined covariate — is an identifier drawn from a fixed
    cohort instrument, so referential validity is decided by set membership
    rather than by a model judging text.

    Absent deliberately: no `novelty` field (that is the reviewer's job), no
    self-reported `confidence` (uncalibrated), no free-text `notes`.
    `extra="forbid"` is what stops this becoming a tangle.
    """

    model_config = ConfigDict(extra="forbid")

    # --- identity ---------------------------------------------------------- #
    # min_length=1 on both: a record whose protocol_id was the empty string saved
    # as a dotfile, because the driver builds the filename from it, and a
    # dictionary_version of "" pins nothing while this field's own description
    # says it pins the record to a build hash. Neither is the model's to write —
    # agent/tool_authority.apply_record_identity fills both from the driver — so
    # the floor is a tripwire on the wrapper, not a demand on the model.
    protocol_id: str = Field(min_length=1)
    dictionary_version: str = Field(min_length=1,
                                    description="pins this record to a build hash; "
                                                "protocols built against different "
                                                "dictionary versions are not comparable")

    # --- the question ------------------------------------------------------ #
    question: str
    exposure: Ref
    outcome: Ref
    expected_direction: ExpectedDirection
    falsifier: str = Field(description="prose; model-comparison and binary-outcome "
                                       "falsifiers do not reduce to a threshold")
    falsifier_threshold: FalsifierThreshold | None = None
    model_spec: ModelSpec

    # --- covariates: reasoning first, verdict second ----------------------- #
    adjusted_covariates: list[CausalAdjustment] = Field(min_length=1)
    excluded_variables: list[CausalAdjustment] = Field(
        min_length=1,
        description="an omitted-by-accident variable and an omitted-on-purpose "
                    "one are indistinguishable unless exclusions are stated with "
                    "a causal role")
    undetermined_covariates: list[CausalAdjustment] = Field(
        default_factory=list,
        description="usually the largest list. Temporality is unrecoverable from "
                    "a two-column codebook for most items, so honest abstention "
                    "is the modal outcome, not a defect. Each entry ships as a "
                    "paired sensitivity specification.")
    # LAST OF THE COVARIATE FIELDS, and outside the three lists on purpose. The
    # three above are adjudications of variables that RESOLVED; this one records
    # a construct that did not, so it has no role, no key, and no place in the
    # role-to-list mapping. Declared after them because a model should not reach
    # for it until it has finished with what it did find.
    sought_covariates: list[UnresolvedCovariate] = Field(
        default_factory=list,
        description="constructs you searched for and could not bind to any key. "
                    "A covariate the instrument does not appear to carry is a "
                    "finding about the instrument, and a design that simply "
                    "omits it looks complete when it is not. Not a fourth "
                    "covariate list: nothing here is adjusted for.")

    # --- feasibility ------------------------------------------------------- #
    estimability: Estimability
    access: Access
    derivation_ref: str | None = None

    # --- bookkeeping, system-written --------------------------------------- #
    selection_rationale: SelectionRationale
    provenance: Provenance
    status: Status
    blocked_on: list[BlockedOn] = Field(default_factory=list)

    # --- attestations ------------------------------------------------------ #
    derivation_not_fitted_to_outcome: Literal[True] = Field(
        default=True,
        description="ATTESTATION ONLY. Nothing verifies this. Its purpose is to "
                    "put the claim on the record so a later violation is visible. "
                    "Never describe an attestation as a check.")
    no_participant_data_used: Literal[True] = True

    # ----------------------------------------------------------------------- #

    @model_validator(mode="after")
    def _roles_match_their_lists(self) -> ProtocolSpecification:
        """A mediator in the adjusted list fails validation loudly and is logged,
        rather than being silently relabelled by the decoder into something that
        looks correct.
        """
        # EVERY MESSAGE NAMES THE LEGAL ROLES AND WHERE THIS ONE BELONGS. The
        # excluded and undetermined messages used to say only which role was
        # wrong, and the role-to-list mapping appears in no prompt, so a live run
        # on 2026-08-27 spent all four transductions being told
        # "role=unadjudicated cannot appear in excluded_variables" with nothing
        # to say where unadjudicated does go. A rejection the reader cannot act
        # on costs the whole sample.
        for lst, name, allowed in (
                (self.adjusted_covariates, "adjusted_covariates", ADJUSTED_ROLES),
                (self.excluded_variables, "excluded_variables", EXCLUDED_ROLES),
                (self.undetermined_covariates, "undetermined_covariates",
                 UNDETERMINED_ROLES)):
            for entry in lst:
                if entry.role in allowed:
                    continue
                belongs = next(
                    (n for n, roles in (("adjusted_covariates", ADJUSTED_ROLES),
                                        ("excluded_variables", EXCLUDED_ROLES),
                                        ("undetermined_covariates",
                                         UNDETERMINED_ROLES))
                     if entry.role in roles), None)
                raise ValueError(
                    f"role={entry.role.value} cannot appear in {name} "
                    f"(key={_ref_key(entry.variable)}). {name} takes only "
                    f"{sorted(r.value for r in allowed)}. "
                    + (f"role={entry.role.value} belongs in {belongs}: move this "
                       f"entry there, or change its role to one {name} takes and "
                       f"say why in the justification."
                       if belongs else
                       "Reason to a role this list takes, or move the entry."))
        return self

    @model_validator(mode="after")
    def _wording_is_verbatim(self) -> ProtocolSpecification:
        """`quoted_wording` must be the dictionary's text for `key`.

        Line 92 has described this field as "verbatim dictionary text" since the
        schema was written, and nothing enforced it. In the only real record the
        pipeline has produced, six of seven were paraphrased LABELS — m1:Q3.10
        carried "Race" against an instrument that asks "What race do you consider
        yourself to be? Check all that apply. - Selected Choice", and m1:Q3.11
        carried "Education level". A protocol whose wording is the model's
        summary cannot be checked against the instrument by a human reader, which
        is the entire purpose of carrying the wording.

        Whitespace is normalised: the codebooks contain hard newlines inside
        quoted fields and a newline-versus-space difference is not a paraphrase.
        """
        truth = _dictionary_wording()
        if not truth:
            return self                      # dictionary absent; build.py raises
        bad, missing = [], []
        for ref, where in self._all_variable_refs():
            expected = truth.get(ref.key)
            if expected is None:
                # KEY_PATTERN is a SHAPE check. `linked:household_poverty`
                # satisfies it and exists nowhere. Until this validator existed
                # the schema accepted invented keys, which meant the only
                # well-formed output for an unanswerable pair was a fabricated
                # one — see NotSpecifiable below.
                missing.append(f"{where} {ref.key}")
                continue
            if _norm(ref.quoted_wording) != _norm(expected):
                bad.append(f"{where} {ref.key}: got {ref.quoted_wording[:60]!r}, "
                           f"instrument says {expected[:60]!r}")
        if missing:
            raise ValueError(
                "these keys match the key pattern but exist in no registry: "
                + "; ".join(missing[:4])
                + ". A key that resolves nowhere cannot anchor a protocol. If the "
                "measure this pair needs is genuinely unavailable, emit a "
                "NotSpecifiable record naming the blocker — do not invent a key "
                "to make the record well-formed.")
        if bad:
            raise ValueError(
                "quoted_wording must be the instrument's text verbatim, not a "
                "label or paraphrase. Copy it from resolve_variable(). "
                + "; ".join(bad[:4]))
        return self

    def _all_variable_refs(self):
        for ref, where in ((self.exposure, "exposure"), (self.outcome, "outcome")):
            if isinstance(ref, VariableRef):
                yield ref, where
        for lst, name in ((self.adjusted_covariates, "adjusted"),
                          (self.excluded_variables, "excluded"),
                          (self.undetermined_covariates, "undetermined")):
            for e in lst:
                if isinstance(e.variable, VariableRef):
                    yield e.variable, name

    def _coding_gated_text(self) -> list[tuple[str, str]]:
        """The design fields HARD RULE 3 is enforced on, with their values.

        Returns:
            `(dotted path, text)` pairs, omitting the two optional fields when
            they are null. Every path is a member of `CODING_GATED_FIELDS`.
        """
        # Attribute access, not a walk with a path allowlist. A field renamed
        # here fails at import; a renamed string in an allowlist silently stops
        # being gated, which is how a check comes to pass on nothing.
        #
        # DECLARATION ORDER, matching CODING_GATED_FIELDS and the record's own
        # field order, so the rejection a model sees names the earliest offending
        # field rather than whichever one this list happened to visit first.
        out = [("question", self.question)]
        if self.expected_direction.magnitude:
            out.append(("expected_direction.magnitude",
                        self.expected_direction.magnitude))
        out.append(("falsifier", self.falsifier))
        if self.falsifier_threshold:
            out.append(("falsifier_threshold.unit",
                        self.falsifier_threshold.unit))
        out.append(("model_spec.form", self.model_spec.form))
        out.append(("estimability.exposure_contrast",
                    self.estimability.exposure_contrast))
        return out

    @model_validator(mode="after")
    def _no_response_coding_is_asserted(self) -> ProtocolSpecification:
        """HARD RULE 3, enforced: a design field may not state a response coding.

        Returns:
            The validated record.

        Raises:
            ValueError: If a gated field names a value label, an anchored scale
                range, an n-point scale or a missing-code convention.
        """
        # The rule was stated in agent/specifier.py::SYSTEM and repeated in
        # resolve_variable's own return text since both were written, and
        # enforced NOWHERE: VERIFIED 2026-08-27 and again on 2026-08-28 that
        # three fabricated coding claims injected into a validating record were
        # accepted by ProtocolSpecification and by apply_tool_authority alike.
        # That is this codebase's signature failure and this is its fifth
        # recorded instance.
        #
        # REJECTION, NOT REPAIR. There is no correct value to substitute, the
        # way apply_tool_authority substitutes the run's own analytic_n: the
        # environment holds no coding, so the only honest edit is one the model
        # has to make. The message therefore carries the remedy as well as the
        # diagnosis — three live runs were lost to rejections that named a
        # defect and no legal move.
        for where, text in self._coding_gated_text():
            name = _states_a_coding(text)
            if name is None:
                continue
            raise ValueError(
                f"{where} states a response coding ({name}): {text[:90]!r}. "
                f"The instrument carries none — all 2,804 dictionary entries "
                f"have value_labels, response_options, value_type, "
                f"missing_codes and measurement_level null — so a coding "
                f"written here was supplied by you, not looked up, and it "
                f"reads to a later reader as method detail somebody verified. "
                f"Restate this field without the codes: 'highest versus lowest "
                f"category' says the contrast without inventing the scale. If "
                f"the design genuinely cannot be specified without knowing the "
                f"coding, that is an admitted gap, not a licence to supply "
                f"one — put "
                f"{BlockedOn.response_coding.value!r} in blocked_on and say so.")
        return self

    @model_validator(mode="after")
    def _no_covariate_repeats_an_anchor(self) -> ProtocolSpecification:
        """Gate 4, in-record half: the outcome may not also be a covariate."""
        anchors = {_ref_key(self.exposure), _ref_key(self.outcome)}
        for lst, name in ((self.adjusted_covariates, "adjusted"),
                          (self.excluded_variables, "excluded"),
                          (self.undetermined_covariates, "undetermined")):
            for entry in lst:
                if _ref_key(entry.variable) in anchors:
                    raise ValueError(
                        f"{_ref_key(entry.variable)} is an anchor of this design "
                        f"and cannot also appear in {name}_covariates")
        return self

    @model_validator(mode="after")
    def _no_covariate_named_twice(self) -> ProtocolSpecification:
        seen: dict[str, str] = {}
        for lst, name in ((self.adjusted_covariates, "adjusted"),
                          (self.excluded_variables, "excluded"),
                          (self.undetermined_covariates, "undetermined")):
            for entry in lst:
                k = _ref_key(entry.variable)
                if k in seen:
                    # The remedy, not just the diagnosis. This exact error ended
                    # three live runs across two sessions, every one of them
                    # after both transduction attempts: the model was told what
                    # was wrong and never told that deleting one entry was the
                    # allowed fix.
                    raise ValueError(
                        f"{k} appears in both {seen[k]} and {name}. A covariate "
                        f"goes in exactly one of the three lists — delete its "
                        f"entry from whichever of {seen[k]} and {name} it "
                        f"belongs in less, and keep the other.")
                seen[k] = name
        return self

    @model_validator(mode="after")
    def _no_sought_construct_named_twice(self) -> ProtocolSpecification:
        """Two entries for one construct are padding, not two findings.

        Returns:
            The validated record.

        Raises:
            ValueError: If two `sought_covariates` entries name the same
                construct after whitespace and case normalisation.
        """
        # The keyed lists get this from `_no_covariate_named_twice`, which
        # compares keys. There is no key here, so the comparison is on the
        # normalised construct prose — a low bar that only catches a genuine
        # repeat, which is the only thing worth catching: the length floors
        # already make padding with prose expensive, and repeating one entry is
        # the cheap way around them.
        #
        # PUNCTUATION IS PART OF THE NORMALISATION, and that is the whole reason
        # `_norm_construct` exists rather than `_norm(...).casefold()`. `_norm`
        # collapses whitespace and nothing else, so two entries identical up to a
        # TRAILING PERIOD validated together — measured. Adding a period is
        # cheaper than either of the two things this check is defending: the
        # three prose floors above, and the requirement to say which construct
        # the second search was for.
        seen: dict[str, int] = {}
        for i, entry in enumerate(self.sought_covariates):
            k = _norm_construct(entry.construct_sought)
            if k in seen:
                raise ValueError(
                    f"sought_covariates[{i}] repeats the construct named in "
                    f"sought_covariates[{seen[k]}] "
                    f"({entry.construct_sought!r}). One "
                    f"entry per construct — if the second search was for a "
                    f"different construct, say which; if it was the same "
                    f"search, delete it and put every phrase you tried in the "
                    f"one entry's search_phrases.")
            seen[k] = i
        return self

    @model_validator(mode="after")
    def _a_threshold_on_an_unknown_n_discloses_it(self) -> ProtocolSpecification:
        """A numeric falsifier must name the n it is falsifiable at, and its blocker.

        Returns:
            The validated record.

        Raises:
            ValueError: If a threshold is stated against an environment-computed
                curve without naming a point on it, or if the design rests on an
                analytic n nobody has computed and names no blocker.
        """
        t, est = self.falsifier_threshold, self.estimability
        sde = est.smallest_detectable_effect
        if not (t and sde.curve):
            # No curve means this record never went through estimate_detectability
            # — a hand-built specimen. Nothing to bind it to.
            return self
        if sde.at_n is None:
            raise ValueError(
                "falsifier_threshold is stated but smallest_detectable_effect."
                "at_n is null. The detectable effect is a CURVE while the "
                "analytic n is unknown, so a threshold is only checkable once "
                "the record names the candidate n it claims to be falsifiable "
                "at. Pick a point on the curve and state it.")
        # A design whose falsifiability rests on an n the environment could not
        # compute has to say so. derive_status already forces such a record to
        # draft; without this it could stay silent about WHY, and "n unknown, no
        # blocker named" is the shape §5 rule 5 exists to forbid.
        #
        # THE PREVALENCE BLOCKER CANNOT SATISFY THIS ONE. It is added to every
        # record that went through estimate_detectability, so counting it here
        # would make this check unfalsifiable overnight: every record would
        # "name a blocker" and none of them would be naming one about the n.
        # An admission about one unknown quantity is not an admission about a
        # different one.
        gaps = set(self.blocked_on) - {BlockedOn.outcome_prevalence_unconfirmed}
        if est.n_source is NSource.unknown and not gaps:
            raise ValueError(
                f"this record claims a falsifier detectable at n={sde.at_n} "
                f"while n_source=unknown, and names no blocker. An admitted gap "
                f"is the correct output here, but it has to be admitted: put the "
                f"missing count in blocked_on.")
        return self

    @model_validator(mode="after")
    def _an_asserted_prevalence_is_admitted_as_one(self) -> ProtocolSpecification:
        """An outcome frequency nobody measured must be blocked on, not just noted.

        Returns:
            The validated record.

        Raises:
            ValueError: If the record carries an asserted outcome frequency
                without the blocker that admits nothing here can confirm it.
        """
        sde = self.estimability.smallest_detectable_effect
        if (sde.asserted_baseline_prevalence is not None
                and BlockedOn.outcome_prevalence_unconfirmed not in self.blocked_on):
            raise ValueError(
                f"smallest_detectable_effect.asserted_baseline_prevalence="
                f"{sde.asserted_baseline_prevalence} is an assumption no tool in "
                f"this environment can confirm, and the record does not admit it. "
                f"Add {BlockedOn.outcome_prevalence_unconfirmed.value!r} to "
                f"blocked_on. §5 rule 5: an unknowable population parameter is "
                f"admitted with a named blocker, never quietly relied on — the "
                f"same treatment the analytic n already gets.")
        return self

    @model_validator(mode="after")
    def _falsifier_is_detectable(self) -> ProtocolSpecification:
        """A falsifier below the smallest detectable effect cannot be falsified by
        the study it is attached to.
        """
        t, sde = self.falsifier_threshold, self.estimability.smallest_detectable_effect
        # Read off a CURVE, not off `value`. The two are kept equal by
        # apply_tool_authority, but the curves are the environment's return value
        # and `value` is a scalar somebody could later edit; comparing against
        # the derived copy is how a check comes to be pointed at a different row
        # than the one the record discloses.
        if t and (sde.curve or sde.worst_case_curve) and sde.at_n is not None:
            # A UNIT MISMATCH IS A REFUSAL, NOT AN ABSTENTION. The comparison
            # used to be guarded by `t.unit == sde.unit` and simply not happen
            # otherwise, which made the whole floor check optional: any threshold
            # in any other unit sailed past it in silence. Found in the first
            # green live record, 2026-08-27 — Haiku wrote `0.68 odds ratio`
            # against a percentage-point curve and the record was accepted with
            # its falsifier never compared to anything.
            #
            # estimate_detectability computes a RISK DIFFERENCE and nothing else,
            # so a threshold in any other unit is not checkable against this
            # study's power. That is a real limit and the honest response is to
            # say so, not to wave the record through: state the threshold as a
            # risk difference, or state the falsifier in prose and leave
            # falsifier_threshold null, which the schema allows.
            if sde.unit and t.unit != sde.unit:
                raise ValueError(
                    f"falsifier_threshold is in {t.unit!r} but the detectable "
                    f"effect this study can reach is in {sde.unit!r}, so the "
                    f"threshold cannot be checked against the study's power and "
                    f"would pass unexamined. Either restate the threshold as a "
                    f"difference in {sde.unit} — the quantity "
                    f"estimate_detectability computes — or drop "
                    f"falsifier_threshold entirely and put the criterion in the "
                    f"`falsifier` prose, which is the correct output for a "
                    f"model-comparison or ratio-scale falsifier.")
            # THE COMPARATOR IS THE CALLER-INDEPENDENT BOUND. `curve` is computed
            # under an outcome frequency the caller asserted and nothing here can
            # check, and the detectable effect shrinks as that frequency moves
            # away from the maximising one — so a record checked against its own
            # `curve` is a record grading itself on a floor it chose. Measured on
            # the eight live records that existed on 2026-08-27: every one of
            # them set its threshold at or a hair above its own asserted floor,
            # and every one of them sits below this bound.
            bound = {pt.n: pt.sde_percentage_points for pt in sde.worst_case_curve}
            if not bound:
                # A record with a disclosed curve but no bound cannot be gated at
                # all. estimate_detectability returns both together, so this can
                # only be a record that predates the bound or one edited by hand;
                # either way the honest answer is that the check cannot run, not
                # that it passed.
                raise ValueError(
                    "smallest_detectable_effect carries a curve but no "
                    "worst_case_curve, so the falsifier can only be compared "
                    "against a floor computed under an assumed outcome frequency "
                    "the caller supplied. Re-run estimate_detectability: it "
                    "returns the caller-independent bound alongside the curve, "
                    "and that bound is what the threshold is checked against.")
            floor = bound.get(sde.at_n)
            if floor is None:
                raise ValueError(
                    f"smallest_detectable_effect.at_n={sde.at_n} is not a point "
                    f"on the bound this record carries ({sorted(bound)}).")
            if abs(t.value) < abs(floor):
                raise ValueError(
                    f"falsifier threshold {t.value} {t.unit} is below the "
                    f"smallest detectable effect {floor} {sde.unit} at "
                    f"n={sde.at_n}. That floor is the bound at the outcome "
                    f"frequency which MAXIMISES the detectable effect, not the "
                    f"one this record assumed, because a threshold checked "
                    f"against an assumed frequency is checked against a number "
                    f"the record chose. Raise the threshold, or name a larger n "
                    f"on the curve and disclose that larger claim.")
            return self
        if t and sde.value is None:
            # Found live: the model wrote the whole detectability curve into the
            # free-text `assumptions` field and left `value` null, so this check
            # had nothing to compare against and passed vacuously — a 13pp
            # falsifier sailed through unexamined. A check that silently
            # abstains is worse than no check, because the record then claims a
            # falsifier that was never tested against the study's power.
            raise ValueError(
                "falsifier_threshold is set but smallest_detectable_effect.value "
                "is null, so the threshold cannot be checked against the study's "
                "power. Call estimate_detectability and put the number for your "
                "stated n in `value` with its `at_n` — prose in `assumptions` is "
                "not a substitute.")
        if t and sde.value is not None and sde.unit and t.unit == sde.unit:
            if abs(t.value) < abs(sde.value):
                raise ValueError(
                    f"falsifier threshold {t.value} {t.unit} is below the smallest "
                    f"detectable effect {sde.value} {sde.unit} at n={sde.at_n}")
        return self

    @model_validator(mode="after")
    def _status_matches_blockers(self) -> ProtocolSpecification:
        expected = derive_status(self)
        if self.status is not expected:
            raise ValueError(
                f"status={self.status.value} but derive_status() says "
                f"{expected.value}. status is system-written; do not set it "
                "by hand.")
        return self

    @model_validator(mode="after")
    def _derivations_are_referenced_not_inlined(self) -> ProtocolSpecification:
        uses_derivation = any(isinstance(r, DerivationRef)
                              for r in (self.exposure, self.outcome))
        if uses_derivation and not self.derivation_ref:
            raise ValueError("a derived exposure or outcome requires derivation_ref "
                             "naming a signed file in curated/derivations/")
        return self

    # --- k=5 selection ------------------------------------------------------ #

    def canonical_form(self) -> dict:
        """The record reduced to its design decisions, for set-equality dedup.

        Five samples per enumerated pair are deduplicated on this, then ordered by
        gate status and estimability — never by model score. Prose outputs cannot
        be deduplicated this way, which is one concrete thing the typed record
        buys that a hypothesis paragraph does not.
        """
        # `sought_covariates` IS DELIBERATELY ABSENT. Three reasons, and the
        # first is the one that decides it: this dict is prose-free by design and
        # `test_canonical_form_ignores_prose_but_not_design` pins that, while a
        # sought construct is nothing but prose — folding it in would make two
        # samples that phrased the same gap differently into two designs. Second,
        # it is not a design decision: the fitted model is identical whether or
        # not the gap is written down. Third, every saved record carries its
        # record_hash in its FILENAME, and adding a key here would change the
        # hash of all 21 of them without any of their designs having changed.
        # The cost, stated rather than hidden: two samples for one pair that
        # differ ONLY in whether they disclose a gap hash IDENTICALLY, so dedup
        # has to pick one. HASH ORDER CANNOT PICK IT — equal hashes have no
        # order, and saying so was a false mechanism carried in three primaries
        # at the time this field landed. The real selector was seed order, via
        # `setdefault`: whichever sample arrived first won, and because `parked`
        # iterates DISTINCT hashes the loser was not parked either, so a
        # disclosing sample behind a silent one left the run entirely. That is
        # settled in `specifier::specify` by a tie-break on
        # `specifier::_disclosure`, not here — folding the field into this dict
        # would cost the three properties above.
        def cov(lst):
            return sorted((_ref_key(e.variable), e.role.value) for e in lst)
        return {
            "exposure": _ref_key(self.exposure),
            "outcome": _ref_key(self.outcome),
            "direction": self.expected_direction.direction.value,
            "model_form": self.model_spec.form,
            "unit": self.model_spec.unit_of_analysis.value,
            "clustering": self.model_spec.clustering,
            "adjusted": cov(self.adjusted_covariates),
            "excluded": cov(self.excluded_variables),
            "undetermined": cov(self.undetermined_covariates),
        }

    def record_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.canonical_form(), sort_keys=True).encode()
        ).hexdigest()[:16]


def _ref_key(ref) -> str:
    if isinstance(ref, VariableRef):
        return ref.key
    if isinstance(ref, DerivationRef):
        return f"derivation:{ref.derivation_id}"
    return f"area:{ref.measure_id}"


# --------------------------------------------------------------------------- #
# status is derived, never asserted
# --------------------------------------------------------------------------- #

def derive_status(p: ProtocolSpecification) -> Status:
    """Pure. The truth table, written down:

        n_source == unknown            -> draft
        blocked_on is non-empty        -> draft
        access.decision != pass        -> draft
        otherwise                      -> ready_for_review

    blocked_on still varies protocol-to-protocol, but one of its members no
    longer does: `outcome_prevalence_unconfirmed` is written onto every record
    that called estimate_detectability, because calling it at all means asserting
    an outcome frequency nothing here can confirm. That is deliberate and it has
    a cost — a blocker present on everything discriminates between nothing — so
    it is paid for in two places. `_a_threshold_on_an_unknown_n_discloses_it`
    refuses to let it satisfy the n-gap admission, and the day co-completion
    counts arrive is the day it stops being universal: a record whose frequency
    was never confirmed would otherwise flip silently to ready_for_review
    carrying a number the model supplied from its own prior. This blocker is what
    makes that flip impossible, which is the failure it exists for — a future
    one, not today's.
    """
    if p.estimability.n_source is NSource.unknown:
        return Status.draft
    if p.blocked_on:
        return Status.draft
    if p.access.decision is not GateDecision.pass_:
        return Status.draft
    return Status.ready_for_review


def json_schema() -> dict:
    return ProtocolSpecification.model_json_schema()


if __name__ == "__main__":
    s = json_schema()
    print(json.dumps(s, indent=1)[:400], "...")
    print(f"\n{len(s['properties'])} top-level properties, "
          f"{len(s.get('$defs', {}))} nested definitions")
    print("field order:", ", ".join(list(s["properties"])[:8]), "...")


# --------------------------------------------------------------------------- #
# The refusal path
#
# THE RATIONALE FOR THIS SECTION IS IN COMMENTS, NOT IN ITS DOCSTRINGS, and that
# is a rule and not a style choice. §3 of the handoff says docstrings in this
# module are prompt text because model_json_schema() copies them into
# `description`. That was true of ProtocolSpecification only until 2026-08-28,
# when agent/specifier.py started pasting NotSpecifiable's schema into a second
# transduction call. The docstring this class carried until then explained that a
# probe would read an invented key as recall — an instruction to the model to
# behave differently on the exact measurement being taken. Comments are not
# copied by model_json_schema(); docstrings are. Write the reasoning here.
#
# WHAT THIS SECTION IS FOR. Before it existed the output space was `valid
# protocol` or `nothing`, and `exposure` is a required field. For a pair whose
# exposure resolves nowhere, the only well-formed record was one naming a key
# that satisfied KEY_PATTERN and existed in no registry. The structure rewarded
# fabrication and then counted it as yield.
# --------------------------------------------------------------------------- #

class RefusalReason(str, Enum):
    """Why a stated pair cannot be specified against this instrument.

    Every value names a condition a tool in this environment can confirm. There
    is deliberately no `insufficient_information` and no `too_uncertain`: a
    reason no tool can check is a reason that can be asserted at will, which
    turns this path into an escape hatch from the work.
    """

    exposure_unresolvable = "exposure_unresolvable"
    outcome_unresolvable = "outcome_unresolvable"
    registry_empty = "registry_empty"
    free_text_anchor = "free_text_anchor"
    no_signed_derivation = "no_signed_derivation"
    anchors_are_the_same_construct = "anchors_are_the_same_construct"
    no_contrast_definable = "no_contrast_definable"
    access_gate_refused = "access_gate_refused"


#: The lookups each reason requires, declared ONCE and read by three places:
#: `_refusal_is_earned` below (does the RECORD cite them), agent/specifier.py's
#: `_refusal_gate` (did the RUN actually make them), and the checklist the system
#: prompt generates from it. It was a literal inside the validator until
#: 2026-08-28, so the gate and the prompt would each have had to restate it —
#: and a reason added to the enum without a matching restatement is a reason the
#: gate does not know about. Same construction, and the same failure it avoids,
#: as REQUIRED_CALLS and the role table in agent/specifier.py.
REFUSAL_EVIDENCE: dict[RefusalReason, frozenset[str]] = {
    RefusalReason.exposure_unresolvable: frozenset({"resolve_variable"}),
    RefusalReason.outcome_unresolvable: frozenset({"resolve_variable"}),
    RefusalReason.registry_empty: frozenset({"registry_coverage",
                                             "resolve_variable"}),
    RefusalReason.free_text_anchor: frozenset({"resolve_variable"}),
    RefusalReason.no_signed_derivation: frozenset({"list_derivations"}),
    RefusalReason.no_contrast_definable: frozenset({"get_contrast_convention"}),
    RefusalReason.access_gate_refused: frozenset({"check_access"}),
    RefusalReason.anchors_are_the_same_construct: frozenset({"resolve_variable"}),
}


# C15, 2026-08-28. REFUSAL_EVIDENCE above checks WHICH tools were called. It does
# not check what they returned, and a validator that reads only tool names accepts
# a refusal contradicted by its own citation: measured on merged main, a
# NotSpecifiable claiming access_gate_refused validated while citing
# check_access -> "ok", a call in which the gate did not refuse. check_access is
# in REQUIRED_CALLS, so that evidence is present on every run, which made it the
# cheapest refusal in the enum to fabricate at schema level.
#
# The outcome vocabulary this is written against, measured 2026-08-28:
#   resolve_variable  -> unique | group | construct | ambiguous | not_found
#   registry_coverage -> ok      (emptiness is in the payload; the specifier
#                                 stamps "<prefix>: coverage none")
#   check_access      -> ok      (the verdict is in `decision`, not `outcome`)
#   list_derivations  -> ok
#
# A value of None is not a gap left open by accident: it records that the tool's
# outcome field CANNOT entail the reason, so only the call's presence is
# checkable. Making one of those look enforced would be the failure this rule
# exists to catch.
REFUSAL_OUTCOMES: dict[RefusalReason, dict[str, frozenset[str] | None]] = {
    RefusalReason.exposure_unresolvable: {
        "resolve_variable": frozenset({"not_found", "ambiguous"})},
    RefusalReason.outcome_unresolvable: {
        "resolve_variable": frozenset({"not_found", "ambiguous"})},
    RefusalReason.registry_empty: {
        "registry_coverage": frozenset({"coverage none"}),
        "resolve_variable": frozenset({"not_found", "ambiguous"})},
    RefusalReason.anchors_are_the_same_construct: {
        "resolve_variable": frozenset({"construct"})},
    # check_access returns `outcome: "ok"` whatever it decides, so an outcome
    # that entails a refusal is one nothing in this environment produces. The
    # member stays because it names a real failure mode a richer environment
    # would have; requiring the entailment keeps it unclaimable meanwhile,
    # rather than leaving it the easiest refusal to assert.
    RefusalReason.access_gate_refused: {
        "check_access": frozenset({"refer", "fail", "refused"})},
    # Free-textness is a field of the payload, not the outcome: resolve_variable
    # returns `unique` for a free-text item exactly as for any other.
    RefusalReason.free_text_anchor: {"resolve_variable": None},
    RefusalReason.no_signed_derivation: {"list_derivations": None},
    RefusalReason.no_contrast_definable: {"get_contrast_convention": None},
}


class RefusalEvidence(BaseModel):
    """One tool call that establishes the refusal.

    A refusal carries the lookups that force it, for the same reason a protocol
    carries its wording: so a reader can check it without rerunning the model.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    argument: str
    outcome: str = Field(description="the tool's own outcome string, verbatim")


class NotSpecifiable(BaseModel):
    """A pair that cannot be specified, as a first-class output.

    Emit this instead of a protocol when the environment cannot supply an anchor
    the design would need. It is a legitimate result, not a failed one.

    It carries NO design — no covariates, no model form, no expected direction,
    no threshold. A record that speculates about the study it would have written
    is not this; it is a protocol with a disclaimer, and it lets unsupported
    reasoning back in through the door this shuts. State only what the lookups
    in `evidence` establish.
    """

    model_config = ConfigDict(extra="forbid")

    pair_id: str
    dictionary_version: str
    reason: RefusalReason
    statement: str = Field(min_length=30, description=
                           "what cannot be established, in one sentence a "
                           "reviewer can check against the evidence below")
    evidence: list[RefusalEvidence] = Field(min_length=1)
    blocked_on: list[BlockedOn] = Field(default_factory=list)
    what_would_unblock: str = Field(min_length=15, description=
                                    "the named artifact or decision that would "
                                    "make this pair specifiable")
    provenance: Provenance

    @model_validator(mode="after")
    def _refusal_is_earned(self) -> NotSpecifiable:
        """The stated reason must be backed by a lookup that actually ran.

        Without this the refusal path is strictly easier than the work, and a
        model under any pressure will take it. The gate is symmetric with the
        one on protocols: a protocol must show the calls that support its
        assertions, and a refusal must show the calls that force it.
        """
        need = REFUSAL_EVIDENCE.get(self.reason)
        if need is None:
            # A KeyError here would read as a crash; it is a design hole. A
            # reason with no declared evidence is one nothing can check, which
            # is precisely what RefusalReason's docstring says may not exist.
            raise ValueError(
                f"reason={self.reason.value} has no entry in REFUSAL_EVIDENCE, "
                f"so no lookup could earn it. Declare the evidence it requires "
                f"before adding the member.")
        got = {e.tool for e in self.evidence}
        if not need <= got:
            raise ValueError(
                f"reason={self.reason.value} requires evidence from "
                f"{sorted(need)}, but the record cites only {sorted(got)}. A "
                f"refusal must show the lookups that force it.")

        # Naming the tool is not enough: the call it names must have returned
        # something that entails the reason. Substring rather than equality
        # because the specifier stamps a descriptive outcome for the registry
        # case ("linked: coverage none") and the raw field elsewhere.
        wanted = REFUSAL_OUTCOMES.get(self.reason, {})
        for tool, entailing in wanted.items():
            if entailing is None or tool not in need:
                continue
            seen = [e.outcome for e in self.evidence if e.tool == tool]
            if not any(any(w in (o or "") for w in entailing) for o in seen):
                raise ValueError(
                    f"reason={self.reason.value} cites {tool} but none of its "
                    f"outcomes {seen} entails the refusal; one of "
                    f"{sorted(entailing)} would. A citation that does not "
                    f"support the claim is not evidence.")
        return self

    @model_validator(mode="after")
    def _refusal_states_a_remedy(self) -> NotSpecifiable:
        """`registry_empty` must name the artifact that would populate it, so a
        refusal converts into a request the study team can act on rather than a
        dead end.
        """
        if (self.reason is RefusalReason.registry_empty
                and not self.blocked_on):
            raise ValueError(
                "reason=registry_empty must name a blocker in blocked_on "
                "(e.g. area_measure_inventory) — an empty registry is a pending "
                "request, not a permanent property of the study.")
        return self

    def record_hash(self) -> str:
        payload = {"pair_id": self.pair_id, "reason": self.reason.value,
                   "dictionary_version": self.dictionary_version,
                   "evidence": sorted((e.tool, e.argument, e.outcome)
                                      for e in self.evidence)}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
