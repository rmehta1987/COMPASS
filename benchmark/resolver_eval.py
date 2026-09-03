"""What kind of answer a free-text request has, and whether a model can say so.

WHY THIS EXISTS. C16 (`TASKS.md`) puts a model between the researcher's prose and
the instrument: they type "self-rated overall health" and something has to decide
which variable that is. The failure mode is not missing the right item, it is
NAMING one when the codebook cannot support naming one — a request that spans a
whole roster family, one that has to be computed from other items, one that four
different variables answer equally well. A resolver that always returns its best
guess scores well on the easy half and is wrong in a way nobody can see on the
rest. This module measures the thing that matters: does the resolver know what
KIND of answer the request has.

The design is ported from a browser harness (`tests/resolver_eval_v2.jsx`,
untracked) that measured it live. Three things changed in the port, all of them
because the harness's answer space was the bare `qid` printed in the codebook:

  * KEYS, NOT `qid`s. `qid` is not unique — 121 of the built dictionary's 2,666
    distinct `qid`s are used by more than one question, covering 259 of its
    2,804 entries, because the three modules renumber independently. `Q9.1` is
    "How old were you when you had your first menstrual
    period" in module 2 and a tobacco-pipe preamble in module 3. Measured over
    the harness's own fixture: 77 of its 508 candidates and 8 of its 46 gold
    answers were ids of that kind, one pool listed `Q9.2` twice meaning two
    different questions, and the scorer compared the bare string, so a resolver
    that found the right wording in the wrong module scored correct. Everything
    here is a `build/dictionary.json` key (`m2:Q9.1`), which is unique by
    construction.

  * WORDING COMES FROM `env/labels.py::cite`, NOT FROM THE FIXTURE. The harness
    froze each candidate's text inline, and 94 of its 508 candidates no longer
    said what the instrument says: 63 had their whitespace collapsed, 31 were
    truncated at 170 characters or carried mojibake from a cp1252 read. Storing
    keys and citing them at render time makes that class of drift
    unrepresentable, and it is the same guarantee `Cited` exists for — see
    `AGENTS.md` §Hard Constraints on `question_text` byte for byte.

  * n=1 IS REFUSED. The harness admitted a single shortlist (`min(2, nSamples)`),
    and a single sample cannot disagree with itself, so the critic's one input
    signal — how much the samples agreed — was silently absent while the run
    still scored. `MIN_SAMPLES` refuses it, per `AGENTS.md` §Contamination
    Practice: a prose resolver refuses to start unconfirmed at n=1.

WHAT IT REUSES, rather than rebuilding. Candidate wording is `env.labels.cite`,
which is the only maker of a key bound to its text; rendering is that module's
own `Cited.render`, so the pool a model reads is built by the code that already
guarantees no bare key reaches it. The lexical control arm is
`env.tools.search_variables` as shipped, called, never reimplemented. The fixture
is checked by pydantic. The roster family is read off dictionary fields rather
than parsed out of key strings, which is what the harness did with a regex.

THE SCHEMA IS THE INSTRUMENT HERE. `CriticVerdict.model_json_schema()` is prompt
text — the five verdicts, `recipe`, `missing_dimension` — and the reason the
measurement works at all is that "no single item is right" is a first-class value
in it rather than something the model has to express by picking an item anyway.
So this module's model docstrings are subject to the same rule as
`agent/schema.py`'s: no study design, exposure, outcome, paper count, cohort
figure or prevalence may appear in them. They are scanned —
`benchmark/contamination_check.py::model_visible_surface` carries both prompts and
both schemas.

TWO REPORTS, AND ONLY ONE OF THEM NEEDS A MODEL. `evaluate_pools` measures
whether the gold answer is even reachable in the candidate set a given pool arm
builds — no model call, deterministic, and the number that says whether a live
resolver figure is about resolution or about retrieval. `evaluate` runs the
resolver itself. Read them in that order, always: a resolver cannot name an item
it was never shown.

Run the model-free half: `python -m benchmark.resolver_eval` from the repository
root.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent import prompt_contract as contract
from env import labels, tools

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "benchmark" / "fixtures" / "resolver_queries.json"

#: The five kinds of answer a request can have. Ordered as the prompt lists them.
VERDICTS = ("resolved", "family", "derive", "ambiguous", "absent")

#: Shortlists below this and the run is refused, not scored. The critic's only
#: evidence that a request is underdetermined is disagreement between
#: independent shortlists, and one shortlist cannot disagree with itself.
#: `AGENTS.md` §Contamination Practice: refuse to start unconfirmed at n=1.
MIN_SAMPLES = 2

#: How many items a shortlist is asked for. The harness's number, kept so the
#: ported figures stay comparable.
SHORTLIST_SIZE = 5

#: The most shortlists one row may ever draw, first pass and granted extras
#: together. A ceiling, not a target: without one, a critic that asks for more
#: on every row turns a fixed-cost benchmark into an open-ended one, and the
#: refusal is what makes "it asked and did not get them" a reportable outcome
#: rather than an invisible one.
MAX_SAMPLES = 9

#: Printed above every figure this module produces.
BIAS_BANNER = "KNOWN BIAS — read every figure below as an UPPER BOUND"

#: The ONE rule `score_query` implements, in the fixture's own words. Mirrored
#: here for the same reason `retrieval_eval.GOLD_RULE` is: the report PRINTS the
#: fixture's sentence as the definition behind every figure, so a fixture stating
#: a different rule would publish one the scorer never applied.
ANSWER_RULE = (
    "an exact answer is correct when the resolved key equals the gold key; a "
    "family answer is correct when any returned key belongs to the gold key's "
    "roster family; derive and absence answers are correct on the verdict alone")

#: `(prompt) -> raw model text`. One argument because the backends this is run
#: through fix their own system prompt to "emit one JSON object and nothing
#: else"; every instruction the resolver gives is in the prompt, which is also
#: what makes the whole model-visible surface scannable from one string.
ModelFn = Callable[[str], str]

#: `(query) -> candidate keys, most plausible first`. The seam the pool arms plug
#: into, so a retrieval experiment is scored by the same code as the frozen pool.
PoolFn = Callable[["ResolverQuery"], "tuple[str, ...]"]

Outcome = Literal["correct", "arguable", "malformed", "wrong", "confident_wrong",
                  "over_abstained"]

#: What each outcome means, for the report. `confident_wrong` is separated from
#: `wrong` for every kind of request, which the harness did only for three of
#: four: naming an item when the codebook cannot support naming one is the
#: failure this benchmark exists to see, and it must not be averaged into
#: ordinary error.
OUTCOME_MEANING: dict[str, str] = {
    "correct": "right",
    "arguable": "defensible, not the key's answer",
    "malformed": "right reasoning, unusable keys",
    "wrong": "wrong",
    "confident_wrong": "named one item where the key says none is right",
    "over_abstained": "abstained on a request that resolves",
}


# --------------------------------------------------------------------------- #
# the schemas the model is shown — prompt text, scanned surfaces
# --------------------------------------------------------------------------- #


class ResolvedItem(BaseModel):
    """One codebook item, named by its key and the wording that key stands for.

    Both fields are required, so a key with no wording beside it cannot be
    returned. That is the same guarantee `env/labels.py::Cited` gives on the way
    in, applied to the way out: the wording is what a reader can check, and a key
    on its own is a label the reader has to look up.

    Attributes:
        key: The item's key, copied character for character from the start of a
            candidate line.
        wording: That candidate's question wording, copied from the same line.
    """

    key: str
    wording: str


class Shortlist(BaseModel):
    """A ranked shortlist of candidates for one request.

    Attributes:
        items: The most plausible candidates, most plausible first.
        note: One sentence on what the ranking turned on.
    """

    items: tuple[ResolvedItem, ...] = ()
    note: str = ""


class CriticVerdict(BaseModel):
    """What kind of answer a request has, and the items that carry it.

    Attributes:
        verdict: `resolved` when exactly one item is right; `family` when the
            request spans every member of a repeated family and returning one
            member would be wrong; `derive` when no item measures this and it
            must be computed from others; `ambiguous` when several candidates are
            genuinely different variables and the wording cannot say which is
            meant; `absent` when the codebook does not measure this at all.
        items: The items the verdict names — one for `resolved`, any member of
            the family for `family`, the inputs for `derive`, empty otherwise.
        recipe: How to compute the value, when the verdict is `derive`.
        missing_dimension: The single fact that would settle it, when the verdict
            is `ambiguous`.
        more_samples_requested: How many further shortlists would change this
            verdict, or 0. Ask when the shortlists shown cannot settle the
            question — most often because the request spans a repeated family
            larger than the shortlists can show. Asking is a request, not a
            decision: it is granted by rule, and a verdict is still required in
            this reply.
        more_samples_reason: What the further shortlists would settle.
        family_size: When the verdict is `family`, the number of roster members
            the chosen item's own candidate line states it is asked of. One
            member names the whole family, so this is what says WHICH family
            without listing it.
        reason: Two sentences at most.
    """

    verdict: Literal["resolved", "family", "derive", "ambiguous", "absent"]
    items: tuple[ResolvedItem, ...] = ()
    recipe: str = ""
    missing_dimension: str = ""
    more_samples_requested: int = 0
    more_samples_reason: str = ""
    family_size: int = 0
    reason: str = ""


# --------------------------------------------------------------------------- #
# the fixture
# --------------------------------------------------------------------------- #


class Narrowing(BaseModel):
    """A clarification to re-run an ambiguous request with, and what it should do.

    Attributes:
        dimension: The dimension the clarification supplies.
        supply: The clarification, in the researcher's words.
        gold: The key the clarification should resolve to, or None when it should
            NOT resolve — the control arm, without which "narrowing helped" is
            unfalsifiable.
        note: Why this row is shaped the way it is.
    """

    dimension: str
    supply: str
    gold: str | None = None
    note: str = ""


class ResolverQuery(BaseModel):
    """One fixture row: a request, its candidate pool and the answer it has.

    Attributes:
        id: Stable row id.
        tier: How resolvable the request is, 1 (one item measures it) to 5 (the
            codebook cannot pin it down).
        kind: The kind of answer the row has: `exact`, `family`, `derive` or
            `abstain`.
        request: The researcher's free text.
        gold: The answer's keys. One for `exact`, every member for `family`,
            empty for `derive` and `abstain`.
        accept_keys: Keys whose family is a defensible second answer, scored
            `arguable` rather than `wrong`.
        expected: What the answer is, in prose, for rows that have no key.
        note: The trap the row was written to set.
        pool: The frozen candidate pool, in the order the harness listed it.
        narrowing: The clarification arm, when the row has one.
    """

    id: str
    tier: int
    kind: Literal["exact", "family", "derive", "abstain"]
    request: str
    gold: tuple[str, ...] = ()
    accept_keys: tuple[str, ...] = ()
    expected: str = ""
    note: str = ""
    pool: tuple[str, ...] = Field(min_length=1)
    narrowing: Narrowing | None = None


class ResolverFixture(BaseModel):
    """The committed request fixture.

    `answer_rule` and `known_bias` are `min_length=1` for the reason
    `benchmark/retrieval_eval.py::QueryFixture` gives: the first defines what
    counts as correct and the second is the only thing between these numbers and
    their being quoted as ground truth.

    Attributes:
        schema_: Fixture schema identifier, read from the `schema` key.
        generated: The date the fixture was generated.
        dictionary_version: The build the keys were resolved against.
        generator: What generated it.
        sample: How the sample was drawn.
        answer_rule: What counts as a correct answer.
        known_bias: The bias a reader must carry into every figure.
        queries: The rows, in fixture order.
    """

    schema_: str = Field(alias="schema")
    generated: str
    dictionary_version: str
    generator: str
    sample: str
    answer_rule: str = Field(min_length=1)
    known_bias: str = Field(alias="KNOWN_BIAS", min_length=1)
    queries: tuple[ResolverQuery, ...] = Field(min_length=1)


def load_fixture(path: Path = FIXTURE) -> ResolverFixture:
    """Read and validate the committed fixture.

    Args:
        path: The fixture file.

    Returns:
        The parsed fixture.

    Raises:
        FileNotFoundError: If the fixture is missing. It is committed, so this is
            a checkout problem rather than a cue to regenerate it.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; it is committed, so this is a checkout problem, "
            f"not a regeneration cue.")
    return ResolverFixture.model_validate(json.loads(path.read_text()))


# --------------------------------------------------------------------------- #
# the roster family — read off dictionary fields, never parsed out of a key
# --------------------------------------------------------------------------- #

_FAMILIES: dict[tuple[str, str, str, str], tuple[str, ...]] | None = None
_DUPLICATE_TEXT: dict[str, int] | None = None


def _family_id(entry: dict) -> tuple[str, str, str, str]:
    r"""The identity of the roster family one entry belongs to.

    One question asked once per roster member is one family: everything about the
    entry is equal across its members except which member it is. So the identity
    is every field that distinguishes a question from another question, and
    `roster_row` — the field that distinguishes a member from another member — is
    the one deliberately left out.

    Parsed from no string. The harness derived this with a regex over the id
    (`/^\d+_/` then `/(#\d+)?(_\d+)*(_TEXT)?$/`), which happens to agree here
    and is a second definition of a relation the dictionary already records.

    MEASURED on build 6fcd02755bf3: 1,397 families over 2,804 entries, 1,279 of
    them a single item; the repeated ones have 2, 3, 5, 15 or 20 members. Two
    families do not differ by `roster_row` — `m1:Q3.10`'s pair of text companions
    and `m2:Q785`, the one `qid` the build had to split by occurrence — so this
    is a family relation with two known exceptions, not an identity.

    Args:
        entry: A `build/dictionary.json` entry.

    Returns:
        The family identity, as a tuple of the entry's non-member fields.
    """
    return (str(entry["construct_key"]), str(entry["matrix_block"]),
            str(entry["matrix_col"]), str(entry["subitem_text"]))


def _families() -> dict[tuple[str, str, str, str], tuple[str, ...]]:
    """Every roster family in the built dictionary, built once.

    Returns:
        Family identity mapped to its member keys, in dictionary order.
    """
    global _FAMILIES
    if _FAMILIES is None:
        grouped: dict[tuple[str, str, str, str], list[str]] = {}
        for e in tools._load()["entries"]:
            grouped.setdefault(_family_id(e), []).append(str(e["key"]))
        _FAMILIES = {k: tuple(v) for k, v in grouped.items()}
    return _FAMILIES


def family_of(key: str) -> tuple[str, ...]:
    """The roster family one key belongs to, itself included.

    Args:
        key: A fully qualified variable key.

    Returns:
        Every member key, in dictionary order. A one-tuple when the question is
        asked once.

    Raises:
        KeyError: If the key is not in the built dictionary.
    """
    return _families()[_family_id(_entry(key))]


def _entry(key: str) -> dict:
    """The dictionary entry for one key, or a diagnosis of why there is none.

    Args:
        key: A fully qualified variable key.

    Returns:
        The entry.

    Raises:
        KeyError: If the key is not in the built dictionary.
    """
    tools._load()
    entry = tools._BY_KEY.get(key)
    if entry is None:
        raise KeyError(
            f"{key!r} is not in build/dictionary.json "
            f"({tools.dictionary_version()}). A fixture row pointing at a key "
            f"the dictionary no longer holds is a stale fixture, not a resolver "
            f"error, and scoring it as one would report a rebuild as a "
            f"regression.")
    return entry


def _duplicate_text_modules() -> dict[str, int]:
    """How many modules print each wording, keyed by the collapsed wording.

    The fact a resolver most needs and cannot see from one candidate line: the
    same question asked in two modules is two variables, and picking either
    without saying which wave is meant is the `ambiguous` case rather than a
    resolution.

    Returns:
        Collapsed `question_text` mapped to the number of distinct modules
        printing it.
    """
    global _DUPLICATE_TEXT
    if _DUPLICATE_TEXT is None:
        mods: dict[str, set[str]] = {}
        for e in tools._load()["entries"]:
            mods.setdefault(labels._flat(str(e["question_text"])),
                            set()).add(str(e["module"]))
        _DUPLICATE_TEXT = {k: len(v) for k, v in mods.items()}
    return _DUPLICATE_TEXT


# --------------------------------------------------------------------------- #
# the pool the model reads
# --------------------------------------------------------------------------- #


def candidate_line(key: str) -> str:
    """One candidate as the model sees it: key, wording, and the facts about it.

    The key and wording half is `env/labels.py::Cited.render` verbatim, so the
    pool is rendered by the module that guarantees a key never appears without
    its text, and the separator is that module's `_MARK` — verified to occur in
    none of the 2,804 wordings, so a reader can split on it safely.

    The facts are the three a candidate line can carry without inventing
    anything: which module prints it, how many roster members share the
    question, and whether another module prints the same wording. The harness
    also flagged direct identifiers and wrote a prose description of each family
    by hand; neither is a dictionary field, so neither is here.

    Args:
        key: A fully qualified variable key.

    Returns:
        The rendered line.

    Raises:
        KeyError: If the key is not in the built dictionary.
        labels.CitationUnavailable: If the key cannot be bound to wording.
    """
    entry = _entry(key)
    facts = [f"module {entry['module']}"]
    n_family = len(family_of(key))
    if n_family > 1:
        facts.append(f"asked of each of {n_family} roster members")
    n_modules = _duplicate_text_modules()[
        labels._flat(str(entry["question_text"]))]
    if n_modules > 1:
        facts.append(f"same wording printed in {n_modules} modules")
    return f"{labels.cite(key).render()}  ({'; '.join(facts)})"


def render_pool(keys: Sequence[str]) -> str:
    """Render a candidate pool, one line per key, in the order given.

    Never truncated and never budgeted, unlike `CitedSet.render`: a pool the
    model is asked to choose from cannot silently lose the right answer, and a
    pool too large to render is a finding about the pool arm rather than
    something to trim here.

    Args:
        keys: The candidate keys, most plausible first.

    Returns:
        The block, one candidate per line.
    """
    return "\n".join(candidate_line(k) for k in keys)


def pool_frozen(query: ResolverQuery) -> tuple[str, ...]:
    """The fixture's own pool — the arm the ported figures are scored on.

    Args:
        query: The fixture row.

    Returns:
        The row's committed candidate keys.
    """
    return query.pool


def pool_searched(query: ResolverQuery,
                  limit: int = 45) -> tuple[str, ...]:
    """The lexical control arm: what `search_variables` returns for the request.

    The control arm C16 names. It takes its input from the request alone — never
    from the gold key's label — so a figure scored on it is comparable to a live
    run's, which is the whole reason `evaluate_pools` reports how often it drops
    the answer.

    `search_variables` collapses roster repeats under one representative, so a
    family answer arrives as a single member here. That is the retrieval layer's
    behaviour, not a defect to compensate for, and `family_of` is what makes it
    scorable anyway.

    Args:
        query: The fixture row.
        limit: Candidates to return. Defaults to the frozen pools' size so the
            two arms are scored over the same budget.

    Returns:
        The hit keys in rank order; empty when the search matched nothing.
    """
    result = tools.search_variables(query.request, limit)
    return tuple(str(h["key"]) for h in result.get("hits", []))


def pool_whole_instrument(query: ResolverQuery) -> tuple[str, ...]:
    """Every key in the instrument, with no retrieval step at all.

    The arm that asks what the schema is worth on its own: hand the model the
    codebook and let the verdict do the work. It is the honest upper end of the
    pool spectrum and it is expensive — MEASURED 2026-09-01 on build
    6fcd02755bf3, the rendered block is 2,804 lines and 423,866 characters, and
    the shortlist prompt around it 425,542 — so it is a named arm a caller opts
    into, never the default.

    Args:
        query: The fixture row. Unused; the pool does not depend on the request,
            which is the point of this arm.

    Returns:
        Every key, in dictionary order.
    """
    del query
    return tuple(str(e["key"]) for e in tools._load()["entries"])


#: The pool arms by name, for the CLI and for a report that has to say which one
#: it measured. A figure without this name is not comparable to another.
POOL_ARMS: dict[str, PoolFn] = {
    "frozen": pool_frozen,
    "searched": pool_searched,
    "instrument": pool_whole_instrument,
}


# --------------------------------------------------------------------------- #
# the prompts — scanned surfaces, see model_visible_surface
# --------------------------------------------------------------------------- #

#: The candidate line's shape, stated as a grammar rather than as a list of
#: things not to do. Rendered into both prompts.
#:
#: BOTH BOUNDARIES ARE STATED BECAUSE BOTH WERE GOT WRONG, by different models,
#: at opposite ends of the same line. MEASURED 2026-09-01 on GQ012, searched
#: arm, three tiers:
#:
#:   * The earlier rule said "the key is the text before the first ' | '".
#:     `env/labels.py::Cited.render` prints a roster item as
#:     `m2:1_Q16.8#1_3 [roster row 1] | ...`, so on 1,520 of 2,804 entries that
#:     is the key PLUS the tag. claude-haiku-4-5 returned
#:     `m2:1_Q16.8#1_3 [roster row 1]`, copied exactly as instructed, and scored
#:     `malformed` on a verdict whose reasoning was right.
#:   * The replacement fixed where a key STARTS and still never said where a
#:     wording ENDS. claude-opus-5 then returned four keys whose wording carried
#:     the trailing fact clause — `... - 1 - Breast cancer (module 2; asked of
#:     each of 20 roster members)` — and scored `malformed` for it, on the same
#:     row, with `family` and correct reasoning. claude-haiku-4-5 and
#:     claude-sonnet-5 guessed the boundary correctly on the same wording.
#:
#: A rule that three models read three ways is not an instruction, and an eval
#: whose result moves with it is not a measurement (`AGENTS.md` §Verification
#: Discipline). Every figure produced before this text is a figure produced
#: under a different instrument.
#:
#: "First run of non-space characters" is exact rather than nearly right: no key
#: in the built dictionary contains whitespace, checked by
#: `tests/test_resolver_eval.py::test_no_variable_key_contains_whitespace`.
_COPY_RULE = (
    "HOW TO READ A CANDIDATE LINE. Every line has the same shape:\n"
    "    KEY [optional roster tag] | WORDING  (facts about the item)\n"
    "  - The KEY is the first run of non-space characters on the line. No key "
    "contains a space, so a bracketed tag such as '[roster row 1]' is NOT part "
    "of it.\n"
    "  - The WORDING is the text between the ' | ' and the parenthesised clause "
    "that ends the line. That clause states facts ABOUT the item — its module, "
    "its family size — and is NOT part of the wording.\n"
    "  - Copy both exactly, character for character. Do not add to either, trim "
    "either, or tidy the spacing of either.")

#: How a repeated family appears in the pool, and what to return for one.
#:
#: WHY A FAMILY ANSWER IS ONE KEY AND NOT A LIST. Any member identifies the
#: whole family — `family_of` expands it from dictionary fields — so enumerating
#: members buys nothing, and it costs: the members of a roster family differ
#: only at an index buried mid-wording (`- 1_Q16.9#1 -` against
#: `- 2_Q16.9#1 -`), so returning N members means transcribing N near-identical
#: strings without error. MEASURED on GQ012: claude-sonnet-5 returned five and
#: got all five right; claude-opus-5 returned four and mis-transcribed all four.
#: Asking for one member removes a failure mode that has nothing to do with
#: whether the model identified the family.
#:
#: `family_size` is what makes the answer checkable without the list: the count
#: is printed on the member's own line, so a model that has read the line it
#: cites can state it, and an answer naming members of two different families
#: becomes visible instead of merely scoring wrong.
#:
#: THE LAST PARAGRAPH IS THE ONE TO WATCH. Naming what a question is asked OF is
#: the discrimination GQ013 turns on — household members against the
#: respondent's mother and father — and a prompt that hands over the
#: distinguishing move is close to handing over the answer. It is here rather
#: than withheld because the user asked for it; `RESOLVER_PROMPT_ARMS` keeps the
#: prompt without it runnable, and every report names which arm produced it, so
#: the pair stays measurable.
_FAMILY_RULE = (
    "HOW A REPEATED FAMILY APPEARS HERE. A line ending 'asked of each of N "
    "roster members' is ONE member of a family of N: the same question, put "
    "once per sibling, per household member, per child. The other N-1 members "
    "may or may not be among the candidates you were shown — the count on the "
    "line is authoritative, and you do not need to see them to know they "
    "exist. Those N lines are not N different variables.\n"
    "If your verdict is `family`, return EXACTLY ONE member key and set "
    "`family_size` to the N its own line states. One member names the whole "
    "family; a list of members does not say anything more, and every key you "
    "return must belong to the SAME family.\n"
    "Two families can both look plausible. Before choosing, say what each one "
    "is asked OF — this sibling, this household member, the respondent's own "
    "mother — and take the one whose subject is the subject the request names.")

#: Rendered into the critic prompt. THE ASYMMETRY IS THE POINT: the model may
#: say it needs more evidence, and it may not decide whether it gets any. What
#: happens next is `grant_samples`, a pure function of how many were asked for,
#: how many were already drawn and whether this row has been granted extras
#: before — never of how good the stated reason is. That keeps the loop's
#: control flow out of the model's hands in the spirit of `AGENTS.md` §Hard
#: Constraints, while letting the one thing the model can see and the harness
#: cannot — that the shortlists in front of it do not settle the question —
#: reach the harness at all.
#:
#: The measured case behind it: a shortlist shows `SHORTLIST_SIZE` items, so
#: three of them can surface at most 15 distinct keys, and GQ012's answer is a
#: family of 20. The union CANNOT hold that family whole. What stops this being
#: blindness rather than truncation is that every candidate line already states
#: how many roster members share the question, so a family's extent is visible
#: on one line even when the shortlists show three of its members — which is
#: exactly the distinction the rule below asks the model to make before asking.
_MORE_SAMPLES_RULE = (
    "If the shortlists you were shown do not let you decide, you may ask for "
    "more of them. Set `more_samples_requested` to the number of additional "
    "shortlists you need and say in `more_samples_reason` what they would "
    "settle. Ask when more candidates would change your verdict — not to defer "
    "one: a verdict is required in this reply either way, and asking is a "
    "request that is granted by rule, at most once and up to a fixed total. "
    "Before asking about the extent of a repeated family, read the candidate "
    "lines again: each one states how many roster members share that question, "
    "so a family's size is already in front of you even when the shortlists "
    "show only some of its members.")


#: The critic prompt's arms. `with_family_rule` is the default; `unaided` drops
#: that one block, so the rule's effect can be measured rather than assumed.
#:
#: `structured` is a different REPRESENTATION of the same two stages, not a
#: different procedure: same k shortlists, same critic over their union, same
#: sampling, but candidates arrive as typed JSON objects through
#: `agent/prompt_contract.py` and the model answers with INDICES it never has to
#: transcribe. See docs/adr/003-index-selection.md. One difference is not
#: cosmetic and is named in every report that uses it:
#: `agent/prompt_contract.py::VariableSelection` carries no
#: `more_samples_requested` field, so a `structured` run cannot ask for extra
#: shortlists and its `extra_requested` is 0 by construction rather than by
#: choice.
#:
#: A report always names the arm it used.
RESOLVER_PROMPT_ARMS = ("with_family_rule", "unaided", "structured")


def shortlist_prompt(query: ResolverQuery, pool: Sequence[str],
                     size: int = SHORTLIST_SIZE) -> str:
    """The prompt for one independent shortlist.

    Args:
        query: The fixture row.
        pool: The candidate keys to show, in the order to show them.
        size: How many candidates to ask for.

    Returns:
        The full prompt.
    """
    return "\n".join([
        f'A researcher asked for: "{query.request}"',
        "",
        "Candidate items from the survey codebook:",
        render_pool(pool),
        "",
        f"Shortlist the {size} most plausible items, most plausible first.",
        _COPY_RULE,
        "",
        "Return one JSON object matching this schema and nothing else:",
        json.dumps(Shortlist.model_json_schema()),
    ])


def critic_prompt(query: ResolverQuery, samples: Sequence[Shortlist],
                  agreed: Agreement, clarification: str = "",
                  arm: str = "with_family_rule") -> str:
    """The prompt that decides what kind of answer the request has.

    The shortlists are shown as their union with a count of how many ranked each
    item first, and the agreement figures are stated rather than left to be
    inferred. Disagreement between independent samples is the only evidence this
    call has that a request is underdetermined, so it is handed over as evidence
    instead of being averaged away — which is why `MIN_SAMPLES` refuses a run
    that cannot produce any.

    Args:
        query: The fixture row.
        samples: The shortlists that returned, in sample order.
        agreed: How much they agreed.
        clarification: The researcher's follow-up, when this is the narrowing
            arm. Empty on the first pass.
        arm: Which prompt arm to render. `with_family_rule` includes
            `_FAMILY_RULE`; `unaided` omits it, so the rule's effect on the
            family rows can be measured instead of assumed.

    Returns:
        The full prompt.

    Raises:
        ValueError: If `arm` names no prompt arm. Refused rather than defaulted:
            a typo that silently rendered the other arm would put two prompts
            behind one label, and every figure this module prints names its arm.
    """
    if arm not in RESOLVER_PROMPT_ARMS:
        raise ValueError(f"{arm!r} is not a prompt arm; "
                         f"expected one of {RESOLVER_PROMPT_ARMS}")
    ranked_first: dict[str, int] = {}
    union: list[str] = []
    for s in samples:
        for i, item in enumerate(s.items):
            if item.key not in union:
                union.append(item.key)
            if i == 0:
                ranked_first[item.key] = ranked_first.get(item.key, 0) + 1
    rows = "\n".join(
        f"{candidate_line(k)}\n     ranked first by "
        f"{ranked_first.get(k, 0)} of {len(samples)} shortlists"
        for k in union if k in tools._BY_KEY)
    said = (f'\n\nThe researcher has since clarified: "{clarification}"'
            if clarification else "")
    return "\n".join([
        f'A researcher asked for: "{query.request}"{said}',
        "",
        (f"{len(samples)} independent shortlist"
         f"{'s were' if len(samples) != 1 else ' was'} produced. "
         f"{'Their' if len(samples) != 1 else 'Its'} union:"),
        rows,
        "",
        f"Agreement on the first choice: {agreed.on_key} of {agreed.n} named "
        f"the same item; {agreed.on_family} of {agreed.n} named the same roster "
        f"family.",
        "",
        "Decide what kind of answer this request has. Where the shortlists "
        "disagree, treat the disagreement as evidence that the request is "
        "underdetermined.",
        "",
        "You have keys and question wording. You do not have response options, "
        "value labels, skip logic or any data. If separating two candidates "
        "would need a fact that is not in the wording you were shown, that is "
        "ambiguous, not a close call. Do not pick one to be helpful.",
        "",
        "For each candidate, first ask what would make it the wrong choice. "
        "Then decide.",
        "",
        *((_FAMILY_RULE, "") if arm == "with_family_rule" else ()),
        _MORE_SAMPLES_RULE,
        "",
        _COPY_RULE,
        "",
        "Return one JSON object matching this schema and nothing else:",
        json.dumps(CriticVerdict.model_json_schema()),
    ])


# --------------------------------------------------------------------------- #
# running the two calls
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Agreement:
    """How much a set of shortlists agreed on their first choice.

    Attributes:
        n: Shortlists asked for.
        returned: Shortlists that came back parseable and non-empty.
        on_key: The largest number that named the same first key.
        on_family: The largest number whose first key was in the same roster
            family. Never below `on_key`: two members of one family are the same
            question asked of two roster members, and a resolver that has found
            the family has done the hard half.
        first_keys: Each returned shortlist's first key, in sample order.
    """

    n: int
    returned: int
    on_key: int
    on_family: int
    first_keys: tuple[str, ...]


def agreement(samples: Sequence[Shortlist], n_asked: int) -> Agreement:
    """Measure how much the shortlists agreed on their first choice.

    Args:
        samples: The shortlists that returned.
        n_asked: How many were asked for, including any that failed.

    Returns:
        The agreement figures.
    """
    first = tuple(s.items[0].key for s in samples if s.items)

    def most(values: Sequence[str]) -> int:
        counts: dict[str, int] = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return max(counts.values()) if counts else 0

    fam = [family_of(k)[0] if k in tools._BY_KEY else k for k in first]
    return Agreement(n=n_asked, returned=len(samples), on_key=most(first),
                     on_family=most(fam), first_keys=first)


def _parse[M: BaseModel](raw: str, model: type[M]) -> M:
    """Read one JSON object out of a model reply and validate it.

    Args:
        raw: The reply, which may carry a markdown fence or prose around the
            object.
        model: The pydantic model to validate against.

    Returns:
        The validated object.

    Raises:
        ValueError: If no JSON object is present, or it does not validate. The
            caller records the failure as an outcome; it is never retried
            silently, because a silently retried call turns a malformed-output
            rate into zero.
    """
    text = raw.replace("```json", "").replace("```", "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    return model.model_validate(json.loads(text[start:end + 1]))


def _unusable(items: Sequence[ResolvedItem],
              pool: Sequence[str]) -> tuple[str, ...]:
    """The returned items that cannot be checked against the pool they came from.

    Two failures, one name: a key that was not among the candidates, and a key
    that was but whose wording is not what that line said. Both mean the same
    thing downstream — the answer cannot be traced to an item — and neither is
    repaired here, because a repaired answer is a different measurement.

    Wording is compared whitespace-collapsed, which is exactly the difference
    `agent/schema.py::_wording_is_verbatim` already forgives: the codebooks carry
    hard newlines inside quoted fields and the rendered line does not.

    Args:
        items: What the model returned.
        pool: The keys it was shown.

    Returns:
        One diagnosis per unusable item, empty when every item checks out.
    """
    shown = set(pool)
    bad: list[str] = []
    for item in items:
        if item.key not in shown:
            bad.append(f"{item.key}: not among the candidates shown")
            continue
        want = labels._flat(labels.cite(item.key).wording)
        if labels._flat(item.wording) != want:
            bad.append(f"{item.key}: wording returned is not this item's")
    return tuple(bad)


def run_shortlists(model: ModelFn, query: ResolverQuery, pool: Sequence[str],
                   n: int, arm: str = "with_family_rule"
                   ) -> tuple[tuple[Shortlist, ...], tuple[str, ...]]:
    """Ask for `n` independent shortlists and keep whatever comes back.

    Every arm returns the same internal `Shortlist` of key-and-wording items, so
    only the prompt and the reply schema differ between them and the scoring
    path downstream is identical.

    Args:
        model: The model call.
        query: The fixture row.
        pool: The candidates to show.
        n: How many shortlists to ask for.
        arm: Which prompt arm to render.

    Returns:
        `(shortlists that returned, one error string per one that did not)`.
    """
    surface = (structured_shortlist_contract(query, pool)
               if arm == "structured" else None)
    prompt = surface.render() if surface else shortlist_prompt(query, pool)
    good: list[Shortlist] = []
    errors: list[str] = []
    for i in range(n):
        try:
            if surface is not None:
                raw = _parse(model(prompt), VariableShortlist)
                parsed = Shortlist(
                    items=_items_from_indices(surface, raw.indices),
                    note=raw.note)
            else:
                parsed = _parse(model(prompt), Shortlist)
            if parsed.items:
                good.append(parsed)
            else:
                errors.append(f"sample {i}: empty shortlist")
        except Exception as exc:
            errors.append(f"sample {i}: {type(exc).__name__}: {exc}")
    return tuple(good), tuple(errors)


def grant_samples(asked_for: int, drawn: int, already_granted: bool) -> int:
    """How many further shortlists a request earns. A pure function.

    The whole of what happens after a critic asks for more evidence, and it
    reads none of the reason it gave. The model can see something the harness
    cannot — that the shortlists in front of it do not settle the question — and
    the harness decides what to do about it, which is the division `AGENTS.md`
    §Hard Constraints draws for `agent/specifier.py::_rank` and the reason this
    is a function and not a branch inside the loop: it can be tabled in a test.

    Granted at most once per row. A second grant would let a critic that asks on
    every reply walk the cap up one call at a time, and the run would stop being
    a fixed-cost measurement without anything in the report saying so.

    Args:
        asked_for: What the critic requested. Zero, absent or negative is no
            request.
        drawn: Shortlists this row has already drawn.
        already_granted: Whether this row has been granted extras before.

    Returns:
        Shortlists to draw now: 0 when nothing was asked, when a grant was
        already made, or when the row is at `MAX_SAMPLES`; otherwise what was
        asked for, clipped to the cap.
    """
    if asked_for <= 0 or already_granted:
        return 0
    return max(0, min(asked_for, MAX_SAMPLES - drawn))


def run_critic(model: ModelFn, query: ResolverQuery, pool: Sequence[str],
               samples: Sequence[Shortlist], agreed: Agreement,
               clarification: str = "",
               arm: str = "with_family_rule") -> tuple[CriticVerdict, bool]:
    """Ask what kind of answer the request has, with one repair attempt.

    The repair is the harness's, kept because it separates two failures that look
    alike: a critic that reasoned correctly and copied a key badly, and one that
    reasoned wrongly. It is REPORTED rather than absorbed — `repaired` reaches
    the report, so a run whose figures rest on second attempts says so.

    Args:
        model: The model call.
        query: The fixture row.
        pool: The candidates that were shown.
        samples: The shortlists that returned.
        agreed: Their agreement.
        clarification: The narrowing arm's follow-up, or empty.
        arm: Which prompt arm to render.

    Returns:
        `(the verdict, whether it took a second attempt)`.

    Raises:
        ValueError: If the reply cannot be parsed on either attempt.
    """
    if arm == "structured":
        union: list[str] = []
        for sample in samples:
            for item in sample.items:
                if item.key not in union:
                    union.append(item.key)
        surface = structured_critic_contract(query, union, clarification)
        chosen = _parse(model(surface.render()), contract.VariableSelection)
        # No repair turn: an index either resolves or it does not, and a second
        # ask cannot make an unoffered candidate offered. `repaired` is False by
        # construction here, which is the point rather than an omission.
        return CriticVerdict(
            verdict=chosen.verdict,
            items=_items_from_indices(surface, chosen.indices),
            recipe=chosen.recipe, missing_dimension=chosen.missing_dimension,
            reason=chosen.reason), False

    prompt = critic_prompt(query, samples, agreed, clarification, arm)
    out = _parse(model(prompt), CriticVerdict)
    bad = _unusable(out.items, pool)
    if bad and out.verdict in ("resolved", "family"):
        again = _parse(model(
            f"{prompt}\n\nYour previous reply returned items this pool cannot "
            f"account for:\n  " + "\n  ".join(bad) +
            "\n\nReply again, copying each key and its wording from the "
            "candidate line it came from."), CriticVerdict)
        return again, True
    return out, False


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


def answer_line(query: ResolverQuery) -> str:
    """The row's correct answer, on one line, for a table or a saved record.

    A row's answer is one of three shapes and they do not render alike: one key,
    a whole roster family, or a sentence for the rows where no key is right at
    all. A family renders as its size and one member rather than twenty keys —
    naming every member would push the request itself off the line, and any
    member identifies the family under `family_of`.

    Args:
        query: The fixture row.

    Returns:
        The answer, as a reader should see it.
    """
    if query.kind == "family" and query.gold:
        return f"family of {len(family_of(query.gold[0]))}, e.g. {query.gold[0]}"
    if query.gold:
        return ", ".join(query.gold)
    return query.expected or f"no key — {query.kind}"


def score_query(query: ResolverQuery, verdict: CriticVerdict,
                pool: Sequence[str]) -> Outcome:
    """Score one verdict against the row's answer.

    THE RULE, in one place, and `ANSWER_RULE` states it in the fixture's words.
    An exact answer is correct when the resolved key equals the gold key. A
    family answer is correct when any returned key belongs to the gold key's
    roster family, because every member is the same question asked of a different
    roster member and picking a different member is not a different answer.
    `derive` and `absent`/`ambiguous` answers are correct on the verdict alone —
    there is no key to compare, which is the point of those rows.

    ONE DEVIATION from the harness this is ported from, deliberately: naming a
    single item where the answer key says none is right scores `confident_wrong`
    for EVERY kind of request. The harness scored it that way for three of four
    kinds and folded it into `wrong` for exact requests, so the failure this
    benchmark exists to see was invisible in exactly the tier where a resolver is
    most likely to commit.

    Args:
        query: The fixture row.
        verdict: What the critic returned.
        pool: The candidates the critic was shown.

    Returns:
        The outcome.
    """
    if verdict.verdict in ("resolved", "family") and _unusable(
            verdict.items, pool):
        return "malformed"
    keys = tuple(i.key for i in verdict.items)
    named = verdict.verdict == "resolved"

    if query.kind == "exact":
        if named:
            return "correct" if keys[:1] == query.gold[:1] else "confident_wrong"
        if verdict.verdict in ("ambiguous", "absent"):
            return "over_abstained"
        return "wrong"

    if query.kind == "family":
        if named:
            return "confident_wrong"
        if verdict.verdict != "family" or not keys:
            return "wrong"
        gold_family = set(family_of(query.gold[0]))
        if any(k in gold_family for k in keys):
            return "correct"
        accepted = {m for a in query.accept_keys for m in family_of(a)}
        return "arguable" if any(k in accepted for k in keys) else "wrong"

    if query.kind == "derive":
        if verdict.verdict == "derive":
            return "correct"
        return "confident_wrong" if named else "wrong"

    if verdict.verdict in ("ambiguous", "absent"):
        return "correct"
    return "confident_wrong" if named else "wrong"


NarrowOutcome = Literal["narrow_resolved", "narrow_correctly_stuck",
                        "narrow_still_stuck", "narrow_wrong_key",
                        "narrow_false_resolve"]

#: The kinds of request where the answer key says NO SINGLE ITEM is right, so
#: naming one is a claim about the codebook and not merely a wrong pick.
NO_SINGLE_ANSWER_KINDS = ("family", "derive", "abstain")


def is_false_resolution(result: QueryResult) -> bool:
    """Whether this row is a FALSE POSITIVE: one item named where none is right.

    THE DISTINCTION `confident_wrong` ALONE CANNOT MAKE. On a `family`, `derive`
    or `abstain` row, answering `resolved` asserts something about the
    instrument that is not true — that a single variable measures the request —
    and a researcher who acts on it analyses one sibling as though it were the
    family, or one item as though it were a derivation. On an `exact` row the
    same outcome means the resolver picked the wrong item from a set where one
    was right, which is an error of identification and recoverable by looking at
    the wording it returned.

    Both score `confident_wrong`, because both are a confident wrong answer.
    Only the first is a false positive, and pooling them would let a run report
    a rate for a failure it had not measured.

    Args:
        result: One row's result.

    Returns:
        True when the resolver named a single item on a row whose answer is not
        a single item.
    """
    return (result.outcome == "confident_wrong"
            and result.kind in NO_SINGLE_ANSWER_KINDS)


#: What each narrowing outcome means. `narrow_correctly_stuck` and
#: `narrow_false_resolve` are the control: one fixture row supplies a
#: clarification that CANNOT resolve, because "narrowing helped" is unfalsifiable
#: without a row where it must not.
NARROW_MEANING: dict[str, str] = {
    "narrow_resolved": "the clarification resolved it",
    "narrow_correctly_stuck": "correctly still stuck",
    "narrow_still_stuck": "the clarification did not help",
    "narrow_wrong_key": "narrowed to the wrong item",
    "narrow_false_resolve": "resolved a request that stays unresolvable",
}


def score_narrowing(query: ResolverQuery,
                    verdict: CriticVerdict) -> NarrowOutcome | None:
    """Score the second pass, after a clarification was supplied.

    Args:
        query: The fixture row.
        verdict: What the critic returned on the second pass.

    Returns:
        The outcome, or None when the row has no narrowing arm.
    """
    if query.narrowing is None:
        return None
    keys = tuple(i.key for i in verdict.items)
    named = verdict.verdict == "resolved"
    if query.narrowing.gold is None:
        return "narrow_false_resolve" if named else "narrow_correctly_stuck"
    if named:
        return ("narrow_resolved" if keys[:1] == (query.narrowing.gold,)
                else "narrow_wrong_key")
    return "narrow_still_stuck"


# --------------------------------------------------------------------------- #
# the model-free half: is the answer even in the pool
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PoolOutcome:
    """Whether one pool arm put one row's answer in front of the resolver.

    Attributes:
        id: The fixture row.
        kind: The row's kind of answer.
        size: Candidates the arm produced.
        reachable: Whether any gold key is in the pool, or None for a row with
            no gold key — `derive` and `abstain` rows, where reachability is not
            defined and counting them either way would move the denominator
            without meaning anything.
        rank: 1-based position of the first gold key in the pool, or None when
            no gold key is in it.
    """

    id: str
    kind: str
    size: int
    reachable: bool | None
    rank: int | None


@dataclass(frozen=True)
class PoolReport:
    """What a pool arm reaches, before any model is asked anything.

    Attributes:
        arm: The pool arm's name.
        fixture_path: The fixture scored, relative to the repository root.
        dictionary_version: `version_hash` of the dictionary the keys resolve
            against.
        known_bias: The fixture's `KNOWN_BIAS`, verbatim.
        results: One outcome per fixture row, in fixture order.
    """

    arm: str
    fixture_path: str
    dictionary_version: str
    known_bias: str
    results: tuple[PoolOutcome, ...]

    def __post_init__(self) -> None:
        """Refuse a report that carries no bias notice.

        Raises:
            ValueError: If `known_bias` is empty or whitespace.
        """
        if not self.known_bias.strip():
            raise ValueError(
                "PoolReport built with no known_bias. The fixture's KNOWN_BIAS "
                "is what stops these numbers being read as ground truth.")

    @property
    def scored(self) -> tuple[PoolOutcome, ...]:
        """The rows reachability is defined for: those with a gold key."""
        return tuple(r for r in self.results if r.reachable is not None)

    @property
    def reachable(self) -> int:
        """How many of `scored` had a gold key in the pool."""
        return sum(1 for r in self.scored if r.reachable)

    @property
    def scope(self) -> str:
        """The glob, the filter and the definitions behind every figure here."""
        no_gold = len(self.results) - len(self.scored)
        return "\n".join([
            f"fixture         {self.fixture_path}",
            f"pool arm        {self.arm}",
            f"rows            {len(self.results)} in the fixture; "
            f"{len(self.scored)} scored",
            f"filter          {no_gold} row(s) carry no gold key (derive and "
            f"abstain): reachability is undefined for them and they are out of "
            f"the denominator, not counted as misses",
            f"dictionary      build/dictionary.json {self.dictionary_version}",
            "def reachable   rows with at least one gold key among the "
            "candidates the arm produced",
        ])


def evaluate_pools(arm: str = "frozen", fixture: ResolverFixture | None = None,
                   pool: PoolFn | None = None) -> PoolReport:
    """Measure what a pool arm reaches. No model is called.

    Read this before any resolver figure from the same arm. A resolver cannot
    name an item it was never shown, so a low score against an arm that drops the
    answer half the time is a retrieval result wearing a resolution result's
    clothes.

    Args:
        arm: The pool arm's name, for the report and for `POOL_ARMS`.
        fixture: A pre-loaded fixture; the committed one when omitted.
        pool: The pool callable. `POOL_ARMS[arm]` when omitted.

    Returns:
        The report.

    Raises:
        KeyError: If `arm` names no pool arm and no callable was supplied.
    """
    fx = fixture if fixture is not None else load_fixture()
    fn = pool if pool is not None else POOL_ARMS[arm]
    results: list[PoolOutcome] = []
    # A 22-row sweep through the lexical arm would otherwise land 22 entries in
    # the shared tool log and read, in a live run's audit trail, as calls the
    # Specifier made. Measuring is not running.
    depth = len(tools.LOG.calls)
    try:
        for q in fx.queries:
            keys = fn(q)
            rank: int | None = None
            for i, k in enumerate(keys, start=1):
                if k in q.gold:
                    rank = i
                    break
            results.append(PoolOutcome(
                id=q.id, kind=q.kind, size=len(keys),
                reachable=None if not q.gold else rank is not None, rank=rank))
    finally:
        del tools.LOG.calls[depth:]
    return PoolReport(arm=arm, fixture_path=_fixture_label(FIXTURE),
                      dictionary_version=tools.dictionary_version(),
                      known_bias=fx.known_bias, results=tuple(results))


def _fixture_label(path: Path) -> str:
    """The fixture path as a report should print it.

    Args:
        path: The fixture file that was read.

    Returns:
        The path relative to the repository root, or absolute when it lies
        outside.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- #
# the live half
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QueryResult:
    """What the resolver did on one row.

    Attributes:
        id: The fixture row.
        kind: The row's kind of answer.
        tier: The row's tier.
        pool_size: Candidates the arm produced for it.
        samples_drawn: Shortlists this row actually drew, extras included.
        answer: The row's correct answer, rendered by `answer_line`. Carried on
            the result so a saved run says what the right answer was, rather
            than needing the fixture read back beside it at the version it was
            scored against.
        model_calls: Every call this row made — shortlists, the critic, any
            repair, any second critic after extras, and the narrowing pass.
            Counted at the callable rather than derived from the other fields,
            because a repair on a critic pass that extras later superseded is
            invisible in them and would be silently dropped from any cost
            figure computed afterwards.
        extra_requested: What the first verdict asked for, or 0.
        extra_granted: What `grant_samples` allowed. Reported apart from
            `extra_requested` because a refused request is a result — a critic
            that keeps asking at the cap is telling you the cap is wrong.
        agreed: How much the shortlists agreed.
        verdict: What the critic returned, or None when the row was blocked.
        outcome: The score, or None when the row was blocked.
        narrow_outcome: The score after a clarification, or None when the row has
            no narrowing arm or never reached it.
        repaired: Whether the critic's answer took a second attempt.
        blocked: Why the row was not scored, or empty when it was.
        errors: One line per shortlist that did not return.
    """

    id: str
    kind: str
    tier: int
    pool_size: int
    answer: str
    samples_drawn: int
    model_calls: int
    extra_requested: int
    extra_granted: int
    agreed: Agreement | None
    verdict: CriticVerdict | None
    outcome: Outcome | None
    narrow_outcome: NarrowOutcome | None
    repaired: bool
    blocked: str
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolverReport:
    """One resolver run over the fixture.

    Attributes:
        arm: The pool arm's name.
        prompt_arm: Which critic prompt was rendered. Carried, not optional:
            `with_family_rule` tells the model how a repeated family appears in
            the pool and what to return for one, so two runs under different
            arms are not the same measurement.
        model_name: What answered, as the caller named it.
        n_samples: Shortlists asked for per row.
        fixture_path: The fixture scored, relative to the repository root.
        dictionary_version: `version_hash` of the dictionary behind the pools.
        known_bias: The fixture's `KNOWN_BIAS`, verbatim.
        answer_rule: The fixture's `answer_rule`, verbatim.
        results: One result per fixture row, in fixture order.
        sampling_note: How the k samples were drawn, and whether that is
            reproducible. Carried, not optional: the CLI backend exposes no seed
            and no temperature, so "3 independent samples" means something
            different there than through an API, and two agreement figures drawn
            differently are not on the same scale.

    Raises:
        ValueError: If `known_bias` is empty, or `answer_rule` is not the rule
            `score_query` implements.
    """

    arm: str
    prompt_arm: str
    model_name: str
    n_samples: int
    fixture_path: str
    dictionary_version: str
    known_bias: str
    answer_rule: str
    results: tuple[QueryResult, ...]
    sampling_note: str

    def __post_init__(self) -> None:
        """Refuse a report with no bias notice or the wrong answer rule.

        Raises:
            ValueError: If `known_bias` is empty or whitespace.
            ValueError: If `answer_rule` is not `ANSWER_RULE`.
        """
        if not self.known_bias.strip():
            raise ValueError(
                "ResolverReport built with no known_bias. The fixture's "
                "KNOWN_BIAS is what stops these numbers being read as ground "
                "truth; a report without it must not exist.")
        if " ".join(self.answer_rule.split()) != ANSWER_RULE:
            raise ValueError(
                f"The fixture states an answer rule this module does not "
                f"implement.\n  fixture says:  {self.answer_rule}\n  scorer "
                f"does:   {ANSWER_RULE}\nThe report PRINTS the fixture's "
                f"sentence as the definition behind every figure, so this run "
                f"would publish a rule that was never applied. Change "
                f"`score_query` and `ANSWER_RULE` together, or restore the "
                f"fixture's sentence.")

    @property
    def scored(self) -> tuple[QueryResult, ...]:
        """The rows that produced a verdict."""
        return tuple(r for r in self.results if r.outcome is not None)

    def tally(self) -> dict[str, int]:
        """Count the outcomes.

        Returns:
            Every outcome name mapped to its count, zeros included — an absent
            key and a zero read differently, and a tally that omits its zeros
            cannot be compared to another run's.
        """
        counts = dict.fromkeys(OUTCOME_MEANING, 0)
        for r in self.scored:
            if r.outcome is not None:
                counts[r.outcome] += 1
        return counts

    def narrow_tally(self) -> dict[str, int]:
        """Count the narrowing outcomes.

        Returns:
            Every narrowing outcome mapped to its count, zeros included.
        """
        counts = dict.fromkeys(NARROW_MEANING, 0)
        for r in self.results:
            if r.narrow_outcome is not None:
                counts[r.narrow_outcome] += 1
        return counts

    @property
    def blocked(self) -> tuple[QueryResult, ...]:
        """The rows that never reached a verdict."""
        return tuple(r for r in self.results if r.blocked)

    @property
    def repairs(self) -> int:
        """How many verdicts took a second attempt."""
        return sum(1 for r in self.results if r.repaired)

    @property
    def failed_calls(self) -> int:
        """How many shortlist calls did not come back usable."""
        return sum(len(r.errors) for r in self.results)

    @property
    def false_resolutions(self) -> tuple[QueryResult, ...]:
        """Rows where one item was named and the key says none is right."""
        return tuple(r for r in self.scored if is_false_resolution(r))

    @property
    def misidentifications(self) -> tuple[QueryResult, ...]:
        """Rows where one item was named, one was right, and it was another."""
        return tuple(r for r in self.scored
                     if r.outcome == "confident_wrong"
                     and not is_false_resolution(r))

    @property
    def model_calls(self) -> int:
        """Every model call this run made, across all rows."""
        return sum(r.model_calls for r in self.results)

    @property
    def extra_requests(self) -> int:
        """How many rows asked for further shortlists."""
        return sum(1 for r in self.results if r.extra_requested)

    @property
    def extra_grants(self) -> int:
        """How many rows were given them."""
        return sum(1 for r in self.results if r.extra_granted)

    @property
    def shortlists_drawn(self) -> int:
        """Shortlists this run drew in total, extras included.

        The run's real size. `n_samples` is what it asked for per row on the
        first pass, and a figure quoted as "at k samples" is wrong the moment a
        single extra is granted.
        """
        return sum(r.samples_drawn for r in self.results)

    @property
    def scope(self) -> str:
        """The glob, the filter and the definitions behind every figure here."""
        return "\n".join([
            f"fixture         {self.fixture_path}",
            f"pool arm        {self.arm}",
            f"prompt arm      {self.prompt_arm}",
            f"model           {self.model_name}",
            f"samples         {self.n_samples} shortlists per row, then one "
            f"critic over their union; a critic may request more, granted by "
            f"rule up to {MAX_SAMPLES} per row",
            f"drawn           {self.shortlists_drawn} shortlists over "
            f"{len(self.results)} rows; {self.extra_requests} row(s) asked for "
            f"extras and {self.extra_grants} were granted",
            f"sampling        {self.sampling_note}",
            f"rows            {len(self.results)} in the fixture; "
            f"{len(self.scored)} scored, {len(self.blocked)} blocked",
            "filter          a blocked row is reported, never scored and never "
            "counted as an error",
            f"dictionary      build/dictionary.json {self.dictionary_version}",
            f"answer rule     {self.answer_rule}",
        ])


#: What `evaluate` records about sampling when the caller says nothing. Names the
#: degradation rather than leaving it to be discovered: `agent/cli_backend.py`
#: exposes no seed and no temperature, so k samples vary without being
#: reproducible.
DEFAULT_SAMPLING_NOTE = (
    "UNCONTROLLED — the caller supplied no note. If this ran through the CLI "
    "backend there is no seed and no temperature, so the samples vary without "
    "being reproducible and the agreement figure is not repeatable.")


def evaluate(model: ModelFn, arm: str = "frozen", n_samples: int = 3,
             fixture: ResolverFixture | None = None,
             pool: PoolFn | None = None, model_name: str = "unnamed",
             sampling_note: str = DEFAULT_SAMPLING_NOTE,
             prompt_arm: str = "with_family_rule") -> ResolverReport:
    """Run the resolver over the fixture and score it.

    Args:
        model: The model call: prompt in, raw text out.
        arm: The pool arm's name, for the report and for `POOL_ARMS`.
        n_samples: Shortlists per row. At least `MIN_SAMPLES`.
        fixture: A pre-loaded fixture; the committed one when omitted.
        pool: The pool callable. `POOL_ARMS[arm]` when omitted.
        model_name: What to record as having answered.
        sampling_note: How the samples were drawn, and whether that repeats.
        prompt_arm: Which critic prompt to run — see `RESOLVER_PROMPT_ARMS`.

    Returns:
        The report, one result per fixture row.

    Raises:
        ValueError: If `n_samples` is below `MIN_SAMPLES`. A single shortlist
            cannot disagree with itself, so the critic's one signal that a
            request is underdetermined would be absent while the run still
            scored — `AGENTS.md` §Contamination Practice, a prose resolver
            refuses to start unconfirmed at n=1.
        KeyError: If `arm` names no pool arm and no callable was supplied.
    """
    if n_samples < MIN_SAMPLES:
        raise ValueError(
            f"n_samples={n_samples} is below MIN_SAMPLES={MIN_SAMPLES}. The "
            f"critic's only evidence that a request is underdetermined is "
            f"disagreement between independent shortlists, and {n_samples} "
            f"shortlist(s) cannot disagree. Run this at {MIN_SAMPLES} or more, "
            f"or report it as a single-sample probe and not as a resolver "
            f"figure.")
    fx = fixture if fixture is not None else load_fixture()
    fn = pool if pool is not None else POOL_ARMS[arm]
    results: list[QueryResult] = []
    depth = len(tools.LOG.calls)
    try:
        for q in fx.queries:
            results.append(_run_row(model, q, fn(q), n_samples, prompt_arm))
    finally:
        del tools.LOG.calls[depth:]
    return ResolverReport(
        arm=arm, prompt_arm=prompt_arm, model_name=model_name,
        n_samples=n_samples, fixture_path=_fixture_label(FIXTURE),
        dictionary_version=tools.dictionary_version(),
        known_bias=fx.known_bias, answer_rule=fx.answer_rule,
        results=tuple(results), sampling_note=sampling_note)


def _run_row(model: ModelFn, query: ResolverQuery, pool: tuple[str, ...],
             n_samples: int, arm: str = "with_family_rule") -> QueryResult:
    """Resolve one row: k shortlists, one critic, any extras, the narrowing arm.

    THE SECOND CRITIC CALL IS THE SCORED ONE when extras are granted. The first
    verdict is required even when it asks for more — asking is not a way to
    defer deciding — but it was reached without evidence the harness then
    supplied, so scoring it would score a question the critic had already said
    it could not answer. What the run keeps of the first verdict is that it
    asked, and how much.

    Args:
        model: The model call.
        query: The fixture row.
        pool: The candidates for this row.
        n_samples: Shortlists to draw on the first pass.
        arm: Which critic prompt arm to render.

    Returns:
        The row's result, blocked rather than scored when too few shortlists
        returned to measure agreement.
    """
    calls = 0

    def counted(prompt: str) -> str:
        """Call the model and count it.

        Every path out of this function goes through here, so the count is the
        row's real cost rather than a reconstruction from the fields that
        happened to survive — a repair on a superseded critic pass leaves no
        other trace.

        Args:
            prompt: The prompt to send.

        Returns:
            The raw reply.
        """
        nonlocal calls
        calls += 1
        return model(prompt)

    if not pool:
        return QueryResult(
            id=query.id, kind=query.kind, tier=query.tier, pool_size=0,
            answer=answer_line(query), samples_drawn=0, model_calls=0,
            extra_requested=0, extra_granted=0,
            agreed=None, verdict=None, outcome=None, narrow_outcome=None,
            repaired=False,
            blocked="the pool arm produced no candidates for this row")

    samples, errors = run_shortlists(counted, query, pool, n_samples, arm)
    agreed = agreement(samples, n_samples)
    if len(samples) < MIN_SAMPLES:
        return QueryResult(
            id=query.id, kind=query.kind, tier=query.tier, pool_size=len(pool),
            answer=answer_line(query), samples_drawn=n_samples,
            model_calls=calls, extra_requested=0,
            extra_granted=0, agreed=agreed, verdict=None, outcome=None,
            narrow_outcome=None, repaired=False, errors=errors,
            blocked=(f"only {len(samples)} of {n_samples} shortlists returned; "
                     f"{MIN_SAMPLES} are needed before agreement means "
                     f"anything"))

    verdict, repaired = run_critic(counted, query, pool, samples, agreed,
                                   arm=arm)
    drawn, asked, granted = n_samples, max(0, verdict.more_samples_requested), 0
    # A loop, not a branch, so `grant_samples` is what ends it: the policy —
    # once per row, never past the cap — lives in the pure function where a test
    # can table it, and not in this control flow where it could only be read.
    while (now := grant_samples(max(0, verdict.more_samples_requested), drawn,
                                already_granted=granted > 0)):
        more, more_errors = run_shortlists(counted, query, pool, now, arm)
        drawn += now
        granted += now
        samples = samples + more
        errors = errors + more_errors
        agreed = agreement(samples, drawn)
        verdict, repaired = run_critic(counted, query, pool, samples, agreed,
                                       arm=arm)

    outcome = score_query(query, verdict, pool)

    narrow: NarrowOutcome | None = None
    if verdict.verdict == "ambiguous" and query.narrowing is not None:
        again, _ = run_critic(counted, query, pool, samples, agreed,
                              query.narrowing.supply, arm)
        narrow = score_narrowing(query, again)

    return QueryResult(
        id=query.id, kind=query.kind, tier=query.tier, pool_size=len(pool),
        answer=answer_line(query), samples_drawn=drawn, model_calls=calls,
        extra_requested=asked,
        extra_granted=granted, agreed=agreed, verdict=verdict, outcome=outcome,
        narrow_outcome=narrow, repaired=repaired, blocked="", errors=errors)


# --------------------------------------------------------------------------- #
# the live backend
# --------------------------------------------------------------------------- #

#: The default resolver model. NOT the Specifier's pin: `AGENTS.md` §Hard
#: Constraints pins the in-pipeline Specifier to `claude-haiku-4-5` as the proxy
#: for the 8-27B target, and `TASKS.md` C17 says in as many words that the pin
#: covers the Specifier and not a resolver — a larger resolver is legitimate,
#: and a record that hides which model resolved is not. So this is a default a
#: caller may raise, and every report names what answered.
DEFAULT_RESOLVER_MODEL = "claude-haiku-4-5"

#: What `live_model` records about its own sampling. The degradation is named
#: rather than discovered: `agent/cli_backend.py` exposes no seed and no
#: temperature flag, so the k shortlists vary — which is what makes them
#: independent, and what makes the agreement figure unrepeatable.
LIVE_SAMPLING_NOTE = (
    "k separate `claude -p` invocations, each a fresh process with no shared "
    "state. The CLI exposes no seed and no temperature, so the samples are "
    "independent but NOT reproducible: a rerun will not repeat this agreement "
    "figure, and two runs' agreement figures are comparable only in "
    "distribution.")


def live_model(model_id: str = DEFAULT_RESOLVER_MODEL,
               mode: str = "benchmark") -> tuple[ModelFn, str]:
    """A model call backed by headless `claude -p`, sealed and toolless.

    REUSES `agent/cli_backend.py::ClaudeCliBackend.transduce` rather than
    shelling out here, and the reuse is the safety property, not a convenience:
    that path already runs in a `SealedWorktree` — an empty `mkdtemp` cwd, so no
    project memory, no `CLAUDE.md`, no user settings — and already denies every
    built-in tool, so the model cannot `cat` the dictionary instead of reading
    the pool it was shown. A resolver that read the instrument off disk would
    produce exactly the answers this benchmark is trying to measure it failing
    to produce.

    Its fixed system prompt — one JSON object, no prose, no fence — is the one
    this module wants, which is why every instruction the resolver gives lives
    in the prompt. That is also what keeps the whole model-visible surface
    scannable from the strings `model_visible_surface` already collects.

    Args:
        model_id: The model to run.
        mode: The registry mode the seal is built for. `benchmark` here; the
            resolver reaches no tools either way.

    Returns:
        `(the model call, the sampling note to record with the run)`.
    """
    from agent.cli_backend import ClaudeCliBackend

    backend = ClaudeCliBackend(model=model_id, mode=mode)

    def call(prompt: str) -> str:
        return str(backend.transduce(prompt).content)

    return call, LIVE_SAMPLING_NOTE


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def format_pool_report(report: PoolReport) -> str:
    """Render a pool report, bias notice above the first figure.

    Args:
        report: The report to render.

    Returns:
        The full text.
    """
    n = len(report.scored)
    lines = [
        f"resolver pool reachability — arm {report.arm!r}, no model called",
        "",
        report.scope,
        "",
        BIAS_BANNER,
        f"    {report.known_bias}",
        "",
        f"answer reachable {report.reachable:>3}/{n}  "
        f"{100 * report.reachable / n if n else 0:5.1f}%",
        "",
        "per row — 'rank -' means no gold key is in the pool at all:",
    ]
    for r in report.results:
        rank = "n/a" if r.reachable is None else (
            "-" if r.rank is None else str(r.rank))
        lines.append(f"    {r.id}  {r.kind:<8} pool {r.size:>5}  rank {rank:>5}")
    return "\n".join(lines)


def format_row_table(report: ResolverReport) -> str:
    """One line per row: what it cost, what it agreed on, and what it got wrong.

    The aggregate tally says how often the resolver was right; it cannot say
    WHERE. This says which requests failed, what the answer was, how many model
    calls the row took, whether it asked for more evidence, how much the
    shortlists agreed, and whether the failure was a false positive — a single
    item named where none is right — or a wrong pick from a set where one was.

    The agreement column is `on_key / returned`, never `on_key / n`: a run whose
    shortlists partly failed would otherwise report agreement diluted by calls
    that never produced an opinion, which reads as disagreement.

    Args:
        report: The report to render.

    Returns:
        The table, header first.
    """
    head = (f"{'row':<7}{'t':<3}{'kind':<9}{'result':<17}{'calls':>6}"
            f"{'smp':>5}{'asked':>7}{'agree':>8}{'FP':>4}  answer")
    lines = [head, "-" * len(head)]
    for r in report.results:
        agree = ("  n/a" if r.agreed is None or not r.agreed.returned
                 else f"{r.agreed.on_key}/{r.agreed.returned}")
        asked = (f"{r.extra_requested}"
                 f"{'' if r.extra_requested == r.extra_granted else '!'}")
        result = r.outcome or ("BLOCKED" if r.blocked else "-")
        lines.append(
            f"{r.id:<7}{r.tier:<3}{r.kind:<9}{result:<17}{r.model_calls:>6}"
            f"{r.samples_drawn:>5}{asked:>7}{agree:>8}"
            f"{'yes' if is_false_resolution(r) else '-':>4}  {r.answer[:44]}")
    lines += [
        "",
        "calls  every model call the row made, repairs and narrowing included",
        "smp    shortlists drawn, extras included",
        "asked  further shortlists the critic requested; '!' means refused",
        "agree  shortlists naming the same first item, over those that returned",
        "FP     false positive: one item named where the key says none is right",
    ]
    return "\n".join(lines)


def format_report(report: ResolverReport) -> str:
    """Render a resolver report, bias notice above the first figure.

    Args:
        report: The report to render.

    Returns:
        The full text.
    """
    tally = report.tally()
    n = len(report.scored)
    lines = [
        f"resolver — {report.model_name} over the committed fixture",
        "",
        report.scope,
        "",
        BIAS_BANNER,
        f"    {report.known_bias}",
        "",
    ]
    for name, meaning in OUTCOME_MEANING.items():
        lines.append(f"{tally[name]:>4}/{n}  {name:<16} {meaning}")
    lines += [
        "",
        f"{report.repairs:>4}      verdict(s) took a second attempt after "
        f"returning an unusable key",
        f"{report.failed_calls:>4}      shortlist call(s) did not come back "
        f"usable",
        f"{len(report.blocked):>4}      row(s) blocked before a verdict",
        f"{report.extra_requests:>4}      row(s) asked for further shortlists; "
        f"{report.extra_grants} granted, "
        f"{report.extra_requests - report.extra_grants} refused at the cap",
        f"{report.model_calls:>4}      model call(s) over "
        f"{len(report.results)} rows",
        "",
        f"{len(report.false_resolutions):>4}/{n}  FALSE POSITIVES — one item "
        f"named where the key says none is right",
        f"{len(report.misidentifications):>4}/{n}  misidentified — one item was "
        f"right and another was named",
    ]
    narrow = report.narrow_tally()
    if any(narrow.values()):
        lines += ["", "after a clarification was supplied:"]
        for name, meaning in NARROW_MEANING.items():
            lines.append(f"{narrow[name]:>4}      {name:<24} {meaning}")
    if report.blocked:
        lines += ["", "blocked rows:"]
        lines += [f"    {r.id}  {r.blocked}" for r in report.blocked]
    lines += ["", format_row_table(report)]
    return "\n".join(lines)


def _main(argv: Sequence[str] | None = None) -> int:
    """Print what each pool arm reaches. No model is called.

    The live half needs a model, so it is not what a bare `python -m` run does:
    a benchmark command that silently spends money is a benchmark command people
    stop running.

    Args:
        argv: Command line, or None to read `sys.argv`.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__ or "")
    ap.add_argument("--arm", default="frozen", choices=sorted(POOL_ARMS),
                    help="which pool arm to measure")
    ap.add_argument("--live", action="store_true",
                    help="run the resolver itself, through headless `claude -p`")
    ap.add_argument("--model", default=DEFAULT_RESOLVER_MODEL,
                    help="the resolver model, when --live")
    ap.add_argument("--samples", type=int, default=3,
                    help=f"shortlists per row on the first pass, at least "
                         f"{MIN_SAMPLES}")
    ap.add_argument("--rows", default="",
                    help="comma-separated row ids, for a pilot over a subset")
    args = ap.parse_args(argv)

    if not args.live:
        print(format_pool_report(evaluate_pools(args.arm)))
        return 0

    fixture = load_fixture()
    if args.rows:
        wanted = [r.strip() for r in args.rows.split(",") if r.strip()]
        by_id = {q.id: q for q in fixture.queries}
        fixture = fixture.model_copy(
            update={"queries": tuple(by_id[r] for r in wanted)})
    model, note = live_model(args.model)
    print(format_report(evaluate(
        model, arm=args.arm, n_samples=args.samples, fixture=fixture,
        model_name=args.model, sampling_note=note)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


# --------------------------------------------------------------------------- #
# the structured arm — candidates as typed records, answers as indices
# --------------------------------------------------------------------------- #


class VariableShortlist(BaseModel):
    """A ranked shortlist of candidate indices for one request.

    Field descriptions are prompt text — `SelectionContract.render` puts
    `model_json_schema()` into the prompt — so the `agent/schema.py` rule binds
    this class: no study design, exposure, outcome, paper count, cohort figure
    or prevalence.

    `outcome` exists so a shortlist can decline. The line-format arm has no way
    to: on the 2026-09-01 run GQ015 returned an empty list three times and the
    row was BLOCKED as three failed calls, when an empty shortlist for a
    request no single item measures may be the correct answer. Here declining is
    a value, which is the same rule `SelectionContract` enforces on the critic.

    Attributes:
        outcome: `shortlisted` when candidates are offered, `absent` when no
            candidate is plausible.
        indices: The most plausible candidate `index` values, most plausible
            first.
        note: One sentence on what the ranking turned on.
    """

    outcome: Literal["shortlisted", "absent"]
    indices: tuple[int, ...] = ()
    note: str = ""


def candidate_facts(key: str) -> dict[str, object]:
    """The facts a structured candidate carries, from dictionary fields only.

    The same three the line format put in a parenthesised clause, plus the grid
    column that the line format buried at character 99 of a 99-character
    identical prefix. Named fields, so the model reads them instead of parsing
    them out of a string.

    Args:
        key: A fully qualified variable key.

    Returns:
        The facts, omitting any that do not apply to this item.

    Raises:
        KeyError: If the key is not in the built dictionary.
    """
    entry = _entry(key)
    facts: dict[str, object] = {"module": str(entry["module"])}
    # READ, not derived. This grouped by `family_of` until build c272da5de196
    # gained the column: `agent/prompt_contract.py` names `roster_family_size`
    # in prompt text and cannot import this module, so the value the model reads
    # was computed somewhere the surface describing it could not see.
    #
    # The two definitions agree on all 1,520 roster rows and differ on five
    # non-roster ones, where `family_of`'s tuple key groups three write-in slots
    # on `m1:Q3.10` and the two occurrences of `m2:Q785`. The column is null
    # there, which is right: none of those five is a question asked once per
    # roster member.
    if entry["roster_family_size"] is not None:
        facts["roster_family_size"] = int(entry["roster_family_size"])
    if entry["roster_row"] is not None:
        facts["roster_row"] = int(entry["roster_row"])
    if entry["subitem_text"]:
        facts["grid_column"] = str(entry["subitem_text"])
    n_modules = _duplicate_text_modules()[
        labels._flat(str(entry["question_text"]))]
    if n_modules > 1:
        facts["same_wording_in_n_modules"] = n_modules
    return facts


def _contract_for(task: str, keys: Sequence[str],
                  output_model: type[BaseModel], refusal: str,
                  name: str) -> contract.SelectionContract:
    """Build a contract over these keys, indexed 1..n in the order given.

    Args:
        task: The stage's own task text. Each stage supplies its own: the
            critic's task asks what KIND of answer a request has, which is not
            what a shortlist is being asked, and gluing one onto the other puts
            a verdict instruction in front of a ranking call.
        keys: The candidate keys to offer.
        output_model: The answer's schema.
        refusal: The value meaning "no candidate answers this".
        name: The surface's name.

    Returns:
        The contract.
    """
    return contract.SelectionContract(
        name=name, task=task, output_model=output_model, refusal=refusal,
        candidates=contract.candidates_from_keys(
            keys, {k: candidate_facts(k) for k in keys}))


def structured_shortlist_contract(query: ResolverQuery,
                                  pool: Sequence[str]
                                  ) -> contract.SelectionContract:
    """The shortlist stage, as a contract.

    Args:
        query: The fixture row.
        pool: The candidate keys to show, in the order to show them.

    Returns:
        The contract whose `render` is the shortlist prompt.
    """
    return _contract_for(
        f'A researcher asked for: "{query.request}"\n\n'
        f"Shortlist the {SHORTLIST_SIZE} most plausible items, most plausible "
        f"first. You are ranking candidates, not deciding the answer: another "
        f"call decides what kind of answer this request has.",
        pool, VariableShortlist, "absent", "resolver_shortlist")


def structured_critic_contract(query: ResolverQuery, keys: Sequence[str],
                               clarification: str = ""
                               ) -> contract.SelectionContract:
    """The critic stage, as a contract over the union of the shortlists.

    Re-indexed 1..n over the union rather than over the pool: the critic is
    shown a different candidate list from the shortlists, and an index that
    meant one item in one prompt and another in the next is the failure this
    representation exists to remove, reintroduced between two calls.

    Args:
        query: The fixture row.
        keys: The union of shortlisted keys, in first-seen order.
        clarification: The narrowing arm's follow-up, or empty.

    Returns:
        The contract whose `render` is the critic prompt.
    """
    said = (f'\n\nThe researcher has since clarified: "{clarification}"'
            if clarification else "")
    task = contract.retrieval_contract(f"{query.request}{said}", ()).task
    return _contract_for(task, keys, contract.VariableSelection, "absent",
                         "resolver_critic")


def _items_from_indices(surface: contract.SelectionContract,
                        indices: Sequence[int]) -> tuple[ResolvedItem, ...]:
    """Resolve returned indices to items, so every arm scores the same way.

    An index outside the offered range is DROPPED rather than raised on, and
    that is the whole difference between the arms in one line: the line format
    could return a key that resolved to nothing, and this cannot — the worst it
    can do is name a candidate that was not offered, which leaves nothing to
    score rather than something unusable.

    Args:
        surface: The contract the indices came from.
        indices: What the model returned.

    Returns:
        One item per resolvable index, in the order given.
    """
    out: list[ResolvedItem] = []
    for i in indices:
        try:
            cited = surface.resolve(int(i))
        except (IndexError, ValueError, TypeError):
            continue
        out.append(ResolvedItem(key=cited.key, wording=cited.wording))
    return tuple(out)
