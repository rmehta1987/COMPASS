# COMPASS — phrasing fusion, measured

**Model under test:** `bge-small` fine-tuned (`nn0, t=0.10`), the `deploy/` bundle,
build `3dc8415eccfe`. Fixture, gold rule, `stem_option_dup` and the dictionary build
([`build.py`](build.py), the dictionary builder since the 2026-09-03 merge) at `3dc8415eccfe` unchanged.
Companion to [`CHARACTERISATION.md`](CHARACTERISATION.md), which characterises the shipped retriever; this
document tests whether a phrasing ensemble improves it. The brief this answers is
recorded verbatim in [`BRIEF_ensemble.md`](BRIEF_ensemble.md), so the decision rules and expectations quoted
below can be checked against what was asked rather than a paraphrase of it.

Every number is read from a JSON artifact in `out/` written by a script in `src/`, cited
on the row. Every retrieval number is produced **through the shipped `deploy/` bundle**
with its checksum, dictionary-hash and row-order guards live, and every table is anchored
to a control that reproduces R@1 0.567 exactly.

---

## One-line answer

**Fusion does not deliver, and the *lexical* leakage caveat that qualified every number
in this project dissolves.** The best fusion rule's point estimate recovers **22.8%** of
the 25-point oracle gap, under the brief's own 25% floor — but on 56 effective items that
comparison cannot resolve either side of the threshold it is judged against, so the
finding is *no demonstrated effect*, not a measured shortfall. Task 4 was not built. A
real rewriter, run anyway because task 3's abstention comparison could not be made honest
without one, moves R@1 by **+4.0 points that a paired item-clustered test cannot
distinguish from zero** (95% CI **[−0.018, +0.098]**). Abstention survives fusion, but the
shipped threshold does not: under `max_cos` with rewritten negatives it drops from
rejecting 43/44 to **35/44**.

---

## Summary

| | headline | § | source |
|---|---|---|---|
| **1. Overlap** | **The lexical leakage caveat dissolves; a structural one is opened.** R@1 by query/gold overlap quartile is **0.482 / 0.554 / 0.643 / 0.589** — non-monotonic. Item-level correlation with k/4 is **−0.023 (perm p 0.87)**. Within every query-length stratum, overlap buys nothing. What *does* predict correctness is the absolute count of shared content words (**rho 0.186, perm p 0.005**) — query informativeness, not lexical copying. What the test *cannot* see: whether sight of the gold conferred structural knowledge of which framing to write. §4's rewriter loses to the fixture's phrasings 0.625 vs 0.563, and 4× on `residence_commute`, which is what that would look like. | §1 | `out/fusion_task1_overlap.json` (withdrawn from git 2026-09-03: quotes gold stems per row; sha256 `0808bb02944a39f6…`, [`PROVENANCE.md`](PROVENANCE.md)) |
| **2. Fusion** | **No demonstrated effect, underpowered.** Best deployable rule **0.625** (`max_cos`, tied by `min_rank`) against 0.567 shipped and 0.821 oracle — a point estimate of 22.8% of the gap, but [0.494, 0.740] overlaps the control's [0.441, 0.692] and spans the 25% floor it is tested against. **Decision: do not build the rewriter** — the burden was on fusion to show the gain. The 10 items at 0/4 are **not** rescued, exactly as §1a predicts. `residence_commute` moves 0.062 → 0.250, which *is* its oracle. | §2 | [`out/fusion_task2_rules.json`](out/fusion_task2_rules.json) |
| **2a. RRF** | **The brief's prediction was wrong.** RRF was expected to lose to the control. It gains: **0.589 vs 0.567**, third of five rules. Reported as a measured correction. | §2 | same |
| **3. Abstention** | **Separation survives; the threshold does not.** AUROC holds at 0.974–0.991. But with negatives rewritten too, `max_cos` at the shipped τ = 0.7295 rejects **35/44, not 43/44**. Re-deriving τ → 0.7737 restores 42/44 at the same recall. `mean_cos` does not inflate and keeps 43/44 at the **unchanged** τ. | §3 | [`out/fusion_task3_abstention.json`](out/fusion_task3_abstention.json) |
| **3a. The asymmetry, sized** | Four-phrasing positives against one-phrasing negatives overstates rejection at the same τ by **34 points** (86.4% vs 52.3%). The brief said to state this bias; it is measured instead. | §3 | same |
| **4. Real rewriter** | **Not built — measured as a by-product of §3.** Best rule `mean_cos` **0.6071** (+4.0), McNemar p 0.163, item-clustered 95% CI **[−0.018, +0.098]**. The rule ordering **inverts** against §2: `max_cos` is best on fixture phrasings and *worst* on generated ones. `residence_commute` **unchanged at 0.062**. | §4 | [`out/fusion_task4_rewriter.json`](out/fusion_task4_rewriter.json) |

### Premises in the brief that were wrong

Corrected in place, because in each case the task survived the correction.

1. **The "~31% content-word overlap" for failing queries does not reproduce** (§1). Under
   three stated definitions the failing rows average **0.510** (query-side coverage),
   **0.194** (Jaccard) or **0.221** (gold-side coverage); no definition tried lands on 31%.
   The cited 0% examples are real and verified (`NSAID utilization frequency` and
   `circadian sleep schedule` both measure exactly 0.000). But the average is wrong, and
   correcting it *strengthens* the brief's conclusion rather than weakening it: the failing
   rows do not have low overlap, they have **very nearly the same overlap as the succeeding
   rows** — 0.510 vs 0.571 query-side, 0.194 vs 0.232 Jaccard, 0.221 vs 0.272 gold-side.
   Overlap is not the axis the failures lie on.
2. **RRF was expected to lose and does not** (§2). It beats the single-query control by
   2.2 points.
3. **Task 2 is not a clean ceiling for task 4** (§4). It is a ceiling for `max_cos` and
   `min_rank`, and a *floor* for `mean_cos` — generated rewrites beat the fixture's
   phrasings there (0.6071 vs 0.5714), because the fixture phrasings were written under a
   "do not copy distinctive phrases" instruction and the rewrites were not.

---

## 0. What was run

| Script | Produces | Purpose |
|---|---|---|
| [`src/phrase_overlap.py`](src/phrase_overlap.py) | `out/fusion_task1_overlap.json` (withdrawn, see below) | Task 1. No model loaded; ranks are read from the committed `out/char_pos_bge-small_ft.json`. |
| [`src/fusion_eval.py`](src/fusion_eval.py) | [`out/fusion_task2_rules.json`](out/fusion_task2_rules.json) | Task 2. Loads `deploy/` with all guards on; refuses to continue unless the `single` control reproduces the committed artifact row for row. |
| [`src/gen_paraphrases.py`](src/gen_paraphrases.py) | [`out/rewrites_positives.json`](out/rewrites_positives.json), [`out/rewrites_negatives.json`](out/rewrites_negatives.json) | The inference-time rewriter. `claude-haiku-4-5` via `claude -p --allowed-tools ""` — no network, no tools — matching [`src/gen_training.py`](src/gen_training.py). One prompt, blind to which set a request came from. |
| [`src/fusion_abstain.py`](src/fusion_abstain.py) | [`out/fusion_task3_abstention.json`](out/fusion_task3_abstention.json) | Task 3, four configurations. |
| [`src/fusion_rewriter.py`](src/fusion_rewriter.py) | [`out/fusion_task4_rewriter.json`](out/fusion_task4_rewriter.json) | Task 4's measurement, with paired flip tests. |

Nothing existing was modified by this work (as of its date, 2026-09-03, before the CPU
port of the same day added `deploy/template.py`, `deploy/smoke_test.py` and new manifest
fields, commit e446cf8). `retrieval_queries.json`, `fixtures/negative_requests.json`, the
dictionary build and every `src/char_*.py` are untouched.

### The artifacts

Every figure in this document reads from one of these six. Five are tracked in the
repository, so their links resolve; each is the complete record for its task, not a summary
of one. The sixth, task 1's, was withdrawn from git on 2026-09-03 because it quotes the gold
stem of every row and the repository is public; its sha256 and size are in
[`PROVENANCE.md`](PROVENANCE.md) and its figures are all in §1.

| artifact | schema | size | what it holds |
|---|---|---|---|
| `out/fusion_task1_overlap.json` (withdrawn, training machine only) | `compass_phrase_overlap/1` | 254 KB | Per-row overlap under all four tokenisation × gold-text variants, the correlations with their permutation p-values, R@1 by fixed bin and by quartile, the length-confound control, and the 27 zero-overlap rows named. |
| [`out/fusion_task2_rules.json`](out/fusion_task2_rules.json) | `compass_phrasing_fusion/1` | 32 KB | Five fusion rules plus the oracle ceiling, the parity check against the shipped artifact, per-item fused ranks, the single→fused transition table, and per-stratum recall. |
| [`out/fusion_task3_abstention.json`](out/fusion_task3_abstention.json) | `compass_fusion_abstention/1` | 24 KB | Four configurations × two rules: score distributions, three AUROCs each, the re-derived threshold, behaviour at the shipped τ, and the hardest negatives per configuration. |
| [`out/fusion_task4_rewriter.json`](out/fusion_task4_rewriter.json) | `compass_rewriter_fusion/1` | 30 KB | Per-rule paired flip tables, exact McNemar and item-clustered bootstrap CIs, worked gained/lost examples with their rewrites, strata, and the latency measurements. |
| [`out/rewrites_positives.json`](out/rewrites_positives.json) | `compass_query_rewrites/1` | 57 KB | All 672 generated rewrites for the 224 positive requests, with the full prompt and its sha256. |
| [`out/rewrites_negatives.json`](out/rewrites_negatives.json) | `compass_query_rewrites/1` | 15 KB | The same for the 44 held-out negatives, from the same prompt. |

**A convention worth knowing when reading the links.** A file reference in a link is
tracked in git and resolves; a reference in plain code may or may not be tracked
([`PROVENANCE.md`](PROVENANCE.md) lists the training-machine ones). So [`src/char_report.py`](src/char_report.py),
[`deploy/manifest.json`](deploy/manifest.json) and five of the six artifacts above are
clickable, while `out/fusion_task1_overlap.json`, `out/char_pos_bge-small_ft.json`,
`retrieval_queries.json` and `fixtures/negative_requests.json` are not — `.gitignore`
excludes `out/`, `*.json` and `fixtures/` wholesale with named exceptions, and the artifacts
behind [`RESULTS.md`](RESULTS.md) and [`CHARACTERISATION.md`](CHARACTERISATION.md) were never
added ([`PROVENANCE.md`](PROVENANCE.md) lists them with checksums).
They exist in the working tree and every claim resting on them was re-verified here; they
are simply not retrievable from the remote. Two intermediates from this work are also
deliberately untracked: `out/fusion_sims_pos.pt` (a 224 × 1,353 cosine cache, a torch
pickle, regenerable via [`src/fusion_eval.py`](src/fusion_eval.py) `--save-sims`) and the `out/rw_shards_*` resume
shards, whose content is fully contained in the two `rewrites_*.json` files.

**Parity, asserted not claimed.** [`src/fusion_eval.py`](src/fusion_eval.py) re-encodes all 224 queries through
the bundle and compares against `out/char_pos_bge-small_ft.json`: R@1 **0.567**, **0 of
224 rows with a differing rank**, max |Δcos| **7.21e-07**. [`src/fusion_abstain.py`](src/fusion_abstain.py)
re-derives the threshold from scratch and gets τ = **0.729476**, 43/44 rejected, AUROC
**0.9823** — the shipped figures to the last digit, under the same batched encoding that
produced them (encoding queries one at a time moves τ* to 0.731902 on the Spark: the knife
edge in `CHARACTERISATION.md` §3 and `deploy/manifest.json::abstention.knife_edge`). If
either check fails the script
raises rather than reporting.

---

## 1. Task 1 — the overlap test

### Definition, stated before the numbers

Content words are lowercased `[a-z0-9]+` tokens of length ≥ 2 with a stoplist removed
(standard English, plus the instrument function words that appear in nearly every stem —
`please`, `describe`, `following`, `ever`, `other`, `often`, `times`). The stoplist is
committed in [`src/phrase_overlap.py::STOPWORDS`](src/phrase_overlap.py).

Three ratios per row, over the query's content words `Qc` and the gold's `Gc`:

| | | |
|---|---|---|
| **`cov_query`** | \|Qc ∩ Gc\| / \|Qc\| | **primary.** The leakage direction: a query that copied the gold scores high. |
| `cov_gold` | \|Qc ∩ Gc\| / \|Gc\| | always small — queries are 2–5 words, stems are sentences |
| `jaccard` | \|Qc ∩ Gc\| / \|Qc ∪ Gc\| | |

Two gold texts (the target's indexed `stem + option`, and the fixture row's own `text`
field) and two tokenisations (unstemmed, and a **light suffix normaliser — not Porter**,
committed as `light_stem`). All four combinations are in the artifact; they agree to
three decimals on every aggregate, so the conclusion does not rest on the stemmer.

### The distribution

| set | n | mean `cov_query` | p10 | p50 | p90 | rows at exactly 0 |
|---|---|---|---|---|---|---|
| all rows | 224 | **0.545** | 0.000 | 0.500 | 1.000 | 27 |
| correct top-1 | 127 | 0.571 | 0.250 | 0.500 | 1.000 | 10 |
| incorrect top-1 | 97 | **0.510** | 0.000 | 0.500 | 1.000 | 17 |
| rows of the 19 blind-spot items (0/4, 1/4) | 76 | 0.559 | 0.000 | 0.500 | 1.000 | 9 |

**The failing rows are not the low-overlap rows.** They average 0.510 against 0.571 for
the succeeding rows — a 6-point difference on a metric whose range is [0, 1]. The
blind-spot items, the ones §1a reads as failing because the query omits the
discriminator, average **0.559**, *above* the fixture mean.

### Does R@1 rise with overlap?

| `cov_query` quartile | range | mean | n | **R@1** | R@10 |
|---|---|---|---|---|---|
| Q1 | 0.00 – 0.33 | 0.141 | 56 | **0.482** | 0.857 |
| Q2 | 0.33 – 0.50 | 0.426 | 56 | **0.554** | 0.964 |
| Q3 | 0.50 – 0.75 | 0.633 | 56 | **0.643** | 0.964 |
| Q4 | 0.75 – 1.00 | 0.979 | 56 | **0.589** | 0.893 |

**Non-monotonic — it turns over at Q4.** And at item level, where the leakage question
actually lives, the correlation between an item's mean overlap and its k/4 score is
**Spearman −0.023, permutation p 0.867** (20,000 permutations; no scipy in this venv, and
n = 56 is too small for an asymptotic p anyway). Row-level: rho 0.090, p 0.173.

### The length confound, and what actually predicts correctness

`cov_query` is mechanically coupled to query length: a 1-content-word query can only
score 0.0 or 1.0. Queries here run 1–6 content words (median 3). So the Q1→Q3 rise could
be a length effect wearing a hat. Controlling for it:

| query length | n | R@1 | overlap = 0 | (0, 0.5] | (0.5, 1.0] |
|---|---|---|---|---|---|
| 1–2 words | 71 | 0.493 | 0.500 (n=12) | 0.485 (n=33) | 0.500 (n=26) |
| 3 words | 82 | 0.537 | 0.222 (n=9) | 0.516 (n=31) | 0.619 (n=42) |
| 4+ words | 71 | **0.676** | 0.333 (n=6) | 0.730 (n=37) | 0.679 (n=28) |

**Within every length stratum the overlap gradient is flat or reverses.** What separates
the rows is the row on the left: R@1 goes 0.493 → 0.537 → 0.676 with query length. And
the absolute count of shared content words — which rises with length rather than falling
with it — is the one lexical statistic that does correlate: **rho 0.186, permutation p
0.005**, against rho 0.090 (p 0.17) for the coverage ratio.

The only real effect in the coverage metric is a floor: the 27 rows with **zero** overlap
score R@1 0.370 against ~0.58–0.66 everywhere else. Having *no* word in common hurts.
Having *more* words in common, above zero, does nothing.

### Verdict, against the interpretation recorded before running

The pre-recorded rule was: *rises monotonically → leakage is real and the upper-bound
caveat stands; flat or non-monotonic → the caveat largely dissolves and 0.567 may be a
lower bound.*

**It is non-monotonic, and the item-level correlation is zero.** The caveat largely
dissolves. The fixture's queries do share about half their content words with the gold —
the generator did see the wording — but that sharing **buys them nothing**, so removing
it would not cost the model much either. A study-team request stream would differ from
this fixture mainly in being *longer and more specific*, and on this evidence that would
move R@1 **up**, not down.

Three things this does not license. The queries were written by the same generator family
as the 13,528 training pairs, and **register alignment is not measured here** — it is not
a lexical-overlap phenomenon and this test cannot see it. And the fixture still contains
zero rows for four strata (§4 of [`CHARACTERISATION.md`](CHARACTERISATION.md)). The request set is still worth
asking for; §7's framing of *why* changes, as the brief anticipated.

**And there is a second channel this test cannot reach, with evidence for it later in this
document.** Sight of the gold may confer *structural* knowledge rather than vocabulary —
which of several plausible framings of a construct to write down at all. §4 measures the
gap without being able to name it: the fixture's phrasings beat a real rewriter's on
`max_cos` (**0.625 vs 0.563**), and on `residence_commute` by four-fold — **0.250 against
0.062**, where fixture fusion lands exactly on that stratum's oracle while the rewriter
does not move it a single row. A rewriter has strictly more information about the *request*
than the fixture's writer had, and strictly less about the *target*; that it loses on
precisely the stratum of near-identical commute items is what a framing effect would look
like. Content-word overlap cannot see this, because the fixture's writer was instructed
not to copy words — only to know which question was meant. **So §1's conclusion is
narrower than "no leakage": lexical leakage is ruled out, and a structural advantage from
sight of the gold is neither ruled out nor measured.** It would inflate the fixture's
numbers without leaving a lexical trace, and the study-team request set is the only
instrument here that would detect it.

---

## 2. Task 2 — leave-one-out fusion

56 items × 4 phrasings. For each row: its own query plus the other three phrasings of the
same item, all four encoded and retrieved against the same 1,353 frozen vectors, fused,
scored on the unchanged 224-row denominator.

**Read the effective sample size first.** Every fused rule gives all four phrasings of an
item the *same* ranking, so the 224-row denominator is 56 items counted four times. R@1
on 224 rows equals the fraction of the 56 items retrieved, and the Wilson intervals below
are computed on **n = 56**, not 224.

| rule | R@1 | R@5 | R@10 | p50 | p90 | max | 95% CI (n=56) | **recovery of the oracle gap** |
|---|---|---|---|---|---|---|---|---|
| `single` (control) | **0.567** | 0.862 | 0.920 | 1 | 9 | 82 | [0.441, 0.692] | — |
| **`max_cos`** | **0.625** | 0.929 | 0.946 | 1 | 4 | 51 | [0.494, 0.740] | **22.8%** |
| **`min_rank`** | **0.625** | 0.929 | 0.946 | 1 | 5 | 59 | [0.494, 0.740] | **22.8%** |
| `rrf` | 0.589 | 0.929 | 0.964 | 1 | 4 | 51 | [0.459, 0.708] | 8.8% |
| `mean_cos` | 0.571 | 0.929 | **0.964** | 1 | 4 | 50 | [0.441, 0.692] | 1.7% |
| *oracle, best phrasing per item* | *0.821* | — | — | — | — | — | *[0.702, 0.900]* | *100%* |

### Decision

The rule recorded before running: *below ~0.63 (under ~25% of the gap) → fusion does not
exploit the disjointness and task 4 is not worth building; above ~0.70 → build it.*

**No demonstrated effect, and the experiment is underpowered. Task 4 is not built.**
`max_cos` [0.494, 0.740] overlaps `single` [0.441, 0.692] across most of its range, and
neither comes near the oracle's lower bound of 0.702: on 56 items this design cannot
resolve a 5.8-point difference in either direction. **22.8% is therefore not a measured
quantity** — it is a point estimate from a comparison whose interval spans both sides of
the 25% threshold it is being judged against. The decision rule is satisfied, but by an
absence of evidence rather than by evidence of absence, and the honest statement of the
result is that fusion has not been shown to exploit the disjointness on data this thin.
That is enough not to build on, since the burden was on fusion to demonstrate the gain;
it is not enough to conclude fusion cannot deliver one.

**RRF, the measured negative that wasn't.** The brief predicted RRF below the control,
because corroboration voting should let three phrasings outvote the one that found the
item. It lands **above** it — 0.589 vs 0.567. The mechanism C16 measured is real, but
here it is outweighed. Recorded as a correction, not defended.

**The one thing fusion clearly does buy is the top-10 list.** R@5 goes 0.862 → 0.929 for
*every* fused rule, and `mean_cos`/`rrf` take R@10 to 0.964 from 0.920. Rank p90 drops
from 9 to 4. §1a's conclusion is that a top-10 list, not an argmax, is the interface this
model supports; fusion improves that interface materially even though it barely moves
argmax. That is the one result here worth keeping.

### Did mass move to 4/4, or did partial items become differently partial?

Neither — the question's premise does not survive the mechanics. Under any fused rule an
item's four rows share one ranking, so its k/4 can only be **0 or 4**: the histogram is
degenerate by construction. The informative version is which single-query bucket gets
rescued (`max_cos`):

| single-query k/4 | items | now correct | now rank ≤ 10 | fused rank p50 |
|---|---|---|---|---|
| **0 / 4** | 10 | **0** | 7 | 4 |
| 1 / 4 | 9 | 6 | 9 | 1 |
| 2 / 4 | 7 | 3 | 7 | 2 |
| 3 / 4 | 16 | 12 | 16 | 1 |
| 4 / 4 | 14 | 14 | 14 | 1 |

Mass moved, but sideways as much as up: 4 of the 16 items at 3/4 and 4 of the 7 at 2/4
are *lost*. Net +5.8 points at rank 1, and a large gain in the top 10.

### The 10 items at 0/4 — unchanged, as predicted

**None is rescued.** §1a's claim that no rewrite invents a discriminator the request never
contained holds exactly. Four reach rank 2 and stop there:

| gold key | single-query ranks | `max_cos` |
|---|---|---|
| `m3:Q15.9_4_TEXT` | 2, 2, 2, 2 | **2** |
| `m3:Q3.12_2` | 4, 2, 3, 2 | **2** |
| `m2:Q26.12` | 2, 61, 2, 56 | **2** |
| `m3:Q2.16` | 28, 8, 7, 2 | **2** |
| `m3:Q1.4_2` | 3, 3, 3, 3 | 3 |
| `m2:Q9.91` | 4, 5, 9, 3 | 4 |
| `m3:Q5.14` | 7, 6, 29, 2 | 8 |
| `m2:Q776` | 10, 13, 14, 9 | 11 |
| `m3:Q870_2` | 9, 13, 10, 61 | 15 |
| `m2:8_Q16.8#1_1` | 82, 36, 38, 59 | 51 |

`m3:Q15.9_4_TEXT` at rank 2 on all four phrasings and `m3:Q1.4_2` at rank 3 on all four
are the clearest cases: a discriminator absent from every phrasing — "Other (describe)"
versus its parent question, the City subfield versus the standalone city question. Fusion
cannot break a tie that every input agrees on. No ensemble over the query side can supply
information no query contains.

### `residence_commute` — the stratum the brief singled out

| | R@1 | R@10 |
|---|---|---|
| single | **0.062** (1/16) | 0.688 |
| `max_cos` fusion | **0.250** (4/16) | 0.750 |
| oracle | **0.250** | — |

Fusion **saturates this stratum's ceiling exactly** — 0.250 is both what `max_cos`
achieves and the best any phrasing achieves anywhere. Twelve of sixteen rows are still
wrong at rank 1 and four are still outside the top 10. The commute block is not a
phrasing problem, and the commute-exposure line of inquiry does not get a working
retriever out of this.

Two strata **regress**: `cancer_history` 0.613 → 0.550 and `reproductive_hormonal` 0.750
→ 0.500 (n=8). Fusion is not a uniform improvement.

---

## 3. Task 3 — what fusion does to abstention

**Blocking for deployment, and the reason is asymmetric:** [`CHARACTERISATION.md`](CHARACTERISATION.md) §3
establishes that the model detects *absence* at AUROC 0.982 and cannot detect its own
*error* at all (0.640, precision 0.90 unreachable at any τ). Absence detection is the only
reliable guard the tool has, so trading it for R@1 is a bad trade at almost any exchange
rate.

The negatives have one phrasing each. The brief offered a choice: generate paraphrases,
or state plainly that four-draw positives against one-draw negatives is optimistic. **Both
were done** — the asymmetric configuration is reported precisely so the size of the bias
is a number rather than a caveat.

| | positives | negatives | what it is |
|---|---|---|---|
| **A** | own query | own query | must reproduce §3 |
| **B** | 4 fixture phrasings | 1 query | the asymmetric one. Optimistic *by construction* |
| **C** | 4 fixture phrasings | query + 3 rewrites | draw counts match; sources still do not |
| **D** | query + 3 rewrites | query + 3 rewrites | **symmetric and deployable** |

Rewrites come from one prompt applied to both sets with no signal about which set a
request belongs to (`out/rewrites_*.json`). Thresholds are selected on the **224 positives
only** — candidate τ values are drawn from the positive scores alone, so the negatives
cannot influence the choice even through the grid. This is stricter than
[`src/char_report.py`](src/char_report.py), whose grid was the union, and it still reproduces τ = 0.729476.

### The numbers

| config | rule | pos R@1 | neg p50 | neg p90 | neg max | **AUROC** | re-derived τ* | rej @ τ* | recall @ τ* | **rej @ shipped τ** |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** | — | 0.567 | 0.596 | 0.691 | 0.772 | **0.9823** | 0.7295 | **43/44** | 0.558 | **43/44** |
| B | `max_cos` | 0.625 | 0.596 | 0.691 | 0.772 | *0.9976* | 0.6788 | *38/44* | 0.625 | *43/44* |
| C | `max_cos` | 0.625 | **0.678** | 0.759 | **0.843** | 0.9907 | 0.6788 | **23/44** | 0.625 | **35/44** |
| C | `mean_cos` | 0.571 | 0.611 | 0.669 | 0.762 | 0.9821 | 0.7466 | 43/44 | 0.554 | 43/44 |
| **D** | `max_cos` | 0.563 | **0.678** | 0.759 | **0.843** | 0.9847 | **0.7737** | **42/44** | 0.558 | **35/44** |
| **D** | `mean_cos` | **0.607** | 0.611 | 0.669 | 0.762 | 0.9743 | 0.6557 | 35/44 | 0.607 | **43/44** |

*Row A reproduces §3 exactly: τ 0.729476, 43/44, AUROC 0.9823, R@1 0.567.*

### Three findings

**1. The separation survives. The threshold does not.** AUROC never falls below 0.974, and
0 of 44 negatives ever score above the positive median in any configuration. Fusion does
not collapse absence detection — the brief's disqualifying scenario does not occur. But
under `max_cos`, rewriting the negatives raises their p50 from 0.596 to 0.678 and their
max from 0.772 to **0.843**, and the shipped τ = 0.7295 falls from rejecting 43/44 to
**35/44**. **Nine absent-construct requests get answered instead of refused.** Re-deriving
τ on positives only gives 0.7737 and restores 42/44 at recall 0.558 — the shipped recall.
So the mechanism is recoverable, at the cost of a threshold that must be re-derived every
time the rewriter prompt changes.

**2. The asymmetry is worth 34 points, measured.** Config B — four draws for positives,
one for negatives — reports AUROC 0.9976 and τ* = 0.6788 rejecting **86.4%** of negatives.
Config C is the same positives at the same τ* with the negatives given the same four
draws: **52.3%**. Anyone who evaluates a query-expansion scheme against un-expanded
negatives will overstate its abstention by roughly that much.

**3. `mean_cos` does not inflate, and that turns out to matter more than R@1.** Averaging
four cosines cannot exceed the best of them, so the negative distribution barely moves
(max 0.772 → 0.762, *down*). At the **unchanged shipped threshold**, config D / `mean_cos`
gives coverage 0.915, precision **0.634**, recall **0.580**, negatives rejected **43/44** —
better than the shipped operating point on precision and recall at identical rejection,
with no threshold change. Its AUROC is 0.974 against 0.982, the one thing it gives up.
**This is the most attractive-looking number in this document and it is not independent
evidence** — the precision gain is computed over the same flips as §4's R@1, whose 95% CI
straddles zero, and it inherits a non-determinism the latency table does not price. Both
caveats are set out under recommendation 2 in §6; quote the number with them attached.

Precision 0.90 remains **unreachable at any τ in every configuration**. Fusion does not
make a returned result verifiable, and §3's finding that the model cannot flag its own
errors is untouched: AUROC correct-vs-incorrect is 0.44–0.74 across configurations, moving
around without trend.

The hardest negatives shift as rewriting makes them more concrete — `which census area
their address falls in` goes 0.693 → **0.843** on the back of rewrites naming the census
tract and block group explicitly, overtaking the green-space row that topped
[`CHARACTERISATION.md`](CHARACTERISATION.md) §2's hardest-negatives table.

---

## 4. Task 4 — measured, not built

**Status.** Task 2 failed its decision rule, so no rewriter was built as a deployable
component: `deploy/` was unmodified by this work, its threshold is unchanged, and its
guards still pass 4/4 (the same-day CPU port, commit e446cf8, later added files to `deploy/`
without touching the threshold). The numbers below exist because **task 3 could not be answered honestly without a
rewriter** — a symmetric abstention comparison requires running one over the negatives,
and making it symmetric requires running the same prompt over the positives. The R@1
figures fall out of the same encodings.

**Prompt design.** The brief asked for paraphrases moving toward the instrument's register
— naming the drug, the timeframe, the AM/PM field — on the §1a rationale that failures
come from queries lacking the discriminator. §1 above says the mechanism is not lexical
alignment with the gold but **query informativeness**. Same prescription, corrected
rationale: the prompt asks for concrete instances, explicit timeframes and plain-question
wording, i.e. longer and more specific restatements, and forbids inventing facts about
what the survey contains. Committed with its sha256 in [`out/rewrites_positives.json`](out/rewrites_positives.json).

| rule | R@1 | R@5 | R@10 | Δ R@1 | gained | lost | McNemar p | **item-clustered 95% CI on Δ** | §2 same rule |
|---|---|---|---|---|---|---|---|---|---|
| `single` | 0.567 | 0.862 | 0.920 | — | — | — | — | — | 0.567 |
| **`mean_cos`** | **0.607** | 0.862 | 0.911 | **+0.040** | 21 | 12 | 0.163 | **[−0.018, +0.098]** | 0.571 |
| `rrf` | 0.603 | 0.866 | 0.906 | +0.036 | 16 | 8 | 0.152 | [−0.009, +0.080] | 0.589 |
| `min_rank` | 0.571 | 0.875 | 0.911 | +0.004 | 14 | 13 | 1.000 | [−0.045, +0.054] | 0.625 |
| `max_cos` | 0.563 | 0.875 | 0.924 | −0.005 | 14 | 15 | 1.000 | [−0.063, +0.049] | 0.625 |

The bootstrap resamples **items, not rows** — outcomes cluster hard by item (§1 of
[`CHARACTERISATION.md`](CHARACTERISATION.md): +8.0 excess at 0/4, +8.2 at 4/4 against a binomial reference), so a
row-level interval would treat four correlated rows as four independent draws and be too
narrow. McNemar has the same flaw and is shown only for comparison.

**The best result is +4.0 points with a confidence interval that contains zero.** 21 rows
gained, 12 lost. This is not a demonstrated improvement.

**The rule ordering inverts, and the reason is instructive.** `max_cos` won §2 and is
*worst* here; `mean_cos` was second-worst in §2 and wins here. The inputs differ in kind.
The fixture's four phrasings were each written independently from the gold wording under a
"do not copy distinctive phrases" instruction — four roughly equally-good independent
probes, where taking the maximum is safe. A rewriter's three outputs are derived from the
query and some are simply wrong; `max_cos` then promotes whatever spurious target a bad
rewrite scored highest on, while averaging suppresses it. **So §2 is not a clean ceiling
for §4 rule-by-rule** — it bounds `max_cos` and `min_rank`, and `mean_cos` beats its §2
figure (0.607 vs 0.571).

What it gains and loses, concretely. Gained: *"mind-body exercise"* (rank 3 → 1) once
rewritten as *"mind-body exercise such as yoga, tai chi, or pilates"* — the instrument
enumerates exactly those. Lost: *"sibling prostate cancer"* (rank 1 → 2), whose rewrites
expanded "sibling" to *"your brother or sister"*, which is the sibling-roster block's own
wording and pulls the query toward the wrong member of it.

`residence_commute` is **0.0625 under the rewriter — unchanged from shipped**, with R@10
also unchanged at 0.688, against 0.250 / 0.750 under §2's fixture-phrasing fusion. The one
stratum a top-10 list does not rescue is not helped by a real rewriter at all.

### Cost

| | |
|---|---|
| LLM calls per request | **1** |
| measured latency, unbatched | **33.8 s** mean (median 30.0, range 22.9–50.7, n=5) |
| what that number is | `claude -p` CLI session overhead, **not** API latency. A direct API call is ~1 s, as the brief estimates. |
| retriever alone | 2.94 ms/row **batched** (the brief's figure); isolated per-call latency is 18.3 ms on the Spark at 20 threads, 13.4 ms median on the serving machine ([`PROVENANCE.md`](PROVENANCE.md)) |
| encode, 4 draws vs 1 | 11.8 ms vs 2.94 ms batched, i.e. 4× the retriever's cost either way — **negligible** against the 1 s API call, as predicted; against the isolated 13–18 ms per call the same 4× ratio holds |

The LLM dominates by two to four orders of magnitude depending on the route. More
important than the latency: it ends the properties that made argmax attractive — zero
marginal cost per query, no network dependency, no external failure mode, and a
deterministic answer. A rewriter makes the retriever's output **non-reproducible across
runs**, which for a research tool whose value is an auditable variable choice is a real
cost, not a rounding error.

**And the non-determinism reaches further than the ranking.** Because the abstention
threshold is applied to the *fused* score, a rewriter makes the **refusal** non-
deterministic too: a request sitting near τ can be answered on one run and refused on the
next, from identical input against identical frozen vectors. That is the worse of the two
failures, and it is not visible anywhere in this table. See recommendation 2 in §6.

---

## 5. What this does not do

**It does not fix autonomous operation**, and the brief's arithmetic holds. A hypothesis
needs an exposure and an outcome, so pair-correctness is R@1². At the best measured
figure, 0.607² = **0.369** against today's 0.321 — still roughly two hypotheses in three
resting on at least one wrong variable, and §3 says the model cannot flag which. Even the
0.821 oracle gives 0.674.

**It does not touch the four unmeasured strata.** SES/employment, insurance/access,
cancer-screening and demographics still have **zero** fixture rows — 61 targets and 51
constructs. No fusion rule measured on this fixture says anything about them.

**It does not replace the study-team request set** — but §1 changes what to ask for, and
narrows what the set is needed to settle. Not "queries written without sight of the
instrument" as a purity exercise: the *lexical* half of that variable is now measured and
does not predict accuracy. Two sharper questions remain, and both are cheaper to answer
than the original framing.

1. **Is a real researcher's request longer and more specific than this fixture's 2–5 word
   lookup labels?** If it is, §1's length gradient (R@1 0.493 → 0.537 → 0.676 by query
   length) says 0.567 is a **lower** bound.
2. **Does sight of the gold confer structural knowledge — which framing of a construct to
   write down — rather than vocabulary?** §1 cannot see this, and §4 shows the gap it would
   produce: the fixture's phrasings beat a real rewriter's on `max_cos` (0.625 vs 0.563)
   and four-fold on `residence_commute`. A request set written blind is the only instrument
   here that separates the two.

**Two caveats on §1 that the test cannot reach**, and they compound. The fixture's queries
and the 13,528 training pairs came from the same generator family, so **register
alignment** between fixture and training set is untested — it is not a query-to-gold
overlap phenomenon and is invisible to this measurement. And the **structural channel**
above is likewise invisible, because the fixture's writer was instructed not to copy words,
only to know which question was meant. §1 rules out lexical leakage from the gold and
nothing else; neither of these would leave a lexical trace, and both would inflate the
fixture's numbers in the same direction.

---

## 6. Recommendations

1. **Ship nothing from this work.** `deploy/` stays as it is. The best measured gain is
   inside its own confidence interval.
2. **If a future request set makes fusion worth revisiting, use `mean_cos`, not
   `max_cos`.** It is the only rule that improves the shipped operating point without a
   threshold change (§3), and the only one whose ranking is robust to a rewriter producing
   a bad paraphrase. `max_cos`'s advantage in §2 is an artifact of the fixture's phrasings
   being independently gold-derived, which no rewriter reproduces.

   **The operating point in full, since it is easy to miss in §3's table and should not be
   rediscovered later as a missed opportunity.** Config D / `mean_cos`, at the **unchanged**
   shipped τ = 0.7295:

   | | shipped (single) | D / `mean_cos` | |
   |---|---|---|---|
   | precision | 0.6039 | **0.6341** | **+3.0 pts** |
   | recall | 0.5580 | **0.5804** | +2.2 pts |
   | coverage | 0.9241 | 0.9152 | −0.9 pts |
   | negatives rejected | 43/44 | **43/44** | unchanged |
   | AUROC pos vs neg | 0.9823 | 0.9743 | −0.008 |

   Three points of precision for nine-tenths of a point of coverage, at identical negative
   rejection and no threshold change, with AUROC the only other cost. That is the most
   attractive-looking result in this document, which is why it needs both caveats attached
   wherever it is quoted.

   **It is not independent evidence.** Precision is `correct_answered / answered`, so it is
   computed over the same flips as §4's R@1 — the same 21-gained/12-lost table seen through
   a coverage filter (130 correct of 205 answered, against 125 of 207). The +0.040 R@1 those
   flips produce has an item-clustered 95% CI of **[−0.018, +0.098]**. The precision gain
   inherits that interval; it restates §4's uncertainty in a second unit rather than
   corroborating it, and two views of one underpowered comparison are not two results.

   **And it carries a cost §4's latency table does not name.** A non-deterministic rewriter
   makes the **abstention decision** non-deterministic, not merely the ranking. A request
   whose fused score sits near τ can be answered on one run and refused on the next, from
   the same input against the same frozen vectors. For a tool whose value is an *auditable*
   variable choice, an unreproducible refusal is a worse failure than a variable R@1: a
   wrong-but-stable answer can be checked and corrected once, while a request that
   intermittently returns nothing cannot be investigated from its output. `mean_cos` is
   exposed to this exactly as `max_cos` is — averaging stabilises the *ranking* against one
   bad paraphrase, and does nothing about run-to-run variation in the rewriter itself. Any
   deployment would need the rewriter's output cached and versioned per request, at which
   point the cache, not the threshold, becomes the artifact that has to be frozen.
3. **Never evaluate query expansion against un-expanded negatives.** §3 sizes that error at
   34 points of apparent rejection rate. If the 44-row negative set is ever used to
   validate an expansion scheme, it must be expanded by the same prompt.
4. **Two documents should be updated to reflect §1** — *done, 2026-09-03, commit e446cf8
   and the merge that followed*: [`CHARACTERISATION.md`](CHARACTERISATION.md) §7 now carries
   the §1 result, and [`deploy/manifest.json`](deploy/manifest.json)`::known_limitations[0]`
   keeps the register-alignment half and states that the gold-wording-leakage half was
   measured and does not survive. The manifest change was made through
   [`src/freeze_deploy.py`](src/freeze_deploy.py), re-run, guards 4/4.

---

## 7. Constraints observed

| constraint | status |
|---|---|
| No retraining, re-tuning or checkpoint modification | **Held.** No script under `runs/` or [`src/train.py`](src/train.py) was run. |
| `deploy/` guards keep passing all 4 tamper tests | **Re-run: 4/4 pass** — untampered bundle scores R@1 0.567; stale hash, modified file and permuted row order each raise. |
| Negatives never used to select a threshold | **Held, and tightened.** Candidate τ values are drawn from the positives alone (§3), stricter than [`src/char_report.py`](src/char_report.py)'s union grid. |
| 224-row fixture, gold rule, `stem_option_dup`, the dictionary build at `3dc8415eccfe` unchanged | **Held.** No existing file modified; all five new scripts are additive. |
| Load dtype pinned to fp32 | **Held.** Every fusion run goes through [`deploy/retriever.py`](deploy/retriever.py), which loads with `dtype=torch.float32` explicitly (the manifest records it as `float32`); the two fallback re-runs go through [`src/compass_score.py`](src/compass_score.py), which forces the same. Cosine algebra is done in fp64. |
| Frozen `bge-small` (0.375) and `mxbai-l1` (0.469) stay runnable | **Both re-run on CPU, both reproduce.** `bge-small` R@1 **0.375** (@5 0.750, @10 0.866, singleton 0.399, folded 0.304, near-dup 0.434, 140 top-1 errors, within-construct cos p50 0.9099). `mxbai-l1` R@1 **0.469** (@5 0.808, @10 0.915) — the `overall`, `singleton`, `folded_family`, `near_duplicate`, `errors` and `within_construct_cosine` blocks are **byte-identical** to `out/recheck_frozen_mxbai-l1.json`. |
| Every number traceable to a committed JSON artifact | **Held at the time; one artifact since withdrawn.** Six artifacts, cited per section, were tracked in git (`git add -f` past the `out/` and `*.json` ignore rules, 420 KB total). On 2026-09-03 `out/fusion_task1_overlap.json` was withdrawn because it quotes gold stems per row and the repository is public; its checksum is in [`PROVENANCE.md`](PROVENANCE.md) and every §1 figure is stated in this document. Five remain tracked. |

---

*Generated 2026-09-03 from `out/fusion_task1_overlap.json` (withdrawn from git), [`out/fusion_task2_rules.json`](out/fusion_task2_rules.json),
[`out/fusion_task3_abstention.json`](out/fusion_task3_abstention.json), [`out/fusion_task4_rewriter.json`](out/fusion_task4_rewriter.json),
[`out/rewrites_positives.json`](out/rewrites_positives.json) and [`out/rewrites_negatives.json`](out/rewrites_negatives.json).*
