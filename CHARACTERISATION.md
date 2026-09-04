# COMPASS — characterisation of the shipped retriever

**Model under test:** `bge-small` fine-tuned (`nn0, t=0.10`), argmax cosine, no LLM call.
R@1 0.567, 18.3 ms isolated per query on the training machine (2.94 ms/row batched, see
[`PROVENANCE.md`](PROVENANCE.md)), 134.2 MB checkpoint directory (133.5 MB `model.safetensors`),
`runs/bge-small_nn0_t0.10/`.
Companion to `RESULTS.md`, which selects the model; this document characterises it.

Every number is read from a JSON artifact in `out/` written by a script in `src/`, cited
on the row. Nothing here is re-typed from a prior report. The `out/` artifacts, the
fixtures and the checkpoint are on the training machine, not in this public tree; the
sha256 of each, the command that regenerates it and the tracked file that reproduces its
figure are in [`PROVENANCE.md`](PROVENANCE.md). A backticked path below may be tracked or
training-machine-only; `PROVENANCE.md` lists the training-machine ones.

**One-line answer.** The tool is *reliable on some constructs and blind on others*, not a
coin flip — the blind spots are enumerable and listed in §1. It can tell when a requested
construct is **not in the instrument at all** (AUROC 0.982, §2) and it **cannot** tell when
it has picked the wrong construct (AUROC 0.640, §3). Recall is badly lopsided across
domains, and the four strata that matter most to a disparities study are **unmeasured**,
because the 224-row fixture contains no row for any of them (§4).

---

## Summary

Headline result per task. Every figure is expanded, with its full distribution and its
caveats, in the numbered section named on the row.

| | headline | § | source |
|---|---|---|---|
| **1. Phrasing consistency** | Fine-tuning moved mass to 4/4: items at ≥3/4 **double** (15 → 30), items at ≤1/4 nearly halve (33 → 19), 31 items improved / 7 regressed. Against a Binomial(4, 0.567) reference the histogram shows **+8.2 excess at 4/4, +8.0 at 0/4, −13.3 at 2/4** — outcomes cluster by *item*, not per query. This is the reliable-with-blind-spots product, not the coin flip. | §1 | `out/char_task1_phrasing.json` |
| **1a. Blind spots** | All **19** items at 0/4 and 1/4 tabulated with a phrasing each. Read by hand, all but one return an item differing from gold on **one discriminator the query never states**. 81% of all 97 errors are recoverable by rank 10 (R@10 0.920) — a top-10 list, not an argmax, is the interface this model supports. | §1a | same |
| **2. Negatives** | **They separate.** 44-row held-out set: negatives p50 0.596 / max 0.772 against positives p10 0.741. AUROC **0.982** (0.995 vs correct positives). 0/44 negatives above the positive median. The **margin does not separate** (0.550). Lay-register and `adjacent` rows score higher, as predicted, and still fall below the threshold. | §2 | `out/char_task2_negatives.json`, `out/negatives_absence_check.json` |
| **3. Calibration** | At τ = **0.7295** (max-F1 on positives only) the model refuses **43/44** absent-construct requests for **0.9 recall points** — this replaces arm D's `absent` verdict. But cosine separates correct from incorrect top-1 at AUROC **0.640** only, and **precision 0.90 is unreachable at any τ**. It detects absence, not error. Fine-tuning *degraded* the margin as a confidence signal (0.774 → 0.633). | §3 | `out/char_task3_calibration.json` |
| **4. Stratification** | Recall is **10× lopsided**: `residence_commute` **0.062** (R@10 0.688, also worst) against cancer 0.613, `sleep` 0.000 at rank 1 but 1.000 by rank 10. And the brief's question cannot be answered — SES/employment, insurance/access, cancer-screening and demographics have **zero fixture rows** (61 targets / 51 constructs the benchmark never touches). | §4 | `out/char_task4_strata.json` |
| **5. Deployment artifact** | `deploy/`, 137.2 MB, 9 files (7 at the original freeze; `template.py` and `smoke_test.py` added by the CPU port, commit e446cf8), CPU-pinned, 4 threads, no pickle. **Reproduces R@1 0.567 from its own frozen vectors**; vectors bit-identical across rebuilds. Guards fail rather than warn and this is **tested**: 4/4 tamper cases raise (stale hash, modified file, permuted row order). Row 107 — the one GPU/CPU disagreement — scores 0.6239 and is abstained on anyway. | §5 | [`deploy/manifest.json`](deploy/manifest.json) `files`; [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json) `integrity.files` = 9 |
| **6a. `stem_option_dup`** | **Confirmed at +8.0 R@1** on the full 1,353 / 224 set (vs +8.2 on the superseded subset). The full corpus also exposes the mechanism the subset hid: the gain is almost entirely **folded-family recall, 0.304 vs 0.089**. | §6a | `out/gate_full_*.json` |
| **6b. Qwen3 discrepancy** | **Resolved: it is the load dtype, not two harnesses and not the pooling convention.** Loading `qwen3-06b` in its config-declared bfloat16 reproduces the earlier log line for line. The models the two runs agree on are exactly those declaring fp32; `granite-s2` moved ten times further than `qwen3`. | §6b | `out/diag_qwen3-06b_dtype_from_config.json` |

### Three premises in the brief were wrong

Each is corrected in place rather than implemented around, because in every case the task
itself stayed valid — stopping would have withheld four finished tasks over a detail that
changes the framing, not the work.

1. **Air quality is not a clean negative domain** (§2). The brief's pattern omits `pollut`:
   `m2:Q24.11` ("residences within a half mile of the following") and `m2:Q24.12` are both in
   the target corpus. The domain is kept, its rows phrased as *measured* exposure and
   labelled `adjacent`. The brief's `lab values` → 10 rows also did not reproduce, though its
   conclusion holds for a different reason — 49 entries match `blood`.
2. **Cancer is 170 constructs / 271 targets, not ~730** (§4). 730 is close to module 2's
   construct count (749); 1,331 dictionary *entries* match a cancer pattern but fold to 170
   constructs. The brief's SES (15) and cancer-screening (5) figures were right. The
   imbalance is real but ~1.6 : 1 at target level, not 66 : 1.
3. **The Qwen3 discrepancy is a dtype effect** (§6b), and 0.362 appears nowhere in the tree;
   the reproducible pair is 0.379 / 0.375 from the *same* harness.

§7 carries what this still does not settle, the constraints observed, and the two additions
this work makes to the study-team request set.

---

## 0. What was run

| Script | Produces | Purpose |
|---|---|---|
| `src/char_encode.py` | `out/char_pos_*.json`, `out/char_neg_*.json` | Re-encodes on CPU and records the full top-10 neighbourhood per row. `compass_score.py` records `cos_gold`/`cos_top` but not the runner-up, so the top1−top2 margin the brief asks for cannot be recovered from its output. Conventions are **imported** from `compass_score.py`, never re-declared, so this cannot drift. Reproduces R@1 0.567 exactly. |
| `src/char_report.py` | `out/char_task1_phrasing.json`, `out/char_task2_negatives.json`, `out/char_task3_calibration.json` | Tasks 1–3. |
| `src/char_strata.py` | `out/char_task4_strata.json` | Task 4, with the domain classifier committed in the script. |
| `src/verify_negatives.py` | `out/negatives_absence_check.json` | Re-verifies the five negative domains are absent, as an artifact rather than a claim. |
| `src/freeze_deploy.py` | `deploy/` | Task 5, the frozen artifact. |
| `src/test_deploy_asserts.py` | — | Proves the bundle's guards raise rather than warn. 4/4 pass. |
| `fixtures/negative_requests.json` | — | The 44-row held-out negative set. |

---

## 1. Task 1 — phrasing consistency

56 distinct gold items × 4 phrasings = 224 rows (verified against
`retrieval_queries.json`: 56 distinct keys, every one with exactly 4 phrasings).

**Per-item distribution — how many of each item's 4 phrasings land at rank 1**
(`out/char_task1_phrasing.json`):

| phrasings at rank 1 | `bge-small` **frozen** | `bge-small` **fine-tuned** |
|---|---|---|
| 0 / 4 | 18 items (32.1%) | **10 items (17.9%)** |
| 1 / 4 | 15 items (26.8%) | 9 items (16.1%) |
| 2 / 4 | 8 items (14.3%) | 7 items (12.5%) |
| 3 / 4 | 7 items (12.5%) | **16 items (28.6%)** |
| 4 / 4 | 8 items (14.3%) | **14 items (25.0%)** |
| **≥ 3 / 4** | **15** | **30** |
| **≤ 1 / 4** | **33** | **19** |
| aggregate R@1 | 0.375 (84/224) | 0.567 (127/224) |

**Fine-tuning moved mass to 4/4 — verified, not assumed.** Items at ≥3/4 double (15 → 30);
items at ≤1/4 nearly halve (33 → 19). Per-item: **31 improved, 18 unchanged, 7 regressed**.

**And the product is the good one of the two the brief describes.** If each phrasing
succeeded independently at the model's own rate, the histogram would be Binomial(4, 0.567).
It is not close (`binomial_reference` / `excess_over_binomial` in the artifact):

| | 0/4 | 1/4 | 2/4 | 3/4 | 4/4 |
|---|---|---|---|---|---|
| observed (fine-tuned) | 10 | 9 | 7 | 16 | 14 |
| Binomial(4, 0.567) | 2.0 | 10.3 | 20.3 | 17.7 | 5.8 |
| **excess** | **+8.0** | −1.3 | **−13.3** | −1.7 | **+8.2** |

Outcomes cluster by **item**, not by query: 2.4× the expected mass at 4/4, 5× at 0/4, and
a third of the expected mass at 2/4. This is the "reliable with enumerable blind spots"
product, not the coin flip. (The frozen model has the same shape at a worse level — the
polarisation is a property of the task, not of fine-tuning.)

### 1a. The documented blind spots

All 19 fine-tuned items at 0/4 and 1/4, with one phrasing each and what won instead.
Full records, including all four ranks per item, in
`out/char_task1_phrasing.json → blind_spots_fine_tuned`.

| gold key | ft | frozen | gold construct (abbrev.) | option | example phrasing | rank | top-1 returned |
|---|---|---|---|---|---|---|---|
| `m2:8_Q16.8#1_1` | 0/4 | 0/4 | Was this sibling ever diagnosed with … cancer? | Bladder cancer | "family cancer history malignancy" | 82 | `m2:1_Q16.7` |
| `m2:Q26.12` | 0/4 | 2/4 | Which modes of transportation did you use for your typical commute *from this address* | — | "commute transportation mode" | 2 | `m2:Q25.8` |
| `m2:Q776` | 0/4 | 1/4 | Describe the *other* mode(s) of transportation … | — | "commute transportation mode" | 10 | `m2:Q25.8` |
| `m2:Q9.91` | 0/4 | 0/4 | Age when first used *another type of* combined estrogen+progestin | — | "combined oral contraceptive initiation age" | 4 | `m2:Q9.82` |
| `m3:Q1.4_2` | 0/4 | 0/4 | What is your address? | City | "residence location city" | 3 | `m1:Q82` |
| `m3:Q15.9_4_TEXT` | 0/4 | **4/4** | Why did you stop drinking alcohol? – Other (describe) | Text | "alcohol cessation reason" | 2 | `m3:Q15.9` |
| `m3:Q2.16` | 0/4 | 1/4 | How often did you walk while shopping or doing errands | — | "non-exercise ambulatory activity" | 28 | `m3:Q2.32#1_12` |
| `m3:Q3.12_2` | 0/4 | 0/4 | What time do you typically wake up on days off? | AM/PM | "circadian sleep schedule" | 4 | `m3:Q3.12_1` |
| `m3:Q5.14` | 0/4 | 0/4 | How often do you smoke a cigarette before your first meal | — | "time to first cigarette" | 7 | `m3:Q5.2` |
| `m3:Q870_2` | 0/4 | 0/4 | How long using each nicotine replacement product | Product 2 | "nicotine replacement therapy duration" | 9 | `m3:Q6.1` |
| `m2:11_Q16.8#1_3` | 1/4 | 1/4 | sibling cancer types | Breast cancer | "sibling cancer" | 10 | `m2:1_Q16.7` |
| `m2:12_Q16.8#1_9` | 1/4 | 0/4 | sibling cancer types | Head and neck cancer | "oropharyngeal cancer family history" | 2 | `m2:1_Q16.17` |
| `m2:16_Q16.8#1_16` | 1/4 | 1/4 | sibling cancer types | Non-Hodgkin's lymphoma | "brother sister had lymphoma" | 3 | `m2:1_Q16.8#1_14` |
| `m2:2_Q18.9#1_17` | 1/4 | 3/4 | child cancer types | Non-melanoma skin cancer | "non-melanoma skin cancer diagnosis" | 4 | `m2:Q12.75` |
| `m2:Q19.48` | 1/4 | 1/4 | days/week taking **naproxen** regularly | — | "NSAID utilization frequency" | 6 | `m2:Q19.25` (*ibuprofen*) |
| `m2:Q27.12` | 1/4 | 0/4 | commute to **school** on a local road | — | "traffic exposure commute" | 5 | `m2:Q25.12` (*work*) |
| `m2:Q3.5` | 1/4 | 0/4 | ER care in the past **two years** | — | "emergency department utilization" | 2 | `m2:Q3.12` (*12 months*) |
| `m2:Q9.96` | 1/4 | 1/4 | What *other* prescription hormones did you take? | — | "exogenous hormone medication" | 5 | `m2:Q9.95` |
| `m3:Q289` | 1/4 | 0/4 | How often *did* you smoke menthol (past) | — | "menthol cigarette frequency" | 2 | `m3:Q287` (*present tense*) |

**Read this before treating the failures as random.** Reading the nineteen rows by hand — a
manual judgement, not a computed statistic — **all but one** (`m3:Q2.16`) return an item
that differs from the gold on **one discriminator the query never stated**: work vs school
commute, naproxen vs ibuprofen, past vs present tense, 2 years vs 12 months, AM/PM field vs
hour field, city subfield vs the standalone city question, "other type of hormone" vs the
named type. In most of these the *query itself does not contain the information needed to
choose*. That is a property of the request, not only of the encoder — and it means the
ceiling on this fixture is below 1.0 for reasons no model change addresses.

The error taxonomy over all 97 top-1 errors confirms the pattern:

| top-1 error lands on… | fine-tuned (97 errors) | frozen (140 errors) |
|---|---|---|
| the same construct, wrong option | 11 (11.3%) | 11 (7.9%) |
| the same questionnaire block, different question | 50 (51.5%) | 80 (57.1%) |
| the same module, different block | 30 (30.9%) | 43 (30.7%) |
| a different module | 6 (6.2%) | 6 (4.3%) |
| **recoverable at rank ≤ 3 / ≤ 10** | **57 / 79 (59% / 81%)** | 59 / 110 |

63% of errors return a neighbour of the right answer; 81% are recoverable in the top 10
(R@10 = 0.920). A top-10 list, not an argmax, is the interface this model actually supports.

---

## 2. Task 2 — the negative control set

**Fixture:** `fixtures/negative_requests.json`, schema `retrieval_negative_requests/1`,
**44 requests** across the five domains, each labelled `domain` / `register`
(technical | lay) / `adjacency` (clean | adjacent). Authoring method, the three rows that
were **dropped** for being arguably answerable, and a declared bias statement are all
recorded in the fixture itself. Absence re-verified by `src/verify_negatives.py` →
`out/negatives_absence_check.json`: **0 dictionary entries and 0 targets** match any
domain's absent-pattern.

> **Premise correction.** The brief reports the air-quality domain as 0 rows using
> `pm2.5|air quality|particulate|ozone|no2|array of things`. That pattern omits `pollut`.
> **`m2:Q24.11`** ("were any of these residences within a half mile of the following?") and
> **`m2:Q24.12`** ("describe this source of pollution") are both in the target corpus.
> Measured ambient concentration is still absent, so the domain is retained — but its rows
> are phrased as measured exposure and labelled `adjacent`, not `clean`. Separately, the
> brief's note that `lab values` returns 10 rows did not reproduce (`\blab\b` → 0 entries);
> its *conclusion* stands for a different reason — `\bblood\b` matches 49 entries including
> "blood test for prostate cancer (PSA)" and "blood cholesterol checked", so lab-adjacent
> self-report constructs do exist and lab values are not a usable negative domain.

**Top-1 cosine distribution, fine-tuned model** (`out/char_task2_negatives.json`):

| set | n | p10 | p50 | p90 | min | max |
|---|---|---|---|---|---|---|
| positives, all | 224 | 0.7413 | 0.8795 | 0.9573 | 0.5683 | 0.9874 |
| positives, correct top-1 | 127 | 0.7741 | 0.9070 | 0.9617 | — | — |
| positives, incorrect top-1 | 97 | 0.7010 | 0.8356 | 0.9567 | — | — |
| **negatives** | **44** | **0.4034** | **0.5961** | **0.6907** | **0.3116** | **0.7722** |

**They separate.** AUROC 0.9823 (all positives vs negatives), **0.9953** (correct positives
vs negatives). Overlap is one-sided and tiny: **0 of 44** negatives score above the positive
median; exactly **1** correct positive falls below the negative p90. The two ranges overlap
only in [0.5683, 0.7722].

The **margin** does *not* separate negatives — AUROC 0.5501, barely above chance (negative
margin p50 0.0309 vs positive 0.0412). Absolute cosine is the signal; the margin is not.

**Confound check — register.** Negatives written in analyst register could be rejected for
sounding unlike the instrument rather than for being absent. The 12 lay-register rows score
*higher* (p50 0.6374, max 0.6930) than the 32 technical rows (p50 0.5632, max 0.7722), as
predicted — but every lay row still sits below the operating threshold. Likewise the 17
`adjacent` rows (p50 0.6374) score above the 27 `clean` rows (p50 0.5533). The separation
survives both hard cases.

**The five hardest negatives** (what any threshold has to catch):

| cos | request | returned instead |
|---|---|---|
| 0.7722 | distance in miles from the home to the nearest green space | `m2:Q24.11` residences within half a mile of … |
| 0.7134 | median household income of the census block group | `m1:Q5.4` your yearly household income |
| 0.7041 | polygenic risk score for breast cancer | `m2:1_Q18.9#1_3` child diagnosed with breast cancer |
| 0.6930 | which census area their address falls in | `m3:Q1.4_2` What is your address? – City |
| 0.6907 | neighborhood deprivation index | `m3:Q16.1_2` this is a close-knit neighborhood |

Each is a plausible-looking wrong answer of exactly the kind the brief warns about — an
area-level construct answered with a person-level variable, a genotype construct answered
with a family-history variable. Without a threshold, argmax returns every one of them
silently.

> **Caveat on the top row.** `m2:Q24.11`'s response options are `null` in `dictionary.json`
> — the codebook lost the list of things the half-mile question enumerates. Its true content
> is therefore unverifiable from the dictionary, and it may or may not include green space.
> It is the single highest-cosine negative, so this one row of the corpus is worth a
> study-team check.

---

## 3. Task 3 — calibration and the abstention threshold

`out/char_task3_calibration.json`. Threshold semantics: a row is **answered** when
score ≥ τ; precision = correct ÷ answered; recall = correct ÷ all 224 (abstaining costs
recall); negative rejection = fraction of the 44 held-out negatives falling below τ.

**Separating correct from incorrect top-1** — the *other* question, and the model fails it:

| discriminator | AUROC, correct vs incorrect (fine-tuned) | (frozen) |
|---|---|---|
| top-1 cosine | **0.640** | 0.615 |
| top1 − top2 margin | 0.633 | 0.774 |

Note fine-tuning **degraded** the margin as a confidence signal (0.774 → 0.633) even as it
raised R@1 by 19 points. The sibling-cosine collapse (0.9099 → 0.3394) spread the space out,
but it did not make the model's confidence more honest about *which* item it picked.

**Threshold sweep, top-1 cosine, fine-tuned:**

| operating point | τ | coverage | precision | recall | F1 | negatives rejected |
|---|---|---|---|---|---|---|
| no threshold (today) | — | 1.000 | 0.567 | 0.567 | 0.567 | 0 / 44 |
| **max F1** | **0.7295** | **0.924** | **0.604** | **0.558** | **0.580** | **43 / 44 (97.7%)** |
| *(the same rule, queries encoded one at a time on the Spark)* | *0.7319* | *0.9241* | *0.6039* | *0.558* | *0.580* | *43 / 44* |
| all negatives rejected | 0.7722 | 0.821 | 0.625 | 0.513 | 0.564 | 44 / 44 |
| precision ≥ 0.90 | — | **unreachable at any τ** | | | | |

The italic row is the knife edge, found by the CPU port: 0.729476 is the 6-dp rounding of
an *incorrect* positive's score (fixture row 68). Batch encoding, which produced the bold
row, puts that row 1.9e-8 below the threshold; encoding the query alone, as `select()`
does, puts it 4.5e-8 above on the Spark (so τ* moves to the next candidate, 0.731902) and
below again on the x86 serving machine. Recall is identical either way. The shipped value
is unchanged; `deploy/manifest.json::abstention.knife_edge` records the finding and a
robust alternative, and [`deploy/smoke_test.py`](deploy/smoke_test.py) asserts the pair.

**This is the mechanism that replaces arm D's `absent` verdict, and it costs almost
nothing.** At τ = 0.7295 the model refuses 43 of 44 requests for data the instrument does
not contain, while giving up **0.9 recall points** (0.567 → 0.558). Pushing to 44/44 costs
4.5 more points and is not obviously worth it — that last negative is the `m2:Q24.11` row
whose options are missing from the codebook.

**What the threshold does *not* buy.** Precision 0.90 is unreachable on cosine at any τ. On
the margin it is reachable — τ = 0.1855, precision 0.917 — but only by answering **12 of 224
rows (5.4% coverage, recall 0.049)**. There is no operating point at which a returned
result can be treated as verified. A hit is a candidate for a human to confirm.

**Frozen `bge-small`, same analysis**, for the fallback comparison: negatives separate less
well (AUROC 0.948; at max-F1 τ = 0.6538 only 65.9% of negatives are rejected), and precision
0.90 is likewise unreachable. Fine-tuning improved the *abstention* mechanism substantially
even though it did not improve confidence calibration on the answers.

---

## 4. Task 4 — domain and module stratification

`out/char_task4_strata.json`. `dictionary.json` carries **no domain or topic tag** — its only
grouping fields are `module`, `construct_key`, `group_key` and the qid grammar. Domains are
therefore assigned by a priority-ordered keyword regex against the target's cleaned **stem**
(first match wins), committed in `src/char_strata.py::DOMAIN_KEYWORDS`. The pattern list was
extended once on corpus-coverage grounds — the first version left 25% of targets
unclassified, dominated by the `m2:Q5.x` "first told that you had ⟨condition⟩" block and the
`m2:Q19–23.x` named-drug block — not on the basis of any recall number.

> **Premise correction.** The brief states "~730 cancer-history constructs, 71
> chronic-condition, 11 SES/employment, 5 cancer-screening". SES (**15–16**) and
> cancer-screening (**5**) are right. **Cancer is not 730**: the corpus has **170 cancer
> constructs / 271 targets**. 730 is close to module 2's construct count (749); 1,331
> *dictionary entries* match a cancer pattern, but those are roster expansions that fold to
> 170 constructs. The imbalance is real but ~1.6 : 1 at target level, not 66 : 1.

**By module** (`bge-small` fine-tuned; frozen shown for contrast):

| module | corpus targets | fixture rows | ft R@1 | ft R@10 | frozen R@1 |
|---|---|---|---|---|---|
| 1 — contact, roster, demographics | 70 | 4 | 0.750 | 1.000 | 0.000 |
| 2 — conditions, insurance, utilisation, residence | 954 | 152 | 0.605 | 0.908 | 0.388 |
| 3 — activity, tobacco, alcohol, sleep, neighbourhood | 329 | 68 | 0.471 | 0.941 | 0.368 |

**By domain** — and this is the table that matters:

| domain | corpus targets | corpus constructs | fixture rows | ft R@1 | ft R@10 | frozen R@1 |
|---|---|---|---|---|---|---|
| cancer_history | 271 | 170 | 80 | 0.613 | 0.912 | 0.375 |
| healthcare_util | 167 | 75 | 12 | 0.667 | 0.917 | 0.583 |
| medication | 144 | 144 | 32 | 0.625 | 0.969 | 0.281 |
| tobacco | 138 | 110 | 20 | 0.350 | 0.850 | 0.250 |
| chronic_condition | 105 | 103 | 8 | 1.000 | 1.000 | 0.875 |
| **residence_commute** | 97 | 91 | 16 | **0.062** | 0.688 | 0.188 |
| physical_activity | 77 | 64 | 32 | 0.656 | 0.969 | 0.375 |
| family_roster | 40 | 30 | 4 | 0.750 | 1.000 | 0.000 |
| reproductive_hormonal | 36 | 36 | 8 | 0.750 | 1.000 | 0.375 |
| **sleep** | 30 | 26 | 4 | **0.000** | 1.000 | 0.000 |
| alcohol | 29 | 28 | 8 | 0.500 | 1.000 | 1.000 |
| *unclassified (survey admin)* | 158 | 138 | **0** | — | — | — |
| **demographics** | 26 | 17 | **0** | **unmeasured** | — | — |
| **ses_employment** | 16 | 15 | **0** | **unmeasured** | — | — |
| **insurance_access** | 14 | 14 | **0** | **unmeasured** | — | — |
| **cancer_screening** | 5 | 5 | **0** | **unmeasured** | — | — |

Strata are small — `sleep` is 4 rows (1 item), `chronic_condition` 8 rows (2 items) — so a
single row flip moves several of these by 12–25 points. 95% Wilson intervals are in
`out/char_task4_strata.json` on every cell; `chronic_condition` 1.000 means 8/8, with a
lower bound of 0.676, not "solved".

**Recall is not uniform, and it is worst exactly where the instrument is densest with
near-identical items.** `residence_commute` is **0.062** (1/16 rows) against 0.613 for
cancer — a 10× spread. R@10 for the same stratum is 0.688, also the worst: the commute
block (work address / school address / from-residence / to-residence, each with the same
option list) is the one place where the model does not even recover in the top 10. `sleep`
is 0/4 at rank 1 but 4/4 by rank 10 — a pure argmax-tie-break failure between the hour and
AM/PM subfields of the same question.

**The question the brief asks cannot be answered from existing data.** "A model at 0.75 on
cancer and 0.25 on SES has the same aggregate as one that is uniform" — but the 56-item
fixture contains **no SES/employment row, no insurance/access row, no cancer-screening row
and no demographics row at all**. Those four strata are 61 targets / 51 constructs of
instrument that the benchmark never touches. This is not a finding about the model; it is a
gap in the benchmark, and it is a concrete requirement for the study-team request set (§7).

**Fold class and sibling status** (unchanged from `RESULTS.md`, included for completeness):

| stratum | n | ft R@1 | ft R@10 | frozen R@1 |
|---|---|---|---|---|
| singleton | 168 | 0.577 | 0.935 | 0.399 |
| folded family | 56 | 0.536 | 0.875 | 0.304 |
| no siblings | 148 | 0.615 | 0.919 | 0.345 |
| has siblings (near-duplicate) | 76 | 0.474 | 0.921 | 0.434 |

---

## 5. Task 5 — the frozen deployment artifact

`deploy/`, built by `src/freeze_deploy.py`, 137.2 MB, 9 files, CPU-only. Five of the nine
are tracked in this public repository; `deploy/model/` (over GitHub's file limit) and
`deploy/targets.json` (question wording) are copied from the training machine and verified
by sha256 before anything loads.
**The bundle reproduces R@1 = 0.567 from its own frozen vectors** — asserted at build time
and re-asserted by `src/test_deploy_asserts.py`.

| | |
|---|---|
| checkpoint | `deploy/model/` — `model.safetensors` + tokenizer, CPU-loadable, fp32 |
| target vectors | `deploy/target_vectors.safetensors` — 1,353 × 384, **computed on CPU**, 2.0 MB |
| target set | `deploy/targets.json`, keyed to `dictionary_version_hash 3dc8415eccfe` |
| query prefix | `"Represent this sentence for searching relevant passages: "` — **recorded**, not inferred |
| pooling | CLS (not mean) — recorded |
| padding / dtype / max-len | right / float32 / 256 doc, 64 query — recorded |
| target-text rendering | `stem_option_dup` — recorded, with its definition *and* its measured worth |
| runtime | [`deploy/retriever.py`](deploy/retriever.py) — no `torch.load`, no pickle; safetensors both sides; thread count pinned to 4 from the manifest |
| template | [`deploy/template.py`](deploy/template.py) — the instances-only query template, re-exported by `retriever.py` (added by the CPU port) |
| acceptance test | [`deploy/smoke_test.py`](deploy/smoke_test.py) — exits 0 only if arms S, F and I reproduce to the digit; passed on the Spark and on the x86 serving machine ([`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json)) |
| CPU encode-all | 19.2 s at default threads (`out/final_bge-small_ft.json`); 21.0 s at the pinned 4 threads on the Spark (smoke report), about 21 s at the current freeze (`deploy/manifest.json::measured.cpu_encode_all_targets_s`, regenerated on each freeze); 57.9 s on the serving machine ([smoke report](out/smoke_report_x86_64_Wright.json) `reencode.wall_s`). The original freeze printed 18.2 s and a contended first build 34.8 s; neither manifest survives, so those two are unsourced. |

**Hash assertion fails, it does not warn** — and this is tested, not asserted in prose.
`src/test_deploy_asserts.py` tampers with a copy of the bundle three ways and requires each
to raise. **4/4 pass:**

| tamper | result |
|---|---|
| untampered bundle | loads, scores R@1 0.567 ✅ |
| `targets.json` from a different dictionary | `DictionaryHashMismatch` ✅ |
| any shipped file modified after freezing | `BundleIntegrityError` (sha256 in the manifest) ✅ |
| vector row order permuted | `BundleIntegrityError` (row *i* must be `target_id` *i*+1) ✅ |

**Device pinned to CPU, threads pinned to 4.** `retriever.py` has no device parameter; it
reads the thread count from the manifest unless the caller overrides it, because an
unpinned count makes latency unreproducible across machines. Vectors are bit-identical
across rebuilds (`sha256 941dd61a…b96a4` twice), so CPU encoding is deterministic here.
Incidentally, the row that motivates the pin — row 107, *"primary method used to get to
work"*, the single GPU/CPU disagreement at max vector delta 4.06e-7 — scores **cos 0.6239**,
below the abstention threshold. The bundle refuses that query anyway.

**Abstention is wired in.** `select()` applies `min_cos = 0.729476` (the knife-edge value,
§3) and returns `None` below
it; `search()` returns the top-k unfiltered and lets the caller decide. The threshold was
chosen by maximising F1 **on the 224 positives only**; the 44 negatives were then used to
*report* that it rejects 43/44, not to select it. The manifest records this, records the
stricter 0.7722 option, and records what the threshold does **not** do. Smoke test:

```
'exogenous hormone medication'                    -> m2:Q9.95   cos 0.7413
'primary method used to get to work'              -> ABSTAIN (0.6239)
'ambient PM2.5 exposure at the residential address' -> ABSTAIN (0.5912)
'polygenic risk score for breast cancer'          -> ABSTAIN (0.7041)
```

The manifest also carries the four `known_limitations` from §1–§4 in machine-readable form,
so they travel with the artifact rather than living only in this document.

---

## 6. The two confirmations

### 6a. `stem_option_dup` on the full corpus — **confirmed**

The +8.2 R@1 ablation was measured on the superseded 1,241-target / 208-row subset (built by
the since-deleted root `build.py` target builder, which dropped free-text rows). Re-run
at 1,353 targets / 224 rows, `bge-small` frozen, CPU (`out/gate_full_*.json`):

| rendering | R@1 | R@5 | R@10 | singleton R@1 | **folded-family R@1** | near-dup R@1 |
|---|---|---|---|---|---|---|
| **`stem_option_dup`** | **0.375** | 0.750 | 0.866 | 0.399 | **0.304** | 0.434 |
| `stem_option` | 0.295 | 0.719 | 0.857 | 0.363 | 0.089 | 0.224 |
| `verbatim` | 0.281 | 0.705 | 0.835 | 0.369 | 0.018 | 0.158 |
| `stem_dash_option` | 0.272 | 0.714 | 0.848 | 0.345 | 0.054 | 0.158 |

**+8.0 R@1 points** over `stem_option` on the full corpus, against +8.2 on the old subset.
Confirmed, and `stem_option_dup` still wins every cut.

The full corpus also exposes the **mechanism**, which the old subset did not: the gain is
almost entirely **folded-family recall — 0.304 vs 0.089** (and 0.018 for `verbatim`).
Duplicating the stem when a target has no option is what makes a folded roster
representative retrievable at all. `RESULTS.md` §5 attributes the gap to "top-of-list
precision"; that reading should be updated.

### 6b. The Qwen3-Embedding discrepancy — **resolved, and the stated premise is wrong**

The brief describes two independently written harnesses disagreeing on `qwen3-06b`
(0.362 vs 0.375) because of its last-token pooling / left-padding / instruction-prefix
convention.

**Two corrections.** First, I cannot find 0.362 anywhere in the tree; the only
`qwen3-06b` values recorded are **0.379** (`out/frozen_sweep.log`) and **0.375**
(`out/refp32.log`, and `out/frozen_qwen3-06b.json`, the published one). Second, both come
from the **same harness** (`src/compass_score.py`) on the same targets and fixture — the
difference is not two implementations of a convention.

**The cause is the load dtype.** `transformers` v5 honours a repo config's declared dtype;
the fp32 re-run forces `dtype=torch.float32`. Loading `qwen3-06b` in its config-declared
bfloat16 (new diagnostic flag `--dtype-from-config`) reproduces `frozen_sweep.log`
**line for line** — `out/diag_qwen3-06b_dtype_from_config.json`:

| | pre-fp32 log | diagnostic re-run (bf16) | published (fp32) |
|---|---|---|---|
| R@1 / R@5 / R@10 | 0.379 / 0.808 / 0.902 | **0.379 / 0.808 / 0.902** | 0.375 / 0.808 / 0.902 |
| rank p50/p90/max | 2 / 10 / 91 | **2 / 10 / 91** | 2 / 10 / 91 |
| singleton / folded R@1 | 0.452 / 0.161 | **0.452 / 0.161** | 0.446 / 0.161 |
| near-dup ratio | 0.625 | **0.625** | 0.632 |
| top-1 errors | 139 (132 wrong-construct) | **139 (132)** | 140 (133) |
| sibling cos p50 / p90 | 0.8498 / 0.9255 | **0.8498 / 0.9255** | 0.8498 / 0.9242 |

**And the declared dtypes explain the exact pattern the brief observed.** Every model with a
*measured* pre/post pair changed if and only if its config declares a non-fp32 dtype:

| model | config dtype | pre-fp32 | fp32 | changed? |
|---|---|---|---|---|
| `bge-small` | float32 | R@1 0.375 | R@1 0.375, all figures identical | no |
| **`qwen3-06b`** | **bfloat16** | R@1 0.379 | R@1 0.375 | **yes, −0.004** |
| **`gte-mbert`** | **float16** | R@1 0.384 | R@1 0.388 | **yes, +0.004** |
| **`granite-s2`** | **bfloat16** | R@1 0.263 | R@1 0.312 | **yes, +0.049** |
| **`mxbai-l1`** | **float16** | R@1 0.469, R@5 0.804 | R@1 0.469, R@5 **0.808** | **yes, below R@1** |
| `bge-base`, `e5-base`, `nomic-v15`, `embeddinggemma` | float32 | — | published values | *not re-run; a no-op by the rule above, inferred not measured* |

(Sources: `out/frozen_sweep.log` and `out/round2.log` for pre-fp32; `out/refp32.log` and
`out/recheck_frozen_mxbai-l1.json` for fp32.)

So `qwen3-06b` is **not** the only affected config — `granite-s2` moved by 4.9 points, more
than ten times as much, and `mxbai-l1` moved below R@1 — and the affected set is exactly the
non-fp32 configs. `RESULTS.md`
publishes the fp32 numbers throughout, which is the right choice; the forcing line in
`compass_score.py` is doing real work and should not be removed. The `--dtype-from-config`
flag added for this diagnosis is documented as diagnostic-only.

---

## 7. What this does not settle, and the one measurement that would

Now more sharply specified, and narrowed once since the brief. R@1 0.567 carries register
alignment: the same generator family wrote the 224 fixture queries and the 13,528 training
pairs, and an unknown share of the +0.192 over frozen `bge-small` is that alignment. The
fixture's declared *lexical leakage* bias, which this section originally listed alongside
it, was then measured and does not survive (`FUSION.md` §1): item-level Spearman between
query/gold word overlap and rank-1 is −0.023 (permutation p 0.867), R@1 by overlap quartile
is 0.482 / 0.554 / 0.643 / 0.589, non-monotonic, and flat within every query-length
stratum. `deploy/manifest.json::known_limitations[0]` carries the same correction.

The measurement that settles it is a request set written by the study team **without sight
of the instrument**. §1–§4 change what it costs: the model is now described, so an unbiased
set validates a description rather than producing one more headline number. Two things this
work adds to the ask:

1. **It must cover the four unmeasured strata.** SES/employment, insurance/access,
   cancer-screening and demographics have **zero** rows in the current fixture (§4). A
   40–60 request set that reproduces the existing distribution would leave the same hole.
   Suggested floor: ≥ 5 requests each for SES/employment and insurance/access, ≥ 3 for
   cancer-screening (only 5 constructs exist), ≥ 5 for residence/commute (the worst
   stratum, 0.062).
2. **It should include requests for things the instrument does not have.** The 44
   model-authored negatives give an abstention threshold that works (§2–§3), but the
   threshold is derived from a model's idea of an absent construct. Ten or fifteen genuine
   "we wanted X and you don't collect it" requests from the study team would validate it.

**Constraints observed.** The checkpoint was not retrained, re-tuned or changed. The
negatives were not used to tune anything (the threshold is selected on positives; negatives
only report). The 224-row fixture, gold rule and `build.py` at `3dc8415eccfe` are untouched.
The frozen fallbacks still run and still reproduce: `bge-small` frozen 0.375 and
**`mxbai-l1` frozen 0.469** (`out/recheck_frozen_mxbai-l1.json`, every reported figure
identical to `out/frozen_mxbai-l1.json`). The only change to an existing script is the
additive, default-off `--dtype-from-config` flag on `compass_score.py`.

---

*Generated 2026-09-03 from `out/char_*.json`, `out/gate_full_*.json`,
`out/diag_qwen3-06b_dtype_from_config.json`, `out/negatives_absence_check.json`,
`fixtures/negative_requests.json` and `deploy/manifest.json`.*
