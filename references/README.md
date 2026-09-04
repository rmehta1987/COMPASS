# references/

External papers and figures kept for human reading.

**Nothing in this directory may be reachable by the Specifier.** It is not on any
tool path, and `benchmark/contamination_check.py` asserts that `env/tools.py`
never references it. The sealed worktree denies `Read`, `Glob` and `Grep` and runs
from a neutral cwd, so a headless run cannot open these regardless — this
directory exists for people, not for the pipeline.

| file | what it is |
|---|---|
| `astro_agents_reference.pdf` | AstroAgents — multi-agent hypothesis generation from mass-spectrometry data. One of the architecture papers behind the design decisions; **not** a COMPASS cohort paper. |
| `asttroagent.png` | Figure from the above. |

## Not stored here

The COMPASS cohort papers (sixteen inventoried as of 2026-08-27) are **not** in this repo. They describe
this cohort — its exposures, outcomes and realised sample sizes — and are the
sharpest contamination risk in the project. They are inventoried by PMID in
`benchmark/cohort_papers.py`, and their designs belong on the held-out side
under `benchmark/` (off every tool path), never in
`curated/`, a docstring, or a prompt.

    32938600  Cohort profile, BMJ Open 2020
    36065817  Primary-care spatial accessibility -> hypertension, Circ CQO 2022
    37252073  Neighborhood disadvantage -> CRC screening, Prev Med Rep 2023
    38715087  PM2.5/NO2 -> central hemodynamics, Environ Health 2024

The fifth analysis this file once listed as unidentified is PMID 38397711 (n=602, 2024); the bibliography now holds sixteen and
`benchmark/cohort_papers.py` is its only home.
Retrieve any of these through NCBI E-utilities; PubMed's cookie wall blocks
ordinary fetching.
