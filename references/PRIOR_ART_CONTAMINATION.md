# Prior art: contamination control and literature-retrieval ordering

Written 2026-08-28 so the next session does not re-fetch eight papers. **This directory is
fenced from the tool layer** — `benchmark/contamination_check.py::check_holdout_not_reachable`
fails if `env/tools.py` names `references`. Nothing here may be copied into `curated/`, `env/`,
an `agent/` docstring or a prompt.

Everything below is **external** prior art, not COMPASS cohort papers, so it carries no
cohort-contamination risk. The COMPASS bibliography lives on the held-out side under
`benchmark/`, not here.

## Read status — this matters, and an earlier draft got it wrong

Bodies read in full, references and appendices excluded, 2026-08-27/28:

| paper | arXiv | read |
|---|---|---|
| MOOSE-Chem | 2410.07076v3 | body |
| Reconstruction | 2608.16645v3 | body |
| Search-Time Contamination | 2606.05241v1 | body |
| Duan et al., *Do MIAs Work on LLMs?* | 2402.07841v2 | body |
| NewtonBench | 2510.07172v3 | body |
| PreScience | 2602.20459v2 | body |
| CiteME | 2407.12861v2 | body |
| BioDisco | 2508.01285v2 | body |
| AstroAgents | 2503.23170 | implementation read (`AstroAgents.py`) |

**Three claims from an abstract-level sweep did NOT survive body-reading. Do not reinstate them:**

1. **PreScience's per-target leakage filter is appendix-only.** `leakage filter` and
   `contiguous characters` occur **zero times** in the body. What the body says is narrower:
   *"all author- and reference-level metadata … are temporally aligned to each paper's
   publication date to prevent leakage of future information into task inputs."*
2. **NewtonBench's `DataBlind` probe occurs zero times in the body.** Appendix-only.
3. **BioDisco has no contamination control.** `contaminat` occurs **zero times** in its body.
   Its "temporal evaluation" is about whether hypotheses hold up as future discoveries —
   *"testing a system's ability to rediscover known scientific findings using historical data"* —
   and its methodological contribution is replacing Elo with Bradley–Terry for uncertainty
   estimates, not preventing leakage.

## Four distinct mechanisms exist. They are not variants of each other.

**1. Date cutoff plus matched model selection.** MOOSE-Chem runs *"GPT-4o (its training data
is up to October 2023)"* against *"51 chemistry papers published in Nature, Science, or a
similar level in 2024 (all papers are only available online since 2024)"*.

**2. Prompt-time isolation.** Reconstruction §3.2, and note the disclaimer is the important
part: *"The protocol does not prevent a seed from having entered pretraining."* Its six
mechanisms are a temporal cutoff excluding undated references; information isolation from the
seed; anonymous reference IDs *"exposed only as opaque IDs (ref-001, …) with title/abstract
text—no venue shortcuts"*; frozen per-paper bibliographies; evidence binding, where each
hypothesis must cite its supporting references; and judge self-evaluation avoidance. Generation
*"makes no runtime web-search calls."*

**3. Counterfactual ground truth — the only mechanism that closes the pretraining channel.**
NewtonBench mutates canonical physical laws into variants that never existed: *"The
counterfactual law shifts applied to physical laws ensure the tasks are novel and not directly
suitable for training"* (Ethics Statement). 108 shifted laws from 12 canonical, three tiers by
mutation count.

**4. Subtracting what the model already knows.** CiteME: *"we remove all dataset instances that
GPT-4o can correctly answer… GPT-4o was used with no Internet access or any other external
tools. Therefore, it could answer only correctly specified papers that it memorized from its
training process. We ran each sample through GPT-4o five times… we filtered out 124 samples,
leaving 130 samples in total."* Precedented by Bamboogle and GPQA.

## Retrieval ordering, and why MOOSE-Chem is not the precedent it looks like

**MOOSE-Chem does not search literature.** Its retrieval is screening over a fixed, constructed
corpus with the answers planted inside: *"We first find 3000 most cited chemistry papers
published in Nature, and construct a series of I in size of 150, 300, 1000, and 3000. I is
constructed by first adding the ground truth inspiration papers (around 120), then randomly
selecting the remaining needed papers from the 3000 papers, and finally randomizing the order…
Only title and abstract are needed for each paper in I."* So it is a retrieval benchmark with
known positives, not a precedent for design-time literature access.

**AstroAgents puts retrieval after.** In `AstroAgents.py`, scientist agents are called with
`search_analysis: ""` on the first iteration; `process_hypothesis_and_search` then queries
Semantic Scholar with each hypothesis's own `statement`, feeding the next round.

**The ordering follows from what the raw material is.** In MOOSE-Chem the retrieved papers ARE
the material a hypothesis is composed from. In COMPASS the material is the questionnaire, so
literature would be a second, unbounded source — which changes what the benchmark measures
rather than improving how it measures. **Decision for COMPASS: retrieval runs after
transduction, as annotation into `selection_rationale.prior_work`.**

## Two input-side checks the field has and COMPASS does not

- MOOSE-Chem's experts verify *"whether the background does not contain any information in
  inspirations or hypothesis."*
- CiteME excludes excerpts naming authors or acronyms *"which simply tests LM memorization and
  retrieval."*

## Duan et al. §4 — why a date-based comparison may measure the calendar

The setup criticised is exactly a tier design: *"Prior work distinguishes members and
non-members of a target domain based on the knowledge cutoff date of the target model, with
members coming before and non-members coming after the cutoff."*

Finding: *"the temporally shifted settings yield MIA performances significantly higher than
when members and non-members are from the same temporal range."* Mechanism is vocabulary drift,
measured as seven-gram overlap falling from **39.3%** for natural non-members to **13.9%** for
temporally shifted ones. Conclusion: *"decision thresholds derived using temporally-shifted
non-members end up testing for temporal shift rather than membership."*

Their own limit, kept for honesty: *"as we aren't able to reproduce the experimental settings of
prior works … it is inconclusive."*

A rediscovery score is not a likelihood score, so this does not transfer mechanically — but the
confound lives in how the two sets were constructed, and ours would be constructed the same way.
**Their diagnostic is cheap and should gate any tier claim: compare the vocabulary-overlap
distributions of the two paper sets first.**

## Retrieval leakage is a property of the plumbing, not the model

Search-Time Contamination §6, same benchmark, three systems: Gemini Deep Research *"exhibits an
alarmingly high leakage rate of 60% when web search is enabled"*, Step Deep Research 9%, and
Valyu *"an exceptional leakage rate of 0%"*, attributed to differences in search infrastructure.
Method is manual verification: *"If an visited source contains both exact answer and questions,
we label the instance as answer leakage."*

A 0% configuration exists. A frozen corpus read from a build artefact is one.

## Calibration for expectations

Reconstruction, 643 papers, seven frontier models: single-model Match rates *"3.4–15.0%"*, best
average *"13.3% ± 2.3%"*. A multi-agent pipeline — cross-model review plus a Swiss tournament,
still on the frozen bibliography — reaches *"22.9–41.6%… with mean 36.0%"*, an observed 2.4x
lift, reported as an association. **That is the first measured evidence bearing on this
project's minimal-agent versus multi-agent question; it belongs in the decision ledger.**

## How four systems actually retrieve, read from source 2026-08-30

Three repositories read at source (not README, not abstract) by a parallel workflow,
then re-derived against fresh clones by a cold critic on a different model family.
**Commit pins, without which the next fetch drifts and this has to be redone:**
MOOSE-Chem `f8cda98a` (2025-11-12), biomni `400c1f36` (2026-01-14), chemcrow-public
`e7ebd519` (2024-12-19), paper-qa `v1.1.1`.
the Biomni mechanism and the Co-Scientist blog were re-derived independently by the
orchestrator. MOOSE-Chem and ChemCrow findings are the lane's, quoted from source.

**NONE OF THE THREE USES AN EMBEDDING INDEX TO SELECT FROM A FIXED CATALOGUE.**
Selection is an LLM call over candidates pasted into the prompt. Read the scope
exactly: ChemCrow *does* build a FAISS index with embeddings and select by MMR — over
papers scraped per query, which is not a fixed catalogue — so this is not "the field
never selects with embeddings". That pipeline is in fact the nearest existing analogue
to what a scored `search_variables` would become.

- **MOOSE-Chem** walks the corpus in contiguous slices — `cur_title_abstract_pairs =
  inspiration_candidates[start_id:end_id]` — putting every item in front of the model,
  15 per call, keeping 3 (`assert args.num_screening_keep_size in [3]`), over up to 4
  tournament rounds: 150 -> 30 -> 6 -> 3. Grepping the selection path for
  `embed|faiss|sentence_transformer|bm25|tfidf|cosine` returns only the words
  "embedding"/"embedded" inside hardcoded abstracts. Screening runs at temperature 0.0.
- **Biomni** renders its ENTIRE catalogue — 224 tools, 76 data-lake items, 113
  libraries, **55,234 chars measured at `400c1f36`** — as `"{i}. {name}: {description}"`
  into one prompt and asks
  the model for indices, parsed with `re.search(r"TOOLS:\s*\[(.*?)\]", response,
  re.IGNORECASE)`. `ToolRegistry` has no search or rank method at all.
- **ChemCrow** uses FAISS/MMR, but only over papers already fetched; tool selection is
  every tool description in the ReAct prompt.

**NONE OF THE THREE RETURNS A PER-HIT SCORE, AND NONE HAS A THRESHOLD ON A RETRIEVAL
PATH.** So a vocabulary miss is masked by plausible-looking hits, which is the same
defect `env/tools.py::search_variables` has and the field's default rather than a local
embarrassment. An earlier version of this section said "all three return a structurally
non-empty result"; that is FALSE and was corrected 2026-08-30 — Biomni's parser
initialises `{"tools": [], ...}` and its prompt says *"If a category has no relevant
items, use an empty list"*, ChemCrow returns `"Not enough papers found"` on
`len(papers) == 0`, and `search_variables("zzzqqq xyzzyx plughq")` returns `n=0`. What
is missing is not the ability to return nothing. It is any way for a caller to tell a
good hit from a bad one.

- MOOSE-Chem snaps a generated title back onto the corpus by argmax Jaccard with no
  cutoff, and when the match is garbage it prints: *"if max_similarity < 0.3 and
  if_print_warning: print(...)"*. Nothing branches on that number.
- Biomni instructs against abstention: *"Be generous in your selection - include
  resources that might be useful for the task, even if they're not explicitly mentioned
  in the query"* and *"When in doubt about a database tool or molecular biology tool,
  include it rather than exclude it."*
- ChemCrow's MMR returns k=5 regardless; abstention is three downstream text
  heuristics — `if len(papers) == 0`, a substring test for `"Not applicable"`, and
  `if len(context_str) < 10`. The last two live in the pinned dependency
  `paper-qa==1.1.1` (`paperqa/docs.py`), not in ChemCrow's own tree: true of the
  shipped system, but attribute it correctly.

**Templates worth copying, by name.** `Scholar2ResultLLM` (ChemCrow) is the working
shape for `search_literature`: LLM query rewrite -> scraper -> paper-qa over an index ->
abstention gates -> a cited answer. MOOSE-Chem's screener is the shape for
`check_prior_work`, and it is the one whose corpus is a frozen local artefact rather
than a live search, which is what this document already requires.

## Corrections to a claims table, 2026-08-30

**Co-Scientist** — arXiv:2502.18864; Nature DOI 10.1038/s41586-026-10644-y (resolves,
HTTP 200). Verified against v2 only; the claim that "Tournament of Ideas" is also
absent from v1 is a lane report, not re-derived. The Ranking
agent runs an Elo tournament, hypotheses seeded at 1200, pairwise matches decided by
simulated scientific debate (multi-turn for top-ranked, single-turn below). NOT
supported: the name "Tournament of Ideas" (zero occurrences in either arXiv version or
the blog); "thousands of papers summarized iteratively" (the paper never quantifies the
literature read); any mechanism that "drops" weak theories. The official blog states,
in the caption of its GPQA concordance figure: *"The Elo is an auto-evaluation and is
not based on an independent ground truth"*. Its strongest claim is explicitly
self-rated — *"the self-rated quality of results improve and surpass models and
unassisted human experts"* (emphasis on *self-rated* added here; the original is
lowercase). Its human validation
is *"a smaller subset of 11 research goals"* with *"the sample size was small"* in its
own words. **So Reconstruction, not Co-Scientist, is the citation that carries the
multi-agent case** — Reconstruction reports Match against ground truth, Co-Scientist
reports an auto-evaluation.

**ChemCrow** — wrong on all three parts of "18 expert chemistry APIs including Patent
Search". `make_tools` is a flat list: minimum 14 on the README quickstart path, maximum
18, reachable either with Chemspace, Serp and RXN4Chem configured or via the
`local_rxn=True` path with no RXN4Chem key at all; two of those are
`python_repl` and `wikipedia`. "Patent Search" does not exist — `PatentCheck` is a local
Bloom-filter set-membership test returning "Patented" or "Novel", issuing no query and
retrieving no document. The repo's own README: *"This package does not contain all the
tools described in the ChemCrow paper… This repo will not give the same results as that
paper."*

**HypoBench** — real, arXiv:2504.11524, and "Literature + Data" is a genuine named
method the paper reports as best-performing. But the literature methods are evaluated
*"exclusively on the real-world datasets"* — 7 free-text tasks — and NOT on the 5
synthetic tasks that carry typed feature schemas. It is therefore not a precedent for
grounding hypotheses in tabular variables.

**BioSkepsis — NO IDENTIFIER, treat as nonexistent.** Searched with a positive control
on each endpoint: arXiv `all:"bioskepsis"` returned 0 while `all:"biomni"` returned 2;
Crossref returned 0 while the Biomni query returned its DOI; OpenAlex returned one
unrelated 2002 Danish paper. It resolves to a commercial SaaS, and every attribute
attributed to it traces to vendor copy. This is the sixth name this project has had to
strike for want of an id.

## Not pursued

An abstract-level sweep named roughly seven further systems with **no identifier at all**
("HindSight", "CKM", "Test of Time", "DBench-Bio", "Proof of Time", "Before the Action",
"FIRE-Bench"). Treat as nonexistent until someone produces an ID. This project has already
retracted five citations from an earlier review; an unverifiable name is a liability.
