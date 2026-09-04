"""env/labels.py — a variable key cannot be shown to the model without its wording.

INVARIANT: nothing in env/ imports a model or touches the network. This module is
stdlib-only and reads one generated file.

THE MEASURED FAILURE THIS PREVENTS. In a traced live run, 6 of 44 tool calls (14%)
were the model re-asking what a key it had already been given actually says,
because the prompt names member keys bare (`member keys  m3:Q16.1_1,
m3:Q16.1_2, ...`). In the same run the model adjusted for `m1:1_Q6.3` -- whose
text begins "1 - How old is this household member?" -- as if it were the
respondent's own age. A bare key is not a variable; it is a label for one, and a
label the reader has to look up is a label the reader guesses at.

So the fix is a TYPE, not a convention: `Cited` cannot be constructed without the
wording, and `cite()` is the only way to get one. No value in this module holds a
key alone, so there is no code path that can hand out a key with its text
detached.

TWO THINGS THAT LOOK LIKE CLEANUPS AND ARE NOT:

  * `wording` is `question_text` byte for byte. It is NOT rebuilt from
    `stem_text + " - " + subitem_text`: measured on build 6fcd02755bf3, 2 of the
    876 entries carrying both fields do not reconcile that way
    (`m3:Q12.12_3_TEXT`, `m3:Q12.13_3_TEXT`), so that join is a reconstruction
    which is wrong twice, not an identity.

  * The leading roster index ("1 - ") is never stripped. 970 of the 1,520 roster
    entries carry one, and `agent/schema.py::_norm` collapses whitespace and
    nothing else -- so a stripped string fails `_wording_is_verbatim`, which
    diffs a record's `quoted_wording` against this same dictionary. The roster
    row is exposed as its own field instead, which is also the honest fix for the
    `m1:1_Q6.3` confusion above: the other 550 roster entries carry no in-text
    index at all, so a prefix regex is not a referent test, and `roster_row` is
    carried from the dictionary field rather than inferred from the text.

  * Rendering collapses whitespace; the stored `wording` never does. 323 of the
    2,804 `question_text` values carry hard newlines inside the quoted codebook
    field, and a line-oriented citation block cannot tell one of those from a new
    citation. Collapsing is applied at render only, and it is exactly the
    difference `agent/schema.py::_norm` already forgives -- so a model that
    quotes what it was shown still passes `_wording_is_verbatim`, while
    `Cited.wording` stays byte-for-byte `question_text` for anything that diffs
    against the dictionary directly.

RENDER BUDGET. `render()` never truncates silently. What does not fit is named,
key by key, in the render itself -- a citation block that quietly shortened would
recreate the failure above one level down.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

#: Characters of wording one citation block may spend. A funnel anchor construct
#: renders well inside this; a 64-item block does not, and is expected to report
#: the overflow rather than hide it.
CITATION_BUDGET = 600

#: The sub-item separator the instrument itself uses. Shared-prefix factoring
#: snaps back to the last occurrence of this string so a split never lands
#: mid-word: "... - Item A" and "... - Item Absolutely" share the characters
#: "... - Item A", and a raw character prefix would cut inside "Absolutely".
_SEP = " - "

#: Printed between a key and its wording. Verified on build 6fcd02755bf3: this
#: character occurs in 0 of the 2,804 `question_text` values, so a reader can
#: split a rendered line on it without ever splitting inside an instrument
#: string. ASCII on purpose -- a prettier separator was a U+203A, which `ruff`
#: RUF001 flags as confusable and which would have travelled into a prompt as
#: a character the model may or may not reproduce when it quotes back.
#: `tests/test_labels.py::test_render_mark_occurs_in_no_wording` re-checks the
#: absence against the current build rather than trusting this comment.
_MARK = " | "

_INDEX: dict[str, Cited] | None = None


class CitationUnavailable(LookupError):
    """Raised when a key cannot be bound to wording.

    Raising is the point. A `Cited` carrying an empty string would satisfy every
    type check in this module and put a bare key in front of the model anyway --
    which is the failure the module exists to remove, and this codebase's
    signature failure is a guarantee that reads as enforced and is not.
    """


@dataclass(frozen=True, slots=True)
class Cited:
    """One variable key, bound to the instrument's text for it.

    Frozen and slotted so the binding cannot be broken after construction: no
    reassignment of `wording`, and no fourth attribute smuggled on at runtime.

    Attributes:
        key: Fully qualified variable key, e.g. `m1:1_Q6.3`.
        wording: The dictionary's `question_text`, byte for byte. Never rebuilt
            from stem and sub-item, and never stripped of a roster index -- see
            the module docstring for the measurements behind both.
        roster_row: The roster repeat this key belongs to, or None when the key
            is not a roster repeat. Carried from the dictionary field, never
            inferred from the text.
    """

    key: str
    wording: str
    roster_row: int | None = None

    def __post_init__(self) -> None:
        """Reject a citation that cites nothing.

        Raises:
            CitationUnavailable: If `key` or `wording` is empty or blank.
        """
        if not self.key.strip():
            raise CitationUnavailable("a Cited needs a key")
        if not self.wording.strip():
            raise CitationUnavailable(
                f"{self.key!r} has no wording. An empty-string wording is the "
                "silent form of showing the model a bare key -- raise instead.")

    def render(self) -> str:
        """Render this citation on one line, wording verbatim.

        Returns:
            The key, its roster tag if it has one, the mark, and the wording.
        """
        return f"{self.key}{_roster_tag(self)}{_MARK}{_flat(self.wording)}"


@dataclass(frozen=True, slots=True)
class CitedSet:
    """Several citations plus the character budget their rendering may spend.

    Attributes:
        items: The citations, in the order they were asked for, deduplicated by
            key. A tuple rather than a list: `frozen=True` stops rebinding the
            attribute, not mutation of a list behind it.
        budget: Characters of wording `render` may spend before it starts
            reporting omissions. Defaults to `CITATION_BUDGET`.
    """

    items: tuple[Cited, ...] = ()
    budget: int = CITATION_BUDGET

    def keys(self) -> tuple[str, ...]:
        """Return every key in the set, in order.

        Returns:
            The keys, deduplicated, in the order they were cited.
        """
        return tuple(c.key for c in self.items)

    def plan(self) -> tuple[tuple[Cited, ...], tuple[Cited, ...]]:
        """Split the set into what the budget affords and what it does not.

        The shared stem is charged before any item is, because the stem is
        wording too -- a budget counting only the sub-items would under-report
        the cost of exactly the grid batteries factoring exists for.

        Exposed separately from `render` so a caller, or a test, can ask what was
        dropped without parsing prose back out of the rendered block.

        Returns:
            `(kept, dropped)`, both in citation order.
        """
        stem, lines = self._body()
        spent, cut = len(stem), len(self.items)
        for i, line in enumerate(lines):
            if spent + len(line) > self.budget:
                cut = i
                break
            spent += len(line)
        return self.items[:cut], self.items[cut:]

    def render(self) -> str:
        """Render the set as the exact string the model sees.

        A shared prefix across the wordings is factored out and printed once,
        with the split snapped back to the last `" - "`, so a grid battery shows
        its stem followed by its sub-items. The prefix is computed here and never
        stored: a stored prefix is a second copy of the wording that can go stale
        against the dictionary, and the guarantee is that there is one copy.

        Reconstruction is exact by construction, not by convention. The stem is a
        literal character prefix of every wording in the group, and each item's
        printed text is the remainder of its own wording starting at the split,
        so joining the two returns `question_text` byte for byte -- which is what
        `agent/schema.py::_wording_is_verbatim` diffs a record against.

        Returns:
            The citation block. Empty string only for an empty set.
        """
        if not self.items:
            return ""
        kept, dropped = self.plan()
        stem, lines = self._body()

        out: list[str] = []
        if stem and kept:
            out.append(stem)
        out.extend(lines[:len(kept)])
        if stem and kept:
            out.append(
                "    (indented sub-item: its full wording is the stem line above "
                f"followed by the text after {_MARK.strip()!r}.)")
        if dropped:
            out.append(_omission_notice(self.budget, len(kept), dropped))
        return "\n".join(out)

    def _body(self) -> tuple[str, list[str]]:
        """Render the stem and one line per citation, before any budget applies.

        Budgeting measures these strings, so it must see exactly what `render`
        prints. Computing them from two code paths is how a budget starts capping
        something other than what it counts.

        Returns:
            `(stem, lines)`. `stem` is empty when nothing factored, in which case
            each line carries a whole wording.
        """
        stem, remainders = _factor(tuple(_flat(c.wording) for c in self.items))
        if not stem:
            return "", [c.render() for c in self.items]
        return stem, [
            f"    {c.key}{_roster_tag(c)}{_MARK.rstrip()}{rem}"
            for c, rem in zip(self.items, remainders, strict=True)
        ]


def _flat(t: str) -> str:
    """Collapse whitespace for rendering. Never applied to a stored `wording`.

    Character-identical to `agent/schema.py::_norm`, which is the normalisation
    `_wording_is_verbatim` diffs under, so a model quoting what it was rendered
    still validates. `tests/test_labels.py::test_flat_matches_schema_norm`
    asserts the two agree on all 2,804 entries rather than trusting this
    sentence -- a second implementation of a normalisation rule is exactly the
    kind of quiet divergence this codebase keeps finding.

    Args:
        t: Any instrument text.

    Returns:
        The text with runs of whitespace collapsed to single spaces.
    """
    return " ".join(t.split())


def _roster_tag(c: Cited) -> str:
    """Render a citation's roster row as a tag outside its wording.

    The tag sits before the mark, never inside the quoted text, so the wording
    after the mark stays byte-identical to the dictionary. `m1:1_Q6.3` is the
    case that motivated it: its text names a household member, and a live run
    adjusted for it as the respondent's own age.

    Args:
        c: The citation.

    Returns:
        ` [roster row N]`, or empty when the key is not a roster repeat.
    """
    return "" if c.roster_row is None else f" [roster row {c.roster_row}]"


def _common_prefix(strings: Sequence[str]) -> str:
    """Return the longest character prefix shared by every string.

    Args:
        strings: At least one string.

    Returns:
        The shared prefix, possibly empty.
    """
    lo, hi = min(strings), max(strings)
    i = 0
    while i < len(lo) and i < len(hi) and lo[i] == hi[i]:
        i += 1
    return lo[:i]


def _factor(wordings: Sequence[str]) -> tuple[str, list[str]]:
    """Factor a shared stem out of a group of wordings.

    Args:
        wordings: The wordings to factor, in render order.

    Returns:
        `(stem, remainders)` where `stem + remainders[i] == wordings[i]` for
        every i, and each remainder begins with `" - "`. When no shared prefix
        snaps back to a `" - "`, returns `("", list(wordings))` and the caller
        renders each wording whole.
    """
    if len(wordings) < 2:
        return "", list(wordings)
    cut = _common_prefix(wordings).rfind(_SEP)
    if cut <= 0:
        return "", list(wordings)
    return wordings[0][:cut], [w[cut:] for w in wordings]


def _omission_notice(budget: int, shown: int, dropped: Sequence[Cited]) -> str:
    """Name every citation the budget dropped.

    The notice is deliberately not itself charged to the budget. A budget that
    could suppress its own overflow report is silent truncation with extra steps,
    and silent truncation is what this module exists to remove.

    Args:
        budget: The budget that was applied.
        shown: How many citations fit.
        dropped: The citations that did not, in order.

    Returns:
        A single-line notice listing every dropped key.
    """
    return (
        f"    [budget {budget} chars: {shown} wording(s) shown, "
        f"{len(dropped)} withheld -- {', '.join(c.key for c in dropped)}. "
        "Nothing was shortened; cite these keys directly to read their wording.]")


def _index() -> dict[str, Cited]:
    """Load the key-to-citation index, building it once.

    Loads `build/dictionary.json` directly rather than importing `env.tools`.
    `env/tools.py` is the layer that will call `cite()`, so importing it from
    here would make the pair a cycle the moment that wiring lands; this module is
    the lower of the two by construction.

    Returns:
        Every key in the built dictionary, mapped to its citation. Empty when
        `build/` is absent -- `cite` turns that into a raise, so an empty index
        can never be read as an instrument with no variables in it.
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    p = BUILD / "dictionary.json"
    if not p.exists():
        _INDEX = {}
        return _INDEX
    raw = json.loads(p.read_text())
    _INDEX = {
        e["key"]: Cited(
            key=e["key"],
            wording=e["question_text"],
            roster_row=e["roster_row"],
        )
        for e in raw["entries"]
    }
    return _INDEX


def cite(key: str) -> Cited:
    """Bind one variable key to the instrument's wording for it.

    Args:
        key: A fully qualified variable key, e.g. `m1:1_Q6.3`.

    Returns:
        The citation for that key.

    Raises:
        CitationUnavailable: If `build/` is missing, or the key is in no
            registry. Both raise rather than returning an empty citation: a
            caller cannot mistake an exception for a variable, and that is the
            whole safety property here.
    """
    idx = _index()
    if not idx:
        raise CitationUnavailable(
            f"{BUILD / 'dictionary.json'} is missing, so no key can be bound to "
            "its wording. Run `python build.py`. Returning an uncited key here "
            "would put in front of the model exactly the bare label this module "
            "exists to make unrepresentable.")
    try:
        return idx[key]
    except KeyError:
        raise CitationUnavailable(
            f"{key!r} is in no registry, so it has no wording to quote. A key "
            "that resolves nowhere cannot anchor a protocol; do not invent one "
            "to make a record well-formed.") from None


def cite_all(keys: Iterable[str], budget: int = CITATION_BUDGET) -> CitedSet:
    """Bind several keys at once.

    Args:
        keys: Variable keys, in the order they should render. Repeats are
            dropped, keeping the first occurrence: a key rendered twice spends
            the budget twice and tells the reader nothing new.
        budget: Characters of wording the rendering may spend.

    Returns:
        The citations as a `CitedSet`.

    Raises:
        CitationUnavailable: If any key is unbindable. The whole call fails
            rather than returning the bindable subset, because a partial set
            renders as a complete one and the caller never learns which key it
            silently lost.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            ordered.append(k)
    return CitedSet(items=tuple(cite(k) for k in ordered), budget=budget)


# --------------------------------------------------------------------------- #
# the whole-instrument catalogue (arm D)
# --------------------------------------------------------------------------- #

#: A piped Qualtrics reference as it survives into `question_text`, optionally
#: followed by the roster member index that reference expanded to:
#: `... - 1_Q16.9#1 - 1 - Bladder cancer`. It is an artefact of the export, not
#: a question, and it is the ONLY thing distinguishing 20 roster members of the
#: same option from each other. Stripping it is what collapses them.
#:
#: Anchored on ` - Q` or ` - <n>_Q` so it cannot eat instrument text: `Additional
#: Contact #1 - Name` keeps its `#1`, which is content, and ` - Quit smoking`
#: never matches because a digit must follow the Q.
#:
#: DUPLICATED ON PURPOSE, and it should not stay that way: `TASKS.md` item R5
#: strips these from `stem_text` at the source and moves `surface_hash` when it
#: lands. When it does, this regex is what it absorbs.
_PIPED_REFERENCE = re.compile(
    r"\s-\s(?:\d+_)?Q\d+(?:\.\d+)*(?:#\d+)*(?:_\d+)*(?:\s-\s\d+)?(?=\s-\s|$)")

#: Printed immediately before every catalogue index, with no separator.
#:
#: NOT decoration. `benchmark/contamination_check.py::check_markers` matches a
#: token at a left word boundary, so a catalogue numbered `602.` fires the
#: marker `602` — a published cohort figure — on a line that carries no cohort
#: figure at all, and a 1,400-item list collides with EVERY numeric marker
#: below 1,400, permanently. Attaching a letter removes the left boundary, so a
#: bare figure anywhere in this surface is still caught and a position is no
#: longer indistinguishable from a withheld number. Measured 2026-09-02: the
#: unprefixed rendering fired two numeric markers, both of them index positions
#: and neither of them a figure. The numbers are deliberately not repeated here
#: — `tests/test_contamination_surface.py::
#: test_no_source_file_names_a_published_analysis` scans this file, and it
#: caught the first draft of this comment naming one.
_INDEX_PREFIX = "i"

#: Stripped from the FRONT of a wording. `agent/schema.py::_norm` does not do
#: this and `Cited.wording` must never do it; it happens here because two roster
#: members of one question are one selectable item, not two.
_LEADING_ROSTER = re.compile(r"^\s*\d+\s*-\s*")


@dataclass(frozen=True, slots=True)
class CatalogueOption:
    """One selectable item in the whole-instrument catalogue.

    An option is not a row. It is every dictionary key that asks the same
    question of a different roster member, folded into one thing a reader can
    choose — because 20 keys differing only by which sibling they name are one
    variable asked 20 times, and offering them as 20 choices is offering a
    distinction the request cannot make.

    Attributes:
        index: 1-based position in the catalogue, the value a model returns.
        construct_key: The construct these keys belong to. Harness-side only.
        keys: Every dictionary key this option stands for, in build order.
        representative: The key `resolve` binds to, the first of `keys`.
        display: The wording as rendered — whitespace collapsed, leading roster
            index removed, piped references removed. NOT byte-verbatim; the
            verbatim text is `cite(representative).wording`, and `verbatim`
            says whether the two agree.
        remainder: `display` with the construct's shared stem factored off, so
            the stem prints once above its options.
        module: Which module the option lives in.
        roster_family_size: How many people the question was put to, or None.
            The family FACT, kept while the members are folded away.
    """

    index: int
    construct_key: str
    keys: tuple[str, ...]
    representative: str
    display: str
    remainder: str
    module: str
    roster_family_size: int | None

    @property
    def verbatim(self) -> bool:
        """Whether the rendered display still matches the instrument byte for byte.

        Returns:
            True when `display` equals the representative's `question_text`
            under whitespace collapse alone — that is, when nothing but
            whitespace was changed to render it.
        """
        return self.display == _flat(cite(self.representative).wording)


@dataclass(frozen=True, slots=True)
class Catalogue:
    """Every selectable item in the instrument, grouped by construct.

    Attributes:
        options: The options, indexed 1..n in render order.
        stems: Construct key -> the shared stem printed above its options.
        order: The construct keys in render order.
        by_key: Every folded key -> its option's index. Built at construction
            rather than lazily: `slots=True` leaves nowhere to cache it later,
            and a fold that lost a key should fail here, not at lookup.
    """

    options: tuple[CatalogueOption, ...] = ()
    stems: dict[str, str] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    by_key: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Index the folded keys.

        Raises:
            ValueError: If two options claim the same key, which would let one
                index resolve a variable another index also stands for.
        """
        index: dict[str, int] = {}
        for o in self.options:
            for k in o.keys:
                if k in index:
                    raise ValueError(
                        f"{k} is folded into options {index[k]} and {o.index}")
                index[k] = o.index
        object.__setattr__(self, "by_key", index)

    def by_index(self, index: int) -> CatalogueOption:
        """The option a returned index names.

        Args:
            index: The 1-based index a model returned.

        Returns:
            That option.

        Raises:
            IndexError: If outside 1..n. An out-of-range index means the model
                chose something it was not offered, and returning the nearest
                option would hide that.
        """
        if not 1 <= index <= len(self.options):
            raise IndexError(
                f"catalogue index {index} outside 1..{len(self.options)}")
        return self.options[index - 1]

    def index_of_key(self, key: str) -> int | None:
        """Which option, if any, a dictionary key folded into.

        Args:
            key: A fully qualified variable key.

        Returns:
            The 1-based index, or None when the key is in no option.
        """
        return self.by_key.get(key)


def catalogue_display(wording: str) -> str:
    """Render one wording as the catalogue shows it.

    Three removals, each with a reason and none of them cosmetic: whitespace
    collapse, because 323 entries carry hard newlines a line-oriented block
    cannot survive; the leading roster index, because it names a member of a
    family the catalogue folds; and piped Qualtrics references, because they are
    export artefacts that read as question text.

    Args:
        wording: `question_text`, byte for byte.

    Returns:
        The display string.
    """
    return _PIPED_REFERENCE.sub("", _LEADING_ROSTER.sub("", _flat(wording)))


def build_catalogue() -> Catalogue:
    """Fold the whole instrument into one selectable list.

    Order is the built dictionary's own — first appearance of each construct,
    then first appearance of each option within it — so the rendering is a pure
    function of the build and a prompt hash over it is stable.

    Returns:
        The catalogue.

    Raises:
        CitationUnavailable: If `build/` is missing, for the reason `cite`
            raises: an empty catalogue renders as an instrument with no
            questions in it.
    """
    p = BUILD / "dictionary.json"
    if not p.exists():
        raise CitationUnavailable(
            f"{p} is missing, so there is no instrument to render. Run "
            "`python build.py`.")
    entries = json.loads(p.read_text())["entries"]

    grouped: dict[str, dict[str, list[dict]]] = {}
    for e in entries:
        grouped.setdefault(e["construct_key"], {}).setdefault(
            catalogue_display(e["question_text"]), []).append(e)

    options: list[CatalogueOption] = []
    stems: dict[str, str] = {}
    for construct, by_display in grouped.items():
        displays = list(by_display)
        stem, remainders = _factor(displays)
        stems[construct] = stem
        for display, remainder in zip(displays, remainders, strict=True):
            rows = by_display[display]
            options.append(CatalogueOption(
                index=len(options) + 1,
                construct_key=construct,
                keys=tuple(r["key"] for r in rows),
                representative=rows[0]["key"],
                display=display,
                remainder=remainder,
                module=str(rows[0]["module"]),
                roster_family_size=rows[0]["roster_family_size"],
            ))
    return Catalogue(options=tuple(options), stems=stems,
                     order=tuple(grouped))


def render_catalogue(catalogue: Catalogue | None = None) -> str:
    """Render the catalogue as the model reads it.

    One stem per construct, its options beneath, each option carrying the index
    to return. No keys and no identifiers: the model selects a position and the
    harness resolves it, which is why there is nothing here for it to copy
    wrong.

    Args:
        catalogue: The catalogue; built from the current dictionary by default.

    Returns:
        The rendering.
    """
    cat = catalogue or build_catalogue()
    by_construct: dict[str, list[CatalogueOption]] = {}
    for o in cat.options:
        by_construct.setdefault(o.construct_key, []).append(o)

    out: list[str] = []
    module = ""
    for construct in cat.order:
        opts = by_construct[construct]
        if opts[0].module != module:
            module = opts[0].module
            out.append(f"\n=== SECTION {module} ===")
        stem = cat.stems[construct]
        family = opts[0].roster_family_size
        # The family fact prints ONCE per construct where there is a stem to
        # hang it on. Repeating it on all 22 cancer types under one stem spends
        # 22 lines saying one thing about the construct.
        tag = f"  [roster_family_size: {family}]" if family else ""
        if stem:
            out.append(f"{stem}{tag}")
        for o in opts:
            text = (o.remainder.removeprefix(_SEP) if stem else o.display)
            # No indent and no period after the index. Both were nicer to read
            # and together they cost 2,800 characters, which is the difference
            # between a prompt that fits a single `exec` argument and one that
            # does not — see MAX_ARG_STRLEN in tests/test_catalogue.py.
            out.append(f"{_INDEX_PREFIX}{o.index} {text}{'' if stem else tag}")
    return "\n".join(out).strip()
