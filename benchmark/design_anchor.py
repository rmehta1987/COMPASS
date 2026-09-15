"""benchmark/design_anchor.py — the shape of a design-arrow key row, and no rows.

C36. This module holds the TYPES and the VALIDATOR for the design-arrow key.
The rows themselves live in `benchmark/design_key.py`, which is withheld from
every clone but the scoring one. The split is not tidiness and it is not
optional:

- A row names a published paper's exposure and outcome, so it is paper content
  and may not sit in the clone where prompts, `agent/schema.py` docstrings and
  `env/tools.py` are edited (`AGENTS.md` §Contamination Practice, "an agent
  reading paper content for a key or probe is itself a channel").
- The SHAPE is not paper content, and it has to be testable HERE. Putting the
  `__post_init__` and the validator in the withheld module would mean every
  test of them carried a `@needs_design_key` guard, and
  `tests/test_withheld.py::GUARD_CEILING` fires on ADDING a guarded test for
  exactly this reason: a guard is coverage leaving the clone where the code is
  written.

WHAT THIS REPLACES, and why a bare key tuple was not enough.
`benchmark/scorability.py::EXPOSURE_KEYS` was `dict[str, tuple[str, ...]]`. A
tuple of key strings loses three facts, and each loss has a recorded cost:

1. WHICH PHRASE the key answers. PMID 38715087's only keyed row is a covariate
   — `prevalent hypertension` — while its outcome is central hemodynamics, so a
   key read without its term is an adjustment variable passing as outcome
   evidence. Today that depends on a reviewer noticing. `term` records the
   `cohort_papers.py` design-line phrase verbatim, so the pairing is checkable.
2. WHICH RESOLVER decides it. A key string has one implied authority,
   `resolve_variable`. But `agent/schema.py::Ref` has three members, and a
   derivation is resolved by `get_derivation` while an area measure has no
   resolver at all. `kind` selects; nothing is inferred from the string's shape.
3. WHAT IS MISSING when nothing resolves. `blocked_on` names the delivery, in
   the shape `env/tools.py::estimate_n` already uses — null, plus `unknown`,
   plus a named blocker — instead of a blank cell that reads as unfilled work.

THE KIND VOCABULARY IS NOT FREE. Three of the four are
`agent/schema.py::Ref`'s discriminator values and must stay equal to them:
a key that records an exposure the schema cannot express is a key for a
different benchmark. `not_in_instrument` is the fourth and has no `Ref`
counterpart on purpose — it records a REFUTATION, and the schema has no way to
name a thing that is not there. `tests/test_design_anchor.py` pins both halves.

FAIL CLOSED. `__post_init__` rejects every combination of `kind`, `key` and
`blocked_on` that would let a half-filled anchor read as a filled one. That is
the same complaint `benchmark/rediscovery.py::validate_exposure_keys` already
raises for an empty tuple, moved to where it cannot be skipped, and the C32
exemption that failed OPEN — swallowing a PMID and a published n — is the
recorded cost of leaving a partial record looking whole.

C35, DECIDED 2026-09-14, answer C: an `area_measure` anchor is out of scope
EXPLICITLY. It carries no key, it names the delivery that would change that,
and the side it sits on reaches `scorability.py::BLOCKED_ON_DELIVERY` — not
CONFIRMED, and not the REFUTED that would claim the inventory can never arrive.
Answer D — confirm on the descriptor alone — is why `validate_design_key`
complains about an `area_measure` anchor carrying a key: a key nothing resolves
asserts something nothing checks.

HELD OUT BY ASSOCIATION. This module stores no paper content, but it is the
design key's schema and belongs beside it under `benchmark/`, which no tool
path reaches.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.schema import KEY_PATTERN  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS  # noqa: E402
from env.tools import get_derivation, resolve_variable  # noqa: E402

#: The kinds an anchor may take. The first three are
#: `agent/schema.py::Ref`'s discriminator values, in its order;
#: `not_in_instrument` is this module's own and records a refutation.
VARIABLE = "variable"
DERIVATION = "derivation"
AREA_MEASURE = "area_measure"
NOT_IN_INSTRUMENT = "not_in_instrument"

#: Every legal `kind`. Read from here, never retyped
#: (`AGENTS.md` §Testing Patterns).
ANCHOR_KINDS: tuple[str, ...] = (VARIABLE, DERIVATION, AREA_MEASURE,
                                 NOT_IN_INSTRUMENT)

#: The kinds that borrow their name from `agent/schema.py::Ref`. Split out so
#: the test that pins the vocabulary against the schema does not have to
#: hard-code which of ours is the extra one.
SCHEMA_KINDS: tuple[str, ...] = (VARIABLE, DERIVATION, AREA_MEASURE)

#: `resolve_variable`'s only outcome that names a variable a design may assert.
#: Its own log says a group id is a stem "a protocol may never name" and a
#: construct key is the enumeration's id. Spelled as `rediscovery.py` spells it.
RESOLVED = "unique"

#: `get_derivation`'s outcome when the signed file exists.
DERIVATION_OK = "ok"

#: The study-team delivery that would make an area measure resolvable. Named
#: rather than free text so a reader can count the rows waiting on one thing,
#: and so C35's answer B has a single string to switch on later.
AREA_MEASURE_INVENTORY = "area_measure_inventory"


@dataclass(frozen=True)
class Anchor:
    """One side's anchor: a design-line phrase, and what answers it.

    Frozen because a row is an answer key. A mutable anchor could be edited by
    the code reading it, and the thing this file exists to make checkable is
    what the operator wrote.

    Attributes:
        term: The `benchmark/cohort_papers.py` design-line phrase this anchor
            answers, verbatim. Never a paraphrase: the phrase is what makes a
            key checkable against the side it was filed under.
        kind: One of `ANCHOR_KINDS`. Selects the resolver; nothing is inferred
            from `key`'s shape.
        key: The instrument key for `variable`, the signed file's stem for
            `derivation`, None otherwise.
        blocked_on: The missing delivery, for `area_measure` only.
    """

    term: str
    kind: Literal["variable", "derivation", "area_measure", "not_in_instrument"]
    key: str | None = None
    blocked_on: str | None = None

    def __post_init__(self) -> None:
        """Reject every half-filled combination, at construction.

        Structural only: presence, absence and vocabulary. Whether a key
        RESOLVES is `validate_design_key`'s job, because that needs the live
        environment and this runs wherever an anchor is built.

        Raises:
            ValueError: If `term` is blank, `kind` is not in `ANCHOR_KINDS`, or
                `key`/`blocked_on` do not match what `kind` requires.
        """
        if not self.term or not self.term.strip():
            raise ValueError(
                "an anchor with no term records a key against nothing. The "
                "term is the design-line phrase the key answers, and without "
                "it a covariate key is indistinguishable from an outcome one.")
        if self.kind not in ANCHOR_KINDS:
            raise ValueError(
                f"{self.kind!r} is not an anchor kind. One of "
                f"{list(ANCHOR_KINDS)} — the kind selects the resolver, so an "
                f"unknown one has nothing to check it.")
        if self.kind in (VARIABLE, DERIVATION):
            if not self.key:
                raise ValueError(
                    f"a {self.kind!r} anchor for {self.term!r} has no key. "
                    f"That is the whole of its evidence; without it the anchor "
                    f"reads as filled and asserts nothing.")
            if self.blocked_on:
                raise ValueError(
                    f"a {self.kind!r} anchor for {self.term!r} names both a "
                    f"key and a blocker ({self.blocked_on!r}). A key that "
                    f"resolves is not blocked; pick one.")
        elif self.kind == AREA_MEASURE:
            if self.key is None and not self.blocked_on:
                raise ValueError(
                    f"an {AREA_MEASURE!r} anchor for {self.term!r} has neither "
                    f"a key nor a blocker. C35 answer C: it carries "
                    f"{AREA_MEASURE_INVENTORY!r} and says so, rather than "
                    f"reading as a row nobody filled in.")
        elif self.blocked_on or self.key:
            raise ValueError(
                f"a {NOT_IN_INSTRUMENT!r} anchor for {self.term!r} names a "
                f"key or a blocker. It is a refutation on a recorded "
                f"item-level read: there is nothing to resolve and nothing to "
                f"wait for.")


@dataclass(frozen=True)
class DesignKeyRow:
    """One paper's design arrow, both sides, as the operator recorded it.

    Attributes:
        pmid: PubMed identifier, as `benchmark/cohort_papers.py` records it.
        exposure: Anchors for the design line's left-hand side.
        outcome: Anchors for its right-hand side.
        provenance: Where in the paper this was read, and that paper's
            retrievability. Prose, for a human: the point is that a later
            reader can go back to the same place, not that anything parses it.
        filled_by: Who recorded the row. Rows are the operator's; this is what
            makes a row written by anyone else visible rather than assumed.
    """

    pmid: str
    exposure: tuple[Anchor, ...]
    outcome: tuple[Anchor, ...]
    provenance: str
    filled_by: str


def validate_design_key(
        rows: tuple[DesignKeyRow, ...] | None = None) -> list[str]:
    """C12's ACCEPT criterion, generalised over both sides of the design key.

    Checks the whole row rather than only resolution, for the reason
    `rediscovery.py::validate_exposure_keys` already gives: a pmid the
    bibliography does not carry is a typo sitting in the table doing nothing,
    and an empty tuple is a side that LOOKS filled and asserts nothing.

    `scorability._confirm_anchors` resolves the same keys and is deliberately
    not reused: it returns a blocker constant per failure and drops which key
    caused it, which is exactly what an operator pasting a row needs to know.

    Args:
        rows: The table to check. Defaults to the live `DESIGN_KEY`, which is
            withheld from every clone but the scoring one.

    Returns:
        One complaint per problem, empty when every row is usable. Empty is
        also the answer for an empty table — nothing asserted is nothing wrong
        — so a caller that wants to know whether any row EXISTS must count the
        rows, not read this.

    Raises:
        ModuleNotFoundError: If `rows` is None in a clone without the key.
    """
    if rows is None:
        from benchmark.design_key import DESIGN_KEY

        rows = DESIGN_KEY

    known = {p.pmid for p in COHORT_PAPERS}
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.pmid not in known:
            out.append(f"{row.pmid}: not a pmid in benchmark/cohort_papers.py")
        if row.pmid in seen:
            out.append(f"{row.pmid}: a second row for one paper. Two rows can "
                       f"disagree about one design and nothing picks between "
                       f"them; put both sides in one row.")
        seen.add(row.pmid)
        if not row.provenance.strip():
            out.append(f"{row.pmid}: no provenance. A key with no record of "
                       f"where it was read cannot be rechecked, which makes it "
                       f"an assertion rather than a key.")
        if not row.filled_by.strip():
            out.append(f"{row.pmid}: no filled_by. Rows are the operator's, "
                       f"and an unattributed row hides which are not.")
        for side_name, anchors in (("exposure", row.exposure),
                                   ("outcome", row.outcome)):
            out.extend(_complain_about_side(row.pmid, side_name, anchors))
    return out


def _complain_about_side(pmid: str, side: str,
                         anchors: tuple[Anchor, ...]) -> list[str]:
    """Every problem with one side of one row.

    Args:
        pmid: PubMed identifier, for the message.
        side: `"exposure"` or `"outcome"`.
        anchors: That side's anchors.

    Returns:
        One complaint per problem, empty when the side is usable.
    """
    out: list[str] = []
    if not anchors:
        out.append(f"{pmid}: empty {side} tuple — a side that asserts nothing "
                   f"reads as a filled row and blocks nothing")
        return out

    keys = [a.key for a in anchors if a.key is not None]
    if len(set(keys)) != len(keys):
        out.append(f"{pmid}: {side} repeats a key: {sorted(keys)}")
    terms = [a.term for a in anchors]
    if len(set(terms)) != len(terms):
        out.append(f"{pmid}: {side} repeats a term: {sorted(terms)}. Two "
                   f"anchors on one phrase is two answers to one question.")

    for anchor in anchors:
        out.extend(_complain_about_anchor(pmid, side, anchor))
    return out


def _complain_about_anchor(pmid: str, side: str, anchor: Anchor) -> list[str]:
    """One check per `kind`, against the authority that kind names.

    Args:
        pmid: PubMed identifier, for the message.
        side: `"exposure"` or `"outcome"`.
        anchor: The anchor to check.

    Returns:
        One complaint per problem, empty when the anchor resolves.
    """
    where = f"{pmid}: {side} {anchor.term!r}"
    if anchor.kind == VARIABLE:
        if not re.match(KEY_PATTERN, anchor.key or ""):
            return [f"{where}: {anchor.key!r} is not a variable key "
                    f"(agent/schema.py::KEY_PATTERN)"]
        outcome = resolve_variable(anchor.key or "")["outcome"]
        if outcome != RESOLVED:
            return [f"{where}: {anchor.key} resolves {outcome!r}, not "
                    f"{RESOLVED!r}. An anchor must name one variable — a "
                    f"construct key or a group id is the enumeration's id or a "
                    f"stem, and a protocol may name neither."]
        return []

    if anchor.kind == DERIVATION:
        outcome = get_derivation(anchor.key or "")["outcome"]
        if outcome != DERIVATION_OK:
            return [f"{where}: no signed derivation {anchor.key!r} in "
                    f"curated/derivations/. A derivation is a reviewable, "
                    f"signed object; naming one that does not exist is an "
                    f"inline recipe wearing a reference's clothes."]
        return []

    if anchor.kind == AREA_MEASURE:
        if anchor.key is not None:
            # C35 answer D, refused by name. A key here would be checked by
            # nothing -- `resolve_variable` cannot resolve an area measure and
            # no second authority exists yet -- so it asserts exactly as much
            # as the word test did, in a column that looks stricter.
            return [f"{where}: an {AREA_MEASURE!r} anchor carries a key "
                    f"({anchor.key!r}), and no authority in this repository "
                    f"resolves one. C35 answer D is forbidden: a key nothing "
                    f"checks is the word-presence failure in a new costume. "
                    f"Drop the key and keep {AREA_MEASURE_INVENTORY!r}."]
        return []

    return []
