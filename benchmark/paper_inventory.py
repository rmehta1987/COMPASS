"""The per-paper variable inventory: the schema, not the data.

The pre-metadata baseline could only ask whether a hypothesis landed on a
paper's exposure-outcome pair, and the held-out key answered that for three
papers. Asking whether the pipeline SPECIFIES a study the way its authors did
needs, per paper, every variable the analysis used, resolved to instrument
keys: the exposure, the outcome, each covariate with the role the paper gave
it, the design and the expected direction. That inventory is paper content
and an answer key, so it lives on the `scoring-key` branch as
`benchmark/paper_inventory_key.py::INVENTORY`, authored by a person reading
the papers; this module holds only the types it must satisfy and the checks
that catch the failure modes a hand-written key has.

Contract, enforced by the models:

* every paper names at least one exposure and one outcome;
* a variable the instrument holds names its keys and a module region; one it
  does not hold names no keys and says where it lives instead, so absence is
  written down rather than left as a blank;
* covariate roles use the pipeline's own `CausalRole` vocabulary, so recall
  and precision can be scored role by role;
* the design and direction use the record's own vocabularies.

`validate_against_dictionary` runs every key through the resolver the
Specifier uses, so a key that names a stem rather than a variable is caught
before it scores anything. `load_inventory` imports the key lazily and raises
where the key is unreachable, which is every clone but the scoring one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schema import CausalRole, Direction
from pipeline.causal_structure import DESIGNS

KEY_RE = re.compile(r"^m[123]:Q\d+(\.\d+)?[A-Za-z0-9_~.]*$")
ROLES = ("exposure", "outcome", "covariate")
COVARIATE_ROLES = tuple(r.value for r in CausalRole)
DIRECTIONS = tuple(d.value for d in Direction)
#: A paper whose design the pipeline's vocabulary cannot name still gets an
#: inventory; `other` keeps design agreement scorable as "not comparable".
INVENTORY_DESIGNS = (*DESIGNS, "other")
_MODULE_PREFIXES = ("m1", "m2", "m3")
KEY_MODULE = "benchmark.paper_inventory_key"


class InventoryVariable(BaseModel):
    """One variable a paper's analysis used.

    Attributes:
        role: `exposure`, `outcome` or `covariate`.
        label: The paper's own name for it, verbatim, so a reader can check
            the resolution against the paper. Paper content: key branch only.
        keys: Instrument variable keys it resolves to; empty when the
            instrument does not hold it.
        instrument_region: `m2:Q5 diagnosed conditions` for a held variable;
            for an absent one, where it lives instead, e.g. `linked spatial
            measure, not in the instrument`.
        covariate_role: The role the paper gave a covariate, in `CausalRole`
            terms; None for anchors.
        derivation: How several items combine into the variable, when they do.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(pattern="^(" + "|".join(ROLES) + ")$")
    label: str = Field(min_length=1)
    keys: tuple[str, ...] = ()
    instrument_region: str = Field(min_length=1)
    covariate_role: str | None = None
    derivation: str | None = None

    @property
    def in_instrument(self) -> bool:
        """Whether the region names a module of the questionnaire."""
        return self.instrument_region.startswith(_MODULE_PREFIXES)

    @model_validator(mode="after")
    def _consistent(self) -> InventoryVariable:
        for k in self.keys:
            if not KEY_RE.match(k):
                raise ValueError(f"{k!r} is not an instrument key")
        if self.in_instrument and not self.keys:
            raise ValueError(f"{self.label!r}: region {self.instrument_region!r} "
                             f"is in the instrument but no keys are named")
        if not self.in_instrument and self.keys:
            raise ValueError(f"{self.label!r}: keys named but region "
                             f"{self.instrument_region!r} says not in the instrument")
        if self.role == "covariate":
            if self.covariate_role not in COVARIATE_ROLES:
                raise ValueError(f"{self.label!r}: covariate_role must be one of "
                                 f"{COVARIATE_ROLES}, got {self.covariate_role!r}")
        elif self.covariate_role is not None:
            raise ValueError(f"{self.label!r}: only a covariate carries a covariate_role")
        return self


class PaperInventory(BaseModel):
    """Everything the scorer needs to compare a hypothesis with one paper.

    Attributes:
        pmid: PubMed identifier; must appear in `benchmark/cohort_papers.py`.
        design: `cross_sectional`, `repeated_measures` or `other`.
        expected_direction: The paper's reported direction, in the record's
            vocabulary.
        unit_of_analysis: As the paper states it.
        variables: Every variable the analysis used.
        read_on: ISO date the inventory was taken from the paper.
        note: Anything a scorer should know: a subgroup restriction, a
            variable the paper defines ambiguously.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pmid: str = Field(pattern=r"^\d{7,8}$")
    design: str = Field(pattern="^(" + "|".join(INVENTORY_DESIGNS) + ")$")
    expected_direction: str = Field(pattern="^(" + "|".join(DIRECTIONS) + ")$")
    unit_of_analysis: str = Field(min_length=1)
    variables: tuple[InventoryVariable, ...] = Field(min_length=2)
    read_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = ""

    def by_role(self, role: str) -> tuple[InventoryVariable, ...]:
        """The variables with one role, in inventory order.

        Args:
            role: `exposure`, `outcome` or `covariate`.

        Returns:
            Those variables.
        """
        return tuple(v for v in self.variables if v.role == role)

    def keys_by_role(self, role: str) -> frozenset[str]:
        """Every instrument key under one role.

        Args:
            role: `exposure`, `outcome` or `covariate`.

        Returns:
            The union of the role's variables' keys.
        """
        return frozenset(k for v in self.by_role(role) for k in v.keys)

    @property
    def posable(self) -> bool:
        """Whether both anchors are in the instrument, so the pair can be posed."""
        return bool(self.keys_by_role("exposure")) and bool(self.keys_by_role("outcome"))

    @model_validator(mode="after")
    def _anchors(self) -> PaperInventory:
        for role in ("exposure", "outcome"):
            if not self.by_role(role):
                raise ValueError(f"PMID {self.pmid}: no {role} variable")
        labels = [v.label for v in self.variables]
        if len(set(labels)) != len(labels):
            raise ValueError(f"PMID {self.pmid}: duplicate variable labels")
        return self


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
    answer.

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
            for k in v.keys:
                outcome = resolve(k).get("outcome")
                if outcome in ("group", "construct"):
                    bad.append(f"PMID {p.pmid} {v.label!r}: {k} names a {outcome}, "
                               f"not a variable")
                elif outcome != "unique":
                    bad.append(f"PMID {p.pmid} {v.label!r}: {k} does not resolve "
                               f"({outcome})")
    return bad


def posed_pairs(inventory: Iterable[PaperInventory]) -> list[dict[str, str]]:
    """The pairs to pose to the pipeline, one per exposure-outcome key pair.

    A paper with several exposure keys or outcome keys poses each combination;
    a paper missing either anchor from the instrument poses nothing and is
    scorable only on discovery.

    Args:
        inventory: The papers.

    Returns:
        Rows of `pmid`, `exposure_key`, `outcome_key`, in inventory order.
        `pipeline.pose` reads the two keys and ignores the pmid, which is the
        scorer's join field and never enters the generation tree.
    """
    rows: list[dict[str, str]] = []
    for p in inventory:
        for e in sorted(p.keys_by_role("exposure")):
            for o in sorted(p.keys_by_role("outcome")):
                rows.append({"pmid": p.pmid, "exposure_key": e, "outcome_key": o})
    return rows


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

Lives on the scoring-key branch only. Authored by a person reading each paper;
every key resolved with env.tools.resolve_variable before it is written down.
Schema and checks: benchmark/paper_inventory.py.
"""

from benchmark.paper_inventory import InventoryVariable as V
from benchmark.paper_inventory import PaperInventory

INVENTORY: tuple[PaperInventory, ...] = (
    PaperInventory(
        pmid="00000000",                # replace: a pmid from cohort_papers.py
        design="cross_sectional",       # cross_sectional | repeated_measures | other
        expected_direction="increase",  # Direction values
        unit_of_analysis="participant",
        read_on="2026-01-01",
        note="",
        variables=(
            V(role="exposure", label="<the paper's name for the exposure>",
              keys=("m2:Q9.105",), instrument_region="m2:Q9 female medical history"),
            V(role="outcome", label="<the paper's name for the outcome>",
              keys=("m2:Q5.19",), instrument_region="m2:Q5 diagnosed conditions"),
            V(role="covariate", label="<a covariate the paper adjusted for>",
              keys=("m1:Q5.4",), instrument_region="m1:Q5 household",
              covariate_role="confounder"),
            V(role="covariate", label="<a covariate the instrument lacks>",
              keys=(), covariate_role="confounder",
              instrument_region="linked spatial measure, not in the instrument"),
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
