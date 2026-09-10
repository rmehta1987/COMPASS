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

from collections.abc import Collection, Iterable, Mapping
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

#: The fields a row's verbatim variable name may be under. The fixture spells
#: it `label`; `tiered_score.attach_pairs`, the only code here that reads the
#: REAL inventory's anchor rows, spells it `term`. Reading one and not the
#: other makes every row unjoinable and reports a silent table of zeros, so
#: both are accepted and a row carrying neither is refused.
LABEL_FIELDS = ("label", "term")


class InventoryShape(ValueError):
    """The rows are not the shape the match rule can read.

    Raised rather than counted. Every defect this covers -- a missing anchor
    side, an unrecognised status, a repeated paper id, a row with no name --
    otherwise reads in the report as a finding about the INSTRUMENT: a side
    the questionnaire does not carry, or a paper nothing could match. A
    scoring failure published as a result is the defect this module exists to
    avoid, and `tiered_score` raises on the same shapes.
    """


class SideCounts(NamedTuple):
    """One anchor side of the inventory, counted by why a row does or does not match.

    Rows and paper-sides are counted separately because they answer different
    questions: `rows_present_not_confident` says how much of the inventory a
    human reader was unsure of, `excluded_sides` says how many PAPERS that
    cost.

    The five `rows_*` fields below `rows_seen` are a PARTITION: every row on
    the side falls in exactly one, and they sum to `rows_seen`, which is
    counted independently at the top of the loop. `partition_holds` COMPUTES
    that rather than asserting it, so the report can print the claim only when
    it is true. It bounds nothing about rows lost BEFORE the counter -- a side
    stored under a renamed field is caught by the refusal in `_side_keys`, not
    here.
    `rows_not_confident_any_status` sits outside the partition and OVERLAPS it
    deliberately, because rule 3 asks for every `confident == false` row per
    side and a non-confident row can also be a modality or absent row.

    Attributes:
        papers: Papers carrying this side at all.
        matchable_sides: Paper-sides yielding at least one folded key.
        excluded_sides: Paper-sides yielding none, for any reason.
        rows_seen: Rows read on this side, counted independently of the
            partition so the two can disagree.
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
    rows_seen: int
    rows_present_confident: int
    rows_present_not_confident: int
    rows_modality: int
    rows_absent: int
    rows_unresolvable: int
    rows_not_confident_any_status: int

    @property
    def rows_sum(self) -> int:
        """The partition's total, which must equal `rows_seen`.

        Returns:
            The five partition fields summed.
        """
        return (self.rows_present_confident + self.rows_present_not_confident
                + self.rows_modality + self.rows_absent + self.rows_unresolvable)

    @property
    def partition_holds(self) -> bool:
        """Whether every row read left through exactly one branch.

        Returns:
            True when the partition sums to the rows counted at the top of the
            loop. Computed, so the report prints the claim rather than
            asserting it.
        """
        return self.rows_sum == self.rows_seen


def _schema_pin(harness: Handoff | Mapping[str, Any], schema_path: Any = None,
                rows_schema_version: str | None = None) -> str:
    """Check the schema the rows will be read under, and return it.

    The rows are read as plain data, so a schema change moves field names
    underneath this module without any import failing. The pin is what makes
    that loud. It is verified against the blob of the schema file when this
    tree holds one, and carried as declared when it does not -- which is every
    generation clone, since `inventory/` is barred from them. Absent is not
    unverifiable: a harness naming no schema at all is refused either way.

    A second comparison, which is the one that bites in a clone with no
    `inventory/`: where the ROWS declare the schema they were written under,
    it must be the schema the harness names. Without it the pin checks the
    harness against the tree and never checks the rows against anything, so
    rows written under an older schema are read under the newer field names
    with nothing going red. The fixture in this repository is exactly that
    case -- it declares an older blob than the harness does.

    Args:
        harness: The loaded `handoff/for_harness.json`, or the `Handoff` that
            `tiered_score.load_handoff` returns having already pinned it.
        schema_path: The schema file whose blob is recomputed; `tiered_score`'s
            `SCHEMA_PATH` when None.
        rows_schema_version: What the inventory source declared, when it
            declared anything. A directory of per-paper files declares nothing
            and passes None, which checks nothing and says so.

    Returns:
        The `path@blob` string the rows are read under.

    Raises:
        HandoffMismatch: When the harness names no schema, when it names one
            that disagrees with the schema file in this tree, or when the rows
            were written under a different one.
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
    if rows_schema_version is not None and rows_schema_version != declared:
        raise HandoffMismatch(
            f"the rows were written under {rows_schema_version!r} but the "
            f"harness reads them under {declared!r}. The harness's field names "
            f"are the ones this module uses, so the rows would be read under a "
            f"schema they were not authored against.")
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


def _side_keys(rows: Iterable[Mapping[str, Any]], index: Mapping[str, Any],
               statuses: Collection[str] | None = None, where: str = "?",
               ) -> tuple[frozenset[str], SideCounts]:
    """Fold one paper's side into matchable keys, counting every exclusion.

    The branches below are ordered as rule 2 applies them and each row leaves
    through exactly one, so the counts partition the rows.

    Args:
        rows: The side's inventory rows.
        index: The key-to-construct index.
        statuses: The status vocabulary the harness declares. When given, a row
            carrying anything else is REFUSED rather than counted: the
            catch-all branch below means an unrecognised status would land in
            `rows_absent` and be published as an instrument gap, and a
            respelling of `present` itself would make every paper unmatchable
            and print that as a finding.
        where: Named in the refusal, so the operator knows which side of which
            paper to look at.

    Returns:
        The folded keys for this side, and this side's counts as a one-paper
        `SideCounts`.

    Raises:
        InventoryShape: On a status outside the declared vocabulary.
    """
    keys: set[str] = set()
    seen = present = not_confident = modality = absent = unresolvable = 0
    unsure = 0
    for row in rows:
        seen += 1
        confident = row.get("confident") is True
        if not confident:
            unsure += 1
        status = row.get("status")
        if statuses is not None and status not in statuses:
            raise InventoryShape(
                f"{where}: status {status!r} is not one of {sorted(statuses)}. "
                f"Counted rather than refused it would land in rows_absent and "
                f"be reported as the instrument not carrying the variable.")
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
                        excluded_sides=0 if keys else 1, rows_seen=seen,
                        rows_present_confident=present,
                        rows_present_not_confident=not_confident,
                        rows_modality=modality, rows_absent=absent,
                        rows_unresolvable=unresolvable,
                        rows_not_confident_any_status=unsure)
    return frozenset(keys), counts


def _rows_of(paper: Mapping[str, Any], side: str) -> list[Mapping[str, Any]]:
    """One paper's rows for one anchor side, refusing a side that is not there.

    `paper.get(side, [])` would return an empty list for a side the document
    does not carry, and an empty side is counted as EXCLUDED -- indistinguish-
    able in the report from a variable the instrument genuinely lacks. A
    partial export would publish as an instrument gap. `tiered_score` reads
    `paper["exposures"]` and raises on the same shape.

    Args:
        paper: One inventory paper.
        side: `"exposures"` or `"outcomes"`.

    Returns:
        The rows.

    Raises:
        InventoryShape: When the side is missing, or is not a list.
    """
    if side not in paper:
        raise InventoryShape(
            f"{paper.get('paper', paper.get('pmid', '?'))}: no {side!r} in this "
            f"paper. An absent side is not an empty one: counted as empty it "
            f"reports as the instrument not carrying the variable.")
    rows = paper[side]
    if not isinstance(rows, list):
        raise InventoryShape(f"{paper.get('paper', '?')}: {side!r} is "
                             f"{type(rows).__name__}, not a list of rows")
    return list(rows)


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
                    index: Mapping[str, Any],
                    statuses: Collection[str] | None = None,
                    ) -> dict[str, SideCounts]:
    """Count, per side, every row and paper-side the match rule excludes.

    Rule 3 of `INVENTORY_DISCOVERY.md`: a `confident == false` row is excluded
    from matching and COUNTED, never silently dropped. This is the discipline
    `tiered_score.covariate_exclusions` applies to covariates, applied to the
    two anchor sides.

    Args:
        papers: Inventory papers, rows as dicts.
        index: The key-to-construct index.
        statuses: The harness's status vocabulary; see `_side_keys`.

    Returns:
        `"exposures"` and `"outcomes"` to their counts.

    Raises:
        InventoryShape: On a missing side or an unrecognised status.
    """
    zero = SideCounts(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    totals = {side: zero for side in SIDES}
    for paper in papers:
        for side in SIDES:
            where = f"{paper.get('paper', paper.get('pmid', '?'))}.{side}"
            _, counts = _side_keys(_rows_of(paper, side), index, statuses, where)
            totals[side] = _add(totals[side], counts)
    return totals


def in_frame(paper: PaperKey, frame_pairs: Collection[tuple[str, str]],
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
            Must already be materialised, and a one-shot iterator is REFUSED
            rather than accepted: this is called once per paper, `any`
            short-circuits, and a generator shared across those calls would be
            consumed by the first paper while every later one read as out of
            frame. Materialising inside would not help -- the generator is
            still exhausted by the time the second call arrives -- so the only
            defence is to refuse it.
        index: The key-to-construct index.

    Returns:
        True when some live pair joins one of the paper's exposure constructs
        to one of its outcome constructs.

    Raises:
        InventoryShape: When `frame_pairs` is a one-shot iterator.
    """
    if not isinstance(frame_pairs, Collection):
        raise InventoryShape(
            f"frame_pairs is {type(frame_pairs).__name__}, a one-shot "
            f"iterator. in_frame is called once per paper and `any` "
            f"short-circuits, so the first paper would consume it and every "
            f"later paper would read as out of frame. Pass a list.")
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


def analogue_only(paper: Mapping[str, Any],
                  index: Mapping[str, Any]) -> bool:
    """Whether a paper is reachable on both sides ONLY through an analogue.

    Under rule 2 such a paper is unmatchable, and the report says so rather
    than binning it into a tier that would flatter it. This is the tier-B
    question `TIER_STATE.md` leaves open for the operator; naming the shape
    here is not settling it.

    Args:
        paper: One inventory paper, rows as dicts.
        index: The key-to-construct index. The analogue key is RESOLVED through
            it, as the present branch resolves its own: an analogue key the
            build does not hold names no measurement, and reporting the paper
            as reachable-by-analogue would assert the instrument carries one.

    Returns:
        True when neither side has a confident present key and both sides
        carry a confident analogue the build holds.

    Raises:
        InventoryShape: When either anchor side is missing.
    """
    def state(rows: Iterable[Mapping[str, Any]]) -> tuple[bool, bool]:
        rows = list(rows)
        present = any(r.get("status") == MATCHING_STATUS and r.get("key") is not None
                      and r.get("confident") is True
                      and fold(str(r["key"]), index) for r in rows)
        analogue = any(r.get("status") == "modality"
                       and r.get("analogue_key") is not None
                       and r.get("confident") is True
                       and fold(str(r["analogue_key"]), index) for r in rows)
        return present, analogue

    e_present, e_analogue = state(_rows_of(paper, "exposures"))
    o_present, o_analogue = state(_rows_of(paper, "outcomes"))
    return not e_present and not o_present and e_analogue and o_analogue


def key_table_from_inventory(papers: list[dict[str, Any]],
                             harness: Handoff | Mapping[str, Any],
                             *, index: Mapping[str, Any] | None = None,
                             schema_path: Any = None,
                             rows_schema_version: str | None = None,
                             ) -> tuple[PaperKey, ...]:
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
        rows_schema_version: What the inventory source declared; see
            `_schema_pin`.

    Returns:
        The table.

    Raises:
        HandoffMismatch: When the harness names no schema, names one this tree
            contradicts, or names one the rows were not written under.
        InventoryShape: On a repeated paper id, a missing anchor side, an
            unrecognised status, or a paper with no id at all.
    """
    _schema_pin(harness, schema_path, rows_schema_version)
    if index is None:
        index = _dictionary_index()
    statuses = _statuses(harness)
    out: list[PaperKey] = []
    seen: set[str] = set()
    for paper in normalise_papers(list(papers)):
        if "paper" not in paper:
            raise InventoryShape(
                "a paper carries neither `paper` nor `pmid`, so it cannot be "
                "joined to anything the run produced")
        pmid = str(paper["paper"])
        if pmid in seen:
            # Two files for one paper: each row would hold only its own file's
            # keys, so a paper split across them is matchable in neither, while
            # `papers` counts it twice and every rate's denominator inflates.
            raise InventoryShape(
                f"{pmid} appears twice. Two rows for one paper are not merged "
                f"here: each would carry only half the keys and the paper "
                f"count would double.")
        seen.add(pmid)
        exposures, _ = _side_keys(_rows_of(paper, "exposures"), index, statuses,
                                  f"{pmid}.exposures")
        outcomes, _ = _side_keys(_rows_of(paper, "outcomes"), index, statuses,
                                 f"{pmid}.outcomes")
        out.append(PaperKey(pmid=pmid, exposure_terms=(),
                            outcome_keys=tuple(sorted(outcomes)),
                            exposure_keys=tuple(sorted(exposures))))
    return tuple(out)


def _statuses(harness: Handoff | Mapping[str, Any]) -> tuple[str, ...]:
    """The status vocabulary the harness declares, checked against this module.

    Args:
        harness: The harness.

    Returns:
        The vocabulary.

    Raises:
        HandoffMismatch: When it does not contain the status this module
            matches on. A harness whose vocabulary has no `present` would make
            every paper unmatchable and the report would print that as a
            finding about the instrument.
    """
    values = (harness.status_values if isinstance(harness, Handoff)
              else tuple(harness.get("status_values", ())))
    if values and MATCHING_STATUS not in values:
        raise HandoffMismatch(
            f"the harness's status_values {list(values)} do not contain "
            f"{MATCHING_STATUS!r}, which is the only status this module "
            f"matches on; every paper would read as unmatchable")
    return tuple(values)


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
                    schema_path: Any = None,
                    rows_schema_version: str | None = None) -> InventoryInput:
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
        rows_schema_version: What the inventory source declared, when it
            declared anything; see `_schema_pin`.

    Returns:
        The prepared input.

    Raises:
        HandoffMismatch: From the schema pin.
        InventoryShape: From the row reading.
    """
    if index is None:
        index = _dictionary_index()
    table = key_table_from_inventory(papers, harness, index=index,
                                     schema_path=schema_path,
                                     rows_schema_version=rows_schema_version)
    frame: frozenset[str] | None = None
    if frame_pairs is not None:
        pairs = list(frame_pairs)
        frame = frozenset(k.pmid for k in table if in_frame(k, pairs, index))
    normalised = normalise_papers(list(papers))
    statuses = _statuses(harness)
    counted = side_exclusions(normalised, index, statuses)
    return InventoryInput(
        table=table, in_frame=frame,
        excluded_sides={side: dict(counts._asdict()) for side, counts in counted.items()},
        partition_holds=all(c.partition_holds for c in counted.values()),
        analogue_only=sum(1 for paper in normalised
                          if analogue_only(paper, index)))


class SideAgreement(NamedTuple):
    """Two readers compared on one side of one paper, or pooled over papers.

    Never a single percentage. Status agreement and key agreement have
    different denominators -- the second is taken only over rows both readers
    called present -- and a variable one reader listed and the other did not
    has no denominator at all, because there is no shared row to compare. A
    pooled figure would hide which of the three moved.

    Attributes:
        labels_both: Labels both readers listed on this side.
        labels_a_only: Labels only reader A listed.
        labels_b_only: Labels only reader B listed.
        labels_repeated: Labels a reader listed more than once. The extra rows
            are NOT compared: two rows for one variable is an adjudication
            item, and merging them would pick one by file order and score the
            reader as agreeing with themselves.
        status_agree: Shared labels the two gave the same `status`.
        status_compared: Shared labels where BOTH carried a status. A row
            missing the field on both sides is not agreement: `None == None`
            would report a renamed field as a perfect reading.
        key_agree: Shared labels both called present where the keys are the
            same string, or fold to the same construct.
        key_compared: Shared labels both called present and both keyed, the
            denominator of `key_agree`.
    """

    labels_both: int
    labels_a_only: int
    labels_b_only: int
    labels_repeated: int
    status_agree: int
    status_compared: int
    key_agree: int
    key_compared: int


class Agreement(NamedTuple):
    """Two readings compared, per paper and pooled.

    Two fields rather than a `"__pooled__"` entry among the paper ids: sharing
    that namespace makes `len()` over-count the papers by one and puts a row
    labelled `__pooled__` in any table built by iterating.

    Attributes:
        per_paper: Paper id to side to counts, for the papers BOTH readers
            covered.
        pooled: Side to those counts summed.
        papers_a_only: Papers only reader A covered.
        papers_b_only: Papers only reader B covered.
    """

    per_paper: dict[str, dict[str, SideAgreement]]
    pooled: dict[str, SideAgreement]
    papers_a_only: int
    papers_b_only: int


def _label_of(row: Mapping[str, Any]) -> str:
    """One row's verbatim variable name, whichever field it is under.

    Args:
        row: An inventory row.

    Returns:
        The name, stripped and casefolded; empty when the row carries none.
    """
    for field in LABEL_FIELDS:
        value = str(row.get(field, "")).strip()
        if value:
            return value.casefold()
    return ""


def _by_label(rows: list[Mapping[str, Any]],
              where: str) -> tuple[dict[str, Mapping[str, Any]], int]:
    """Index one side's rows by their verbatim label.

    Labels are the only join available: the whole point of a second reading is
    that the two readers may have chosen different keys for the same variable,
    so joining on the key would compare only the rows that already agree.

    Args:
        rows: One side's rows.
        where: Named in the refusal.

    Returns:
        Label to row, and how many labels were repeated.

    Raises:
        InventoryShape: When the side has rows and NONE of them carries a
            name. Returning an empty index instead would make every later
            count zero, and a clean table of zeros reads as two readers who
            compared nothing rather than as a field this code cannot find.
    """
    out: dict[str, Mapping[str, Any]] = {}
    repeated = 0
    for row in rows:
        label = _label_of(row)
        if not label:
            continue
        if label in out:
            repeated += 1
            continue
        out[label] = row
    if rows and not out:
        raise InventoryShape(
            f"{where}: {len(rows)} rows and not one carries a name under any "
            f"of {list(LABEL_FIELDS)}. Joined on nothing, every agreement "
            f"count below would be zero and read as a finished comparison.")
    return out, repeated


def _side_agreement(a_rows: list[Mapping[str, Any]], b_rows: list[Mapping[str, Any]],
                    index: Mapping[str, Any], where: str) -> SideAgreement:
    """Compare two readers on one side of one paper.

    Args:
        a_rows: Reader A's rows for this side.
        b_rows: Reader B's rows for this side.
        index: The key-to-construct index, so two readers who picked a member
            and its construct are not scored as disagreeing.
        where: Named in a refusal.

    Returns:
        The counts.

    Raises:
        InventoryShape: From `_by_label`.
    """
    a, repeat_a = _by_label(a_rows, f"{where}.a")
    b, repeat_b = _by_label(b_rows, f"{where}.b")
    shared = sorted(set(a) & set(b))
    # A row missing `status` on both sides is not agreement: None == None
    # would report a renamed or dropped field as a perfect reading.
    statused = [k for k in shared
                if a[k].get("status") is not None and b[k].get("status") is not None]
    status = sum(1 for k in statused if a[k].get("status") == b[k].get("status"))
    both_present = [k for k in statused
                    if a[k].get("status") == b[k].get("status") == MATCHING_STATUS
                    and a[k].get("key") is not None and b[k].get("key") is not None]
    # String identity first: two readers who typed the SAME key agree even
    # when the build no longer holds it, and folding alone would call that a
    # disagreement because both folds are empty.
    key_agree = sum(1 for k in both_present
                    if str(a[k]["key"]) == str(b[k]["key"])
                    or fold(str(a[k]["key"]), index) & fold(str(b[k]["key"]), index))
    return SideAgreement(labels_both=len(shared), labels_a_only=len(set(a) - set(b)),
                         labels_b_only=len(set(b) - set(a)),
                         labels_repeated=repeat_a + repeat_b, status_agree=status,
                         status_compared=len(statused), key_agree=key_agree,
                         key_compared=len(both_present))


def agreement(a: Iterable[dict[str, Any]], b: Iterable[dict[str, Any]],
              index: Mapping[str, Any] | None = None,
              harness: Handoff | Mapping[str, Any] | None = None,
              schema_path: Any = None) -> Agreement:
    """Compare two readings of the same papers, per paper and per side.

    Task S of `BRIEF_inventory_discovery.md`: a hand-written key has no
    reliability estimate, and that number bounds every figure the inventory
    scores. This computes it and reports it with n on every line. It never
    pools the three quantities into one percentage, and it decides nothing:
    every disagreement is a row for the operator to adjudicate by reading the
    paper.

    Args:
        a: One reader's papers, rows as dicts. The operator's inventory.
        b: The other reader's papers, same shape. The second rater's files.
        index: The key-to-construct index; built from the dictionary when
            None, so the brief's two-argument call works as written.
        harness: When given, its `schema_version` is pinned before a row is
            read, so the reliability estimate is not the one path into these
            rows that skips the pin.
        schema_path: Passed to the pin.

    Returns:
        The comparison; see `Agreement`. A paper only one reader covered is
        COUNTED but not compared: there is nothing to compare, and scoring it
        as a disagreement would confuse coverage with reliability.

    Raises:
        HandoffMismatch: From the pin, when a harness is given.
        InventoryShape: On a repeated paper id, a missing anchor side, or a
            side whose rows carry no name.
    """
    if harness is not None:
        _schema_pin(harness, schema_path)
    if index is None:
        index = _dictionary_index()

    def by_id(papers: Iterable[dict[str, Any]], who: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for paper in normalise_papers(list(papers)):
            pmid = str(paper["paper"])
            if pmid in out:
                # Keeping the last would discard one whole reading of that
                # paper with no count, no warning and no denominator moved.
                raise InventoryShape(
                    f"reader {who} carries {pmid} twice; one reading would be "
                    f"silently discarded")
            out[pmid] = paper
        return out

    by_a, by_b = by_id(a, "a"), by_id(b, "b")
    per_paper: dict[str, dict[str, SideAgreement]] = {}
    zero = SideAgreement(0, 0, 0, 0, 0, 0, 0, 0)
    pooled = {side: zero for side in SIDES}
    for paper in sorted(set(by_a) & set(by_b)):
        per_paper[paper] = {}
        for side in SIDES:
            got = _side_agreement(_rows_of(by_a[paper], side),
                                  _rows_of(by_b[paper], side), index,
                                  f"{paper}.{side}")
            per_paper[paper][side] = got
            pooled[side] = SideAgreement(*(x + y for x, y in
                                           zip(pooled[side], got, strict=True)))
    return Agreement(per_paper=per_paper, pooled=pooled,
                     papers_a_only=len(set(by_a) - set(by_b)),
                     papers_b_only=len(set(by_b) - set(by_a)))
