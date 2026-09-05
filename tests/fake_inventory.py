"""A SYNTHETIC paper inventory for exercising the specification benchmark.

Four papers with real instrument keys and real bibliography pmids, but the
variables, designs and directions are invented so that the driver, the
harness and the modal baseline can be tested before the key exists. Nothing
here was read from a paper. Any run or report built on it must say so:
`pipeline.pose` writes the provenance beside the artefacts and
`benchmark.specification_score` prints it first.

What the four exercise:

* 36065817: a full paper, one covariate found by search (excluded), one the
  instrument lacks (absent).
* 37252073: one covariate the author could not pin (excluded).
* 38715087: an exposure the instrument lacks, so the paper is unreproducible
  and poses nothing.
* 36702470: a prospective design and a mixed direction, so design disagrees
  with any cross-sectional record and direction is not scorable.

Modal set at the default majority share, over the four papers with a
scorable covariate: m1:Q5.4 (4 papers), m2:Q5.6 (2), m2:Q9.1 (2).
"""

from __future__ import annotations

from benchmark.paper_inventory import InventoryVariable as V
from benchmark.paper_inventory import PaperInventory

SYNTHETIC = True


def _ok(role: str, label: str, key: str) -> V:
    return V(role=role, label=label, key=key, in_instrument=True,
             resolution="verified", confident=True)


FAKE_INVENTORY: tuple[PaperInventory, ...] = (
    PaperInventory(
        pmid="36065817", design="cross-sectional", direction="increase",
        read_on="2026-09-04", notes="SYNTHETIC",
        exposures=(_ok("exposure", "synthetic exposure A", "m2:Q9.105"),),
        outcomes=(_ok("outcome", "synthetic outcome A", "m2:Q5.19"),),
        covariates=(_ok("covariate", "income", "m1:Q5.4"),
                    _ok("covariate", "diabetes", "m2:Q5.6"),
                    _ok("covariate", "menarche", "m2:Q9.1"),
                    V(role="covariate", label="oophorectomy", key="m2:Q9.108",
                      in_instrument=True, resolution="found_by_search", confident=False),
                    V(role="covariate", label="neighbourhood index", key=None,
                      in_instrument=False, resolution="absent", confident=True,
                      absent_reason="linked spatial measure"))),
    PaperInventory(
        pmid="37252073", design="cross-sectional", direction="decrease",
        read_on="2026-09-04", notes="SYNTHETIC",
        exposures=(_ok("exposure", "synthetic exposure B", "m2:Q9.69"),),
        outcomes=(_ok("outcome", "synthetic outcome B", "m2:Q5.8"),),
        covariates=(_ok("covariate", "income", "m1:Q5.4"),
                    _ok("covariate", "diabetes", "m2:Q5.6"),
                    V(role="covariate", label="last period", key="m2:Q9.7",
                      in_instrument=True, resolution="verified", confident=False))),
    PaperInventory(
        pmid="38715087", design="cross-sectional", direction="increase",
        read_on="2026-09-04", notes="SYNTHETIC",
        exposures=(V(role="exposure", label="synthetic linked exposure", key=None,
                     in_instrument=False, resolution="absent", confident=True,
                     absent_reason="linked spatial measure"),),
        outcomes=(_ok("outcome", "synthetic outcome C", "m2:Q5.8"),),
        covariates=(_ok("covariate", "income", "m1:Q5.4"),)),
    PaperInventory(
        pmid="36702470", design="prospective", direction="mixed",
        read_on="2026-09-04", notes="SYNTHETIC; per-pair directions invented",
        exposures=(_ok("exposure", "synthetic exposure D", "m2:Q9.105"),),
        outcomes=(_ok("outcome", "synthetic outcome D", "m2:Q5.8"),),
        covariates=(_ok("covariate", "income", "m1:Q5.4"),
                    _ok("covariate", "menarche", "m2:Q9.1"))),
)
