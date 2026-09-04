"""agent/registry.py — the ONLY place a tool dict is constructed.

Contamination control is an architectural property, not a prompt instruction. If
three call sites each assemble their own toolset, the fourth one added later will
quietly include `search_literature` in benchmark mode and every benchmark number
after that is unfalsifiable. So there is one construction site, mode is a required
argument with no default, and a test asserts the benchmark registry contains none
of the retrieval tools.

The registry also emits the OpenAI-style function schemas the served model sees.
The tool-level `description` is still authored by hand: it is the actual control
surface for tool-calling quality on an 8-27B model, and a docstring written for a
human reader is not the same text as an instruction written for a caller that has
one shot at choosing the right tool. That argument rules out introspecting
DOCSTRINGS. It never ruled out pydantic, and the PARAMETERS are now generated from
an argument model per tool, because hand-writing both halves cost this project two
measured failures:

  * Five of twelve tools shipped a parameter with NO description (MEASURED
    2026-08-31: `search_variables.limit`, `get_design_convention.topic`,
    `get_derivation.derivation_id`, `get_contrast_convention.key_or_kind`,
    `check_access.keys`). `limit` changed a protocol — the model passed limit=5
    on 130 of 347 phrase-bearing searches, and a correct item ranked sixth is a
    correct item that was never returned.
  * 59 of 406 `search_variables` calls in the same logs died on the ARGUMENT
    NAME (`query` 33, `search_term` 14, `q` 12) against an error that named the
    name the caller used and never the one the tool wanted.

A `Field(description=...)` is model-facing text written deliberately, next to the
parameter, and unlike a docstring it cannot be omitted silently: a test asserts
every field carries one, and `_check_arguments` names the parameters a caller
missed. Nothing here assembles a JSON Schema by hand —
`BaseModel.model_json_schema()` emits it and `_openai_parameters` only re-keys the
envelope into the shape the tool-calling API expects.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from env import tools as T

Mode = Literal["generation", "benchmark", "curation"]

# Tools that read anything outside the fixed instrument. Present in generation,
# absent in benchmark. They do not exist yet; naming them here is the point —
# the exclusion has to be written down before the tool is written, not after.
RETRIEVAL_TOOLS = {"search_literature", "check_prior_work", "judge_predicate"}


# --------------------------------------------------------------------------- #
# argument models — every field carries model-facing text, and a test enforces it
# --------------------------------------------------------------------------- #

class ResolveVariableArgs(BaseModel):
    """Arguments for `resolve_variable`."""

    key: str = Field(description="e.g. 'm2:Q5.8', 'm3:Q16.1_1', 'm1:Q3.11'")


class SearchVariablesArgs(BaseModel):
    """Arguments for `search_variables`."""

    phrase: str = Field(description="words likely in the question text")
    limit: int = Field(
        default=10,
        description=(
            "How many hits come back. Default 10. This is a CUTOFF, not a "
            "filter: hits are ordered by how much of your wording they cover, "
            "so an item that is the right construct in words you did not use "
            "sits low and disappears from a result that still looks complete. "
            "Lowering it hides candidates rather than sharpening the search, "
            "and a hit you never saw cannot be screened with resolve_variable. "
            "Raise it when a result looks thin, and never conclude from a "
            "short list that the instrument lacks the construct."))


class BrowseVariablesArgs(BaseModel):
    """Arguments for `browse_variables`."""

    module: str = Field(description="'1', '2' or '3'")
    section: str | None = Field(
        default=None,
        description=("a section number from this module's index, e.g. '5'; "
                     "omit for the module page"))


class GetItemGroupArgs(BaseModel):
    """Arguments for `get_item_group`."""

    group_id: str = Field(description="e.g. 'group:m3:Q16.1'")


class NoArgs(BaseModel):
    """Arguments for the tools that take none."""


class GetDesignConventionArgs(BaseModel):
    """Arguments for `get_design_convention`."""

    topic: str = Field(
        description=("one topic name from the list in this description, spelled "
                     "exactly as it appears there. One topic per call; there is "
                     "no 'all'. An unknown topic comes back as not_found with "
                     "the available list, never as a guessed convention."))


class GetDerivationArgs(BaseModel):
    """Arguments for `get_derivation`."""

    derivation_id: str = Field(
        description=("an id exactly as list_derivations returned it — call that "
                     "first. An id is not derivable from the name of a scale, "
                     "and an unrecognised one comes back not_found rather than "
                     "as the nearest recipe."))


class EstimateNArgs(BaseModel):
    """Arguments for `estimate_n`."""

    keys: list[str] = Field(
        description="every key the analysis needs, exposure and outcome included")


class EstimateDetectabilityArgs(BaseModel):
    """Arguments for `estimate_detectability`."""

    baseline_prevalence: float = Field(
        description=("assumed outcome prevalence, 0-1; an assumption you supply, "
                     "recorded as one, and not what the threshold is judged "
                     "against"))


class GetContrastConventionArgs(BaseModel):
    """Arguments for `get_contrast_convention`."""

    key_or_kind: str = Field(
        description=("a resolved variable key, or one kind word: 'likert', "
                     "'scale', 'binary'. Wording that matches no kind falls "
                     "through to a per-standard-deviation contrast rather than "
                     "erroring, so name the kind you mean instead of describing "
                     "the variable."))


class CheckAccessArgs(BaseModel):
    """Arguments for `check_access`."""

    keys: list[str] = Field(
        description=("every key the protocol names — exposure, outcome and each "
                     "covariate. A key this instrument does not carry comes back "
                     "in origin_unknown_keys, which is a DISTINCT state and not a "
                     "pass, so a mistyped key cannot read as cleared."))


# --------------------------------------------------------------------------- #
# the tool table: authored description + generated parameters
# --------------------------------------------------------------------------- #

#: name -> (description shown to the model, argument model). The description is
#: authored; the parameters are generated from the model below.
_TOOLS: dict[str, tuple[str, type[BaseModel]]] = {
    "resolve_variable": (
        ("Resolve one fully qualified variable key against the COMPASS "
         "instrument. ALWAYS call this before writing any key into a protocol. "
         "Returns the exact question wording you must quote verbatim. A bare "
         "question id like 'Q2.4' is NOT a variable name and will come back "
         "ambiguous — keys look like 'm2:Q5.8' (module 1, 2 or 3)."),
        ResolveVariableArgs),
    "search_variables": (
        ("DISCOVERY ONLY. Scored lexical search over question wording to find "
         "candidate variables. You may NOT write a key taken from here into a "
         "protocol — call resolve_variable on it first. Use when you need to "
         "find a covariate but do not know its key. Every hit carries a score "
         "from 0.0 to 1.0 — the share of your search terms' information its "
         "QUESTION WORDING covers; variable keys are not searched, so a term "
         "can never be earned by the key — plus the terms it matched and the "
         "terms it missed. `bm25` is sqlite's raw unnormalised rank, carried so "
         "the ordering can be audited; it is not comparable between queries. "
         "A hit marked below_threshold, or an outcome of "
         "low_confidence, is a LOW-CONFIDENCE CANDIDATE: screen it with "
         "resolve_variable rather than discarding it, because the floor is "
         "conservative and defensible items land below it. below_threshold and "
         "no_match are results about THIS WORDING; neither is a finding that "
         "the instrument lacks the construct. score_discriminates=false means "
         "only ONE term survived tokenisation, so every hit scores 1.000 "
         "whatever it says and the score means nothing — widen the phrase. "
         "Re-query in the words a questionnaire would print, SWAPPING the "
         "terms the result reports as matched by no hit for other wording "
         "rather than deleting them; cutting a query down to one term hides "
         "the miss instead of fixing it."),
        SearchVariablesArgs),
    "browse_variables": (
        ("DISCOVERY ONLY, like search_variables, and the one to use when you "
         "do not know what words the instrument uses. LISTS what a module "
         "contains instead of matching a phrase against it. Call this when a "
         "search comes back empty, low_confidence, or with hits you can tell "
         "are the wrong construct — a miss is a result about your wording, and "
         "browsing is how you find out what the wording actually is. Module "
         "'1' comes back as its complete list of question wordings. Modules "
         "'2' and '3' are too large for that, so they come back as an index of "
         "sections with counts and a signpost; pass section='<n>' from that "
         "index to open one. Every page is COMPLETE at the level it reports, "
         "so an item missing from a listing is genuinely not in that slice — "
         "that is the one thing search cannot tell you. Response coding, value "
         "labels and missing codes are NULL for every variable in this "
         "instrument; do not infer a scale from a listing. You may NOT write a "
         "key taken from here into a protocol — call resolve_variable on it "
         "first and quote that wording."),
        BrowseVariablesArgs),
    "get_item_group": (
        ("List the sub-items of a grid battery and the stem they share. "
         "Sub-item wording is only interpretable together with the stem. Call "
         "this when resolve_variable returns outcome='group'."),
        GetItemGroupArgs),
    "registry_coverage": (
        ("Report which variable registries are populated and which are "
         "declared but empty. Call this before concluding a measure is "
         "unavailable, and before naming any clinical:, lab:, linked: or ehr: "
         "key."),
        NoArgs),
    "get_design_convention": (
        ("Return the project's canonical text on a design topic. Call this "
         "BEFORE deciding clustering, before excluding a mediator, and before "
         "making any claim about a place rather than a person. Topics: "
         "clustering:community_area, adjustment_set:area_exposure, "
         "mediator_exclusion, skip_logic_missingness, small_cells, "
         "place_level_vs_person_level_claims."),
        GetDesignConventionArgs),
    "list_derivations": (
        ("List signed derivations. A multi-item scale or index may ONLY enter "
         "a protocol by naming one of these. Writing an inline recipe is "
         "forbidden and will fail validation."),
        NoArgs),
    "get_derivation": (
        "Return a signed derivation's recipe, unit and component keys.",
        GetDerivationArgs),
    "estimate_n": (
        ("Report the analytic sample size for a set of variables. Currently "
         "DEGRADED: cross-module sets return n=null with n_source='unknown' "
         "and a named blocker, because module co-completion counts do not "
         "exist. Call it anyway — you need the modules_required list and the "
         "blocker for the record. Never invent an n."),
        EstimateNArgs),
    # n_values is NOT advertised, on purpose. It used to be, and the one real
    # record used it to evaluate at n=50, take the 37.8 pp floor that produced,
    # and write a 40 pp "falsifier" just above it. The environment defines the
    # floor a falsifier is measured against; a floor the caller picks is an
    # assumption wearing a measurement's name. The tool still accepts the
    # argument and refuses it in its log, so a caller that guesses it does not
    # get a TypeError that would fail the whole gate.
    #
    # alpha and power left with it on 2026-08-27, for the reason this comment
    # already gives one paragraph up. They were advertised because the tool
    # honours them — but the tool honours n_values in no sense at all and that
    # was never the argument; the argument is that a parameter in the schema is
    # an invitation whatever the tool does with it. MEASURED before the fix:
    # passing alpha=0.50, power=0.50 dropped the supposedly caller-independent
    # bound at n=1000 from 8.86 pp to 2.13, six times the swing prevalence ever
    # bought. The bound now fixes both, so the lever is closed in the code; this
    # removes the invitation as well, because a caller that never sees the
    # parameter cannot launder a loosened one into `assumptions`, which
    # apply_tool_authority stamps into the record as authoritative.
    #
    # They are still ACCEPTED and still shape the caller's own disclosure curve.
    # Unlike a sample size or a prevalence, a significance level is not an
    # unknown the model might know something about — it is a convention — so
    # there is nothing here for the model to contribute and nothing lost by not
    # asking.
    "estimate_detectability": (
        ("Return the smallest detectable effect across a FIXED set of "
         "candidate sample sizes chosen by the environment. Call this BEFORE "
         "writing falsifier_threshold. Two curves come back: one at the "
         "prevalence you assume, and sde_by_n_worst_case_prevalence, which "
         "depends on nothing you assert. The record is judged against the "
         "second — a threshold below THAT curve cannot be falsified by this "
         "study and the record will be rejected. You cannot choose the sample "
         "sizes."),
        EstimateDetectabilityArgs),
    "get_contrast_convention": (
        ("Return the stated contrast for an exposure of a given kind (Likert, "
         "scale, binary). This is a design convention, not a data property."),
        GetContrastConventionArgs),
    "check_access": (
        ("Run the location-reconstruction gate over every key the protocol "
         "names. Call this LAST, once the covariate lists are settled. Returns "
         "a decision plus its working."),
        CheckAccessArgs),
}


def _openai_parameters(model: type[BaseModel]) -> dict:
    """Translate a pydantic argument model into an OpenAI parameters block.

    `model_json_schema()` does the work; this only re-keys the envelope and
    strips what is noise in a prompt. `title` is pydantic's echo of the field
    name and buys a small model nothing. `anyOf: [T, null]` is how an optional
    field is spelled in JSON Schema and reads to a caller as a second type it
    might pass; the parameter simply being absent already says "omit it", so the
    null branch and a null default are dropped.

    Args:
        model: The argument model for one tool.

    Returns:
        `{"type": "object", "required": [...], "properties": {...}}`, with
        `required` omitted when the tool takes no required argument.
    """
    js = model.model_json_schema()
    props: dict[str, dict] = {}
    for name, raw in js.get("properties", {}).items():
        spec = {k: v for k, v in raw.items() if k != "title"}
        branches = [b for b in spec.pop("anyOf", []) if b.get("type") != "null"]
        if len(branches) == 1:
            spec = {**branches[0], **spec}
        if spec.get("default", ...) is None:
            del spec["default"]
        props[name] = spec
    out: dict = {"type": "object"}
    if js.get("required"):
        out["required"] = list(js["required"])
    out["properties"] = props
    return out


#: The model-visible function schemas. GENERATED — edit `_TOOLS` and the argument
#: models, never this. `benchmark/contamination_check.py::model_visible_surface`
#: scans `json.dumps` of these as the `tool_descriptions` surface.
SCHEMAS: dict[str, dict] = {
    name: {"description": description, "parameters": _openai_parameters(model)}
    for name, (description, model) in _TOOLS.items()
}


def true_signature(fn: Callable) -> inspect.Signature:
    """The signature of the tool underneath `env.tools._logged`.

    `_logged` wraps every tool in `def wrapper(*a, **kw)` and copies only
    `__name__` and `__doc__` — no `functools.wraps`, so no `__wrapped__` and
    `inspect.signature` reports `(*a, **kw)`, which accepts anything and tells a
    caller nothing. env/tools.py belongs to another lane, so the wrapper is
    unwrapped from the outside instead: `inspect.unwrap` follows any real
    `__wrapped__` chain, and the closure cell named `fn` is `_logged`'s own
    handle on the function it wrapped.

    Args:
        fn: A registry callable, wrapped or not.

    Returns:
        The signature of the innermost function.
    """
    seen: set[int] = set()
    while True:
        fn = inspect.unwrap(fn)
        code = getattr(fn, "__code__", None)
        if code is None or "fn" not in code.co_freevars or fn.__closure__ is None:
            return inspect.signature(fn)
        inner = fn.__closure__[code.co_freevars.index("fn")].cell_contents
        if not callable(inner) or id(inner) in seen:
            return inspect.signature(fn)
        seen.add(id(inner))
        fn = inner


def _argument_help(name: str, model: type[BaseModel]) -> str:
    """Name the parameters a tool takes, required ones first.

    Args:
        name: Tool name.
        model: Its argument model.

    Returns:
        A phrase like `search_variables takes: phrase (required), limit`.
    """
    fields = model.model_fields
    required = [f for f, i in fields.items() if i.is_required()]
    optional = [f for f in fields if f not in required]
    if not fields:
        return f"{name} takes no arguments"
    named = [f"{f} (required)" for f in required] + optional
    return f"{name} takes: {', '.join(named)}"


def _check_arguments(name: str, model: type[BaseModel], accepted: set[str],
                     args: tuple, kwargs: dict) -> None:
    """Raise a TypeError that names the parameter the tool wanted.

    MEASURED 2026-08-31 over `run/*.tool_log.jsonl` + `run/superseded/` +
    `run/logs/`: 59 of 406 `search_variables` calls died on the argument name —
    `query` 33, `search_term` 14, `q` 12 — and CPython's own message ("got an
    unexpected keyword argument 'query'") names the name the caller invented and
    never `phrase`. A caller cannot correct a name it is not told.

    `accepted` is the argument model's fields UNION the real signature's, not the
    model's alone: `estimate_detectability` deliberately withholds `n_values`,
    `alpha` and `power` from the schema while the tool still accepts them and
    refuses them in its log, precisely so a guessed argument costs a refusal
    rather than the whole gate. Rejecting an unadvertised-but-real parameter here
    would reintroduce the failure that comment exists to prevent.

    TypeError, not a ValueError or an error dict, because that is what
    `mcp/compass_server.py::_call` catches and hands back to the model, and what
    `tests/test_browse.py` pins.

    Args:
        name: Tool name.
        model: Its argument model.
        accepted: Every keyword the underlying function will actually take.
        args: Positional arguments; their names cannot be wrong.
        kwargs: Keyword arguments as the caller spelled them.

    Raises:
        TypeError: On a keyword the function has no parameter for, or a missing
            required parameter.
    """
    unknown = [k for k in kwargs if k not in accepted]
    if unknown:
        raise TypeError(
            f"{name} has no parameter {', '.join(repr(u) for u in sorted(unknown))}. "
            f"{_argument_help(name, model)}. Re-send the same call with the "
            f"parameter named above.")
    if args:
        return  # a positional argument has no name to get wrong
    missing = [f for f, i in model.model_fields.items()
               if i.is_required() and f not in kwargs]
    if missing:
        raise TypeError(
            f"{name} is missing {', '.join(repr(m) for m in missing)}. "
            f"{_argument_help(name, model)}.")


def _checked(name: str, model: type[BaseModel], fn: Callable) -> Callable:
    """Wrap a tool so a misnamed argument comes back naming the right one.

    Args:
        name: Tool name.
        model: Its argument model.
        fn: The registry callable, `_logged`-wrapped.

    Returns:
        The same callable, with the argument-name check in front of it.
    """
    accepted = set(model.model_fields) | set(true_signature(fn).parameters)

    def call(*args: object, **kwargs: object) -> object:
        _check_arguments(name, model, accepted, args, kwargs)
        return fn(*args, **kwargs)

    call.__name__ = name
    call.__doc__ = fn.__doc__
    call.__wrapped__ = fn  # type: ignore[attr-defined]
    return call


def build_registry(mode: Mode) -> tuple[dict[str, Callable], list[dict]]:
    """Return (callables, openai_tool_schemas) for a mode.

    `mode` is required and has no default: a default is how benchmark runs end up
    silently in generation mode.

    Args:
        mode: Which tool set to construct.

    Returns:
        The callables for this mode and the schemas the model is shown.

    Raises:
        ValueError: On an unknown mode.
    """
    if mode not in ("generation", "benchmark", "curation"):
        raise ValueError(f"unknown mode {mode!r}")

    names = set(T.TOOLS)
    if mode == "benchmark":
        names -= RETRIEVAL_TOOLS
    elif mode == "curation":
        names -= {"estimate_detectability", "estimate_n"}

    callables = {n: (_checked(n, _TOOLS[n][1], T.TOOLS[n]) if n in _TOOLS
                     else T.TOOLS[n])
                 for n in sorted(names)}
    schemas = [{"type": "function",
                "function": {"name": n, **SCHEMAS[n]}}
               for n in sorted(names) if n in SCHEMAS]
    return callables, schemas
