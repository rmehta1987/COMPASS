# Hybrid E→D, and the arm E encoder sweep behind it

**Measured 2026-09-02/03.** Build `3dc8415eccfe`. Fixture
`benchmark/fixtures/retrieval_queries.json`, 224 rows, unchanged. Targets
`targets.json` (1,352, byte-reproducible from the build). Selector
`claude-haiku-4-5`, one call per row (k=1), `VariableSelection` unchanged.

Artifacts: `run/hybrid_ed.bge-large.d{10,25,50}.json`,
`run/hybrid_pools.bge-large.json`, `arm_e2.*.json` (9 encoder configs).

```
python build_targets.py --dictionary build/dictionary.json --out targets.json
python encode_and_score.py --targets targets.json \
    --fixture benchmark/fixtures/retrieval_queries.json \
    --model <config> --dictionary-hash 3dc8415eccfe --out arm_e2.<config>.json
python -m generate.hybrid_ed pools   --config bge-large
python -m generate.hybrid_ed produce --config bge-large --depth {10,25,50}
python -m generate.hybrid_ed measure --config bge-large
```

---

## Verdict

**The hybrid is refuted, on the leading indicator the brief nominated.** Commit
rate does not rise when the pool shrinks — it *falls*, from 59.8% to ~54%, and
stays flat across all three depths. End-to-end lands at 0.357–0.388, below arm
D's 0.402 and far below the pool's own argmax at 0.460.

**And the sharper finding: the LLM selector is net-negative against taking the
embedding model's top hit.** At every depth it rescues fewer rows than it
destroys — −16, −23, −20 of 224. Deleting the selector entirely and returning
`bge-large`'s rank 1 scores **0.460**, the best single number any arm has
produced on this fixture.

---

## 1. Task 0 — the free-text exclusion (blocking, done)

`build_targets.py` excluded 43 direct identifiers **and 151 free-text rows**.
Only the first was governance. Verified against `build/dictionary.json`: all four
gold items the second dropped are `is_free_text=True`, none is a direct
identifier, and the identifier exclusion costs **zero** fixture rows.

| gold key | rows | is_free_text | is_direct_identifier |
|---|---|---|---|
| `m2:Q9.96` | 4 | true | false |
| `m2:Q776` | 4 | true | false |
| `m3:Q15.9_4_TEXT` | 4 | true | false |
| `m3:Q870_2` | 4 | true | false |

Removed. **1,352 targets (not the ~1,392 predicted** — the 151 restored rows
mostly fold into existing `(construct, subitem, matrix_col)` groups rather than
each creating one; members went 2,610 → 2,761). **224/224 reachable.** Every
config below is re-scored on this denominator.

The correction barely moved the numbers — `medcpt-a` @10 went 0.808 → 0.799 —
because the restored rows are hard for every config. The denominator is now
honest regardless.

---

## 2. Task 1 — the encoder sweep, nine configs

All on 224 rows, `rows scored 224, gold not a target: 0`.

| config | params | @1 | @5 | @10 | @25 | @50 | p50 | p90 | max | encode | ms/query |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **bge-large** | 335M | **0.460** | 0.790 | **0.906** | 0.951 | **0.987** | 2 | 10 | 154 | 604 s | 81.1 |
| embeddinggemma | 300M | 0.371 | 0.795 | 0.897 | **0.964** | 0.982 | 2 | 11 | **81** | 974 s | 222.9 |
| qwen3-0.6b | 595M | 0.362 | **0.812** | 0.884 | 0.929 | 0.969 | 2 | 12 | 584 | 8,699 s | 1,415 |
| bge-base | 109M | 0.379 | 0.754 | 0.862 | 0.955 | 0.973 | 2 | 16 | 134 | 208 s | 27.4 |
| bge-small | 33M | 0.375 | 0.750 | 0.866 | 0.938 | 0.964 | 2 | 14 | 198 | 43 s | 5.5 |
| bge-small-noprefix | 33M | 0.344 | 0.723 | 0.844 | 0.933 | 0.969 | 2 | 17 | 217 | 85 s | 4.8 |
| biolord | 109M | 0.366 | 0.723 | 0.844 | 0.920 | 0.960 | 2 | 22 | 531 | 165 s | 15.7 |
| medcpt-b | 109M | 0.254 | 0.737 | 0.826 | 0.906 | 0.955 | 3 | 24 | 413 | 155 s | 12.2 |
| medcpt-a | 109M | 0.259 | 0.670 | 0.799 | 0.893 | 0.920 | 3 | 28 | 359 | 162 s | 34.6 |

Machine: 14 cores, 9.9 GB RAM, CPU only, `torch 2.14.0+cpu`,
`transformers 5.16.1`. Peak RSS: bge-small 0.74 GB, bge-base 1.27 GB, bge-large
2.14 GB. EmbeddingGemma ran with `OMP_NUM_THREADS=6` (sharing the box with
Qwen3), so its 222.9 ms/query is an overestimate.

### 2a. Parameter count is not the axis

The brief's interpretation rule was "if `bge-large` adds under ~3 points at @10,
treat capacity as saturated." It added **+4.0**, which reads as capacity binding
— until the two larger models land:

| params | model | @1 | @10 |
|---|---|---|---|
| 33M | bge-small | 0.375 | 0.866 |
| 109M | bge-base | 0.379 | 0.862 |
| 300M | embeddinggemma | 0.371 | 0.897 |
| 335M | bge-large | **0.460** | **0.906** |
| 595M | qwen3-0.6b | 0.362 | 0.884 |

**Three models at 300M–595M score 0.371, 0.460 and 0.362 at @1.** The largest is
the *worst* — below the 33M model — at 14× bge-large's encode time and 17× its
query cost. Whatever `bge-large` has is specific to that checkpoint, not to its
size. A two-point curve would have concluded "capacity binding" from
109M→335M and "capacity saturated" from 335M→595M; both would be wrong.

**This is the strongest evidence in the project against scaling the base model,
and it bears directly on fine-tuning.** Scaling is now measured and does not pay
monotonically.

### 2b. Task 2 — the prefix confound, closed the other way

The brief asked for BioLORD with an instruction prefix from its model card.
**Its card documents none** — it is described as a symmetric sentence-similarity
model with mean pooling and identical treatment of both sides. Inventing a prefix
would be authoring a convention. The confound is closed from the other side
instead, with `bge-small`'s own documented prefix removed:

| config | @1 | @5 | @10 |
|---|---|---|---|
| bge-small **with** prefix | 0.375 | 0.750 | 0.866 |
| bge-small **no** prefix | 0.344 | 0.723 | 0.844 |
| biolord (no prefix, as documented) | 0.366 | 0.723 | 0.844 |

**On equal footing they are identical at @5 and @10, and BioLORD is ahead at
@1.** The earlier claim that a general-purpose model beats the biomedical
specialists was the prefix, not the model. `docs/arm-e-configs.md` has been
corrected.

The prefix is worth +0.022 at @10 — **more than tripling the parameters from 33M
to 109M**, which bought −0.004.

### 2c. Conventions read, not assumed

Two models needed handling the script did not have. Both were read from the
source rather than inferred from the BGE shape:

- **Qwen3-Embedding-0.6B**: last-token pooling, left padding, queries carry
  `Instruct: {task}\nQuery:{q}`, documents carry none, L2-normalised. Added
  `pool="last"` indexing the last **non-pad** token — the card's stated
  equivalent for right-padded input — rather than flipping the padding side
  under every other config. The card warns that omitting the instruction costs
  1–5%.
- **EmbeddingGemma-300m** (gated; read at revision `57c266a740f5` after
  authentication): pooling `mean` confirmed from `1_Pooling/config.json`, prompts
  confirmed verbatim (`task: search result | query: ` /
  `title: none | text: `). Its `modules.json` is
  **`[Transformer, Pooling, Dense, Dense, Normalize]`** — two 768→3072→768 linear
  layers, no bias, Identity activation. `AutoModel` + pool + normalise skips
  both and embeds in the pre-projection space, which is not the published model.
  Added `load_dense()` and a `d_prefix` mechanism (EmbeddingGemma is the first
  config whose query and document prompts differ).

  **Every other config was checked for the same trap** — BGE ×3 and Qwen3 are
  `[Transformer, Pooling, Normalize]`, BioLORD is `[Transformer, Pooling]`. None
  has a post-pooling head, so no earlier result is affected.

### 2d. Near-duplicate skill, as a ratio to each config's own baseline

Raw near-duplicate accuracy conflates near-duplicate skill with general skill, so
each config is scored against its own overall @1. n = 76 rows whose gold sits in
a construct with more than one option.

| config | overall @1 | near-dup @1 | **ratio** | near-dup @10 | sibling cos p50 |
|---|---|---|---|---|---|
| bge-large | 0.460 | **0.605** | **1.32** | 0.974 | 0.8880 |
| bge-small-noprefix | 0.344 | 0.421 | 1.22 | 0.921 | 0.9099 |
| bge-small | 0.375 | 0.434 | 1.16 | 0.921 | 0.9099 |
| bge-base | 0.379 | 0.355 | 0.94 | 0.895 | 0.8777 |
| biolord | 0.366 | 0.329 | 0.90 | 0.855 | 0.6892 |
| qwen3-0.6b | 0.362 | 0.316 | 0.87 | 0.921 | 0.8516 |
| medcpt-a | 0.259 | 0.184 | 0.71 | 0.711 | 0.9248 |
| embeddinggemma | 0.371 | 0.250 | 0.67 | 0.882 | 0.8505 |
| medcpt-b | 0.254 | 0.158 | 0.62 | 0.803 | 0.9698 |

**`bge-large` is the only config that is substantially better on near-duplicates
than on the fixture as a whole**, and it is best in absolute terms by a wide
margin — 0.605 against a field of 0.158–0.434. Since near-duplicates are 76 of
224 rows, this is most of where its @1 lead comes from. The three BGE models
below it cluster at 0.94–1.22; everything else is worse on near-duplicates than
on its own average.

**Sibling cosine does not predict any of it.** Over the nine configs the
correlation between sibling cosine p50 and the near-duplicate ratio is
**−0.023** — no relationship at all. The extremes make the point without the
statistic: BioLORD separates sibling options far better than anything else in the
space (0.689) and lands mid-table at 0.90; `medcpt-b` has the tightest sibling
cluster (0.970) and the worst ratio (0.62); `bge-large` sits in the middle of the
cosine range (0.888) and wins outright. EmbeddingGemma has the second-best
separation and the second-worst ratio.

This is now measured on nine configs rather than four, and it is the second
independent reason to doubt fine-tuning's obvious lever: **in-construct
hard-negative training optimises sibling separation, which is uncorrelated with
the outcome it is supposed to improve.**

---

## 3. The hybrid

Pool `bge-large`, chosen on coverage at depth 10–25. The choice was close
(`embeddinggemma` wins @25 by 3 rows, `bge-large` wins @10 by 2 and @50 by 1);
the tiebreak was that `bge-large`'s argmax of 0.460 sets the harder bar.

**Pools verified before spending anything**: the cached top-50 reproduces the
encoder run exactly — coverage 0.906 / 0.951 / 0.987 at the three depths.

### 3a. Results

| | arm D | depth 10 | depth 25 | depth 50 |
|---|---|---|---|---|
| coverage | 1.000 | 0.906 | 0.951 | **0.987** |
| **1. commit rate** | **0.598** | **0.554** | **0.531** | **0.545** |
| 2. precision when committed | 0.672 | 0.702 | 0.672 | 0.680 |
| 3. conversion | 0.402 | 0.388 | 0.357 | 0.371 |
| **4. END-TO-END over 224** | **0.402** | **0.388** | **0.357** | **0.371** |
| singleton subset (n=168) | — | 0.411 | 0.357 | 0.375 |
| input tok/row (median) | ~40,600 cached | 3,439 | 3,939 | 4,851 |
| output tok/row (median) | 1,659 | 2,005 | 2,416 | 2,066 |
| $/row (median) | 0.0183 | 0.0196 | 0.0230 | 0.0239 |
| total $ | 4.74 | 4.94 | 5.63 | 5.99 |

**Two baselines, because the pool's own top-1 beats the selector:**

- **0.402** — arm D over all 1,400 candidates (the brief's threshold)
- **0.460** — `bge-large` argmax, no model call, ~81 ms

**No depth clears either.** Best is 0.388 at depth 10.

### 3b. The decision rule, applied

> *"Commit rate flat at ~60% at every depth → hypothesis refuted, stop."*

Commit rate is flat at **53–55%**, below arm D's 59.8%, at every depth. The
hypothesis was that a small pool raises the commit rate; it lowered it. **Stop.**

Precision behaved as the arithmetic required (67.2% → 70.2% at depth 10) and it
does not matter: at a 55% commit rate, clearing 0.460 would need 83% precision.

Conversion also *falls* as coverage rises — 0.388 at 90.6% coverage, 0.357 at
95.1%, 0.371 at 98.7%. Coverage rose 8 points from depth 10 to 50 and end-to-end
fell 1.7. The optimum is interior and shallow, which is the shape the brief
flagged as "the attention effect is real."

### 3c. Pool-missed vs could-not-choose

The label arm D's verdicts could not distinguish:

| depth | pool-missed | could-not-choose | ratio |
|---|---|---|---|
| 10 | 21 | 116 | 5.5× |
| 25 | 11 | 133 | 12.1× |
| 50 | **3** | **138** | **46×** |

**At depth 50 the pool fails 3 rows and the selector fails 138.** Making the
encoder better cannot help: 98.7% of rows already have the answer in front of the
selector. Every remaining point is selection.

By verdict, at depth 50: `ambiguous` 66, `resolved`-but-wrong 27, `derive` 23,
`family` 12, `absent` 10. **Ten rows returned `absent` with the answer sitting in
a 50-item list.**

`ambiguous` grows with depth — 61 → 68 → 68 — and at depth 10, 56 of the 61
`ambiguous` rows had gold **in the pool**. Handed ten cosine-ranked candidates
with the right one among them, the selector declines to choose more often than it
did facing 1,400 in instrument order.

### 3d. The selector is net-negative against argmax

The diagnostic that settles what the selector contributes:

| depth | committed | picked pos 1 (right/wrong) | picked 2–5 | picked >5 | **rescued** | **destroyed** | **net** |
|---|---|---|---|---|---|---|---|
| 10 | 124 | 84 (66/18) | 32 | 8 | 21 | 37 | **−16** |
| 25 | 119 | 80 (63/17) | 21 | 18 | 17 | 40 | **−23** |
| 50 | 122 | 83 (67/16) | 26 | 13 | 16 | 36 | **−20** |

*rescued* = gold was not at position 1 and the selector found it anyway.
*destroyed* = gold **was** at position 1 and the selector abstained or picked
something else.

**At every depth the selector destroys roughly twice what it rescues.** Two
thirds of its commitments are just position 1 — where it agrees with argmax and
adds nothing but latency and $0.02 — and on the third where it disagrees, it is
wrong more often than right.

This is not an attention failure. It is the selector treating a cosine-ranked
list as evidence of ambiguity: ten near-neighbours an embedding model ranked
adjacent are by construction mutually similar, which is exactly the input that
makes `ambiguous` the honest answer. Arm D's 1,400 in instrument order gave it
dissimilar neighbours and an easier discrimination.

---

## 4. Where every arm now stands

| arm | @1 / exact match | @10 | cost/row | reachability |
|---|---|---|---|---|
| control (lexical) | 0.152 | 0.536 | ~0 | 18/224 excluded |
| min_rank (C16) | 0.152 | 0.549 | ~0 | 0/224 |
| rrf (C16) | 0.192 | 0.567 | ~0 | 0/224 |
| arm D (1,400 in context) | 0.402 | — | $0.0183 | 0/224 |
| hybrid E→D, depth 10 | 0.388 | — | $0.0196 | 0/224 |
| **arm E argmax (bge-large)** | **0.460** | **0.906** | **~0** | 0/224 |

**The simplest arm wins.** A frozen 335M encoder, no LLM call, no prompt, no
catalogue: 0.460 exact match and 0.906 at depth 10, at ~81 ms and no marginal
cost.

---

## 5. Confounds, stated

**The comparison is tilted toward the embedding arms.** The fixture's
`KNOWN_BIAS` is that its queries were written by a model that had seen each gold
item's wording, which flatters paraphrase matching. Arm E's margin over the
lexical arms is the least trustworthy figure here. **Treat anything under ~0.45
end-to-end as unresolved** — which includes every hybrid depth, and puts arm E's
0.460 barely over the line.

**A conversion change cannot be attributed to pool size alone.** Arm D read 1,400
candidates in instrument order from a cached static system prompt; the hybrid
reads N in cosine order in a per-row user prompt. Size, relevance and caching all
moved together. The control that would isolate it — the same selector over a
random N containing gold — was worth running only if the hybrid won. It did not.

**Arm E's coverage multiplies into every hybrid figure** and carries the same
bias.

**The match rule is folded** at target level for both arm D and the hybrid: a row
is correct when the gold key's *target* is selected, and targets fold roster
members. More permissive than the row-level wording equality the lexical arms are
scored under. Singleton subsets are reported alongside.

---

## 6. What follows

1. **Do not tune the depth.** The rule was recorded before running and the
   leading indicator refuted the hypothesis; depth is not the free parameter.
2. **The unbuilt thing is still the same one.** A request set written without
   sight of the instrument. Every figure in every arm is an upper bound under a
   bias that favours semantic methods, and no further architecture comparison is
   worth more than removing that bias. Arm E's 0.460 sits close enough to the
   "unresolved" line that this is now decision-relevant, not hygiene.
3. **If a selector is wanted at all**, the measured question is no longer "pool
   or catalogue" but "why does a model shown the right answer at position 1
   abstain on it 37 times." That is a prompt and verdict-calibration problem,
   and it is cheap to probe: the same rows, the same pool, a prompt that says
   what `ambiguous` is *for*.
4. **Fine-tuning is weaker than before, on two independent grounds.** Scaling the
   base is measured and non-monotonic (§2a), and the near-duplicate lever that
   hard-negative training would pull does not correlate with the outcome (§2d).

---

## 7. Constraints honoured

Unchanged: `search_variables`, the fixture, the gold rule, `searchable_text`,
`SEARCH_SCORE_FLOOR`, `build.py` at `3dc8415eccfe`. The lexical arms and arm D
are untouched and still runnable. `env/` remains stdlib-only and model-free;
`ENV_MODEL_GRANTS` was not extended — the encoders run at the repo root, not
inside `env/`. `torch`/`transformers`/`numpy` are installed but undeclared in
`pyproject.toml`, so per `AGENTS.md` these arms are **measured, never an
acceptance gate**.

The hybrid's pool prompt joined `benchmark/contamination_check.py`'s scanned
surface (a deterministic pool is rendered, since the scan cannot import `torch`);
447 surfaces, clean.

**The `ruff` exclusion on `build_targets.py` and `encode_and_score.py` needs a
review date.** It was taken so two dropped-in scripts could not raise
`RUFF_CEILING` on code the ceiling is not about. Both have since been edited by
this work (`d_prefix`, `load_dense`, `pool="last"`, four new configs), so they are
no longer purely external. If arm E is adopted they move into `generate/` and
come under the standards; if it is not, the exclusion should be removed with the
scripts.
