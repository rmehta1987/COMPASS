# Arm E — four encoder configurations compared

**Measured 2026-09-02.** Build `3dc8415eccfe`, frozen weights, no training, CPU.
Targets `targets.json` (1,241, byte-reproducible from the build). Fixture
`benchmark/fixtures/retrieval_queries.json`, 224 rows, unchanged.

Notation: **E<sub>config</sub>** names the arm and the encoder it ran under.

| subscript | query encoder | document encoder | order | pooling | query prefix |
|---|---|---|---|---|---|
| E<sub>medcpt-a</sub> | `ncbi/MedCPT-Query-Encoder` | `ncbi/MedCPT-Article-Encoder` | `option_first` | CLS | — |
| E<sub>medcpt-b</sub> | `ncbi/MedCPT-Query-Encoder` | `ncbi/MedCPT-Article-Encoder` | `stem_first` | CLS | — |
| E<sub>biolord</sub> | `FremyCompany/BioLORD-2023` | same (symmetric) | `stem_first` | mean | — |
| E<sub>bge-small</sub> | `BAAI/bge-small-en-v1.5` | same (symmetric) | `stem_first` | CLS | `Represent this sentence for searching relevant passages: ` |

MedCPT is asymmetric — a separate query and article encoder, with the target
rendered as a (title, abstract) pair. `option_first` puts the option in the title
slot and the stem in the abstract slot; `stem_first` is the reverse. BioLORD and
BGE are symmetric: stem and option are concatenated into one string.

Artifacts: `arm_e.medcpt_a.json`, `arm_e.medcpt_b.json`, `arm_e.biolord.json`,
`arm_e.bge_small.json`.

---

## Verdict

**E<sub>bge-small</sub> wins on every measure, and it is the only
general-purpose model of the four.** Both biomedical specialists lose to a 33M
sentence-embedding model trained on no medical corpus in particular — while
running 4× faster to encode and 4× faster to query.

---

## 1. The comparison

Over the script's 208 scored rows (16 of the fixture's 224 have no reachable
target — see §4):

| config | order | @1 | @5 | @10 | @25 | @50 | p50 | p90 | max | encode | query |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E<sub>medcpt-a</sub> | option_first | 0.260 | 0.673 | 0.808 | 0.894 | 0.923 | 3 | 26 | 304 | 157.6 s | 24.8 ms |
| E<sub>medcpt-b</sub> | stem_first | 0.250 | 0.726 | 0.827 | 0.913 | 0.957 | 3 | 23 | 348 | 134.0 s | 27.6 ms |
| E<sub>biolord</sub> | stem_first | 0.365 | 0.745 | 0.846 | 0.918 | 0.957 | 2 | 22 | 471 | 156.6 s | 13.6 ms |
| **E<sub>bge-small</sub>** | stem_first | **0.380** | **0.774** | **0.870** | **0.938** | **0.962** | **2** | **14** | **191** | **40.2 s** | **6.2 ms** |

Over all 224 rows, counting the 16 unreachable as misses — the figure comparable
to every other arm:

| config | @1 | @5 | @10 |
|---|---|---|---|
| E<sub>medcpt-a</sub> | 0.241 | 0.625 | 0.750 |
| E<sub>medcpt-b</sub> | 0.232 | 0.674 | 0.768 |
| E<sub>biolord</sub> | 0.339 | 0.692 | 0.786 |
| **E<sub>bge-small</sub>** | **0.353** | **0.719** | **0.808** |

### Against the other arms

| arm | @1 | @5 | @10 |
|---|---|---|---|
| control (lexical) | 0.152 | 0.415 | 0.536 |
| min_rank (C16) | 0.152 | 0.438 | 0.549 |
| rrf (C16) | 0.192 | 0.469 | 0.567 |
| arm D (in-context selection) | 0.402 exact match | — | — |
| **E<sub>bge-small</sub>, /224** | **0.353** | **0.719** | **0.808** |

E<sub>bge-small</sub> is **+0.241 at @10 over rrf**, the best lexical arm, and
its @1 (0.353) is within 0.05 of arm D's exact-match rate at roughly 1/1000 the
per-query cost.

---

## 2. What the order swap did, and what it did not

`option_first` → `stem_first` on the same MedCPT weights:

| | E<sub>medcpt-a</sub> | E<sub>medcpt-b</sub> |
|---|---|---|
| @1 | 0.260 | 0.250 |
| @5 | 0.673 | **0.726** |
| @10 | 0.808 | **0.827** |
| @50 | 0.923 | **0.957** |
| sibling cosine p50 | 0.9224 | **0.9692** |
| near-duplicate @1 | 0.176 | **0.074** |
| folded-family @1 | 0.018 | **0.000** |

**The swap trades option discrimination for construct recall, and the trade is
visible in both directions.** Putting the stem in the title slot makes the whole
construct easier to find (@5 +0.053, @50 +0.034) and makes options within it
almost indistinguishable — sibling cosine rises to 0.969, near-duplicate @1 falls
by more than half, and folded-family @1 reaches **zero**: not one of 56 rows
ranked first.

This is the axis the single-config report predicted would be binding, and it is.
Neither MedCPT setting is good at both.

---

## 3. Where the winner wins

### By fold size (@1 / @10)

| config | singleton, n=152 | folded family, n=56 |
|---|---|---|
| E<sub>medcpt-a</sub> | 0.349 / 0.836 | 0.018 / 0.732 |
| E<sub>medcpt-b</sub> | 0.342 / 0.849 | 0.000 / 0.768 |
| E<sub>biolord</sub> | **0.447** / 0.875 | 0.143 / 0.768 |
| E<sub>bge-small</sub> | 0.408 / **0.875** | **0.304** / **0.857** |

E<sub>biolord</sub> is the best on singleton rows. **E<sub>bge-small</sub> wins
overall because it is the only config that does not collapse on folded families**
— 0.304 at @1 against 0.000–0.143 for the rest, a 17× improvement over
E<sub>medcpt-a</sub> on the hardest 56 rows.

### Near-duplicates and sibling separation

| config | sibling cos p50 | p90 | near-dup @1 | near-dup @10 |
|---|---|---|---|---|
| E<sub>medcpt-a</sub> | 0.9224 | 0.9561 | 0.176 | 0.721 |
| E<sub>medcpt-b</sub> | 0.9692 | 0.9843 | 0.074 | 0.794 |
| E<sub>biolord</sub> | **0.6766** | **0.8132** | 0.309 | 0.868 |
| E<sub>bge-small</sub> | 0.9051 | 0.9553 | **0.426** | **0.926** |

**Sibling cosine does not predict near-duplicate accuracy.** E<sub>biolord</sub>
separates sibling options far better than anything else in the embedding space
(p50 0.677 against 0.905–0.969) and still loses the near-duplicate rows to
E<sub>bge-small</sub>, which has a cosine spread barely different from
E<sub>medcpt-a</sub>'s. A low sibling cosine is neither necessary nor sufficient;
what matters is whether the *query* lands nearer the right option than the wrong
one, and absolute separation between documents does not measure that.

This retires the intuition that in-construct hard-negative training is the
obvious lever. The config with the best sibling separation is not the config that
gets near-duplicates right.

### Right construct, wrong option

Top-1 sharing the gold's construct, of 208:

| config | right construct | of which wrong option |
|---|---|---|
| E<sub>medcpt-a</sub> | 56 (26.9%) | 2 |
| E<sub>medcpt-b</sub> | 56 (26.9%) | 4 |
| E<sub>biolord</sub> | 79 (38.0%) | 3 |
| E<sub>bge-small</sub> | **90 (43.3%)** | 11 |

Across all four, **the dominant top-1 failure is landing in the wrong construct**
— 57–73% of rows — not choosing the wrong option within the right one (2–11
rows). The improvement from E<sub>medcpt-a</sub> to E<sub>bge-small</sub> is
almost entirely construct-finding: 56 → 90 right constructs. Option confusion
rises slightly (2 → 11) precisely because more rows reach the right construct at
all.

---

## 4. The 16 unreachable rows

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

This is a property of the candidate set, not of any encoder.

---

## 5. Ensembling — measured, and it is the largest number here

Best rank across the four configs, per row:

| k | ANY config gets it | ALL four get it |
|---|---|---|
| @1 | **117/208 (56.2%)** | 25/208 (12.0%) |
| @5 | **192/208 (92.3%)** | 105/208 (50.5%) |
| @10 | **197/208 (94.7%)** | 140/208 (67.3%) |

**An oracle over four frozen encoders reaches 56.2% at rank 1 — more than any
single config (38.0%) and more than arm D's exact-match rate (40.2%).** All four
agree on only 12% of rows at @1, so they are failing on largely disjoint sets.

This is an upper bound, not a method: nothing here picks the right config per
row. But a spread that wide is what fusion exists for, and RRF over four
embedding rankings needs no training and no new dependency beyond what is now
installed. It is the cheapest untested improvement on the board.

---

## 6. Cost

| config | target encode (1,241) | query | relative |
|---|---|---|---|
| E<sub>medcpt-a</sub> | 157.6 s | 24.8 ms/row | 2 encoders, CLS |
| E<sub>medcpt-b</sub> | 134.0 s | 27.6 ms/row | 2 encoders, CLS |
| E<sub>biolord</sub> | 156.6 s | 13.6 ms/row | 1 encoder, mean pool |
| **E<sub>bge-small</sub>** | **40.2 s** | **6.2 ms/row** | 1 encoder, 33M params |

All CPU. Target encoding is once per build hash; query cost is the marginal cost
per request. Against arm D's **$4.74** for 221 rows, every config here is free at
the margin, and the winner is also the cheapest to run by 4×.

---

## 7. What this does not settle

- **The fixture's `KNOWN_BIAS` applies to every row above**: its queries were
  written by a model that had seen each gold item's wording. That flatters
  semantic retrieval over lexical, so **arm E's margin over the lexical arms is
  the least trustworthy figure in this document.** It says little about the
  relative ordering *within* arm E, where all four configs face the same bias.
- **The match rule is folded**, as in arm D: a row is correct when the gold key's
  *target* is at rank k, and targets fold roster members. More permissive than
  the row-level wording equality the lexical arms are scored under. The 152
  singleton rows are the apples-to-apples subset.
- **A general-purpose model beating two biomedical specialists on a biomedical
  instrument is a result worth distrusting until it is reproduced on a request
  set written without sight of the instrument.** One plausible explanation is
  that the requests are researcher shorthand rather than clinical prose, and BGE
  was trained on exactly that register; another is that the bias above rewards
  paraphrase matching, which a general retrieval model is tuned for. Neither is
  established here.
- Nothing under `env/` was touched; `ENV_MODEL_GRANTS` was not extended.
  `torch 2.14.0+cpu`, `transformers 5.16.1` and `numpy 2.5.2` are installed in
  the venv and declared in no manifest. Per `AGENTS.md` these arms are **never an
  acceptance gate**.

## 8. What to run next

1. **RRF over the four rankings.** §5 measures a 56.2% @1 oracle against a 38.0%
   best single config. Pure Python over four rank lists, no training.
2. **E<sub>bge-small</sub> → arm D as the selector.** The pool carries gold for
   87% of scored rows by depth 10 at p50 rank 2; arm D commits on 60% of rows at
   67.2% precision. This is the hybrid the arm D report pointed at, now with a
   better pool than rrf's.
3. **`bge-base` / `bge-large`, and BGE with `option_first`.** The order axis was
   only tested on MedCPT; the winner has never been run in the other
   configuration.
4. **A request set written without sight of the instrument** — still the only
   thing that would make any of these numbers load-bearing.
