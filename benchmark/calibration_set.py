"""benchmark/calibration_set.py — C5: the environment-confirmed calibration set.

WHY THIS IS THE ONLY CONTAMINATION CONTROL THAT ELIMINATES RATHER THAN BOUNDS
THE RISK. Every other control in this project narrows the chance that a design
came from recall rather than reasoning. This one removes the chance entirely,
for one slice: a pair is placed here only when the reason it cannot be
specified is a property of the INSTRUMENT — a key with no response coding, a
battery with no signed recipe, two anchors that are the same question twice, a
registry the study team has not populated — never a property of what any paper
found. No published analysis could contain the "answer" to a pair that has no
answerable design, so a refusal here cannot be recall wearing reasoning's
clothes. This is the same move NewtonBench makes by mutating a physical law
into a counterfactual variant (`references/PRIOR_ART_CONTAMINATION.md`), done
here with dictionary structure instead of a mutated constant.

WHAT "DERIVABLE, NOT ASSERTED" MEANS IN THIS FILE. Every row's verdict is
computed by `_evaluate`, which calls the REAL environment tools
(`env.tools.resolve_variable`, `.registry_coverage`, `.list_derivations`,
`.get_derivation`) live and reads the field of their ACTUAL return value that
forces the verdict. Nothing here is a hand-typed RefusalReason next to a pair
that looks right; `build_calibration_set()` and every test in
`tests/test_calibration_set.py` call the same `_evaluate`, so a reader can
re-run `_evaluate(exposure_key, outcome_key)` on any row and get the identical
verdict and evidence back. `_evaluate` is the single source of truth for both
the build and the check.

THE FOUR CATEGORIES THE SPEC NAMES, AND THE `RefusalReason` EACH ENTAILS.
Handoff T6b (`git show 0a01d7e:HANDOFF_AGENT_PIPELINE.md`) names four
environment-checkable conditions. Each maps onto exactly one
`agent.schema.RefusalReason` member, and the mapping is load-bearing — a row
built under one category and found by `_evaluate` to entail a DIFFERENT reason
would be a bug in this file, not a fact to paper over, so `build_calibration_set`
asserts agreement at build time and raises if it ever disagrees.

    free-text anchor                    -> free_text_anchor
    grid stem, no matching signed
      derivation                        -> no_signed_derivation
    both anchors in one construct       -> anchors_are_the_same_construct
    clinical:/lab:/ehr: key             -> registry_empty

"BOTH ANCHORS IN ONE CONSTRUCT" IS BUILT FROM GRID SUB-ITEMS ONLY, AND THAT IS
A NARROWER CLAIM THAN THE SPEC TEXT. 137 constructs in the dictionary carry
more than one distinct key; 64ish are grid batteries (two sub-items sharing one
`group_key`), the rest are roster repeats (one question asked once per
household member, e.g. `m1:1_Q6.2` .. `m1:15_Q6.2`) or the one duplicate-qid
pair (`m2:Q785~1`/`~2`, confirmed live to be two UNRELATED questions that
happen to share a bare qid — checked, not assumed, after `stem_text` equality
looked like it might generalise and turned out to collide on 4 unrelated
construct pairs first). `RefusalReason.anchors_are_the_same_construct` needs
only `{"resolve_variable"}` evidence per `agent/schema.py`, but `resolve_variable`
returns `group_key` only for a grid sub-item; for a roster repeat it returns
`group_key=None` AND `stem_text=None` for every instance — checked live on
`m1:1_Q6.2`/`m1:2_Q6.2` — so the tool's own return value carries NOTHING that
would let a caller show two roster keys share a construct. The fact is still
true (the dictionary's `construct_key` says so), but it is not RESOLVE_VARIABLE-
DERIVABLE the way the spec's evidence requirement demands, so this file builds
the category only from the ~40 clean grid-subitem constructs, which the
requirement can actually reach.

A FIFTH REGISTRY, FOUND WHILE BUILDING, NOT NAMED IN THE SPEC. The spec's own
prose names three empty registries. `registry_coverage()` — called live, not
copied from memory — reports FOUR as `coverage: "none"`: `clinical`, `lab`,
`ehr`, and also `linked`, blocked on `area_measure_inventory` rather than
`study_team_confirmation`, but empty by the identical mechanism. Excluding it
would be silently overriding what the environment says to match the spec's
wording instead of reporting the mismatch, which is the opposite of the
instruction under §5 rule "fix the fixture, not the rule". So `linked:` rows are
built too, each one's `rationale` says in so many words that the spec's prose
did not name this prefix and why it is included anyway. `KEY_PATTERN` in
`agent/schema.py` accepts a `linked:` key exactly the way it accepts `clinical:`
or `lab:`; `AreaMeasureRef` is the schema's DESIGNED path for a linked measure,
but nothing stops a `VariableRef` from naming one, and `resolve_variable` cannot
tell the two apart. Confirmed live and reported below.

WHAT COULD NOT BE BUILT, AND WHY — READ THIS BEFORE ASSUMING ALL EIGHT
`RefusalReason` MEMBERS ARE COVERED. Only four of the eight are represented
here, matching the spec exactly. The other four were checked, not skipped:

  - `access_gate_refused` requires `env.tools.check_access` to return
    `decision="refer"`, which fires only when `reconstruction_load` (grouped by
    PLACE — residence, workplace, school) exceeds `budget=3`. A two-key pair
    supplies at most two keys, so at most two places, so `load <= 2 < 3` always
    and `decision` can never be anything but `pass` for a bare pair. Confirmed
    live against several location-bearing keys. This reason needs a full
    covariate list, not a pair, and this calibration set is pairs.
  - `no_contrast_definable` requires `get_contrast_convention` to report no
    coverage for a kind. Read `env/tools.py`: the function's `if/elif/else`
    chain ends in an unconditional `else` branch that returns
    `outcome="ok"` with a default contrast for ANY input. As written today it
    has no failure path at all, so nothing — dictionary-derived or otherwise —
    can entail this reason. A genuine environment gap, not a gap in this file.
  - `exposure_unresolvable` / `outcome_unresolvable` are, as `_refusal_is_earned`
    defines them in `agent/schema.py`, satisfied by ANY row that cites
    `resolve_variable` as a tool, whether or not its outcome was a failure — the
    validator checks the SET of tool names cited, never their content. A row
    built under `free_text_anchor` or `registry_empty` also cites
    `resolve_variable` and would satisfy this validator's letter, which means
    the two reasons are not currently distinguishable from the other two by
    the validator alone. Building rows "for" them would either duplicate an
    existing category under a different label or require a key that resolves
    to `ambiguous` — reachable (121 bare qids collide, confirmed live below) but
    not a pair "enumerated from build/dictionary.json" in the sense the spec
    means: an ambiguous key is a malformed CALL, not a property of two real
    constructs paired against each other. Left unbuilt and reported, per the
    instruction to treat a mismatch as a finding rather than force-fitting it.

SIZE AND BALANCE. Four unanswerable categories at N=20 each (80 rows) and one
answerable control arm at N=80 (a clean 1:1 ratio against the combined
unanswerable count, so a per-category refusal rate and the control's
over-refusal rate sit on the same denominator scale). `free_text_anchor`,
`no_signed_derivation` and `anchors_are_the_same_construct` each draw from a
real, checked pool comfortably above 20 (105, 44 and 41 members respectively —
see the pool-size assertions in `build_calibration_set`), so 20 is neither a
single unsupportable member nor most of the available evidence. `registry_empty`
is the one deliberately UNEVEN internally: it is 4 prefixes x 5 rows, and the
5 exist to show the refusal holds across different partner contexts, not
because the registries differ — `registry_coverage()` returns the identical
`coverage: "none"` fact regardless of which real key sits on the other side of
the pair, so within one prefix the five rows are partly redundant BY
CONSTRUCTION, not by an oversight; it is still built at 20 total, matching the
other three, so a per-category rate stays comparable across all four. Twenty
per category and eighty control pairs is a size this module can build, evaluate
and pin in tests in under a second with zero model calls; nothing about the
count is a claim that it is the "right" calibration size for an eventual power
calculation, which needs the refusal path (C4) to even define a rate to power.

WHAT ANSWERABLE MEANS HERE, PRECISELY, AND WHAT IT DOES NOT MEAN. A control-arm
pair is one `_evaluate` finds NONE of the four conditions above. That is a
narrower claim than "this design is well-powered" or "this record reaches
`ready_for_review`" — HANDOFF §6 records that every live record's `n_source` is
`unknown` because module co-completion counts do not exist, so a control pair
still ends in `status=draft`. "Answerable" here means only what this file's
mandate covers: nothing the ENVIRONMENT can check forces a refusal, so an
honest Specifier has no environment-supplied excuse to refuse it, and a refusal
on one of these 80 is over-refusal by this file's own instrument, whatever the
eventual power turns out to be. Established by calling the same live
`resolve_variable` and `env.tools.check_access` this module uses for the
refusal side, not by construction alone — see `_verify_answerable` below.

DO NOT RUN THE REFUSAL PATH AGAINST THIS SET YET. C4 (wiring `NotSpecifiable`
into the Specifier) is Lane A's work, in flight, unmerged at the time this file
was written. This module only builds and pins the set; nothing here drives a
model.

NOTHING PAPER-DERIVED. Every fact this file uses comes from
`build/dictionary.json`, `curated/derivations/*.json` (recipe metadata: unit,
component keys — never a paper's numbers) and `env/tools.py`'s own return
values. `codebook.csv` is never read (§5 rule 1). No cohort paper, PMID, exposure
or realised n from `benchmark/cohort_papers.py` or `benchmark/prevalence_key.py`
is imported or referenced — this file could be built if COMPASS had never
published anything, which is the entire point of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from agent.schema import RefusalReason
from env.tools import (
    dictionary_version,
    get_derivation,
    list_derivations,
    registry_coverage,
    resolve_variable,
)

ROOT = Path(__file__).resolve().parent.parent

#: The three prefixes the C5 spec text names verbatim. `_empty_registry_prefixes`
#: below is the environment-derived set actually used to build rows, and it is a
#: superset of this one — see the module docstring's "fifth registry" section.
SPEC_NAMED_EMPTY_PREFIXES = frozenset({"clinical", "lab", "ehr"})

#: Rows per unanswerable category, and the size of the answerable control arm.
#: Justified in the module docstring's SIZE AND BALANCE section.
#: Dropped 2026-08-28. The category entailed a refusal from "this construct is a
#: grid battery and no signed derivation covers its members". HARD RULE 5 of
#: `agent/specifier.py::SYSTEM` is narrower — a multi-item *scale* enters only
#: through a signed derivation — and nothing in `build/dictionary.json`
#: distinguishes a scale from a checklist: not `is_grid_subitem`, not
#: `matrix_block`, not `construct_key`, and `generate/funnel.py::s2_prune` sets
#: `requires_derivation` from the same broad `is_group` test.
#:
#: The pool was not merely ambiguous, it was wrong. Its members included
#: `m1:Q2.15` ("What is your birthday? - Month / - Day / - Year") and `m1:Q2.2`
#: ("What is your first name and last name? - First Name / - Last Name"): single
#: questions split across input fields, with nothing to derive. A row asserting
#: that the correct output is a refusal because no signed derivation covers
#: "What is your birthday?" would penalise the correct answer.
#:
#: `_no_signed_derivation_pool` is kept, unused by the build, because the
#: category becomes valid the moment the study team says which batteries are
#: scales — that is instrument metadata they can supply, and it is the second
#: ask after the module co-completion counts.
WHY_NO_SIGNED_DERIVATION_WAS_DROPPED = (
    "no dictionary field distinguishes a multi-item scale from a checklist, and "
    "the pool contained compound-field questions (birthday, name) with nothing "
    "to derive"
)

ROWS_PER_UNANSWERABLE_CATEGORY = 20
ROWS_PER_REGISTRY_EMPTY_PREFIX = 5
ANSWERABLE_ROWS = 60


class Evidence(NamedTuple):
    """One live tool call and the field of its return value that entails a verdict.

    Attributes:
        tool: Name of the function in `env.tools` that was called.
        argument: The key passed to it, verbatim.
        field: Dotted path into the tool's return dict naming the entailing
            field — e.g. `"is_free_text"` or `"registries.clinical.coverage"`.
        value: `str()` of that field's real value, from the actual call this
            session made, not typed in by hand.
    """

    tool: str
    argument: str
    field: str
    value: str


class CalibrationPair(NamedTuple):
    """One pair in the calibration set, with the evidence entailing its verdict.

    Attributes:
        pair_id: Stable id, `cal-<category>-<NN>`.
        exposure_key: The exposure anchor — a dictionary key, a bare construct
            key (for a battery with no matching derivation), or a synthetic
            `clinical:`/`lab:`/`linked:`/`ehr:` key.
        outcome_key: The outcome anchor, same rules.
        category: One of the four spec categories, or `"answerable_control"`.
        refusal_reason: The `RefusalReason` `_evaluate` computed, or `None` for
            a control-arm pair `_evaluate` found no reason to refuse.
        dictionary_version: The `build/dictionary.json` hash this row was
            computed against.
        evidence: The live tool calls that force the verdict.
        rationale: One sentence a reader can check against `evidence` by hand.
    """

    pair_id: str
    exposure_key: str
    outcome_key: str
    category: str
    refusal_reason: RefusalReason | None
    dictionary_version: str
    evidence: tuple[Evidence, ...]
    rationale: str


class _Verdict(NamedTuple):
    """`_evaluate`'s raw result, before it is wrapped into a `CalibrationPair`."""

    reason: RefusalReason | None
    evidence: tuple[Evidence, ...]
    rationale: str


class _Resolved(NamedTuple):
    """One anchor's shape, as read off the dictionary — not the live tool call.

    `_evaluate` still calls the live tool for its evidence; this is the ground
    truth `_evaluate` checks that call's answer against.
    """

    key: str
    construct_key: str
    is_free_text: bool
    is_construct_battery: bool
    member_keys: tuple[str, ...]
    group_key: str | None


# --------------------------------------------------------------------------- #
# dictionary access — a private, cached read, independent of env.tools'
# internal caches (agent/schema.py's _dictionary_wording/_signed_derivations
# take the same approach: this file must work whether or not env.tools has
# been imported first, and must never reach into another module's `_`-prefixed
# state).
# --------------------------------------------------------------------------- #

_BY_KEY: dict[str, dict] | None = None
_BY_CONSTRUCT: dict[str, list[dict]] | None = None


def _load_dictionary() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Index `build/dictionary.json` by literal key and by construct key.

    Returns:
        `(by_key, by_construct)`, cached after the first call.
    """
    global _BY_KEY, _BY_CONSTRUCT
    if _BY_KEY is None or _BY_CONSTRUCT is None:
        entries = json.loads((ROOT / "build" / "dictionary.json").read_text())["entries"]
        by_key: dict[str, dict] = {}
        by_construct: dict[str, list[dict]] = {}
        for e in entries:
            by_key[e["key"]] = e
            by_construct.setdefault(e["construct_key"], []).append(e)
        _BY_KEY, _BY_CONSTRUCT = by_key, by_construct
    return _BY_KEY, _BY_CONSTRUCT


_SIGNED_COMPONENT_SETS: dict[str, frozenset[str]] | None = None


def _signed_component_sets() -> dict[str, frozenset[str]]:
    """Every signed derivation's `component_keys`, via the live tools.

    Calls `list_derivations()` then `get_derivation()` on each id — the same
    two calls a Specifier reasoning about a grid battery would make — rather
    than reading `curated/derivations/*.json` directly, so the evidence this
    module records is the tools' own answer, not a shortcut around them.

    Returns:
        Derivation id to the frozenset of its signed `component_keys`, cached
        after the first call.
    """
    global _SIGNED_COMPONENT_SETS
    if _SIGNED_COMPONENT_SETS is None:
        ids = list(list_derivations()["derivations"])
        _SIGNED_COMPONENT_SETS = {
            did: frozenset(str(k) for k in get_derivation(did)["component_keys"])
            for did in ids
        }
    return _SIGNED_COMPONENT_SETS


_EMPTY_REGISTRY_PREFIXES: tuple[str, ...] | None = None


def _empty_registry_prefixes() -> tuple[str, ...]:
    """Registries `registry_coverage()` reports as `coverage: "none"`, live.

    Returns:
        Sorted prefixes, cached after the first call. Confirmed 2026-08-28:
        `("clinical", "ehr", "lab", "linked")` — four, not the three the C5
        spec text names; see the module docstring.
    """
    global _EMPTY_REGISTRY_PREFIXES
    if _EMPTY_REGISTRY_PREFIXES is None:
        regs = registry_coverage()["registries"]
        _EMPTY_REGISTRY_PREFIXES = tuple(sorted(
            str(name) for name, info in regs.items()
            if info["coverage"] == "none"))
    return _EMPTY_REGISTRY_PREFIXES


def _resolve_entry_or_construct(key: str) -> _Resolved:
    """Classify `key` as a literal dictionary key or a bare construct key.

    Args:
        key: A dictionary key (e.g. `"m2:Q5.8"`) or a construct key that names
            a battery/roster as a whole (e.g. `"m1:Q2.2"`).

    Returns:
        The shape `_evaluate` reasons about.

    Raises:
        ValueError: `key` is neither — this module only evaluates real
            dictionary content, never an invented key.
    """
    by_key, by_construct = _load_dictionary()
    entry = by_key.get(key)
    if entry is not None:
        return _Resolved(key, entry["construct_key"], bool(entry["is_free_text"]),
                          False, (), entry["group_key"])
    members = by_construct.get(key)
    if members is not None:
        return _Resolved(
            key, key, any(bool(m["is_free_text"]) for m in members), True,
            tuple(sorted(m["key"] for m in members)), members[0]["group_key"])
    raise ValueError(
        f"{key!r} is neither a literal dictionary key nor a construct key in "
        f"build/dictionary.json — this module only evaluates real dictionary "
        f"content, never an invented one")


def _evaluate(exposure_key: str, outcome_key: str) -> _Verdict:
    """The single source of truth: what does the environment say about this pair?

    Calls the real `env.tools` functions and returns the `RefusalReason` their
    return values entail, in the priority order a Specifier would actually hit
    them: a registry that does not exist is checked before anything about the
    dictionary is read, because such a key is not IN the dictionary to read.

    Args:
        exposure_key: The exposure anchor.
        outcome_key: The outcome anchor.

    Returns:
        `_Verdict(None, ..., ...)` when none of the four checked conditions
        holds — the pair clears every gate this module checks.
    """
    # 1. registry-empty: checked first, because clinical:/lab:/linked:/ehr:
    # keys are never entries in build/dictionary.json, so every check below
    # would raise on one before this rule ever got a chance to fire.
    empty = _empty_registry_prefixes()
    for role, key in (("exposure", exposure_key), ("outcome", outcome_key)):
        prefix = key.split(":", 1)[0]
        if prefix in empty:
            cov = registry_coverage()
            res = resolve_variable(key)
            coverage = str(cov["registries"][prefix]["coverage"])
            spec_note = ("" if prefix in SPEC_NAMED_EMPTY_PREFIXES else
                        " (the C5 spec text names clinical/lab/ehr; `linked` is "
                        "not in that prose — included because registry_coverage() "
                        "reports it empty by the same mechanism, see this file's "
                        "module docstring)")
            evidence: tuple[Evidence, ...] = (
                Evidence("registry_coverage", prefix,
                        f"registries.{prefix}.coverage", coverage),
                Evidence("resolve_variable", key, "outcome", str(res["outcome"])),
            )
            rationale = (
                f"{role} key {key!r} names the {prefix!r} registry, which "
                f"registry_coverage() reports as coverage={coverage!r}, and "
                f"resolve_variable({key!r}) returns outcome={res['outcome']!r} "
                f"rather than 'unique'.{spec_note}")
            return _Verdict(RefusalReason.registry_empty, evidence, rationale)

    exp, out = _resolve_entry_or_construct(exposure_key), \
        _resolve_entry_or_construct(outcome_key)

    # 2. free-text anchor.
    for role, key, info in (("exposure", exposure_key, exp),
                            ("outcome", outcome_key, out)):
        if info.is_free_text:
            res = resolve_variable(key)
            evidence = (Evidence("resolve_variable", key, "is_free_text",
                                str(res["is_free_text"])),)
            rationale = (f"{role} key {key!r} has is_free_text=True in the "
                        f"dictionary, confirmed by resolve_variable({key!r}) — "
                        f"no response coding exists for a free-text item, so it "
                        f"cannot anchor a design (generate/funnel.py's s2_prune "
                        f"applies this identical rule mechanically).")
            return _Verdict(RefusalReason.free_text_anchor, evidence, rationale)

    # 3. both anchors resolve to one construct.
    if exp.construct_key == out.construct_key:
        res_e, res_o = resolve_variable(exposure_key), resolve_variable(outcome_key)
        evidence = (
            Evidence("resolve_variable", exposure_key, "group_key",
                    str(res_e["group_key"])),
            Evidence("resolve_variable", outcome_key, "group_key",
                    str(res_o["group_key"])),
        )
        rationale = (
            f"{exposure_key!r} and {outcome_key!r} both carry construct_key="
            f"{exp.construct_key!r} in the dictionary — two members of the same "
            f"question, not two constructs — corroborated by resolve_variable "
            f"returning the identical group_key {res_e['group_key']!r} for both.")
        return _Verdict(RefusalReason.anchors_are_the_same_construct, evidence,
                        rationale)

    # 4. a battery anchor with no signed derivation matching its exact members.
    signed = _signed_component_sets()
    for role, key, info in (("exposure", exposure_key, exp),
                            ("outcome", outcome_key, out)):
        if not info.is_construct_battery:
            continue
        match = next((did for did, keys in signed.items()
                     if keys == frozenset(info.member_keys)), None)
        if match is not None:
            continue
        res = resolve_variable(key)
        lst = list_derivations()
        evidence = (
            Evidence("resolve_variable", key, "outcome", str(res["outcome"])),
            Evidence("list_derivations", "", "derivations", str(lst["derivations"])),
        )
        rationale = (
            f"{role} key {key!r} is a battery of {len(info.member_keys)} items "
            f"with no matching entry in curated/derivations/ — list_derivations() "
            f"returns {lst['derivations']!r} and none of their signed "
            f"component_keys equals this construct's member set — so it cannot "
            f"be named as a single anchor without inventing a recipe mid-protocol, "
            f"which agent/schema.py's DerivationRef forbids.")
        return _Verdict(RefusalReason.no_signed_derivation, evidence, rationale)

    return _Verdict(
        None, (),
        f"{exposure_key!r} and {outcome_key!r} clear all four "
        f"environment-checkable gates this module evaluates: neither is "
        f"free text, neither names an empty registry, they resolve to "
        f"different constructs, and neither is an unresolved battery.")


# --------------------------------------------------------------------------- #
# row construction — draws pools from the dictionary, builds rows, verifies
# _evaluate agrees with the category each pool was drawn to represent.
# --------------------------------------------------------------------------- #

def _final_clean_pool() -> list[dict]:
    """Plain, unambiguous dictionary entries — never free text or grouped.

    Never free text, never a grid sub-item, never a roster repeat, never a
    text companion, and their own construct_key (this excludes the one
    duplicate-qid entry disambiguated by `~N`).

    Returns:
        Entries sorted by key, for a deterministic draw order.
    """
    by_key, _ = _load_dictionary()
    pool = [e for e in by_key.values()
            if not e["is_free_text"] and not e["is_grid_subitem"]
            and not e["is_roster_repeat"] and not e["is_text_companion"]
            and e["construct_key"] == e["key"]]
    return sorted(pool, key=lambda e: str(e["key"]))


def _free_text_pool() -> list[dict]:
    """Standalone free-text entries, excluding a grid sub-item's own companion.

    Excludes a grid sub-item's own "please specify" companion field, so the
    row's only carried condition is is_free_text.

    Returns:
        Entries sorted by key.
    """
    by_key, _ = _load_dictionary()
    pool = [e for e in by_key.values()
            if e["is_free_text"] and not e["is_grid_subitem"]
            and not e["is_text_companion"]]
    return sorted(pool, key=lambda e: str(e["key"]))


def _no_signed_derivation_pool() -> list[dict]:
    """Grid-battery constructs with no matching signed derivation.

    Returns:
        One dict per construct (`construct_key`, `member_keys`, `module`),
        sorted by construct_key, excluding any construct that is ALSO free
        text (so the row's only carried condition is the missing derivation).
    """
    _, by_construct = _load_dictionary()
    signed = _signed_component_sets()
    out = []
    for ck, rows in by_construct.items():
        if not any(r["is_grid_subitem"] for r in rows):
            continue
        if any(r["is_free_text"] for r in rows):
            continue
        members = tuple(sorted(r["key"] for r in rows))
        if any(keys == frozenset(members) for keys in signed.values()):
            continue
        out.append({"construct_key": ck, "member_keys": members,
                    "module": rows[0]["module"]})
    return sorted(out, key=lambda c: str(c["construct_key"]))


def _same_construct_pool() -> list[dict]:
    """Grid-battery constructs with >=2 members, for a same-construct pair.

    Built from two of that construct's own member keys. Excludes `m3:Q16.1`,
    the one construct WITH a signed derivation
    (`social_cohesion_scale`) — using it here would still correctly entail
    `anchors_are_the_same_construct` (pairing two of its own sub-items is a
    tautology independent of whether the whole battery has a derivation), but
    it is `generate/worked_example.py`'s worked construct and keeping it out of
    this pool keeps the two calibration categories visibly disjoint in a
    report. Also excludes anything free text.

    Returns:
        One dict per construct, sorted by construct_key.
    """
    _, by_construct = _load_dictionary()
    out = []
    for ck, rows in by_construct.items():
        if ck == "m3:Q16.1":
            continue
        if not any(r["is_grid_subitem"] for r in rows):
            continue
        if any(r["is_free_text"] for r in rows):
            continue
        members = sorted(r["key"] for r in rows)
        if len(members) < 2:
            continue
        out.append({"construct_key": ck, "member_keys": tuple(members)})
    return sorted(out, key=lambda c: str(c["construct_key"]))


#: category string -> the RefusalReason a row of that category must entail.
#: Deliberately equal to `RefusalReason.value` for all four: a row's `category`
#: and `str(row.refusal_reason.value)` read identically for every unanswerable
#: row, so a reader never has to cross-reference this table by hand.
_EXPECTED_REASON: dict[str, RefusalReason] = {
    "free_text_anchor": RefusalReason.free_text_anchor,
    "no_signed_derivation": RefusalReason.no_signed_derivation,
    "anchors_are_the_same_construct": RefusalReason.anchors_are_the_same_construct,
    "registry_empty": RefusalReason.registry_empty,
}


def _build_row(pair_id: str, category: str, exposure_key: str, outcome_key: str,
              version: str) -> CalibrationPair:
    """Evaluate one pair and wrap it into a `CalibrationPair`.

    Args:
        pair_id: Stable id for this row, e.g. `"cal-free_text_anchor-01"`.
        category: The category this row was drawn to represent — one of
            `_EXPECTED_REASON`'s keys, or `"answerable_control"`.
        exposure_key: The exposure anchor.
        outcome_key: The outcome anchor.
        version: `build/dictionary.json`'s version_hash.

    Returns:
        The evaluated row.

    Raises:
        AssertionError: `_evaluate` disagrees with the category this pair was
            drawn to represent — a bug in this file's pool-construction, never
            silently swallowed. Answerable rows are exempt from this check
            (they are verified separately by `_verify_answerable`, which also
            checks `check_access`, not just `_evaluate`).
    """
    verdict = _evaluate(exposure_key, outcome_key)
    expected = _EXPECTED_REASON.get(category)
    if expected is not None and verdict.reason is not expected:
        raise AssertionError(
            f"pool-construction bug: pair ({exposure_key!r}, {outcome_key!r}) "
            f"was drawn for category {category!r} but _evaluate says "
            f"{verdict.reason!r}. Fix the pool, not this check.")
    return CalibrationPair(pair_id, exposure_key, outcome_key, category,
                           verdict.reason, version, verdict.evidence,
                           verdict.rationale)


def _verify_answerable(pair: CalibrationPair) -> None:
    """The control arm's extra check: `check_access` too, not just `_evaluate`.

    `_evaluate` only computes the four gates this module builds rows for.
    `access_gate_refused` is a fifth `RefusalReason`; the module docstring
    argues it is structurally unreachable for a bare two-key pair, and this is
    that argument made a live, per-row check rather than a paragraph.

    Args:
        pair: An answerable-control-arm row.

    Raises:
        AssertionError: `_evaluate` found a refusal reason, or the live
            `check_access` call did not return `decision="pass"`.
    """
    from env.tools import check_access
    if pair.refusal_reason is not None:
        raise AssertionError(
            f"control-arm pair {pair.pair_id} was found unanswerable "
            f"({pair.refusal_reason}) — pool-construction bug.")
    access = check_access([pair.exposure_key, pair.outcome_key])
    if access["decision"] != "pass":
        raise AssertionError(
            f"control-arm pair {pair.pair_id} failed check_access: "
            f"{access['decision']!r}, load={access['reconstruction_load']}")


_CACHE: tuple[CalibrationPair, ...] | None = None


def build_calibration_set() -> tuple[CalibrationPair, ...]:
    """Build every row: the three unanswerable categories, then the control arm.

    Deterministic: every pool is sorted before drawing, so re-running this
    against an unchanged `build/dictionary.json` reproduces the identical set.

    Returns:
        `ROWS_PER_UNANSWERABLE_CATEGORY * 2 + ROWS_PER_REGISTRY_EMPTY_PREFIX *
        len(_empty_registry_prefixes()) + ANSWERABLE_ROWS` rows, cached after
        the first call.

    Raises:
        AssertionError: A pool this module depends on shrank below what a
            category needs — better to fail loudly at build time than to
            silently ship a smaller, unbalanced set.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    version = dictionary_version()
    partners = _final_clean_pool()
    n_needed = ROWS_PER_UNANSWERABLE_CATEGORY * 1 + \
        ROWS_PER_REGISTRY_EMPTY_PREFIX * len(_empty_registry_prefixes())
    assert len(partners) >= n_needed, (
        f"clean partner pool has {len(partners)} entries, need {n_needed}")
    partner_cursor = iter(partners)

    rows: list[CalibrationPair] = []

    # ---- free_text_anchor: half free-text-as-exposure, half as-outcome ---- #
    ft_pool = _free_text_pool()
    assert len(ft_pool) >= ROWS_PER_UNANSWERABLE_CATEGORY, (
        f"free-text pool has {len(ft_pool)} entries, need "
        f"{ROWS_PER_UNANSWERABLE_CATEGORY}")
    for i in range(ROWS_PER_UNANSWERABLE_CATEGORY):
        ft_key = str(ft_pool[i]["key"])
        partner_key = str(next(partner_cursor)["key"])
        exposure, outcome = ((ft_key, partner_key) if i % 2 == 0
                            else (partner_key, ft_key))
        pair_id = f"cal-free_text_anchor-{i + 1:02d}"
        rows.append(_build_row(pair_id, "free_text_anchor", exposure, outcome, version))

    # ---- no_signed_derivation: REMOVED 2026-08-28. See the module
    # ---- constant WHY_NO_SIGNED_DERIVATION_WAS_DROPPED for the evidence.
    # ---- anchors_are_the_same_construct: two members of one construct ----- #
    sc_pool = _same_construct_pool()
    assert len(sc_pool) >= ROWS_PER_UNANSWERABLE_CATEGORY, (
        f"same-construct pool has {len(sc_pool)} constructs, need "
        f"{ROWS_PER_UNANSWERABLE_CATEGORY}")
    for i in range(ROWS_PER_UNANSWERABLE_CATEGORY):
        members = sc_pool[i]["member_keys"]
        pair_id = f"cal-anchors_are_the_same_construct-{i + 1:02d}"
        rows.append(_build_row(pair_id, "anchors_are_the_same_construct",
                               str(members[0]), str(members[1]), version))

    # ---- registry_empty: every prefix registry_coverage() reports empty --- #
    for prefix in _empty_registry_prefixes():
        synthetic = f"{prefix}:unconfirmed_measure"
        for i in range(ROWS_PER_REGISTRY_EMPTY_PREFIX):
            partner_key = str(next(partner_cursor)["key"])
            exposure, outcome = ((synthetic, partner_key) if i % 2 == 0
                                else (partner_key, synthetic))
            pair_id = f"cal-registry_empty-{prefix}-{i + 1:02d}"
            rows.append(_build_row(pair_id, "registry_empty", exposure, outcome,
                                   version))

    # ---- answerable control arm: cross-module, all four gates clear ------- #
    clean = _final_clean_pool()
    by_module: dict[str, list[dict]] = {}
    for e in clean:
        by_module.setdefault(str(e["module"]), []).append(e)
    m2_pool, m3_pool = by_module.get("2", []), by_module.get("3", [])
    assert len(m2_pool) >= ANSWERABLE_ROWS and len(m3_pool) >= ANSWERABLE_ROWS, (
        f"module 2/3 clean pools have {len(m2_pool)}/{len(m3_pool)} entries, "
        f"need {ANSWERABLE_ROWS} each")
    for i in range(ANSWERABLE_ROWS):
        exposure_key, outcome_key = str(m3_pool[i]["key"]), str(m2_pool[i]["key"])
        pair_id = f"cal-answerable_control-{i + 1:02d}"
        pair = _build_row(pair_id, "answerable_control", exposure_key, outcome_key,
                          version)
        _verify_answerable(pair)
        rows.append(pair)

    _CACHE = tuple(rows)
    return _CACHE


def category_counts(pairs: tuple[CalibrationPair, ...]) -> dict[str, int]:
    """Rows per category, for a report or a pinned test.

    Args:
        pairs: The set to count, typically `build_calibration_set()`.

    Returns:
        Category name to row count.
    """
    counts: dict[str, int] = {}
    for p in pairs:
        counts[p.category] = counts.get(p.category, 0) + 1
    return counts


if __name__ == "__main__":
    pairs = build_calibration_set()
    counts = category_counts(pairs)
    print(f"C5 calibration set — {len(pairs)} pairs, dictionary "
         f"{pairs[0].dictionary_version}")
    for cat in sorted(counts):
        print(f"  {cat:36s} {counts[cat]:3d}")
    print("\none worked row, in full:")
    row = next(p for p in pairs if p.category == "free_text_anchor")
    print(f"  {row.pair_id}  {row.exposure_key} -> {row.outcome_key}")
    print(f"  reason: {row.refusal_reason}")
    print(f"  rationale: {row.rationale}")
    for ev in row.evidence:
        print(f"  evidence: {ev.tool}({ev.argument!r}).{ev.field} = {ev.value}")
