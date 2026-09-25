"""Model-visible surfaces as typed structures.

The model selects a candidate by INDEX; the harness resolves the index to a
variable key. The model never emits a key, so it cannot emit one wrong. This
removes a measured failure class rather than discouraging it.

Rationale, measurements and prior-art comparison: docs/adr/003-index-selection.md
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from pydantic import BaseModel

from env import labels


@dataclass(frozen=True, slots=True)
class Candidate:
    """One selectable item.

    Attributes:
        index: 1-based position in the contract's candidate list.
        key: The variable key this index resolves to. Not shown to the model.
        wording: The instrument's `question_text`, byte for byte. JSON escapes
            the hard newlines that 323 of the 2,804 entries carry, so no lossy
            whitespace collapse is needed.
        facts: Typed facts about the item (module, roster family size, grid
            column) under typed names, never appended to the wording.
    """

    index: int
    key: str
    wording: str
    facts: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self, *, include_key: bool = False) -> dict[str, Any]:
        """Render as the object the model receives.

        Args:
            include_key: Show `key`. For prompt auditing only — keys are
                withheld from the production prompt so there is nothing to copy.

        Returns:
            The candidate as a JSON-serialisable object.
        """
        out: dict[str, Any] = {"index": self.index, "wording": self.wording}
        if include_key:
            out["key"] = self.key
        return out | dict(self.facts)


@dataclass(frozen=True)
class SelectionContract:
    """One model-visible surface.

    Attributes:
        name: The surface's name.
        task: What to decide. The only prose the model reads.
        output_model: The answer's schema, rendered into the prompt.
        refusal: The literal value meaning "no candidate answers this". Must be
            expressible by `output_model`.
        candidates: What may be selected, in index order.
    """

    name: str
    task: str
    output_model: type[BaseModel]
    refusal: str
    candidates: tuple[Candidate, ...] = ()

    def __post_init__(self) -> None:
        """Validate that the surface can refuse and can resolve.

        Raises:
            ValueError: If `refusal` is blank, names no literal `output_model`
                can express, or if candidate indices are not 1..n in order.
        """
        if not self.refusal.strip():
            raise ValueError(
                f"{self.name}: a surface that cannot express 'no answer' "
                f"answers everything.")
        expressible = _literal_values(self.output_model)
        if self.refusal not in expressible:
            raise ValueError(
                f"{self.name}: refusal {self.refusal!r} is not expressible by "
                f"{self.output_model.__name__}; it allows {sorted(expressible)}.")
        want = tuple(range(1, len(self.candidates) + 1))
        if tuple(c.index for c in self.candidates) != want:
            raise ValueError(
                f"{self.name}: candidate indices must be 1..{len(want)} in "
                f"order, because `resolve` indexes on them.")

    def resolve(self, index: int) -> labels.Cited:
        """Turn a returned index into a citation.

        Args:
            index: The 1-based index the model returned.

        Returns:
            The citation for that candidate.

        Raises:
            IndexError: If outside 1..n. An out-of-range index means the model
                selected something not offered; returning the nearest candidate
                would hide that.
            labels.CitationUnavailable: If the key cannot be bound to wording.
        """
        if not 1 <= index <= len(self.candidates):
            raise IndexError(
                f"{self.name}: index {index} outside 1..{len(self.candidates)}.")
        return labels.cite(self.candidates[index - 1].key)

    def facts_for(self, index: int) -> Mapping[str, Any]:
        """The facts attached to a resolved candidate.

        Lets the harness read values like `roster_family_size` itself instead of
        asking the model to copy an integer it was already given.

        Args:
            index: The 1-based index the model returned.

        Returns:
            That candidate's facts.

        Raises:
            IndexError: If outside 1..n.
        """
        if not 1 <= index <= len(self.candidates):
            raise IndexError(f"{self.name}: index {index} out of range.")
        return self.candidates[index - 1].facts

    def render(self, *, debug: bool = False, catalogue: str | None = None) -> str:
        """Render the task, the candidates and the answer schema.

        Args:
            debug: Include each candidate's key, for auditing the prompt.
            catalogue: A pre-rendered candidate block to print instead of the
                JSON array — `env/labels.py::render_catalogue` for a list too
                long to repeat one stem per row. It must index the SAME 1..n
                positions this contract resolves; nothing here can check that,
                so the caller builds both from one source. Ignored when `debug`
                is set, because the debug view exists to show keys and a
                pre-rendered block has none.

        Returns:
            The prompt.
        """
        block = (json.dumps(
            [c.as_dict(include_key=debug) for c in self.candidates], indent=1)
            if catalogue is None or debug else catalogue)
        return "\n".join([
            self.task,
            "",
            f"Candidates ({len(self.candidates)}), as JSON objects:"
            if catalogue is None or debug else
            f"Candidates ({len(self.candidates)}), grouped under the question "
            f"each belongs to. Each is numbered `i<N>`; its `index` is the "
            f"integer N, which is what you return:",
            block,
            "",
            "Select by `index`. Return the integer only.",
            "",
            f"If no candidate answers the request, return {self.refusal!r}. "
            f"That is an answer, not a failure to give one.",
            "",
            "Return one JSON object matching this schema and nothing else:",
            json.dumps(self.output_model.model_json_schema()),
        ])


def _literal_values(model: type[BaseModel]) -> frozenset[str]:
    """Every literal string value a model's fields can hold.

    Recurses through `Optional`, unions and other generic wrappers: a one-level
    `get_args` returns empty for `Optional[Literal[...]]`, which would reject a
    refusal the model can express and blame the refusal for it.

    Args:
        model: The output model.

    Returns:
        The literal values, empty when the model has no literal-typed field.
    """

    def walk(ann: Any) -> set[str]:
        found: set[str] = set()
        for arg in get_args(ann):
            if isinstance(arg, str):
                found.add(arg)
            else:
                found |= walk(arg)
        return found

    out: set[str] = set()
    for info in model.model_fields.values():
        out |= walk(info.annotation)
    return frozenset(out)


def candidates_from_keys(
    keys: Sequence[str],
    facts: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Candidate, ...]:
    """Build candidates from variable keys, wording bound by `env/labels.py`.

    Wording comes from `cite`, the only maker of a key bound to its text, so a
    candidate cannot carry wording that drifted from the instrument.

    Args:
        keys: The variable keys, in the order to offer them.
        facts: Per-key facts to carry as typed fields.

    Returns:
        The candidates, indexed 1..n.

    Raises:
        labels.CitationUnavailable: If any key cannot be bound to wording.
    """
    facts = facts or {}
    return tuple(
        Candidate(index=i, key=k, wording=labels.cite(k).wording,
                  facts=dict(facts.get(k, {})))
        for i, k in enumerate(keys, start=1))


class VariableSelection(BaseModel):
    """Which codebook items answer a request, selected by index.

    Field descriptions are prompt text: `render` puts `model_json_schema()` into
    the prompt, so no study design, exposure, outcome, paper count, cohort
    figure or prevalence may appear here.

    Attributes:
        verdict: `resolved` when exactly one item is right; `family` when the
            request spans a whole repeated family and one member would be wrong;
            `derive` when no item measures this and it must be computed;
            `ambiguous` when candidates are genuinely different variables and
            the wording cannot say which is meant; `absent` when none of the
            items listed measures this. That is a claim about the list, not
            the codebook: a list drawn from a larger codebook can miss an item
            the codebook has.
        indices: The selected `index` values — one for `resolved`, one member
            for `family`, the inputs for `derive`, empty otherwise.
        recipe: How to compute the value, when the verdict is `derive`.
        missing_dimension: The single fact that would settle an `ambiguous` case.
        reason: Two sentences at most.
    """

    verdict: Literal["resolved", "family", "derive", "ambiguous", "absent"]
    indices: tuple[int, ...] = ()
    recipe: str = ""
    missing_dimension: str = ""
    reason: str = ""


#: The retrieval surface's standing instructions, shared by both contracts
#: below so a change reaches the model through one string rather than two.
#: `docs/adr/003-index-selection.md` records why the abstention pressure runs
#: the way it does here: prior-art system 1 instructs its model AGAINST
#: abstaining, and COMPASS's measured failure is the opposite one — five false
#: positives in 21 rows, every unpinnable request answered with one confident
#: item.
#: The roster-family fact, stated once and read by both surfaces that offer a
#: pool: a family member is no more a default than it is an answer.
ROSTER_NOTE = (
    "A candidate whose `roster_family_size` is N is one member of a family of "
    "N: the same question put once per person. Those N are not N different "
    "variables, and a request naming no particular member is not answered by "
    "any one of them.")

RETRIEVAL_GUIDANCE = (
    "Decide what kind of answer this request has among the survey codebook "
    "items listed below. You have each item's wording and named facts about "
    "it; you do not "
    "have response options, value labels, skip logic or any data. If "
    "separating two candidates would need a fact you were not given, that is "
    "`ambiguous`, not a close call. Do not pick one to be helpful.\n\n"
    + ROSTER_NOTE)


def retrieval_contract(request: str,
                       candidates: Sequence[Candidate]) -> SelectionContract:
    """The retrieval surface: pick codebook items for a researcher's prose.

    Args:
        request: What the researcher asked for, in their words.
        candidates: The items to offer, in the order to offer them.

    Returns:
        The contract.
    """
    return SelectionContract(
        name="retrieval",
        task=f'A researcher asked for: "{request}"\n\n{RETRIEVAL_GUIDANCE}',
        output_model=VariableSelection,
        refusal="absent",
        candidates=tuple(candidates),
    )


def catalogue_contract(candidates: Sequence[Candidate]) -> SelectionContract:
    """The same surface with the request moved OUT of the prompt's head.

    Identical guidance, no request. The caller appends the request after
    `render`, which is what makes the whole instrument a static prefix: 224
    requests then share one cacheable read of ~32k tokens instead of paying for
    it 224 times. The request has to be somewhere, and last is the only place
    that keeps the prefix identical across rows.

    Args:
        candidates: The items to offer, in the order to offer them.

    Returns:
        The contract, whose `task` names no request.
    """
    return SelectionContract(
        name="retrieval-catalogue",
        task=RETRIEVAL_GUIDANCE,
        output_model=VariableSelection,
        refusal="absent",
        candidates=tuple(candidates),
    )


# --------------------------------------------------------------------------- #
# A default to start from, asked only after `ambiguous`
# --------------------------------------------------------------------------- #

# A SECOND CALL, NOT A SOFTER FIRST ONE. The retrieval surface's abstention
# pressure is measured (`docs/adr/003-index-selection.md`: 5 false positives in
# 21 rows), and its `ambiguous` verdict is reported as it came back. Telling
# that call to pick a default anyway would move the verdict with the wording,
# and the verdict would stop being a measurement. So the pick is asked for
# afterwards, of the same pool, and travels BESIDE the verdict: the reader sees
# both that the request was ambiguous and which item was filled in.
#
# `DefaultPick`'s docstring is prompt text (`default_contract` renders
# `model_json_schema()`), so no study design, exposure, outcome, paper count,
# cohort figure or prevalence may appear in it.


class DefaultPick(BaseModel):
    """The one item to start from when several could serve.

    Attributes:
        verdict: `default` when one listed item is a reasonable starting point;
            `none` when no listed item measures what the request names.
        index: The selected `index`, for `default`.
        reason: One sentence: why this item is the one to start from.
    """

    verdict: Literal["default", "none"]
    index: int | None = None
    reason: str = ""


DEFAULT_GUIDANCE = (
    "An earlier reading of this request found that more than one of the "
    "survey codebook items listed below could serve, and that the request's "
    "wording does not say which. The researcher still needs one item to start "
    "from. They will be told it is a default chosen under ambiguity, shown "
    "what would settle it, and asked to confirm or change it before anything "
    "runs.\n\n"
    "Choose the one listed item that most directly measures what the request "
    "names, in the request's own terms. Prefer an item asking about the thing "
    "itself over one asking when it began, about a narrower form of it, or "
    "about something that accompanies it. Return `none` only if no listed "
    "item measures it at all.\n\n"
    + ROSTER_NOTE + " Do not return one of them as the default.")


def default_contract(request: str, role: str, missing_dimension: str,
                     candidates: Sequence[Candidate]) -> SelectionContract:
    """Ask for a default among a pool the retrieval surface called ambiguous.

    Args:
        request: What the researcher asked for, in their words.
        role: The role being filled, as the pair route frames it.
        missing_dimension: What the earlier reading said would settle it.
        candidates: The same pool the ambiguous verdict was given.

    Returns:
        The contract.
    """
    settle = (f"\n\nWhat the earlier reading said would settle it: "
              f"{missing_dimension}" if missing_dimension.strip() else "")
    return SelectionContract(
        name="default-under-ambiguity",
        task=(f'A researcher asked for: "{request}"\n\n'
              f"Which item serves as the {role.upper()} here?{settle}\n\n"
              f"{DEFAULT_GUIDANCE}"),
        output_model=DefaultPick,
        refusal="none",
        candidates=tuple(candidates),
    )


# --------------------------------------------------------------------------- #
# C29-C: split a request into its constructs before anything is retrieved
# --------------------------------------------------------------------------- #

# `RequestSplit`'s docstring is prompt text: `split_prompt` puts
# `model_json_schema()` into the prompt, so no study design, exposure, outcome,
# paper count, cohort figure or prevalence may appear in it. This note sits out
# here rather than in the docstring so the model does not read it.


class RequestSplit(BaseModel):
    """The separate things a question is about, in the question's own words.

    Attributes:
        exposures: Each exposure the question names, in its own words.
        outcomes: Each outcome the question names, in its own words.
        unsplittable: True when the question does not name both an exposure
            and an outcome.
    """

    exposures: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    unsplittable: bool = False


#: The splitter's standing instructions, in the wording the operator chose on
#: 2026-09-11. It reads the researcher's sentence and nothing else: no
#: candidate list and no instrument wording reach this call.
SPLIT_GUIDANCE = (
    "Before anything is looked up, list the separate things this question is "
    "about.\n\n"
    "An exposure is something whose effect the researcher wants to know about, "
    "such as a habit or a condition. An outcome is something that might be "
    "affected by it.\n\n"
    "Write one entry for each separate thing. Two things joined by \"and\" are "
    "two entries.\n\n"
    "Use only the question's own words, in the order it uses them. You may "
    "leave words out, but never add a word or change one.\n\n"
    "If the question does not name both an exposure and an outcome, set "
    "`unsplittable` to true and leave both lists empty.")


class SplitRejected(ValueError):
    """A split the harness will not use, and why."""


def split_prompt(request: str) -> str:
    """The splitter's prompt for one request.

    Args:
        request: What the researcher asked for, in their words.

    Returns:
        The prompt: the request, the guidance, and the answer schema.
    """
    return "\n".join([
        f'A researcher asked: "{request}"',
        "",
        SPLIT_GUIDANCE,
        "",
        "Return one JSON object matching this schema and nothing else:",
        json.dumps(RequestSplit.model_json_schema()),
    ])


def _words(text: str) -> list[str]:
    """The words of a text, case-folded, with punctuation dropped.

    Args:
        text: Any text.

    Returns:
        Its words in order.
    """
    return re.findall(r"[\w'-]+", text.casefold())


def _in_order(entry: str, request: str) -> bool:
    """Whether every word of `entry` appears in `request`, in the same order.

    The guidance lets the splitter leave words out but never add or change one,
    so an entry is a subsequence of the request's words, not merely a run of
    them.

    Args:
        entry: One entry the splitter returned.
        request: The request it was made from.

    Returns:
        True when the entry has at least one word and all of them occur in the
        request in order.
    """
    want = _words(entry)
    words = iter(_words(request))
    return bool(want) and all(w in words for w in want)


def parse_split(request: str, raw: str) -> RequestSplit:
    """Read a splitter reply and refuse any split the request does not support.

    THE WORD RULE IS WHAT MAKES THIS SAFE TO RETRIEVE ON. Every entry must be
    made of the request's own words in the request's order, so the splitter can
    drop words and cut the sentence up but cannot introduce one: no paraphrase,
    no synonym, and no instrument wording it happens to remember. That is
    checked here, in Python, rather than asked for in the prompt and trusted.

    Args:
        request: The request the split was made from.
        raw: The model's reply, which may carry a fence or prose around the
            object.

    Returns:
        The split.

    Raises:
        SplitRejected: When the reply holds no object, an entry adds, changes
            or reorders a word, one entry is named as both kinds, or the lists
            and `unsplittable` disagree. pydantic's `ValidationError` is also a
            `ValueError`, so a caller catching that catches every refusal.
    """
    text = raw.replace("```json", "").replace("```", "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise SplitRejected(f"no JSON object in the reply: {text[:120]!r}")
    split = RequestSplit.model_validate(json.loads(text[start:end + 1]))
    invented = [p for p in (*split.exposures, *split.outcomes)
                if not _in_order(p, request)]
    if invented:
        raise SplitRejected(
            f"not in the question's own words, in order: {invented}")
    both = ({tuple(_words(p)) for p in split.exposures}
            & {tuple(_words(p)) for p in split.outcomes})
    if both:
        raise SplitRejected("named as both exposure and outcome: "
                            f"{sorted(' '.join(b) for b in both)}")
    if split.unsplittable and (split.exposures or split.outcomes):
        raise SplitRejected("unsplittable, yet entries were listed")
    if not split.unsplittable and not (split.exposures and split.outcomes):
        raise SplitRejected("an exposure and an outcome are both needed "
                            "unless the request is unsplittable")
    return split
