"""The per-paper variable inventory: the schema, not the data.

The pre-metadata baseline could only ask whether a hypothesis landed on a
paper's exposure-outcome pair, and the held-out key answered that for three
papers. Asking whether the pipeline SPECIFIES a study the way its authors did
needs, per paper, every variable the analysis used, resolved to instrument
keys: the exposures, the outcomes, every covariate the paper adjusted for,
the design and the reported direction. That inventory is paper content and
an answer key, so it lives on the `scoring-key` branch as
`benchmark/paper_inventory_key.py::INVENTORY`, authored by a person reading
the papers (`benchmark/PAPER_INVENTORY_GUIDE.md`); this module holds only
the types it must satisfy and the checks that catch the failure modes a
hand-written key has.

Three things the schema makes first-class, because each is a different
result from a pipeline failure and the inventory is the only place the
distinction can live:

* `in_instrument=False`: the paper used a variable the questionnaire does
  not hold, a linked spatial measure say. A hypothesis cannot recover it,
  and the harness counts such papers apart from failures.
* `resolution="found_by_search"`: the author could only locate the key by
  searching the instrument, so retriever error entered the answer key. The
  harness excludes those rows and reports how many; a key partly authored
  by the retriever cannot measure the retriever. `verified` means the key
  was checked to exist and to name a variable, not a stem.
* `confident=False`: the author could not pin the variable. Excluded and
  counted the same way.

`validate_against_dictionary` runs every key through the resolver the
Specifier uses. `load_inventory` imports the key lazily and raises where the
key is unreachable, which is every clone but the scoring one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schema import CausalRole, Direction
from pipeline.causal_structure import CROSS_SECTIONAL, REPEATED_MEASURES

KEY_RE = re.compile(r"^m[123]:Q\d+(\.\d+)?[A-Za-z0-9_~.]*$")
ROLES = ("exposure", "outcome", "covariate")
RESOLUTIONS = ("verified", "found_by_search", "absent")
COVARIATE_ROLES = tuple(r.value for r in CausalRole)
#: The paper's reported direction, in the record's vocabulary, plus `mixed`
#: for a paper whose pairs disagree; a mixed paper is not scored on direction.
DIRECTIONS = (*(d.value for d in Direction), "mixed")
#: How the inventory names a design, and what the pipeline's two designs map
#: to. Anything else compares as disagreement with a cross-sectional record.
DESIGNS = ("cross-sectional", "prospective", "repeated-measures", "nested case-control",
           "case-control", "other")
DESIGN_TO_PIPELINE = {"cross-sectional": CROSS_SECTIONAL,
                      "repeated-measures": REPEATED_MEASURES}
KEY_MODULE = "benchmark.paper_inventory_key"
#: A covariate is modal when at least this share of the scorable papers
#: adjusted for it: a majority rule, stated rather than tuned.
MODAL_SHARE = 0.5


class InventoryVariable(BaseModel):
    """One variable a paper's analysis used.

    Attributes:
        role: `exposure`, `outcome` or `covariate`; must match the tuple it
            sits in.
        label: The paper's own name for it, verbatim, so a reader can check
            the resolution. Paper content: key branch only.
        key: The instrument variable key, or None when the instrument does
            not hold it.
        in_instrument: False for a variable the questionnaire lacks.
        absent_reason: Required when `in_instrument` is False: where the
            variable lives instead, e.g. `linked spatial measure`.
        resolution: `verified` (checked with `resolve_variable` to exist and
            name a variable), `found_by_search` (located with
            `search_variables`; excluded from scoring), or `absent`.
        confident: False when the author could not pin the variable;
            excluded from scoring.
        covariate_role: Optional, the role the paper gave a covariate, in
            `CausalRole` terms; lets recall be reported by role.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(pattern="^(" + "|".join(ROLES) + ")$")
    label: str = Field(min_length=1)
    key: str | None = None
    in_instrument: bool
    absent_reason: str = ""
    resolution: str = Field(pattern="^(" + "|".join(RESOLUTIONS) + ")$")
    confident: bool
    covariate_role: str | None = None

    @property
    def scorable(self) -> bool:
        """In the instrument, verified, and pinned: a row the harness may use."""
        return self.in_instrument and self.resolution == "verified" and self.confident

    @property
    def exclusion(self) -> str | None:
        """Why the harness leaves this row out, or None when it may use it."""
        if not self.in_instrument:
            return "absent"
        if self.resolution == "found_by_search":
            return "found_by_search"
        if not self.confident:
            return "not_confident"
        return None

    @model_validator(mode="after")
    def _consistent(self) -> InventoryVariable:
        if self.in_instrument:
            if self.key is None or not KEY_RE.match(self.key):
                raise ValueError(f"{self.label!r}: in the instrument but key "
                                 f"{self.key!r} is not an instrument key")
            if self.resolution == "absent":
                raise ValueError(f"{self.label!r}: in the instrument but resolution "
                                 f"is 'absent'")
            if self.absent_reason:
                raise ValueError(f"{self.label!r}: absent_reason given for a variable "
                                 f"in the instrument")
        else:
            if self.key is not None:
                raise ValueError(f"{self.label!r}: key {self.key!r} named but "
                                 f"in_instrument is False")
            if not self.absent_reason.strip():
                raise ValueError(f"{self.label!r}: in_instrument is False; say where "
                                 f"the variable lives in absent_reason")
            if self.resolution != "absent":
                raise ValueError(f"{self.label!r}: not in the instrument, so "
                                 f"resolution must be 'absent'")
        if self.resolution == "found_by_search" and self.confident:
            raise ValueError(f"{self.label!r}: a key found by search is never "
                             f"confident; set confident=False")
        if self.covariate_role is not None:
            if self.role != "covariate":
                raise ValueError(f"{self.label!r}: only a covariate carries a "
                                 f"covariate_role")
            if self.covariate_role not in COVARIATE_ROLES:
                raise ValueError(f"{self.label!r}: covariate_role must be one of "
                                 f"{COVARIATE_ROLES}")
        return self


class PaperInventory(BaseModel):
    """Everything the scorer needs to compare a hypothesis with one paper.

    Attributes:
        pmid: PubMed identifier; must appear in `benchmark/cohort_papers.py`.
        exposures: The paper's exposure variables.
        outcomes: The paper's outcome variables.
        covariates: Every variable the paper adjusted for.
        design: One of `DESIGNS`.
        direction: The paper's reported direction for its exposure-outcome
            pair, one of `DIRECTIONS`; `mixed` when its pairs disagree.
        notes: Anything a scorer should know: a subgroup restriction, an
            ambiguous variable definition, the per-pair directions of a
            `mixed` paper.
        read_on: ISO date the inventory was taken from the paper.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pmid: str = Field(pattern=r"^\d{7,8}$")
    exposures: tuple[InventoryVariable, ...] = Field(min_length=1)
    outcomes: tuple[InventoryVariable, ...] = Field(min_length=1)
    covariates: tuple[InventoryVariable, ...] = ()
    design: str = Field(pattern="^(" + "|".join(re.escape(d) for d in DESIGNS) + ")$")
    direction: str = Field(pattern="^(" + "|".join(DIRECTIONS) + ")$")
    notes: str = ""
    read_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @property
    def variables(self) -> tuple[InventoryVariable, ...]:
        """Every variable, anchors first."""
        return (*self.exposures, *self.outcomes, *self.covariates)

    def scorable_keys(self, role: str) -> frozenset[str]:
        """The keys the harness may use under one role.

        Args:
            role: `exposure`, `outcome` or `covariate`.

        Returns:
            Keys of the scorable variables with that role.
        """
        group = {"exposure": self.exposures, "outcome": self.outcomes,
                 "covariate": self.covariates}[role]
        return frozenset(v.key for v in group if v.scorable and v.key)

    def excluded(self) -> Counter[str]:
        """Why rows were left out, counted.

        Returns:
            `absent`, `found_by_search`, `not_confident` to their counts.
        """
        return Counter(v.exclusion for v in self.variables if v.exclusion)

    @property
    def posable(self) -> bool:
        """Both anchors scorable, so the pair can be posed to the pipeline."""
        return (bool(self.scorable_keys("exposure"))
                and bool(self.scorable_keys("outcome")))

    @property
    def reproducible(self) -> bool:
        """Every anchor is in the instrument; False is a limit, not a failure."""
        return all(v.in_instrument for v in (*self.exposures, *self.outcomes))

    @model_validator(mode="after")
    def _roles_match_their_tuple(self) -> PaperInventory:
        for name, group in (("exposure", self.exposures), ("outcome", self.outcomes),
                            ("covariate", self.covariates)):
            for v in group:
                if v.role != name:
                    raise ValueError(f"PMID {self.pmid}: {v.label!r} sits in "
                                     f"{name}s but carries role {v.role!r}")
        labels = [v.label for v in self.variables]
        if len(set(labels)) != len(labels):
            raise ValueError(f"PMID {self.pmid}: duplicate variable labels")
        return self


# ---------------------------------------------------------------- validation


def validate_inventory(inventory: Iterable[PaperInventory],
                       known_pmids: Iterable[str] | None = None,
                       ) -> tuple[PaperInventory, ...]:
    """Check an inventory as a whole.

    Args:
        inventory: The papers.
        known_pmids: The bibliography's pmids; every inventory pmid must be
            one of them. Read from `benchmark.cohort_papers` when None.

    Returns:
        The inventory as a tuple.

    Raises:
        ValueError: On a duplicate pmid or one the bibliography lacks.
    """
    if known_pmids is None:
        from benchmark.cohort_papers import COHORT_PAPERS
        known_pmids = [p.pmid for p in COHORT_PAPERS]
    known = set(known_pmids)
    out = tuple(inventory)
    seen: set[str] = set()
    for p in out:
        if p.pmid in seen:
            raise ValueError(f"PMID {p.pmid} appears twice")
        if p.pmid not in known:
            raise ValueError(f"PMID {p.pmid} is not in the bibliography")
        seen.add(p.pmid)
    return out


def validate_against_dictionary(inventory: Iterable[PaperInventory],
                                resolve: Callable[[str], dict[str, Any]]) -> list[str]:
    """Run every key through the Specifier's resolver.

    A key that resolves to a group or a construct names a stem, which no
    protocol may name; a key that does not resolve names nothing. Either
    would let the inventory score a hypothesis against a variable nobody can
    answer. This is the `verified` check, and it is the only use of the
    tools an author may make: `search_variables` to FIND a key is
    `found_by_search`, and the harness drops it.

    Args:
        inventory: The papers.
        resolve: `env.tools.resolve_variable`, or a test double returning a
            dict with an `outcome` field.

    Returns:
        One string per bad key, empty when every key is a variable.
    """
    bad: list[str] = []
    for p in inventory:
        for v in p.variables:
            if v.key is None:
                continue
            outcome = resolve(v.key).get("outcome")
            if outcome in ("group", "construct"):
                bad.append(f"PMID {p.pmid} {v.label!r}: {v.key} names a {outcome}, "
                           f"not a variable")
            elif outcome != "unique":
                bad.append(f"PMID {p.pmid} {v.label!r}: {v.key} does not resolve "
                           f"({outcome})")
    return bad


# ---------------------------------------------------------------- derived


def posed_pairs(inventory: Iterable[PaperInventory]) -> list[dict[str, str]]:
    """The pairs to pose to the pipeline, one per scorable exposure-outcome pair.

    Args:
        inventory: The papers.

    Returns:
        Rows of `pmid`, `exposure_key`, `outcome_key`, in inventory order.
        `pipeline.pose` reads the two keys and ignores the pmid, which is the
        scorer's join field and never enters the generation tree.
    """
    rows: list[dict[str, str]] = []
    for p in inventory:
        for e in sorted(p.scorable_keys("exposure")):
            for o in sorted(p.scorable_keys("outcome")):
                rows.append({"pmid": p.pmid, "exposure_key": e, "outcome_key": o})
    return rows


def covariate_counts(inventory: Iterable[PaperInventory]) -> Counter[str]:
    """How many papers adjusted for each scorable covariate key.

    Args:
        inventory: The papers.

    Returns:
        Key to paper count.
    """
    c: Counter[str] = Counter()
    for p in inventory:
        c.update(p.scorable_keys("covariate"))
    return c


def modal_covariates(inventory: Sequence[PaperInventory],
                     share: float = MODAL_SHARE) -> frozenset[str]:
    """The conventional adjustment set: covariates most papers share.

    Adjustment sets are conventional. A specifier that always proposes age,
    sex, race, income, BMI and smoking scores high recall on almost any
    paper with no hypothesis-specific reasoning, so raw recall is a ceiling
    effect; the margin over this set is the result.

    Args:
        inventory: The papers.
        share: A key is modal when at least this share of the papers with a
            scorable covariate adjusted for it.

    Returns:
        The modal keys; empty when no paper has a scorable covariate.
    """
    papers = [p for p in inventory if p.scorable_keys("covariate")]
    if not papers:
        return frozenset()
    threshold = max(1, ceil(share * len(papers)))
    return frozenset(k for k, n in covariate_counts(papers).items() if n >= threshold)


class Degeneracy(BaseModel):
    """Whether design and direction agreement can be metrics at all.

    Reported from the inventory before either is adopted: if every paper
    shares one design, "always say that design" scores 1.00 and design
    agreement measures nothing; if most exposures are hypothesised as
    harmful, "always predict harm" is the baseline agreement is measured
    against.

    Attributes:
        papers: Papers in the inventory.
        designs: Design to paper count.
        design_majority: The most common design and its share.
        design_degenerate: True when one design covers every paper.
        directions: Direction to paper count, `mixed` included.
        direction_majority: The most common non-mixed direction and its
            share among non-mixed papers.
        direction_scorable: Papers whose direction is not `mixed`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    papers: int
    designs: dict[str, int]
    design_majority: tuple[str, float] | None
    design_degenerate: bool
    directions: dict[str, int]
    direction_majority: tuple[str, float] | None
    direction_scorable: int


def _majority(c: Counter[str], total: int) -> tuple[str, float] | None:
    if not c or total == 0:
        return None
    k, v = c.most_common(1)[0]
    return k, v / total


def degeneracy(inventory: Sequence[PaperInventory]) -> Degeneracy:
    """Check design and direction for degeneracy; see `Degeneracy`.

    Args:
        inventory: The papers.

    Returns:
        The report.
    """
    designs = Counter(p.design for p in inventory)
    directions = Counter(p.direction for p in inventory)
    unmixed = Counter(p.direction for p in inventory if p.direction != "mixed")
    n = len(inventory)
    return Degeneracy(
        papers=n, designs=dict(designs), design_majority=_majority(designs, n),
        design_degenerate=n > 0 and len(designs) == 1,
        directions=dict(directions),
        direction_majority=_majority(unmixed, sum(unmixed.values())),
        direction_scorable=sum(unmixed.values()))


def load_inventory() -> tuple[PaperInventory, ...]:
    """Import and validate the inventory from the key branch.

    Returns:
        The validated inventory.

    Raises:
        ImportError: Where `benchmark/paper_inventory_key.py` is unreachable.
        ValueError: When the key fails validation.
    """
    import importlib

    mod = importlib.import_module(KEY_MODULE)
    return validate_inventory(mod.INVENTORY)


TEMPLATE = '''"""Per-paper variable inventory: the answer key for specification scoring.

Lives on the scoring-key branch only. Authored by a person reading each paper.
Schema, checks and the authoring guide: benchmark/paper_inventory.py and
benchmark/PAPER_INVENTORY_GUIDE.md on the working branch.
"""

from benchmark.paper_inventory import InventoryVariable as V
from benchmark.paper_inventory import PaperInventory

INVENTORY: tuple[PaperInventory, ...] = (
    PaperInventory(
        pmid="00000000",          # replace: a pmid from cohort_papers.py
        design="cross-sectional",  # see DESIGNS in paper_inventory.py
        direction="increase",      # see DIRECTIONS; mixed when the pairs disagree
        read_on="2026-01-01",
        notes="",
        exposures=(
            V(role="exposure", label="<the paper's name for the exposure>",
              key="m2:Q9.105", in_instrument=True, resolution="verified", confident=True),
        ),
        outcomes=(
            V(role="outcome", label="<the paper's name for the outcome>",
              key="m2:Q5.19", in_instrument=True, resolution="verified", confident=True),
        ),
        covariates=(
            V(role="covariate", label="<a covariate the paper adjusted for>",
              key="m1:Q5.4", in_instrument=True, resolution="verified", confident=True,
              covariate_role="confounder"),
            V(role="covariate", label="<one located only by searching>",
              key="m2:Q9.1", in_instrument=True, resolution="found_by_search",
              confident=False),
            V(role="covariate", label="<one the instrument lacks>",
              key=None, in_instrument=False, resolution="absent", confident=True,
              absent_reason="linked spatial measure"),
        ),
    ),
)
'''


def template() -> str:
    """A skeleton `paper_inventory_key.py` that validates as written.

    Returns:
        Python source with one synthetic paper to replace.
    """
    return TEMPLATE
