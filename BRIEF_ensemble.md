# BRIEF — phrasing ensemble

The task brief this work was run against, recorded verbatim so that the decision
rules, the expectations and the premise corrections in `FUSION.md` can be checked
against what was actually asked rather than against a paraphrase of it.

*Editorial note (2026-09-04): the brief below quotes "2.94 ms" as the retriever's per-query
cost. That figure is batched throughput (`query_ms_per_row`), not per-call latency; see
`PROVENANCE.md` §Latency. The brief is otherwise recorded verbatim.*

**Answered by:** `FUSION.md` (artifacts `out/fusion_task1_overlap.json` (withdrawn from git),
`out/fusion_task2_rules.json`, `out/fusion_task3_abstention.json`,
`out/fusion_task4_rewriter.json`, `out/rewrites_positives.json`,
`out/rewrites_negatives.json`).

**Outcome in one line.** Task 1's pre-recorded interpretation resolved to the
"caveat dissolves" branch. Task 2 failed its own decision rule (22.8% of the
oracle gap recovered against a 25% floor), so task 4 was not built as a
component — it was measured anyway, because task 3's symmetric abstention
comparison could not be made honest without a real rewriter. Three premises in
the brief were wrong and are corrected in `FUSION.md`: the ~31% overlap figure,
the prediction that RRF would lose, and the claim that task 2 is a clean ceiling
for task 4.

---

# Phrasing ensemble — measure the fusion before generating anything

`CHARACTERISATION.md` §1 contains a finding it does not draw out. The per-item
phrasing histogram says:

| phrasings at rank 1 | items |
|---|---|
| 0 / 4 | **10** |
| 1 / 4 | 9 |
| 2 / 4 | 7 |
| 3 / 4 | 16 |
| 4 / 4 | 14 |

**46 of 56 items have at least one phrasing that lands at rank 1.** So
best-phrasing-per-item is **0.821** against the shipped **0.567** — 25 points of
headroom, from phrasing alone, with no retraining.

That number is an oracle: it assumes you know which phrasing to trust. Tasks 1
and 2 below measure how much of it a real fusion rule recovers, **using only the
fixture you already have.** No LLM, no new data, no model change. Only if that
works does task 4 build a rewriter.

Model under test: `bge-small` fine-tuned (`nn0, t=0.10`), the `deploy/` bundle.
Build `3dc8415eccfe`. Fixture unchanged.

---

## Task 1 — the overlap test (do this first, it reframes everything)

Before measuring fusion, settle whether the fixture's declared leakage bias is
real. Every report has carried "queries were written by a model that saw the gold
wording, so all numbers are an upper bound." **The evidence in
`CHARACTERISATION.md` argues against it:**

- §1a found 18 of 19 blind spots fail because *the query never states the
  discriminator* — the gold's distinguishing detail is systematically **absent**
  from the query, which is the opposite of leakage.
- Content-word overlap between the failing queries and their gold wording
  averages ~31%, with three at 0% (`NSAID utilization frequency` vs "taking
  naproxen such as Naprosyn, Anaprox, or Aleve"; `circadian sleep schedule` vs
  "what time do you typically wake up on days off").
- 10 items are 0/4 across all four phrasings, which gold paraphrases could not be.
- The generation prompt said *"do not copy distinctive phrases."* A model that saw
  the gold and was told to avoid its distinctive terms produces queries with the
  discriminator removed — **the anti-copying instruction may have made the fixture
  harder than reality, not easier.**

**Measure it.** For each of the 224 rows compute content-word overlap between
`query` and the gold target's wording (stopword-stripped, stemmed or not — state
which). Then:

- correlate per-item mean overlap against that item's k/4 score
- report R@1 by overlap quartile
- report the overlap distribution for correct vs incorrect top-1

**Interpretation, recorded before running:** if R@1 rises monotonically with
overlap, leakage is real and concentrated in the high-overlap items, and the
upper-bound caveat stands. If R@1 is flat or non-monotonic across quartiles, the
caveat largely dissolves and **0.567 may be a lower bound** for a real query
stream, since researchers who have read the codebook would use more of the
instrument's vocabulary, not less.

This changes the interpretation of every number in the project and costs one
script.

---

## Task 2 — leave-one-out fusion, no LLM

The fixture already contains four phrasings per item. Treat three of them as if a
rewriter had produced them.

For each of the 224 rows: take that row's query plus the **other three phrasings
of the same gold item**, encode all four, retrieve against the same 1,353
vectors, fuse, and score against the unchanged gold rule on the unchanged 224
denominator.

### Fusion rules to compare

| rule | definition | why it is in the list |
|---|---|---|
| **single** (control) | the row's own query only | reproduces 0.567; if it does not, stop |
| **max_cos** | highest `cos(q_i, t)` over all (phrasing, target) pairs | the principled favourite — §2 established absolute cosine is comparable across queries for this model, AUROC 0.982 |
| **min_rank** | best rank across phrasings, tie-broken by cosine | exploits disjointness directly; the 0.821 oracle is this rule with perfect tie-breaking |
| **mean_cos** | mean cosine per target across phrasings | the corroboration-flavoured option, for contrast |
| **rrf** | `sum 1/(60+rank)` | **expected to lose.** Included as a measured negative, not a candidate — see below |

**Why RRF is expected to lose, and why to run it anyway.** RRF rewards
corroboration. With 32 of 56 items partial, failures are disjoint across
phrasings, so a single phrasing that finds the item gets outvoted by a wrong item
three phrasings rank consistently. C16 already measured this mechanism: `rrf`
demoted 11 rows the shipped search had at rank 1. Run it so the claim is measured
rather than asserted, and expect it below `single`.

### Report

R@1, R@5, R@10, rank p50/p90/max per rule, plus:

- **the oracle (0.821) as a ceiling row**, so recovery fraction is legible:
  `(rule − 0.567) / (0.821 − 0.567)`
- per-item k/4 histogram under the winning rule against the single-query
  histogram — did mass move to 4/4, or did partial items just become
  differently partial?
- the 10 items at 0/4: unchanged, as expected? §1a says no rewrite invents a
  discriminator the request never contained, so these should not move. If they
  do, that is a finding.
- **`residence_commute`** specifically. It is 0.062 at R@1 and 0.688 at R@10 —
  the one stratum a top-10 list does not rescue. If fusion does not move it,
  say so; it is the stratum the commute-exposure line of inquiry runs through.

**Decision rule, recorded before running.** If the best rule recovers under ~25%
of the oracle gap (i.e. lands below ~0.63), fusion does not exploit the
disjointness and task 4 is not worth building. If it recovers over ~50% (above
~0.70), a rewriter is worth building.

---

## Task 3 — what fusion does to abstention (blocking for deployment)

**This is the risk to the one mechanism that currently works cleanly.**

`deploy/` ships `min_cos = 0.7295`, which rejects 43 of 44 held-out negatives for
0.9 recall points, at AUROC 0.982. Under `max_cos` fusion **every score inflates,
including the negatives** — four draws instead of one. The threshold will not
survive unchanged and the separation may narrow.

So run the 44-row negative fixture through the winning fusion rule too, and
report:

- negative cosine distribution under fusion vs single (p10/p50/p90/max)
- AUROC, positives vs negatives, under fusion
- the re-derived max-F1 threshold, **selected on positives only** — the negatives
  report, they do not select, exactly as `CHARACTERISATION.md` §3 did it
- negatives rejected at the new threshold, and the recall it costs

For the negatives you have only one phrasing each, so **generate three
paraphrases per negative by the same method used for the positives**, or state
plainly that the comparison is single-phrasing negatives against four-phrasing
positives and is therefore optimistic about separation. Do not leave that
asymmetry unstated.

**If fusion destroys the abstention separation, that is likely disqualifying.**
Absence detection at AUROC 0.982 is worth more than 25 points of R@1 in an
autonomous pipeline, because §3 also established the model **cannot** detect its
own errors (AUROC 0.640, precision 0.90 unreachable at any threshold). Abstention
on absent constructs is the only reliable guard the tool has.

---

## Task 4 — only if tasks 2 and 3 both pass

Build the rewriter: one LLM call per request producing 3 paraphrases, then the
winning fusion rule.

**Prompt design constraint from task 1.** The fixture's phrasings were written
under a "do not copy distinctive phrases" instruction, and that is *not* what you
want at inference. A rewriter should generate paraphrases that move toward the
instrument's register — naming the drug, the timeframe, the AM/PM field — because
§1a shows failures come from the query *lacking* the discriminator. Ask for
plausible restatements including concrete instances, not abstractions.

Report: R@1/R@5/R@10 against leave-one-out fusion (task 2 is the ceiling a real
rewriter must approach), latency per query, cost per query, and the abstention
figures from task 3 re-derived on generated rather than fixture phrasings.

Note the cost shape: 4 encodes is ~11.8 ms against 2.94 ms, negligible; the LLM
call is ~1 s and dominates entirely. For a research tool that is acceptable, but
it ends the "zero marginal cost" property that made argmax attractive — state it.

---

## What this does not do

**It does not fix autonomous operation.** A hypothesis needs an exposure and an
outcome, so R@1 squares. Even at the 0.821 oracle, pair-correctness is 0.674 —
better than today's 0.321, still one in three hypotheses resting on a wrong
variable, and §3 says the model cannot flag which. Fusion improves the tool; it
does not make the pipeline self-certifying.

**It does not touch the four unmeasured strata.** SES/employment,
insurance/access, cancer-screening and demographics have **zero** fixture rows
(§4) — 61 targets and 51 constructs the benchmark never tests. No fusion rule
measured on this fixture says anything about them.

**It does not replace the study-team request set.** Task 1 changes what to ask
for, though: not "queries written without sight of the instrument" as a purity
exercise, but the concrete question of whether a real researcher's phrasing sits
*closer* to the instrument's wording than the fixture's does. If it does, every
number here is a lower bound.

---

## Constraints

- Do not retrain, re-tune or modify the checkpoint. The `deploy/` bundle's guards
  must keep passing all 4 tamper tests.
- Do not use the 44 negatives to select a threshold. They report only.
- The 224-row fixture, the gold rule, `stem_option_dup`, and `build.py` at
  `3dc8415eccfe` are unchanged.
- Fix the load dtype to fp32 as `compass_score.py` already does. §6b showed
  `granite-s2` moved 4.9 R@1 points between bf16 and fp32 — any comparison that
  does not pin dtype is measuring load precision.
- Frozen `bge-small` (0.375) and frozen `mxbai-l1` (0.469) must stay runnable as
  fallbacks.
- Every number traceable to a committed JSON artifact.

## Order

Task 1 and task 2 are independent and both cheap — run them together. Task 3
gates deployment. Task 4 only if 2 and 3 pass.

If a premise here is wrong, say so and stop rather than implementing around it —
three premises in the last brief were wrong and correcting them in place was the
right call, so do that where the task itself survives.
