"""A per-paper key table built from the variable inventory, not the prevalence key.

`benchmark/baseline_score.py` builds its table from two sources that were never
meant to be a variable inventory: a PREVALENCE key on the outcome side, and
prose design fragments handed to the deployed retriever on the exposure side.
On the exposure side a retriever MISS and a genuine ABSENCE are the same empty
result, so the ceiling that rule produces is not a statement about the
instrument. `benchmark/INVENTORY_DISCOVERY.md` pre-registers the replacement;
this module implements it and nothing else.

What it never does. It does not author, extend or correct the inventory --
`benchmark/PAPER_INVENTORY_GUIDE.md` §Who writes it: a person, on the key side.
It reads rows as DATA and never imports the inventory's schema module, pinning
`schema_version` instead, the discipline `benchmark/tiered_score.py` already
follows. It names no default path under `inventory/`: the caller says where the
rows came from, so this module reaches for nothing in a clone that bars them.

Reuse, for the member/construct fold (`AGENTS.md` §Efficiency). The fold is the
BUILT DICTIONARY's own key-to-construct index, `pipeline/pose.py::construct_index`
over `generate/funnel.py::load_constructs` -- the same index the posed-pair
driver and `benchmark/tiered_score.py` resolve against, so a paper's key and a
run's construct cannot be folded two different ways in one report. Not
`sqlite3`: the index is a few thousand entries built once per process and read
by exact key, so a database would add a schema, a file and a migration to a
dict lookup. Not `pydantic`: it validates SHAPES and would have to be given the
inventory's schema to do so, which is the one thing this module must not import
-- rows are read as data precisely so a schema change reddens the pin rather
than being read under stale field names.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

from benchmark.baseline_score import InventoryInput, PaperKey
from benchmark.tiered_score import (
    Handoff,
    HandoffMismatch,
    normalise_papers,
    schema_version_of,
)

#: An inventory row matches only from this status. `modality` is deliberately
#: absent: an analogue is a different measurement, so a record adjusting the
#: self-report analogue of a measured exposure is not a rediscovery of the
#: paper that measured it (`INVENTORY_DISCOVERY.md` rule 2, `TIER_STATE.md`
#: on tier B).
MATCHING_STATUS = "present"

#: The two anchor sides, in report order.
SIDES = ("exposures", "outcomes")


class SideCounts(NamedTuple):
    """One anchor side of the inventory, counted by why a row does or does not match.

    Rows and paper-sides are counted separately because they answer different
    questions: `rows_present_not_confident` says how much of the inventory a
    human reader was unsure of, `excluded_sides` says how many PAPERS that
    cost.

    The five `rows_*` fields below `excluded_sides` are a PARTITION: every row
    on the side falls in exactly one, and they sum to the row count. That is
    what makes "counted, never silently dropped" checkable rather than
    asserted -- `rows_sum` is compared against the rows actually read.
    `rows_not_confident_any_status` sits outside the partition and OVERLAPS it
    deliberately, because rule 3 asks for every `confident == false` row per
    side and a non-confident row can also be a modality or absent row.

    Attributes:
        papers: Papers carrying this side at all.
        matchable_sides: Paper-sides yielding at least one folded key.
        excluded_sides: Paper-sides yielding none, for any reason.
        rows_present_confident: Rows that match under rule 2.
        rows_present_not_confident: Present rows excluded because `confident`
            is not true.
        rows_modality: Rows excluded because an analogue is another
            measurement, whatever their `confident` flag.
        rows_absent: Rows excluded because the instrument does not carry the
            variable at all.
        rows_unresolvable: Present, confident rows whose key the built
            dictionary does not hold, so it folds to nothing. Counted, never
            passed over: a key that names nothing is a defect in the inventory
            or a moved build, and scoring it as an ordinary miss hides both.
        rows_not_confident_any_status: Every row with `confident` not true.
            Overlaps the partition; see above.
    """

    papers: int
    matchable_sides: int
    excluded_sides: int
    rows_present_confident: int
    rows_present_not_confident: int
    rows_modality: int
    rows_absent: int
    rows_unresolvable: int
    rows_not_confident_any_status: int

    @property
    def rows_sum(self) -> int:
        """The partition's total, which must equal the rows read.

        Returns:
            The five partition fields summed.
        """
        return (self.rows_present_confident + self.rows_present_not_confident
                + self.rows_modality + self.rows_absent + self.rows_unresolvable)


def _schema_pin(harness: Handoff | Mapping[str, Any],
                schema_path: Any = None) -> str:
    """Check the schema the rows will be read under, and return it.

    The rows are read as plain data, so a schema change moves field names
    underneath this module without any import failing. The pin is what makes
    that loud. It is verified against the blob of the schema file when this
    tree holds one, and carried as declared when it does not -- which is every
    generation clone, since `inventory/` is barred from them. Absent is not
    unverifiable: a harness naming no schema at all is refused either way.

    Args:
        harness: The loaded `handoff/for_harness.json`, or the `Handoff` that
            `tiered_score.load_handoff` returns having already pinned it.
        schema_path: The schema file whose blob is recomputed; `tiered_score`'s
            `SCHEMA_PATH` when None.

    Returns:
        The `path@blob` string the rows are read under.

    Raises:
        HandoffMismatch: When the harness names no schema, or names one that
            disagrees with the schema file in this tree.
    """
    declared = (harness.schema_version if isinstance(harness, Handoff)
                else str(harness.get("schema_version", "")))
    if not declared:
        raise HandoffMismatch(
            "the harness names no schema_version, so the rows below would be "
            "read under whatever field names this module happens to use. A "
            "harness that cannot say which schema it was built against is "
            "refused, not defaulted.")
    live = schema_version_of(schema_path)
    if live is not None and declared != live:
        raise HandoffMismatch(
            f"schema_version {declared!r} but the schema in this tree is "
            f"{live!r}. The inventory is read as data and its module is never "
            f"imported, so a moved schema is silent unless this pin bites.")
    return declared


def fold(key: str, index: Mapping[str, Any]) -> frozenset[str]:
    """Every key that names the same construct as `key`.

    The inventory names a VARIABLE key and a run resolves a term to a
    CONSTRUCT, so comparing the two as strings scores a correct resolution as a
    miss -- `tests/fake_tiered_inventory.json` carries that trap on purpose.
    Folding both sides to the construct makes the comparison symmetric: a
    paper's member key meets a record that landed on the construct holding it,
    and a paper's construct key meets a record that landed on a member of it.

    Args:
        key: An inventory key.
        index: `pipeline.pose.construct_index` output, or any mapping from a
            key to an object carrying `construct_key` and `member_keys`.

    Returns:
        The key, its construct and that construct's members; empty when the
        built dictionary holds no such key.
    """
    construct = index.get(key)
    if construct is None:
        return frozenset()
    return frozenset({key, construct.construct_key, *construct.member_keys})


def _side_keys(rows: Iterable[Mapping[str, Any]],
               index: Mapping[str, Any]) -> tuple[frozenset[str], SideCounts]:
    """Fold one paper's side into matchable keys, counting every exclusion.

    The branches below are ordered as rule 2 applies them and each row leaves
    through exactly one, so the counts partition the rows.

    Args:
        rows: The side's inventory rows.
        index: The key-to-construct index.

    Returns:
        The folded keys for this side, and this side's counts as a one-paper
        `SideCounts`.
    """
    keys: set[str] = set()
    present = not_confident = modality = absent = unresolvable = 0
    unsure = 0
    for row in rows:
        confident = row.get("confident") is True
        if not confident:
            unsure += 1
        status = row.get("status")
        if status == "modality":
            modality += 1
        elif status != MATCHING_STATUS:
            absent += 1
        elif not confident:
            not_confident += 1
        else:
            key = row.get("key")
            folded = frozenset() if key is None else fold(str(key), index)
            if folded:
                present += 1
                keys |= folded
            else:
                unresolvable += 1
    counts = SideCounts(papers=1, matchable_sides=1 if keys else 0,
                        excluded_sides=0 if keys else 1,
                        rows_present_confident=present,
                        rows_present_not_confident=not_confident,
                        rows_modality=modality, rows_absent=absent,
                        rows_unresolvable=unresolvable,
                        rows_not_confident_any_status=unsure)
    return frozenset(keys), counts


def _add(a: SideCounts, b: SideCounts) -> SideCounts:
    """Sum two `SideCounts` field by field.

    Args:
        a: One.
        b: The other.

    Returns:
        The sum.
    """
    return SideCounts(*(x + y for x, y in zip(a, b, strict=True)))


def side_exclusions(papers: Iterable[Mapping[str, Any]],
                    index: Mapping[str, Any]) -> dict[str, SideCounts]:
    """Count, per side, every row and paper-side the match rule excludes.

    Rule 3 of `INVENTORY_DISCOVERY.md`: a `confident == false` row is excluded
    from matching and COUNTED, never silently dropped. This is the discipline
    `tiered_score.covariate_exclusions` applies to covariates, applied to the
    two anchor sides.

    Args:
        papers: Inventory papers, rows as dicts.
        index: The key-to-construct index.

    Returns:
        `"exposures"` and `"outcomes"` to their counts.
    """
    zero = SideCounts(0, 0, 0, 0, 0, 0, 0, 0, 0)
    totals = {side: zero for side in SIDES}
    for paper in papers:
        for side in SIDES:
            _, counts = _side_keys(paper.get(side, []), index)
            totals[side] = _add(totals[side], counts)
    return totals


def in_frame(paper: PaperKey, frame_pairs: Iterable[tuple[str, str]],
             index: Mapping[str, Any]) -> bool:
    """Whether the run's frame contained a pair this paper could be matched on.

    Rule 4 of `INVENTORY_DISCOVERY.md`. Both of the paper's confident present
    sides are folded to constructs and looked for as an ORDERED pair among the
    candidates `generate/funnel.py::s2_prune` left live. A paper the frame
    never contained bounds nothing, however well the inventory keys it.

    Args:
        paper: One row of the inventory-backed table.
        frame_pairs: `(exposure_construct, outcome_construct)` for every live
            candidate, enumerated from the funnel -- never a hand-typed list.
        index: The key-to-construct index.

    Returns:
        True when some live pair joins one of the paper's exposure constructs
        to one of its outcome constructs.
    """
    if not paper.exposure_keys or not paper.outcome_keys:
        return False
    exposures = {c for k in paper.exposure_keys
                 if (c := _construct(k, index)) is not None}
    outcomes = {c for k in paper.outcome_keys
                if (c := _construct(k, index)) is not None}
    return any(e in exposures and o in outcomes for e, o in frame_pairs)


def _construct(key: str, index: Mapping[str, Any]) -> str | None:
    """The construct key holding `key`, or None when the build has neither.

    Args:
        key: A variable or construct key.
        index: The key-to-construct index.

    Returns:
        The construct key, or None.
    """
    construct = index.get(key)
    return None if construct is None else str(construct.construct_key)


def analogue_only(paper: Mapping[str, Any]) -> bool:
    """Whether a paper is reachable on both sides ONLY through an analogue.

    Under rule 2 such a paper is unmatchable, and the report says so rather
    than binning it into a tier that would flatter it. This is the tier-B
    question `TIER_STATE.md` leaves open for the operator; naming the shape
    here is not settling it.

    Args:
        paper: One inventory paper, rows as dicts.

    Returns:
        True when neither side has a confident present key and both sides
        carry a confident analogue.
    """
    def state(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, bool]:
        rows = list(rows)
        present = any(r.get("status") == MATCHING_STATUS and r.get("key") is not None
                      and r.get("confident") is True for r in rows)
        analogue = any(r.get("status") == "modality"
                       and r.get("analogue_key") is not None
                       and r.get("confident") is True for r in rows)
        return present, analogue

    e_present, e_analogue = state(paper.get("exposures", []))
    o_present, o_analogue = state(paper.get("outcomes", []))
    return not e_present and not o_present and e_analogue and o_analogue


def key_table_from_inventory(papers: list[dict[str, Any]],
                             harness: Handoff | Mapping[str, Any],
                             *, index: Mapping[str, Any] | None = None,
                             schema_path: Any = None) -> tuple[PaperKey, ...]:
    """Build the per-paper key table the inventory supports.

    One `PaperKey` per paper, in input order. `exposure_terms` is empty: the
    inventory names keys, so nothing here is ever handed to the retriever, and
    a paper whose side is `absent`, `modality` or not `confident` gets an empty
    tuple on that side rather than a guess. `side_exclusions` counts what that
    cost.

    Args:
        papers: Inventory papers as `tiered_score.load_papers` yields them,
            rows as dicts. Either the fixture's `paper` id or the schema's
            `pmid` is accepted.
        harness: The loaded `handoff/for_harness.json`, or the `Handoff` from
            `tiered_score.load_handoff`. Its `schema_version` is pinned.
        index: The key-to-construct index; built from the dictionary when None.
        schema_path: Passed to the pin; see `_schema_pin`.

    Returns:
        The table.

    Raises:
        HandoffMismatch: When the harness names no schema, or names one this
            tree contradicts.
    """
    _schema_pin(harness, schema_path)
    if index is None:
        index = _dictionary_index()
    out: list[PaperKey] = []
    for paper in normalise_papers(list(papers)):
        exposures, _ = _side_keys(paper.get("exposures", []), index)
        outcomes, _ = _side_keys(paper.get("outcomes", []), index)
        out.append(PaperKey(pmid=str(paper["paper"]), exposure_terms=(),
                            outcome_keys=tuple(sorted(outcomes)),
                            exposure_keys=tuple(sorted(exposures))))
    return tuple(out)


def _dictionary_index() -> Mapping[str, Any]:
    """The built dictionary's key-to-construct index.

    Imported inside the function: the dictionary needs `build/dictionary.json`,
    which is withheld from the public tree, and this module's tests inject
    their own index.

    Returns:
        Every variable key and construct key to its construct.
    """
    from generate.funnel import load_constructs
    from pipeline.pose import construct_index

    constructs, _ = load_constructs()
    return construct_index(constructs)


def inventory_input(papers: list[dict[str, Any]],
                    harness: Handoff | Mapping[str, Any],
                    *, frame_pairs: Iterable[tuple[str, str]] | None = None,
                    index: Mapping[str, Any] | None = None,
                    schema_path: Any = None) -> InventoryInput:
    """Prepare everything `baseline_score.score` needs for the inventory rule.

    The scorer never reads an inventory row, never imports the inventory's
    schema and never enumerates a frame; this function does all three and
    hands over plain counts and folded keys.

    Args:
        papers: Inventory papers, rows as dicts.
        harness: The loaded `handoff/for_harness.json`, or a `Handoff`.
        frame_pairs: `(exposure_construct, outcome_construct)` for every
            candidate the funnel left live, from `pipeline/run.py --frame-only`
            against the frame the run used. None means NOT ENUMERATED, which
            the report prints as unknown and never as zero.
        index: The key-to-construct index; built from the dictionary when None.
        schema_path: Passed to the schema pin.

    Returns:
        The prepared input.

    Raises:
        HandoffMismatch: From the schema pin.
    """
    if index is None:
        index = _dictionary_index()
    table = key_table_from_inventory(papers, harness, index=index,
                                     schema_path=schema_path)
    frame: frozenset[str] | None = None
    if frame_pairs is not None:
        pairs = list(frame_pairs)
        frame = frozenset(k.pmid for k in table if in_frame(k, pairs, index))
    normalised = normalise_papers(list(papers))
    return InventoryInput(
        table=table, in_frame=frame,
        excluded_sides={side: counts._asdict()
                        for side, counts in side_exclusions(normalised,
                                                            index).items()},
        analogue_only=sum(1 for paper in normalised if analogue_only(paper)))
