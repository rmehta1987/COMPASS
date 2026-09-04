# Arm E — zero-shot biomedical embedding retrieval

**Measured 2026-09-02.** Build `3dc8415eccfe`, model `medcpt-a`
(`ncbi/MedCPT-Query-Encoder` / `ncbi/MedCPT-Article-Encoder`), frozen weights, no
training, CPU. Artifact `arm_e.medcpt_a.json`, targets `targets.json`.

```
python build_targets.py --dictionary build/dictionary.json --out targets.json
python encode_and_score.py --targets targets.json \
    --fixture benchmark/fixtures/retrieval_queries.json \
    --model medcpt-a --dictionary-hash 3dc8415eccfe --out arm_e.medcpt_a.json
```

## Verdict

**Arm E is the strongest pool-builder measured and the weakest selector.** It
puts the gold item in the top 10 for three-quarters of rows — better than every
lexical arm — and picks it first only a quarter of the time. It is the mirror
image of arm D.

---

## 1. Headline

```
medcpt-a  (option_first, cpu)
  rows scored        208   gold not a target: 16
  recall@1/5/10      0.260 / 0.673 / 0.808
  rank p50/p90/max   3.0 / 26 / 304
  near-dup @1/@10    0.176 / 0.721  (n=68)
  sibling cos p50    0.9224  p90 0.9561
  encode 157.6s   query 24.8ms/row
```

### Two denominators, and the smaller one is the script's

`build_targets.py` excluded **43 direct identifiers** and **151 free-text /
text-companion rows**. **Only the first was governance.** An earlier version of
this report attributed both to governance grounds; that was wrong, and the
free-text exclusion was a bug. All four gold items it dropped are
`is_free_text=True` and none is a direct identifier — verified against
`build/dictionary.json` 2026-09-02, where the identifier exclusion costs **zero**
fixture rows and the free-text exclusion cost four:

| gold key | rows | is_free_text | is_direct_identifier |
|---|---|---|---|
| `m2:Q9.96` | 4 | true | false |
| `m2:Q776` | 4 | true | false |
| `m3:Q15.9_4_TEXT` | 4 | true | false |
| `m3:Q870_2` | 4 | true | false |

A researcher asking about commute mode should find `m2:Q776`. The exclusion was
removed on 2026-09-02; the corrected target set is **1,352 targets with 224/224
reachable**, and every figure in this document predates that fix and stands on a
208-row denominator the bug created. See `docs/arm-e-size-curve.md` for the
corrected numbers.

The script reports over its own 208. Counting the 16 as misses gives the figure
comparable to every other arm. **Both are stated everywhere below; neither
substitutes for the other.**

---

## 2. The four-arm comparison

| arm | @1 | @5 | @10 | reachability |
|---|---|---|---|---|
| control (lexical) | 0.152 | 0.415 | 0.536 | 18/224 excluded |
| min_rank (C16) | 0.152 | 0.438 | 0.549 | 0/224 |
| rrf (C16) | 0.192 | 0.469 | 0.567 | 0/224 |
| arm D (in-context selection) | 0.402 exact match | — | — | 0/224 |
| **arm E, over 208** | **0.260** | **0.673** | **0.808** | — |
| **arm E, over 224** | **0.241** | **0.625** | **0.750** | **16/224 excluded** |

Arm D returns a selection and has no @k. Arm E returns a ranking and has no
single answer. The only column where all five are commensurable is @1, and there
**arm D leads (0.402), arm E is second (0.241–0.260), and the lexical arms trail
(0.152–0.192)**.

At the depth a screening stage actually reads, **arm E is far ahead**: 0.750 at
@10 against rrf's 0.567.

---

## 3. Full recall curve

| k | of 208 | of 224 |
|---|---|---|
| @1 | 54 — 26.0% | 54 — 24.1% |
| @2 | 89 — 42.8% | 89 — 39.7% |
| @3 | 111 — 53.4% | 111 — 49.6% |
| @5 | 140 — 67.3% | 140 — 62.5% |
| @10 | 168 — 80.8% | 168 — 75.0% |
| @20 | 184 — 88.5% | 184 — 82.1% |
| @25 | 186 — 89.4% | 186 — 83.0% |
| @50 | 192 — 92.3% | 192 — 85.7% |
| @100 | 202 — 97.1% | 202 — 90.2% |
| @250 | 206 — 99.0% | 206 — 92.0% |
| @1241 (all) | 208 — 100% | 208 — 92.9% |

**Rank distribution:** p50 **3**, p75 7, p90 26, p95 66, p99 123, mean 13.2,
max 304.

The curve is steep early and flat late: half the rows are in the top 3, and going
from depth 25 to depth 250 buys 20 rows. **A screening stage reading 10–25
candidates captures 81–89% of what this arm can ever deliver.** That is the
number C17 should size its window on.

---

## 4. Where it fails

### By fold size

| gold target folds | rows | @1 | @5 | @10 | p50 rank |
|---|---|---|---|---|---|
| one key | 152 | **0.349** | 0.750 | 0.836 | 2 |
| many keys (roster family) | 56 | **0.018** | 0.464 | 0.732 | 6 |

**One correct top-1 in 56 folded-family rows.**

### By near-duplicate exposure

| gold construct | rows | @1 | @10 | p50 rank |
|---|---|---|---|---|
| has sibling options | 68 | 0.176 | 0.721 | 4 |
| no siblings | 140 | 0.300 | 0.850 | 2 |

### The sibling cosine, and what it does *not* explain

Cosine between options *within* a construct, 1,882 pairs:
**p50 0.9224, p90 0.9561, max 0.9966.** The frozen model barely separates
"Bladder cancer" from "Brain cancer" under the same stem.

That looks like the whole story and **it is not**. Of the 56 top-1 misses on
sibling-bearing rows, only **2** picked a sibling — the right question with the
wrong option. The other 54 landed in a different construct entirely. Across all
208 rows, the top-1 shares the gold's construct **56 times (26.9%)** against an
@1 of 26.0%: **the top-1 is in the wrong construct for 152 of 208 rows.**

**Arm E's dominant failure is finding the wrong question, not the wrong option
within the right question.** The high sibling cosine is a real property of the
embedding space that would bite a system relying on option-level discrimination;
it is not what is costing the measured @1 here.

### The margin a reranker must beat

`cos_top − cos_gold` on missed rows: **p50 0.0224**, p90 0.0574, max 0.0842.
Median gold cosine 0.6825, median top cosine 0.7007. The correct answer loses by
about two points of cosine — close enough that a reranker over the top 10 has
real headroom, and close enough that the ordering is fragile.

### Worst rows

| rank | gold | request |
|---|---|---|
| 304 | `m2:Q26.12` | primary method used to get to work |
| 258 | `m1:Q5.7` | household occupancy |
| 163 | `m2:Q26.12` | usual way of getting to work |
| 123 | `m2:Q19.48` | NSAID utilization frequency |
| 112 | `m2:8_Q16.8#1_1` | family cancer history malignancy |
| 111 | `m1:Q5.7` | household size |
| 90 | `m3:Q2.12` | domestic activity |
| 87 | `m2:1_Q18.17` | cancer year |

`m1:Q5.7` (household size) and `m2:Q26.12` (commute) are among the 18 rows the
lexical control could not reach at any rank either — **these are hard for both
retrieval families, which points at the requests, not the method.**

---

## 5. Cost

| | |
|---|---|
| target encoding | 157.6 s, once, 1,241 targets, CPU |
| query encoding | 24.8 ms/row |
| model download | 2 encoders, `ncbi/MedCPT-*` |
| marginal cost per row | ~0 |

Against arm D's **$4.74** for 221 rows. Arm E is effectively free per query once
the targets are encoded, and the target encoding is invalidated only by a build
hash change.

---

## 6. Provenance and scope

- **`targets.json` is byte-reproducible.** Re-running `build_targets.py` against
  `build/dictionary.json` produced an identical file: same `3dc8415eccfe`, same
  1,241 targets, same skip counts (43 identifier, 151 text capture). The script
  asserts the hash and exits 2 on a mismatch.
- **1,241 targets from 2,610 members.** Grouped on
  `(construct_key, subitem_text, matrix_col)`; 284 targets carry siblings.
- **Folded match rule**, as in arm D: a row is correct when the gold key's
  *target* is at rank k. Targets fold roster members, so this is more permissive
  than the row-level wording equality the lexical arms are scored under. The
  singleton rows (152) are the apples-to-apples subset.
- **Nothing under `env/` was touched.** The encoder runs at the repo root; the
  no-network invariant on `env/` is intact and `ENV_MODEL_GRANTS` was not
  extended.
- **`torch 2.14.0+cpu`, `transformers 5.16.1`, `numpy 2.5.2` are installed in
  the venv but not declared in `pyproject.toml`.** `AGENTS.md` records embedding
  arms as unreproducible here and **never an acceptance gate**; that second
  clause stands regardless of what is installed.
- **`build_targets.py` and `encode_and_score.py` are excluded from `ruff`,
  unmodified**, with the reason recorded in `pyproject.toml`. They contributed 26
  of 249 errors and would have raised `RUFF_CEILING` on code it is not about.

## 7. Known bias

The fixture's `KNOWN_BIAS`: its queries were written by a model that had seen
each gold item's wording. **Every figure here is an upper bound**, and the bias
plausibly favours a semantic method over a lexical one — paraphrase-of-gold is
precisely what an embedding model is good at. Arm E's margin over the lexical
arms is therefore the least trustworthy number in this document.

Settling it needs a request set written without sight of the instrument.

---

## 8. Would fine-tuning help? — assessment, not measurement

**Probably yes for the measured deficit, but not on this fixture, and not
first.** The reasoning:

**What fine-tuning would target.** The obvious candidate is the 0.92 sibling
cosine — contrastive training with in-construct hard negatives is the textbook
fix, and it would separate 22 cancer types under one stem. But §4 shows that
deficit is **not** what is costing the measured @1: only 2 of 56 sibling-row
misses picked a sibling, while 152 of 208 top-1s are in the wrong construct
entirely. Training the model to separate siblings would fix a failure that
barely occurs. The real gap is **query→construct alignment** — a short
researcher's phrase against a questionnaire sentence — which is a domain
adaptation problem, and fine-tuning does address it.

**Why not on this fixture.** The only labelled pairs available are the 224 rows
over **56 distinct gold items**, and their `KNOWN_BIAS` is that a model wrote
them while looking at the gold wording. Training on those and evaluating on those
is circular twice over: too few items to generalise, and the supervision encodes
the leak the benchmark already warns about. Any gain would be unfalsifiable here.

**What to do before fine-tuning, in order, each cheap and already runnable:**

1. **The other three model configs.** `medcpt-b` (stem/option order swapped),
   `biolord`, `bge-small` are already in `encode_and_score.py` — three commands,
   no new code. `option_first` vs `stem_first` is exactly the axis §4 says is
   binding, and it is untested.
2. **The hybrid.** Arm E supplies the pool (75% of rows carry gold by depth 10,
   p50 rank 3); arm D or a screening stage picks within it. Arm D commits on 60%
   of rows at 67.2% precision and abstains honestly on the rest. Neither arm
   alone beats that combination on paper, and it needs no training at all.
3. **A request set written without sight of the instrument.** Until that exists,
   no measured improvement on this fixture can be trusted — including a
   fine-tuned model's.

**If fine-tuning is still wanted after those**, the shape that would be
defensible: contrastive training on (request, target) pairs with in-construct
hard negatives, supervision authored by the study team rather than by a model
that saw the answers, and held-out constructs rather than held-out rows — because
holding out rows from 56 items leaks the item.

**And a governance note.** A fine-tuned checkpoint is a new artefact. Outside
`env/` it is unconstrained. If it were ever to run *inside* `env/`, `AGENTS.md`
requires a grant in `tests/test_specifier.py::ENV_MODEL_GRANTS` with all four
properties, reviewer-judged: vendored pinned weights, deterministic output,
inspectable text for the surface scan, and logged disagreement with the lexical
order. Only the user extends that list.
