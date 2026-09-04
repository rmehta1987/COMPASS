# COMPASS — deterministic query expansion, paired test

**Model under test:** `bge-small` fine-tuned (`nn0, t=0.10`), the `deploy/` bundle,
build `3dc8415eccfe`, guards live, fp32, threshold unchanged. Fixture, gold rule,
`stem_option_dup` and the dictionary build at `3dc8415eccfe` unchanged. The brief is recorded verbatim in
[`BRIEF_query_expansion.md`](BRIEF_query_expansion.md). Companion to
[`FUSION.md`](FUSION.md), whose §1 length gradient this tests.

Every number below is read from one of four JSON artifacts in `out/`. Two are tracked in
git; the other two (§2's and §3's) were withdrawn from git on 2026-09-03 because they quote
gold stems per row and the repository is public. Their checksums are in
[`PROVENANCE.md`](PROVENANCE.md), and every figure they carry is reproduced by
[`deploy/smoke_test.py`](deploy/smoke_test.py) in
[`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json) (`acceptance.F`,
`threshold.F`). Every retrieval goes through the shipped bundle, single query, no fusion,
and every table is anchored to a control that reproduces R@1 0.567 row for row.

> **What ships is arm I, not arm F.** After this document was written the population slot
> was dropped from the shipped contract (a post-hoc revision, §2a and §5): the deployed
> template renders instances only. Arm I measures R@1 **0.6429**, R@5 0.8884, R@10
> **0.9375**, rank p90 7, 43/44 negatives rejected, AUROC 0.9874 — the same R@1 as F, four
> rows gained and four lost, and 0.4 points lower at R@10 (smoke report `acceptance.I`;
> `deploy/manifest.json::template`).

---

## One-line answer

**The pre-registered test passes and the template ships under its own rule — but the
gain is not the length gradient.** Arm F moves R@1 **0.567 → 0.643** (+0.076, item-clustered
95% CI **[+0.009, +0.147]**, 22 gained / 5 lost), and the abstention threshold **survives
unchanged** (43/44 at the shipped τ, AUROC 0.987). Yet the template could only touch
**18 of 56 items**, because the fixture carries target-side metadata for nothing else; the
whole gain sits in those 18 (0.548 → 0.823) and comes from the **instances slot** — the
matrix option label — not from population, which is net negative. A post-hoc sensitivity
that drops the 7 rows whose query never named the cancer type at all ("sibling cancer" for
the breast-cancer column) gives **+0.046, CI [−0.014, +0.106]**: under the bar, containing
zero. The construct and timeframe slots, the ones the length hypothesis is actually about,
are **untested here** because no metadata can fill them.

---

## Summary

| | headline | § | source |
|---|---|---|---|
| **0. Pre-registration** | Template, field-derivation rules, negatives' fields, decision rule and predictions committed at `d9d7be4` with sha256 `5f890fa5…` before any retrieval. Rendered strings for all 268 requests frozen there; the scoring scripts refuse to run if the template's hash changes. | §0 | [`out/qx_preregistration.json`](out/qx_preregistration.json) |
| **1. What could be tested** | Metadata supplies only **population** (roster block) and **instances** (matrix column label). 62 of 224 rows in 18 items change; **162 rows in 38 items are unchanged**, including every `residence_commute`, `tobacco`, `medication` and `sleep` row. Timeframe and construct elaboration have no metadata source and are untested. | §1 | same |
| **2. Paired test** | **F: +0.076 R@1, CI [+0.009, +0.147]**, 22/5/197. P (population only): +0.005, CI [−0.022, +0.027]. 1–2-word subgroup F: +0.113, CI [+0.026, +0.214]. R@5 0.862 → 0.888, R@10 0.920 → 0.942. One 0/4 item rescued to 4/4 (bladder cancer, ranks 82/36/38/59 → 1). `residence_commute` **unchanged at 0.062**. | §2 | `out/qx_task2_paired.json` (withdrawn from git; sha256 `913736170edb6e83…`; figures reproduced in the smoke report `acceptance.F`) |
| **2a. Where it comes from** | Post hoc. Population-only rows **0.647 → 0.588** (+2 −3). Instance rows 0.511 → 0.911 (+20 −2). Excluding the 7 rows where the option label supplied a concept the query never contained: **+0.046, CI [−0.014, +0.106]**. | §2 | same |
| **3. Abstention** | **Threshold survives unchanged.** F: shipped τ rejects **43/44** (clean 27/27, adjacent 16/17), AUROC **0.9867**, negative max **falls** 0.772 → 0.732, τ* re-derived on positives only is the same 0.729476. At that τ: precision 0.604 → **0.683**, recall 0.558 → **0.634**, coverage 0.924 → 0.929. The negative side is the weaker half of the symmetry (§3). | §3 | `out/qx_task3_abstention.json` (withdrawn from git; sha256 `221dbc4946fd2f67…`; figures reproduced in the smoke report `threshold`) |
| **4. Corpus size** | Sensitivity curve, not a benchmark. R@1 **0.673 / 0.624 / 0.589 / 0.567** at 40 / 60 / 80 / 100 % of constructs; **−1.45 R@1 points per 100 targets**, −0.38 R@10 points. A module the size of module 3 (329 targets) would cost ~4.8 R@1 points. The template's gain is flat across pool sizes (+7.0 to +7.6). | §4 | [`out/qx_task4_corpus_size.json`](out/qx_task4_corpus_size.json) |

### Premises checked

1. **"Roster family size gives population" is not quite right.** In this instrument the
   size-20 family in module 2 holds both the pregnancy roster (Q8) and the sibling roster
   (Q16). The population table is keyed on the roster *block* instead. Task survived.
2. **"The 10 items at 0/4 are expected unchanged."** Nine are. One is rescued, and the
   reason matters: its four queries (`sibling cancer`, `sibling had cancer`, …) never
   named bladder cancer, and the option label did. The expansion *can* supply a
   discriminator the request never contained — when the field comes from the gold's
   metadata. That is the experiment's stated main threat, realised on 7 rows.
3. **The length gradient reproduces in shape** (F: 0.582 / 0.529 / 0.758 by resulting
   length) but the rows that moved stratum are the roster/matrix rows, so it is not an
   independent confirmation of the gradient.

---

## 0. Pre-registration

[`src/query_expand.py`](src/query_expand.py), sha256
`5f890fa5791bdcaf1f8fa99d37dcf888fa89ace7ba6c43a03c9bc6c6139c29ee`, committed at
`d9d7be4` together with the negatives' fields
([`fixtures/negative_expansion_fields.json`](fixtures/negative_expansion_fields.json), sha256
`00fa0ba5…`) and [`out/qx_preregistration.json`](out/qx_preregistration.json), which holds
every rendered string. Both scoring scripts verify the hash and re-render the strings
before scoring, and stop on any difference. The hash is unchanged at the time of writing.

**The template.** `[population] construct [timeframe][: instance, …]`. Construct is
emitted verbatim. A term is added only when its content words are not already present
(light-stemmed, [`src/phrase_overlap.py`](src/phrase_overlap.py) tokenisation), so the
expansion is strictly additive information. Role is carried on the dataclass and **not
rendered**: no stem says "exposure". Nothing names the structure the target sits in — the
population word is the specifier's relationship noun, never the roster block's stem.

**Field sources on the fixture, stated as the brief asked, because this is the main
threat.** The specifier knows the fields from the hypothesis; the fixture has no
specifier, so each row's fields come from its gold target's *metadata*, and only from
metadata that encodes something the specifier would genuinely know:

| field | source | rows carrying it |
|---|---|---|
| construct | the row's own query, verbatim | 224 |
| population | `POPULATION_BY_ROSTER_BLOCK[(module, block)]` when the target is a roster repeat: m1:Q6 household member, m2:Q8 pregnancy, m2:Q16 sibling, m2:Q18 child. Non-roster targets get None — including the mother/father questions, whose population is only in the stem. | 56 |
| timeframe | **None on every row.** `dictionary.json` has no timeframe field; it lives only in the stem. **Untested.** | 0 |
| instances | `(option,)` when `matrix_col` is non-null, else `()`. Grid sub-items and text companions (`Text`, `AM/PM`, `City`, `Product 2`) are structure, not instances, and are excluded by that rule. | 60 |

**On the negatives**, which have no metadata: population from the request (only n44 asks
about someone other than the participant), instances as 1–3 examples or synonyms an
analyst would list, hand-written from the request text alone before any negative was
scored. The asymmetry — positives' instances are the codebook's own label, negatives' are
an analyst's vocabulary — is stated in §3, and arm P bounds it.

**What was seen before registering.** `FUSION.md` and `CHARACTERISATION.md` in full (they
name the 0/4 items), the 56 gold targets' metadata and stems once, and the 44 negatives.
Not opened: any per-row rank or correctness file, or the 224 queries beyond the first six.

**Decision rule.** F vs S on all 224 rows: ships if the item-clustered 95% CI on Δ R@1
excludes zero *and* the point estimate exceeds +0.05; does not ship if the CI contains
zero. P is diagnostic and decides nothing.

---

## 1. What the fixture can and cannot test

| | rows | items |
|---|---|---|
| changed under F (population and/or instance added) | **62** | **18** |
| of which population only | 17 | 7 |
| of which instance only | 27 | — |
| of which both | 18 | — |
| unchanged under F | **162** | **38** |

The 38 untouched items include every row of `residence_commute` (16), `tobacco` (20),
`medication` (32), `sleep` (4), `alcohol`, `reproductive_hormonal` and `chronic_condition`.
For a singleton target — most of the corpus — the metadata carries nothing a specifier
would add, so the template leaves the query alone. **The brief's central case,
`NSAID utilization frequency` restored to "nonsteroidal anti-inflammatory medication use,
past 12 months: ibuprofen, naproxen, aspirin", is exactly the case this fixture cannot
simulate**: construct elaboration, timeframe and instances for a singleton all come from
the specifier's head, and reading them off the stem would be copying the gold. The paired
test below is therefore a test of the population and instance slots on roster and matrix
targets, and of nothing else.

---

## 2. Task 2 — the paired test

Single retrieval per row per arm through `deploy/`. Arm S reproduces
`out/char_pos_bge-small_ft.json`: R@1 0.567, **0 of 224 rows with a differing rank**,
max |Δcos| 7.21e-07.

### All 224 rows, 56 items

| arm | R@1 | R@5 | R@10 | content words | shared with gold | rows changed | Δ R@1 | gained | lost | McNemar p | **item-clustered 95% CI** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S | 0.567 | 0.862 | 0.920 | 3.02 | 1.59 | 0 | — | — | — | — | — |
| P | 0.571 | 0.857 | 0.924 | 3.17 | 1.75 | 35 | +0.005 | 5 | 4 | 1.000 | [−0.022, +0.027] |
| **F** | **0.643** | 0.888 | 0.942 | 3.68 | 2.25 | 62 | **+0.076** | **22** | **5** | 0.0015 | **[+0.009, +0.147]** |

McNemar is shown for comparison only; it treats four correlated phrasings as four draws
and is too narrow. The bootstrap resamples the 56 items, same routine and seed as
[`src/fusion_rewriter.py`](src/fusion_rewriter.py).

### The 1–2-content-word subgroup, 71 rows, 42 items

| arm | R@1 | R@5 | R@10 | content words | shared | rows changed | Δ R@1 | gained | lost | McNemar p | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S | 0.493 | 0.831 | 0.873 | 1.86 | 1.07 | 0 | — | — | — | — | — |
| P | 0.549 | 0.817 | 0.887 | 2.00 | 1.21 | 10 | +0.056 | 4 | 0 | 0.125 | [+0.014, +0.113] |
| **F** | **0.606** | 0.873 | 0.915 | 2.37 | 1.58 | 17 | **+0.113** | 9 | 1 | 0.021 | **[+0.026, +0.214]** |

The effect is largest here, as predicted — with the caveat that 17 rows changed and 9 of
them flipped.

### R@1 by resulting query length

| stratum | S (n) | F (n) |
|---|---|---|
| 1–2 words | 0.493 (71) | 0.582 (55) |
| 3 words | 0.537 (82) | 0.529 (70) |
| 4+ words | **0.676** (71) | **0.758** (99) |

Rows that moved up a stratum under F: 16 from 1–2 words, R@1 0.250 → 0.688; 21 from
3 words, 0.619 → 0.810. The gradient reproduces in shape, but the rows that moved are the
roster/matrix rows, so this is the same effect seen twice, not a second confirmation.

### Strata (committed classifier on the gold stem)

| stratum | rows | S | P | **F** | F @10 | rows changed | fusion `max_cos` (§2 of FUSION.md) |
|---|---|---|---|---|---|---|---|
| cancer_history | 80 | 0.613 | 0.625 | **0.813** | 0.975 | 54 | 0.550 |
| medication | 32 | 0.625 | 0.625 | 0.625 | 0.969 | 0 | — |
| physical_activity | 32 | 0.656 | 0.656 | 0.656 | 0.969 | 4 | — |
| tobacco | 20 | 0.350 | 0.350 | 0.350 | 0.850 | 0 | — |
| **residence_commute** | 16 | **0.062** | 0.062 | **0.062** | **0.688** | **0** | 0.250 |
| healthcare_util | 12 | 0.667 | 0.667 | 0.750 | 0.917 | 4 | — |
| reproductive_hormonal | 8 | 0.750 | 0.750 | 0.750 | 1.000 | 0 | 0.500 |
| alcohol / chronic_condition / sleep / family_roster | 8 / 8 / 4 / 4 | 0.50 / 1.00 / 0.00 / 0.75 | same | same | — | 0 | — |

**The whole gain is `cancer_history`**, +16 rows on the sibling and child cancer-type
checklists. `residence_commute` does not move because no commute target is a roster or
matrix item; the template has nothing to add to it.

### Item histogram and the 0/4 items

k/4 under S: {0: 10, 1: 9, 2: 7, 3: 16, 4: 14}. Under F: {0: 9, 1: 7, 2: 6, 3: 11, 4: **23**}.

One of the ten 0/4 items is rescued: `m2:8_Q16.8#1_1` (sibling, bladder cancer), ranks
82 / 36 / 38 / 59 → **1 / 1 / 1 / 1**. Its four queries were `family cancer history
malignancy`, `sibling had cancer`, `sibling cancer`, `family cancer diagnosis`. None
names bladder cancer; the template added `sibling` and `: Bladder cancer`. The other nine
are untouched — none is a roster or matrix item — and stay exactly where they were.

### Gains and losses, worked

The 22 gains are all instance or population additions on the cancer checklists:
`sibling cancer` → `sibling cancer: Breast cancer` (10 → 1), `CRC sibling` →
`CRC sibling: Colon cancer/rectal cancer` (3 → 1), `chest pain condition` → `chest pain
condition: Angina` (2 → 1), `HNC family` → `sibling HNC family: Head and neck cancer (…)`
(2 → 1). The cosine to the gold rises from ~0.5–0.8 to ~0.95 on each.

The 5 losses are all **population** losses, the failure FUSION.md §4 named:

| query | expanded | rank | now beaten by | margin |
|---|---|---|---|---|
| `prostate sibling` | `prostate sibling: Prostate cancer` | 1 → 2 | `m2:1_Q16.27` *What year was this sibling diagnosed with prostate cancer?* | 0.0001 |
| `brother prostate diagnosis` | `sibling brother prostate diagnosis: Prostate cancer` | 1 → 2 | same | 0.0000 |
| `family history prostate cancer` | `sibling family history prostate cancer` | 1 → 2 | same | 0.0037 |
| `when diagnosed colon cancer` | `child when diagnosed colon cancer` | 1 → 2 | `m2:1_Q18.9#1_8` child checklist, *Colon cancer/rectal cancer* | 0.035 |
| `age rectal cancer diagnosed` | `child age rectal cancer diagnosed` | 1 → 2 | same | 0.006 |

Adding the roster noun pulls the query toward the roster's *other* question about the
same cancer. Population-only rows, all 17: **0.647 → 0.588** (+2 −3). The population slot
is net negative on this fixture.

### Post hoc: where the +0.076 comes from

Computed after the numbers above were read; characterises, decides nothing.

| rows changed under F | rows | items | S | F | gained | lost |
|---|---|---|---|---|---|---|
| population added, no instance | 17 | 7 | 0.647 | 0.588 | 2 | 3 |
| instance added, sharing ≥1 content word with the query | 33 | 12 | 0.545 | 0.879 | 13 | 2 |
| instance added, sharing no content word with the query | 12 | 8 | 0.417 | 1.000 | 7 | 0 |

The lexical split does not separate "restated the concept" from "supplied it" —
`sibling cancer` + `Breast cancer` shares "cancer" and yet the query never named breast
cancer, while `CRC sibling` + `Colon cancer/rectal cancer` shares nothing and names it
exactly. So a hand-judged list was made instead: rows whose query contains **no word,
abbreviation or lay synonym for the option's specific concept**, only the generic
"cancer". There are **7**, in two items: the three breast-cancer rows above
(`sibling cancer`, `cancer sister`, `sibling cancer history`) and the four bladder-cancer
rows. On these, the option label did not lengthen the request; it answered it. The list
is in the artifact so it can be disputed.

| | n rows | Δ R@1 | 95% CI | gained | lost |
|---|---|---|---|---|---|
| **pre-registered: all rows** | 224 | **+0.076** | **[+0.009, +0.147]** | 22 | 5 |
| minus the 7 discriminator-supplied rows | 217 | **+0.046** | **[−0.014, +0.106]** | 15 | 5 |
| 1–2 words, all | 71 | +0.113 | [+0.026, +0.214] | 9 | 1 |
| 1–2 words minus them | 67 | +0.060 | [0.000, +0.132] | 5 | 1 |

**The pre-registered result clears the bar. The result without those two items does not,
on either criterion.** Which reading is right depends on a fact this fixture cannot
supply: whether a specifier who wants sibling breast cancer would ever write
`sibling cancer`. The brief's premise says no — the pipeline knows the construct — and
under that premise the 7 rows are defective fixture rows the template correctly repairs.
Under the stricter reading, the template was handed the answer on those rows. Both
numbers are reported; the decision rule was registered on the first.

### Decision

**F passes the pre-registered rule** (CI excludes zero, +0.076 > +0.05), subject to §3,
which it passes. What ships is narrower than F: a query contract in which the specifier's
**instance** field is appended deterministically and the population slot is left unused
(arm I, the post-hoc revision recorded in §5 and in `deploy/manifest.json::template`; R@1
0.6429 / R@5 0.8884 / R@10 0.9375, p90 7). That is justified for matrix targets, on this
evidence; the population slot was net negative here (−1 row on the 17 it touched) and
awaits the study-team request set as its held-out check.
**It is not evidence that lengthening a singleton request recovers the length
gradient** — that is untested and remains the study-team request set's question.

---

## 3. Task 3 — the negatives and the threshold

The same template applied to both sides in every arm. Arm S reproduces
CHARACTERISATION.md §3: τ 0.729476, 43/44, AUROC 0.9823, R@1 0.567. Queries were encoded
in batches of 64, as in every artifact this table compares against; the τ* column depends
on that (see the knife-edge note below the table).

| arm | pos R@1 | neg p10 | p50 | p90 | **max** | **AUROC** | τ* (positives only) | rej @ τ* | recall @ τ* | **rej @ shipped τ** | admitted |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S | 0.567 | 0.403 | 0.596 | 0.691 | 0.772 | 0.9823 | 0.7295 | 43/44 | 0.558 | **43/44** | n23 |
| P | 0.571 | 0.403 | 0.614 | 0.691 | 0.772 | 0.9813 | 0.7295 | 43/44 | 0.563 | 43/44 | n23 |
| **F** | **0.643** | 0.412 | 0.578 | 0.687 | **0.732** | **0.9867** | **0.7295** | **43/44** | **0.634** | **43/44** | n42 |

**The case that applies: the threshold survives unchanged.** Under F the shipped τ still
rejects 43/44, τ* re-derived on positives only lands on the same value, and no re-derivation
is needed. Nothing here requires the re-derive-once-and-freeze path the brief allowed for.

Why τ* is the same value under S, P and F is not a grid accident. The candidate set is the
distinct top-1 scores of the 224 positives (221 values), and F1 over positives is piecewise
constant between positive scores, so that set is exhaustive: no denser grid can find a
different optimum (the smoke test re-derives it over the exhaustive set and a 20,001-point
dense grid on every run, `threshold.*`). The F1-maximising candidate is the score of a row
the template did not change, which is why the value survives templating.

**The knife edge, found by the CPU port.** 0.729476 is the 6-dp rounding of an *incorrect*
positive's score (fixture row 68). In the batched encoding above that row sits 1.9e-8 below
the threshold; encoding the query alone, as `select()` does, puts it 4.5e-8 above on the
Spark, so τ* moves to the next candidate, 0.731902, in every arm — and back below on the x86
serving machine. Recall is identical at both values and 43/44 holds in every arm; under F
and I the one surviving negative (n42, 0.7316) sits inside that window. The shipped value is
unchanged; `deploy/manifest.json::abstention.knife_edge` records the finding and a robust
alternative (0.73174), and [`deploy/smoke_test.py`](deploy/smoke_test.py) asserts the pair
{0.729476, 0.731902} rather than one side.

**The operating point at the unchanged τ**, in full:

| | shipped (S) | F | |
|---|---|---|---|
| precision | 0.604 | **0.683** | +7.9 pts |
| recall | 0.558 | **0.634** | +7.6 pts |
| coverage | 0.924 | 0.929 | +0.5 pts |
| negatives rejected | 43/44 | 43/44 | unchanged |
| clean / adjacent rejected | 26/27 / 17/17 | 27/27 / 16/17 | the one admitted negative changes |
| AUROC pos vs neg | 0.9823 | 0.9867 | +0.004 |
| AUROC correct vs incorrect | 0.640 | 0.719 | still cannot flag its own errors |

The admitted negative moves from n23 (*distance in miles from the home to the nearest
green space*, 0.772 → 0.643 once expanded) to n42 (*what kind of neighborhood income
level they live in: median household income*, 0.732, nearest `m1:Q5.4` household income —
an adjacent row, and a near-miss the instrument arguably half-answers). Precision 0.90
becomes reachable at τ 0.967 with 21 rows answered — 9% coverage — which is not an
operating point. This precision gain is the same 22/5 flip table as §2 seen through the
coverage filter, and inherits every caveat there.

**The negative side is the weaker half of the symmetry, and it is reported as such.**
26 of 44 negatives score *lower* expanded, 18 higher, mean −0.015. The analyst's
instances (`ADI`, `SVI`, `RUCA`, `WGS`, `PRS`, `tract FIPS code`) are tokens the
instrument never uses, so they pull the request *away* from the corpus; the codebook's
option label does the opposite for positives. Nothing can restate an absent construct in
the instrument's own words — that is what absence means — so this asymmetry is partly the
phenomenon itself. But it means the 43/44 under F is a floor for what an analyst's
vocabulary does, not a ceiling. Arm P, where negatives are practically unexpanded (1 row
changes), shows that population alone leaves both sides where they were.

---

## 4. Task 4 — corpus-size sensitivity

**A sensitivity curve, not a benchmark.** Sampling by `construct_key`, options never
split; the 56 gold items' constructs always retained whole; 20 seeds per level.

| constructs | targets (mean) | **S R@1** | sd | S R@5 | S R@10 | F R@1 | F R@10 |
|---|---|---|---|---|---|---|---|
| 40 % (426) | 622 | **0.673** | 0.023 | 0.915 | 0.947 | 0.742 | 0.973 |
| 60 % (640) | 867 | **0.624** | 0.018 | 0.893 | 0.933 | 0.696 | 0.956 |
| 80 % (853) | 1,108 | **0.589** | 0.016 | 0.873 | 0.924 | 0.663 | 0.946 |
| 100 % (1,066) | 1,353 | **0.567** | — | 0.862 | 0.920 | 0.643 | 0.942 |

Slope over the range: **−1.45 R@1 points per 100 targets**, −0.74 R@5, −0.38 R@10. The
rise toward 40% is the smaller pool, nothing else. Its use is the extrapolation: a module
the size of module 3 (329 targets) would cost about **4.8 R@1 points** and 1.3 R@10
points if its constructs distract like the existing ones do; a module the size of module
1 (70 targets), about 1 point. The template's gain is flat across pool sizes, +7.0 to
+7.6, so whatever it is worth it is not worth less in a larger dictionary.

---

## 5. What this does not do

**It does not fix autonomous operation.** At 0.643, pair-correctness is 0.643² = **0.413**
against today's 0.321 — still more than one hypothesis in two resting on a wrong variable,
and §3 shows the model still cannot flag which (AUROC 0.72).

**It does not test the length hypothesis on singleton targets.** 38 of 56 items were
untouchable from metadata. Whether `NSAID utilization frequency`, restored to the
construct, timeframe and instances a specifier knows, retrieves better is the question the
brief asked and the one this fixture cannot answer. It needs requests with those fields
actually filled — which is the study-team request set, with one more field to collect:
not only "are a researcher's requests longer than 2–5 words", but **do they name the
population and the instance**, since those are the two slots this work shows to matter,
in opposite directions.

**It does not touch the four unmeasured strata.** SES/employment, insurance/access,
cancer-screening and demographics still have zero fixture rows.

**The population slot was dropped from the shipped contract — a post-hoc revision, recorded
as one.** It is pre-registered as part of F, F clears the rule, and P alone does not — on 17
rows it loses 3 and gains 2 (0.647 → 0.588), with one mechanism: the roster noun pulls the
query toward the roster block's *other* question about the same cancer, at margins down to
0.0001. This document originally kept the slot in, flagged, because dropping it is a
revision in light of results. The CPU port (commit e446cf8) made the revision and recorded
it as such in `deploy/manifest.json::template.population_slot`, shipping instances only
(arm I: R@1 0.6429, the same as F; R@10 0.9375 vs 0.942). The held-out check the brief asks
for is the study-team request set; until it runs, the revision is unconfirmed and both
figures are reported.

---

## 6. Constraints observed

| constraint | status |
|---|---|
| No retraining, re-tuning or checkpoint modification | **Held.** |
| `deploy/` guards pass 4/4 | **Re-run after all four tasks: 4/4.** |
| Arm S reproduces R@1 0.567 row for row | **Held**, 0 rank mismatches, max |Δcos| 7.21e-07; and again in task 3 (τ, rejection, AUROC to the last digit). |
| Negatives never select a threshold | **Held.** Candidate τ from the 224 positives alone. |
| fp32 | **Held.** All retrieval through [`deploy/retriever.py`](deploy/retriever.py); cosine algebra in fp64. |
| No model call at query time | **Held.** The template is string concatenation. The negatives' fields were authored by hand once, before scoring, and are frozen. |
| Template committed with sha256 before task 2 | **Held**, `d9d7be4`; scripts assert the hash. |
| Every number traceable to a committed JSON artifact | **Held at the time; two artifacts since withdrawn.** Four artifacts were `git add -f`'d past the `out/` and `*.json` ignore rules. On 2026-09-03 `out/qx_task2_paired.json` and `out/qx_task3_abstention.json` were withdrawn (gold stems per row, public repository); their checksums are in [`PROVENANCE.md`](PROVENANCE.md) and their figures are reproduced by the tracked smoke report. |

## Scripts and artifacts

| script | produces |
|---|---|
| [`src/query_expand.py`](src/query_expand.py) | the template; `--preregister` → [`out/qx_preregistration.json`](out/qx_preregistration.json) |
| [`src/qx_paired.py`](src/qx_paired.py) | `out/qx_task2_paired.json` (withdrawn from git) |
| [`src/qx_abstain.py`](src/qx_abstain.py) | `out/qx_task3_abstention.json` (withdrawn from git) |
| [`src/qx_corpus_size.py`](src/qx_corpus_size.py) | [`out/qx_task4_corpus_size.json`](out/qx_task4_corpus_size.json) |

*Generated 2026-09-03.*
