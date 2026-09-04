# Arm D — whole-dictionary in-context selection

**Measured 2026-09-02.** Build `3dc8415eccfe`, model `claude-haiku-4-5`, prompt
`3a28d114ff64`, artifact `run/arm_d.claude-haiku-4-5.3a28d114ff64.json`.
Fixture `benchmark/fixtures/retrieval_queries.json`, 224 rows, unchanged.
Reproduce: `python -m generate.arm_d measure` (training machine only: the artifact under
`run/` and the fixture are withheld from the public repository).

## Verdict

**Arm D loses, and it loses in the aggregate rather than on near-duplicates.**
It is the best single-answer arm by a wide margin and it does not beat a deep
ranked pool. C16 and C17 are not moot.

---

## 1. The comparison

| arm | gold_excluded | @1 | @5 | @10 |
|---|---|---|---|---|
| control | 18/224 | 0.152 | 0.415 | 0.536 |
| min_rank | 0/224 | 0.152 | 0.438 | 0.549 |
| rrf | 0/224 | 0.192 | 0.469 | 0.567 |
| **arm D** | **0/224, by construction** | **0.402** | — | — |

Arm D returns a selection, not a ranking, so it has no @5 or @10. Its figure is
an exact-match rate, and the only honest column to read it against is **@1**:

| figure | arm D | best lexical |
|---|---|---|
| exact match / recall@1 | **40.2%** (90/224) | 19.2% (rrf) |
| the same, on singleton rows | **45.2%** (76/168) | — |
| gold among *any* returned index | 51.8% (116/224) | — |
| gold anywhere in a pool a screen could read | — | **56.7%** @10 (rrf) |

**Arm D is 2.1× the best lexical arm at rank 1 and below every arm at rank 10.**
That is the whole result. It answers, it answers better than any single lexical
guess, and it answers less often correctly than a screening stage reading ten
candidates would.

`gold_excluded 0/224` is real but carries no information: nothing filters, so
nothing can be excluded. It is a property of the design, not a measurement of it.

### Match rule, stated explicitly

A candidate is a `(construct, option)` after roster members are folded together
— 1,400 options under 1,080 stems, from 2,804 dictionary rows. A row is a match
when **the gold key is one of the keys the selected candidate stands for**
(*folded*), using the first returned index.

This is a documented departure from the retrieval gold rule, and it is more
permissive. What separates 20 roster members of one option in `question_text` is
a leaked piped Qualtrics reference (`- 1_Q16.9#1 - 1 -`), which `TASKS.md` R9
names as the only discriminator for 44 of the 224 rows. The catalogue strips it,
so those rows are one candidate and row-level wording equality cannot be applied.
The **singleton** figure (45.2%, on the 168 rows whose gold candidate stands for
exactly one key) is the apples-to-apples number; the folded figure is what the
arm can actually be asked to do. One residual collision: two distinct gold items
fold into the single candidate `m2:Q16.8 / Cancer of the esophagus`.

---

## 2. Abstention — where arm D actually loses

| verdict | n | % | folded match | gold among returned indices |
|---|---|---|---|---|
| `resolved` | 113 | 50.4% | 79 | 83 |
| `family` | 21 | 9.4% | 11 | 12 |
| `derive` | 30 | 13.4% | 6 | 16 |
| `ambiguous` | 55 | 24.6% | 2 | 5 |
| `absent` | 5 | 2.2% | 0 | 0 |
| malformed | 0 | — | — | — |

**Precision when it commits: 67.2%** (90 of 134 decisive rows). **It commits on
only 60% of rows.**

The failure is not false confidence. It is the opposite:

- **`ambiguous` on 24.6% of rows, and in only 5 of those 55 was the gold item
  even among the indices offered as the ambiguity.** So this is not a model
  hedging between the right item and its neighbour — on 50 of 55 it had not
  located the right item at all and said so. That is honest, and it is a miss.
- **`derive` on 13.4%**, with gold among the named inputs 16 times. Half of
  these are defensible readings of a request that spans several items.
- **`absent` on 5 rows, all false** by the gold rule. Every fixture row has a
  gold item, so every `absent` is an error. The five:
  `m3:Q2.25` "outdoor hours", `m3:Q2.55` "stretching frequency",
  `m2:Q27.12` "commute route", `m2:Q9.91` "age started birth control pills",
  `m2:Q9.91` "age when first used combined birth control". Three of these are
  requests the lexical arms also failed on; "stretching frequency" is one of the
  18 rows the control could not reach at any rank.

**The ADR 003 worry did not materialise.** Prior-art system 1 instructs its model
against abstaining; this system's measured failure was five false positives in 21
rows. Removing the filter did *not* push the model into confident wrong answers:
false `absent` is 2.2%, and the dominant non-answer is `ambiguous`, which names
its own uncertainty. If anything the pressure ran the other way — arm D abstains
or defers on 40% of rows.

---

## 3. Near-duplicates — the predicted failure did not appear

This was the stated long-context risk: 22 cancer types differing by one word in a
flat list of 1,400 is where attention should degrade.

| cut | rows | exact match, folded |
|---|---|---|
| gold in a construct with **more than one option** | 76 | **39.5%** (30/76) |
| gold in a **single-option** construct | 148 | **40.5%** (60/148) |

**A one-point difference. Flat-list near-duplicates cost arm D essentially
nothing.** If arm D had failed here, the fix would have been the rendering. It
did not, so the rendering is not the problem.

A *different* cut does show degradation, and it is worth separating:

| cut | rows | exact match |
|---|---|---|
| gold candidate stands for **one** key | 168 | **50.0%** (84/168) |
| gold candidate stands for **many** keys (a roster family) | 56 | **25.0%** (14/56) |

Roster-family rows are half as accurate. That is not a near-duplicate problem —
those rows are folded to *one* line each, so there are fewer lookalikes, not more.
It is that a request naming no particular family member genuinely underdetermines
the answer, which is what `family` exists to express: all 21 `family` verdicts
fall on these rows, and 11 of 21 are right. The remainder scatter into
`ambiguous` (14) and `derive` (11).

---

## 4. Token cost

Prompt caching applied, and getting it to apply dictated the prompt's shape.

| | |
|---|---|
| rows called | 221 distinct requests |
| cache **read** per row | median 40,584 tokens |
| cache **created** per row | median 2,495 (only 4 rows created >30k) |
| output tokens per row | median 1,659, max 7,738 |
| cost per row | median **$0.0183** |
| total | **$4.74** |

The expected shape — one full read plus short suffixes — held. Four full
creations, one per worker thread, because each thread runs its own sealed
worktree.

**This only works with the instrument as the system prompt.** Measured on the
same catalogue with the request appended to the *user* prompt: 38,084 tokens
re-created every row, $0.081–0.145 per row, no cache read at all — 3–5× the cost.
`agent/prompt_contract.py::catalogue_contract` therefore names no request; the
request is the user turn. Output tokens are the real remaining cost: the model
reasons over the whole instrument, and a row that went to 7,738 output tokens
cost more in generation than in context.

---

## 5. Three things building it found

**a. The structural fold is coarser than the gold rule.** Collapsing on
`(construct, subitem, matrix_col, matrix_block)` gives 1,399 slots but hides 507
distinct normalised wordings across 45 of them, and 11 of the fixture's 56 gold
items live in those slots. Any arm built on that collapse would be scored against
candidates it was never shown. Hence the two match rules above.

**b. A numbered catalogue collides with numeric markers, permanently.** The first
rendering fired two markers in `check_markers` — both were *index positions*, not
figures, and every numeric marker below 1,400 collides with a position forever.
Two changes, both applying rules the codebase already had rather than exempting
the surface:

- catalogue indices are `i`-prefixed, so a position is lexically not a number;
- `check_markers` now matches *numeric* markers at a number boundary
  (`(?<!\w)…(?!\d)`), the same boundary `check_markers_are_not_instrument_content`
  already used on the other side of that file. Non-numeric markers keep substring
  matching. Cost, stated in the docstring: a numeric marker glued to the right of
  a word character no longer fires. Four leak forms are planted as positive
  controls in `tests/test_specifier.py`.
- The three-digit marker that fired moved to `benchmark/leak_facts.py`, where
  `_published_n_tokens`' own four-digit rule says short n belong. Its retention
  comment read "it has never fired"; that stopped being true.

**This is an amendment to a contamination control and wants your review.** The
file scan then caught the report author writing a published analytic n into
`env/labels.py` while documenting it — the control worked.

**c. `--append-system-prompt-file` is accepted and silently ignored** by this CLI
build (probed behaviourally: a system prompt demanding a fixed word had no effect
on the reply). So the whole prompt must fit one `exec` argument. At 131,283 bytes
it exceeded Linux's `MAX_ARG_STRLEN` of 131,072 and failed all 221 rows of a live
pass with `Errno 7`, which reads exactly like a model refusal. The rendering is
trimmed to 127,083 chars and `tests/test_catalogue.py::test_the_whole_prompt_fits_one_exec_argument`
pins it with 2 KB of headroom.

---

## 6. What this does not settle

The fixture's `KNOWN_BIAS` is that its queries were written by a model that had
seen each gold item's wording. **That bias plausibly favours arm D more than the
lexical arms** — a model reading every candidate is helped most by a request
already phrased in the instrument's own words. Arm D's 40.2% is an upper bound
under a bias that flatters it, and it still loses to a ranked pool at @10.

The follow-up that would settle it is a request set written without sight of the
instrument, not a migration.

## 7. Implications

- **C16 and C17 are not moot.** Arm D does not remove the need for a screening
  stage; at the depth a screen reads, the lexical arms are ahead.
- **Arm D is the best *selector* measured.** If a stage needs one answer rather
  than a pool — a confirmation step, a prose resolver — 40.2% with a 67.2%
  commit-precision and a 2.2% false-absent rate beats taking any lexical arm's
  top hit at 15–19%.
- **The obvious hybrid is untested and cheap:** hand arm D the fused pool from
  `rrf` (which contains the gold item for 56.7% of rows at depth 10, 92% at depth
  250) instead of all 1,400 candidates. That is C17 with a different candidate
  source, and it is the experiment this result points at.
- **Do not degrade the lexical arms.** They remain ahead where a pool is what is
  wanted, and the comparison has to stay runnable.
