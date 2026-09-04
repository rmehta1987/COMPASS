# references/

External papers and figures kept for human reading.

**Nothing in this directory may be reachable by the Specifier.** It is not on any
tool path, and `benchmark/contamination_check.py` asserts that `env/tools.py`
never references it. The sealed worktree denies `Read`, `Glob` and `Grep` and runs
from a neutral cwd, so a headless run cannot open these regardless — this
directory exists for people, not for the pipeline.

| file | what it is |
|---|---|
| `PRIOR_ART_CONTAMINATION.md` | Prior-art reading on contamination and retrieval; the primary for `docs/adr/003`. |
| `astro_agents_reference.pdf`, `asttroagent.png` | **Not published in this repository** (third-party paper and figure). AstroAgents — multi-agent hypothesis generation from mass-spectrometry data; an architecture reference, **not** a COMPASS cohort paper. |

## Not stored here

The COMPASS cohort papers are **not** in this repo. They describe this cohort — its
exposures, outcomes and realised sample sizes — and are the sharpest contamination risk
in the project. They are inventoried by PMID in `benchmark/cohort_papers.py`, which is
their only home (this file once duplicated part of that list with designs; the duplicate
was removed on 2026-09-03 so the module owns the count and the content). Their designs
belong on the held-out side under `benchmark/` (off every tool path), never in
`curated/`, a docstring, or a prompt.
Retrieve any of these through NCBI E-utilities; PubMed's cookie wall blocks
ordinary fetching.
