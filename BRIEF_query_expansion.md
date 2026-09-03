# Query expansion — deterministic template, paired test

`FUSION.md` §1 found that what predicts retrieval accuracy is **query length**,
not lexical overlap with the gold:

| query length | n rows | R@1 | pair-correctness (R@1²) |
|---|---|---|---|
| 1–2 content words | 71 | 0.493 | 0.243 |
| 3 words | 82 | 0.537 | 0.288 |
| 4+ words | 71 | **0.676** | **0.457** |

And the one lexical statistic that correlates is the absolute **count** of shared
content words (rho 0.186, perm p 0.005), not the coverage ratio (rho 0.090,
p 0.17).

The fixture's queries are 2–5 word lookup labels because a generator was
instructed to write terse requests and avoid distinctive phrases. **The pipeline
is in the opposite position:** by the time the specifier needs a variable it
already knows the construct, the variable's role, the population and the
timeframe. `NSAID utilization frequency` is what remains after all of that is
discarded.

This brief tests whether putting it back recovers the length gradient.

Model: `bge-small` fine-tuned (`nn0, t=0.10`), the `deploy/` bundle, guards live,
threshold unchanged. Build `3dc8415eccfe`. Fixture, gold rule and
`stem_option_dup` unchanged.

---

## Statistics — read this before designing anything

**Do not split the fixture 60/40.** Rows cluster by item (4 phrasings each), so
effective n is **56 items**, not 224 rows. Measured cost of splitting:

| n items | Wilson CI at p=0.567 | width |
|---|---|---|
| 56 (all) | [0.437, 0.688] | 0.251 |
| 34 (60% dev) | [0.402, 0.718] | 0.316 |
| 22 (40% test) | [0.366, 0.748] | 0.383 |

At n=22 the half-width is 0.191 against an effect of 0.183. And the target
subgroup — the 71 rows at 1–2 content words — is already only ~18 items. A split
makes the experiment unable to answer its own question.

**Use a paired design instead.** Same row, same gold target, short query versus
expanded query. That is both more powerful and the control for the confound:
longer fixture queries may be longer *because* their targets are more complex, so
length could be proxying target distinctiveness. Holding the target fixed
eliminates that.

Report:

- **Δ R@1 with an item-clustered bootstrap 95% CI**, resampling items not rows —
  `FUSION.md` §4 got width 0.116 this way, which resolves +0.183 comfortably
- the paired flip table: gained / lost / unchanged
- exact McNemar for comparison only, noted as too narrow because it treats four
  correlated rows as four draws
- the same on the 1–2 word subgroup specifically, where the effect should be
  largest

**Overfitting protection comes from pre-registration, not from a split.** See
task 0.

---

## Task 0 — pre-register the template, before looking at any result

The risk a split was meant to address is real: a template tuned by inspecting
which fixture rows it fixes is fitted to the fixture. Handle it by construction
instead.

**Derive the template's fields from target-side structure only** — what
`targets.json` and `dictionary.json` already carry (construct, option, roster
family size, matrix block) plus the role assignment the specifier makes. **Do not
inspect the fixture's gold answers, the 19 blind-spot items, or any per-row
result while designing it.**

Commit the template and its sha256 **before** running task 2. Then a single
evaluation on all 56 items is honest and full-power.

If the template is later revised in light of results, that revision needs its own
held-out confirmation — and say so rather than re-reporting the same number.

---

## Task 1 — build the expansion, deterministically

```python
@dataclass(frozen=True)
class RetrievalRequest:
    construct: str             # "nonsteroidal anti-inflammatory medication use"
    role: VariableRole         # exposure / outcome / confounder
    population: str | None     # "participant" | "sibling" | "household member"
    timeframe: str | None      # "past 12 months" | "lifetime" | "current"
    instances: tuple[str, ...] # ("ibuprofen", "naproxen", "aspirin")

    def to_query(self) -> str:
        """Deterministic template. No model call, no network."""
```

**Determinism is the point.** The rewriter in `FUSION.md` §4 gained +4.0 R@1
inside its own CI and cost non-reproducibility — which reached the *abstention
decision*, so a request scoring near τ could be answered on one run and refused
on the next. A template gets the same length benefit with none of that: same
input, same query, same variable, every run. It also keeps zero marginal cost, no
network dependency and no external failure mode.

**More words is not the mechanism, so do not pad.** §1 says shared-word *count*
is what correlates. `FUSION.md` §4's worked loss shows the failure: `sibling
prostate cancer` fell from rank 1 to 2 when "sibling" was expanded to "your
brother or sister" — the sibling-roster block's own wording, which pulled the
query toward the wrong roster member. Add terms that name the construct and its
instances; do not add terms that name the *structure* the target sits in.

For the source of the expansion fields on the fixture rows: derive them from each
row's gold target's own metadata (roster family size gives population, matrix
block gives the option set). State exactly how, because that choice is the
experiment's main threat — it must not encode which target is correct beyond what
the specifier would genuinely know at query time.

---

## Task 2 — the paired experiment

For each of the 224 rows, retrieve twice through `deploy/`:

1. the row's own query, unchanged — **must reproduce R@1 0.567 exactly**, row for
   row, or stop
2. the same row's query expanded by the template

**Single retrieval each. No fusion, no paraphrase ensemble.** None of `FUSION.md`
§2's or §4's fusion-rule instability applies, and the rule ordering that inverted
between those sections is irrelevant here.

Report, overall and for the 1–2 word subgroup:

| field |
|---|
| R@1, R@5, R@10 short vs expanded |
| **Δ R@1 with item-clustered bootstrap 95% CI** |
| gained / lost / unchanged counts |
| mean content-word count and mean shared-word count, before and after |
| R@1 by resulting query-length stratum, to check the gradient reproduces |
| per-stratum recall, especially `residence_commute` (0.062 shipped, 0.688 @10) |
| the 10 items at 0/4 — expected unchanged, since no expansion supplies a discriminator the request never contained |

**Decision rule, recorded before running.** If the CI on Δ R@1 excludes zero and
the point estimate exceeds +0.05, the template is justified and ships. If the CI
contains zero, it does not ship regardless of the point estimate — that is the
lesson of §4's +4.0.

---

## Task 3 — the negatives, and the threshold (blocking)

**Expanded queries score higher against everything, including absent
constructs.** `FUSION.md` §3 measured this error at **34 points** of apparent
rejection rate when positives were expanded and negatives were not. Do not repeat
it.

Apply the same template to the 44 held-out negatives — using only the fields a
specifier would have for a construct that does not exist, which is the honest and
harder case. Then report:

- negative score distribution, expanded vs not (p10/p50/p90/max)
- AUROC positives vs negatives, expanded
- negatives rejected at the **shipped** τ = 0.7295
- re-derived τ, **selected on positives only** — candidate values drawn from
  positive scores alone, as `src/fusion_abstain.py` already does
- negatives rejected and recall at the re-derived τ

`max_cos` fusion dropped rejection from 43/44 to 35/44 and needed τ re-derived to
0.7737. Template expansion may do the same. **If it does, that is not
disqualifying — a deterministic template's threshold can be re-derived once and
frozen**, unlike a rewriter's, which must be re-derived every time the prompt
changes. Say which case applies.

Absence detection is the only reliable guard this tool has: AUROC 0.982 for
absence against 0.640 for error, with precision 0.90 unreachable at any τ. Trading
it for R@1 is a bad exchange at almost any rate.

---

## Task 4 — optional: corpus-size sensitivity

This is the *other* reading of "60% of the codebook", and it answers a different
and legitimate question: how does retrieval degrade as the dictionary grows?

Score the shipped configuration against corpora of 40 / 60 / 80 / 100% of the
1,353 targets, sampled by **construct** (never splitting a construct's options
across the boundary), with the gold target always retained.

**Report it as a sensitivity curve, not as a benchmark.** Fewer distractors makes
retrieval mechanically easier, so R@1 will rise and that rise is an artifact of
the smaller pool, not a result. Its use is extrapolation: if COMPASS adds a
module, the curve says what that costs.

Run this only if tasks 2 and 3 are done.

---

## Constraints

- No retraining, re-tuning or checkpoint modification. `deploy/` guards must keep
  passing 4/4.
- The unchanged-query arm must reproduce R@1 0.567 row for row, or the run stops.
- Negatives never select a threshold; they report only.
- Load dtype pinned fp32 — `granite-s2` moved 4.9 R@1 points between bf16 and
  fp32, so any comparison that does not pin it measures load precision.
- No model call at query time. If the template needs one, it is not a template
  and belongs in a different brief.
- Every number traceable to a committed JSON artifact, tracked in git.

## What this cannot settle

**It does not fix autonomous operation.** Even at the full length gradient,
pair-correctness is 0.676² = 0.457 — better than today's 0.321, still roughly one
hypothesis in two resting on a wrong variable, and the model cannot flag which.

**The gradient is measured on this fixture's queries.** A template that recovers
it here recovers it on requests written by one generator in one register. The
study-team request set remains the thing that validates it, and `FUSION.md` §5
sharpened what to ask: not "written without sight of the instrument", but **are a
researcher's requests longer and more specific than 2–5 words?**

**Four strata still have zero fixture rows** — SES/employment, insurance/access,
cancer-screening, demographics, 61 targets and 51 constructs. No result here says
anything about them, and they are the mediators a disparities hypothesis needs.

If a premise here is wrong, say so and stop rather than implementing around it.
