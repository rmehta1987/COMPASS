"""benchmark/cohort_papers.py — the COMPASS cohort bibliography, held out.

WHY THIS FILE EXISTS AND WHY IT IS HERE, NOT IN THE HANDOFF
-----------------------------------------------------------
Until 2026-08-28 the design content of four cohort papers — their exposures,
outcomes and realised sample sizes — sat in a table in
`HANDOFF_AGENT_PIPELINE.md` §3. That document is read in full by every session
and by every lane agent, and those same agents then author `curated/`,
`agent/schema.py` docstrings and the prompts. Handoff §3's own rule is that a
design choice must never reach those surfaces; putting the designs in the
document that every author reads first made the rule harder to keep, not easier.

So the table moved here. `benchmark/` is fenced from the tool layer by
`benchmark.contamination_check.check_holdout_not_reachable`, which fails if
`env/tools.py` so much as names it. The handoff now points here instead of
carrying the content.

WHAT THIS IS NOT. It is not the answer key. The answer key needs, per paper, the
exposure and outcome keys resolved against the instrument, the covariate set, the
model form, the tier against a model's knowledge cutoff, and the
environment-forced versus paper-free field partition that keeps a rediscovery
score and a recall score different numbers. That is task C12 and it is not built.
This file is the bibliography those rows will hang from, moved intact so nothing
was lost in the cut.

Sixteen records are indexed. Four were inventoried until 2026-08-27. That is the
number to distrust: the search cannot see paywalled papers with no PMC deposit,
papers naming the cohort only in Methods, papers under a different cohort label,
or papers citing none of the seed PMIDs — and a PubMed phrase search for the
cohort's full name returns zero hits, so there is no reliable name-based search.
Sixteen is a floor.

Fetched via NCBI E-utilities; PubMed's cookie wall blocks ordinary fetching.
"""

from __future__ import annotations

from typing import NamedTuple


class CohortPaper(NamedTuple):
    """One published analysis drawing on the COMPASS cohort.

    Attributes:
        pmid: PubMed identifier.
        year: Publication year as printed by the venue.
        venue: Journal, abbreviated as the record gives it.
        design: Exposure to outcome, plus the method where it is distinctive.
        n: Realised analytic sample as the paper reports it, or a note when the
            paper reports none.
        inventoried_before_2026_08_27: False for the twelve that no exclusion
            list in this project knew about, which is why every tier assignment
            built before that date is wrong.
    """

    pmid: str
    year: int
    venue: str
    design: str
    n: str
    inventoried_before_2026_08_27: bool


#: The four that handoff §3 carried, moved here verbatim, plus the twelve found
#: on 2026-08-27 by `elink pubmed_pubmed_citedin` from the cohort profile and a
#: PMC full-text phrase search. Design detail for the twelve lives in the lane
#: report and in `prevalence_key.py`; it is deliberately not expanded here until
#: C12 builds the answer key properly, so this file stays a bibliography rather
#: than becoming a second, competing half-key.
COHORT_PAPERS: tuple[CohortPaper, ...] = (
    CohortPaper("32938600", 2020, "BMJ Open",
                "cohort profile; recruitment coverage and baseline prevalences",
                "~8,000 recruited", True),
    CohortPaper("36065817", 2022, "Circ Cardiovasc Qual Outcomes",
                "primary-care spatial accessibility (E2SFCA) -> hypertension "
                "control/awareness", "5,096", True),
    CohortPaper("37252073", 2023, "Prev Med Rep",
                "seven linked community characteristics -> CRC screening, WQS",
                "2,836", True),
    CohortPaper("38715087", 2024, "Environ Health",
                "PM2.5/NO2 3-year residential exposure -> central hemodynamics",
                "2,387", True),
    CohortPaper("38397711", 2024, "Int J Environ Res Public Health",
                "Chicago Health Atlas neighbourhood + ambient exposures -> "
                "uterine fibroid diagnosis", "602", False),
    CohortPaper("36702470", 2023, "Am J Epidemiol",
                "eight Chicago Health Atlas characteristics, WQS -> asthma",
                "6,592", False),
    CohortPaper("42034153", 2026, "Environ Res",
                "residential greenspace -> memory performance", "4,048", False),
    CohortPaper("41883377", 2026, "not recorded here",
                "PM2.5 components -> cardiovascular biomarkers",
                "648 (COMPASS arm)", False),
    CohortPaper("39217205", 2024, "not recorded here",
                "PM2.5 exposure windows -> blood pressure", "6,381", False),
    CohortPaper("39238838", 2024, "not recorded here",
                "individual and area characteristics -> household PM2.5",
                "244 households", False),
    CohortPaper("38961645", 2024, "not recorded here",
                "perceived discrimination in health care -> anxiety, "
                "depression, bipolar; g-estimation", "not in retrievable text",
                False),
    CohortPaper("37884074", 2024, "not recorded here",
                "PM2.5 exposure windows -> cardiometabolic biomarkers", "641",
                False),
    CohortPaper("37879000", 2024, "not recorded here",
                "health insurance type and clinic visits -> measured "
                "hypertension", "1,092", False),
    CohortPaper("36823587", 2023, "not recorded here",
                "breast cancer case/control -> serum metabolome", "125 + 125",
                False),
    CohortPaper("33088675", 2020, "not recorded here",
                "tobacco and marijuana use -> serum PSA", "928", False),
    CohortPaper("32542493", 2021, "not recorded here",
                "neighbourhood socioeconomic status -> biospecimen "
                "participation", "5,108 addresses", False),
)

#: PMID 37503099 is the preprint of 38715087, not a separate analysis. Recorded
#: so nobody counts seventeen.
KNOWN_DUPLICATES: dict[str, str] = {"37503099": "38715087"}


def uninventoried() -> tuple[CohortPaper, ...]:
    """The papers no exclusion list in this project knew about before 2026-08-27.

    Returns:
        Every paper whose absence invalidated the tier assignments built when
        the inventory stood at four.
    """
    return tuple(p for p in COHORT_PAPERS if not p.inventoried_before_2026_08_27)
