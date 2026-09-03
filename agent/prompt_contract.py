"""Model-visible surfaces as typed structures.

The model selects a candidate by INDEX; the harness resolves the index to a
variable key. The model never emits a key, so it cannot emit one wrong. This
removes a measured failure class rather than discouraging it.

Rationale, measurements and prior-art comparison: docs/adr/003-index-selection.md
"""

from __future__ import annotations

import json
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
            the wording cannot say which is meant; `absent` when the codebook
            does not measure this.
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
RETRIEVAL_GUIDANCE = (
    "Decide what kind of answer this request has in the survey codebook "
    "below. You have each item's wording and named facts about it; you do not "
    "have response options, value labels, skip logic or any data. If "
    "separating two candidates would need a fact you were not given, that is "
    "`ambiguous`, not a close call. Do not pick one to be helpful.\n\n"
    "A candidate whose `roster_family_size` is N is one member of a family of "
    "N: the same question put once per person. Those N are not N different "
    "variables, and a request naming no particular member is not answered by "
    "any one of them.")


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
