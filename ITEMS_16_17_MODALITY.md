# Items 16 and 17 — modality on the request and the record

Report to the operator, 2026-09-07, written in `/home/mehta5/compass-gen` on branch
`ralph-loop` at `54a91fb`. Human-facing: nothing loads this file, it is outside
`tests/test_contamination_surface.py::SCANNED` (`curated`, `env`, `agent`), and the
in-pipeline Specifier cannot reach it — each headless run gets a `mkdtemp` cwd outside
the project (`agent/sealed.py::SealedWorktree.__init__`). Same standing as
`agent/RUNNING.md`.

Claims are tagged **ran** (this session, command and real output), **per the brief**
(repeated from the 2026-09-07 agent brief, not re-run here) or **UNVERIFIED**.

---

## Headline

**Both items landed and the gate is green.** **ran** `./check.sh`, unpiped, exit 0:

```
build 3dc8415eccfe  (2804 entries, 1080 distinct constructs)
1080 passed, 4 deselected in 39.41s
ruff 226 <= 232 ; mypy 59 <= 59
retrieval_eval ok
arm I through pipeline.retrieve: R@1 0.643 (144/224), abstained 15; smoke_test pins 0.643
canaries: 7/7 hold
pair m3:Q16.1 -> m2:Q5.8: both resolved = True
frame: live 256 (enumerated 384), both resolved 248, floor 248/256
gate: live 256, passed 0, blocked 256, allow_unestimable=False
missing exports: module_co_completion_counts, per_item_non_missing_counts
gate: live 256, passed 256, blocked 0, allow_unestimable=True
passed pairs carry estimability: blocked_no_metadata
smoke_test ALL PASS
tiered_score self-check: 6 components, 19 scoreable cells, 0 problems

GREEN
```

The baseline before this work, **ran** at `54a91fb`, was `1009 passed, 4 deselected`,
with the same ruff, mypy and R@1 figures. Test count rose by 71; no ratchet moved.

Files: `deploy/template.py`, `src/query_expand.py`, `pipeline/retrieval_record.py`,
`pipeline/intake.py`, `deploy/manifest.json`, `tests/test_modality.py` (new), one line of
`tests/test_retrieval_record.py`.

**The strongest objection, and it is not small: the field has no source to be populated
from, so on today's inputs every record the tiered harness scores will still read
`unknown`.** `posed_pairs.json` carries three fields and `pipeline/pose_terms.py::read_cases`
*actively raises* `LeakedField` on a fourth — `CASE_FIELDS = ("case_id", "exposure",
"outcome")`, `pipeline/pose_terms.py:59`. The inventory that knows each variable's modality
is on the scoring side. So item 16 gives the pipeline somewhere to put a declared modality
and closes the plumbing item 18 needs, but it does not by itself unblock the
`modality_mismatch` half of tiered item 8: that needs a decision on whether modality may
travel on the posed-pairs handoff, which means deliberately widening a leak guard. A user
amendment, not a lane's, so this report stops at surfacing it.

---

## Premise check (brief §0) — passed, with one correction

`RetrievalRecord` is in this repo (`pipeline/retrieval_record.py::RetrievalRecord`), as are
`deploy/`, `deploy/smoke_test.py` and `check.sh`. `RetrievalRequest` is defined **twice**:
`src/query_expand.py:156` is the source of truth and `deploy/template.py:98` is a verbatim
copy, per that file's own provenance note — "`RetrievalRequest`, `to_query`, `covered`,
`VariableRole` copied verbatim from src/query_expand.py". Both were changed; **ran**, the
inserted block is byte-identical between them: `Modality block identical: True 1385 1385`.

The treatment-role precedent exists but is named `role: VariableRole`, commented
`# NOT rendered`.

One correction to the brief: `deploy/smoke_test.py` is **check.sh step 10**, not step 2.
Step 2 is pytest.

No vocabulary was invented. `handoff/for_harness.json` already carries `modality_values`
— **ran**: `["self_report", "measured", "ehr", "assay", "linked", "administrative"]` — so
the enum is those six plus `UNKNOWN`, and a test reads that file and fails on drift.

---

## Item 16 — what landed

`Modality(str, enum.Enum)` with `UNKNOWN = "unknown"` first, carried as
`modality: Modality = Modality.UNKNOWN` on `RetrievalRequest` in both copies, at the end of
the field list so positional construction is unaffected. `RequestSnapshot` gained
`modality: str` with a written-out pattern rather than an import, because that module
deliberately holds no reference to the template; a test pins the two against each other.
`RequestSnapshot.from_request` reads it with `getattr(req, "modality", "unknown")` so a
bundle predating the field still snapshots cleanly.

`pipeline/intake.py::parse_request` gained a `modality` parameter and `--modality`,
validated against `modalities()`, which reads the template's own enum rather than restating
it. That is the caller-declaration seam. `auto_intake` and `pose_terms` leave the default,
because neither has a declaration available.

Nothing infers a modality from term text anywhere. Six parametrised tests assert that
wording naming a modality — `"measured blood pressure"`, `"self-reported hypertension"`,
`"EHR stroke diagnosis"`, `"clinic BMI"`, `"assayed cotinine"`, `"administrative claims for
type 2 diabetes"` — still yields `UNKNOWN`.

The record's module docstring said it "is written once and never backfilled: a field added
later would leave earlier artefacts incomparable". That claim is now qualified in place:
`modality` is comparable by construction, because it defaults to `unknown`, every earlier
record carried no declaration, and `unknown` is exactly what "no declaration" means.

---

## Finding 1 — the role precedent was never pinned, so both are pinned now

The brief asked for this to be reported if true. It is: nothing in `tests/` iterates
`VariableRole` and asserts the query is unchanged. "`role` is never rendered" lived only in
a comment and a docstring for the life of the bundle.

Rather than leave the older constraint unprotected while writing exactly the harness that
would cover it, `tests/test_modality.py` parametrises over role *and* modality everywhere.
If that should be a separate item, the role parametrisation is trivially removable.

---

## Finding 2 — items 16 and 17 cannot be separated the way the brief's §3 assumes

`deploy/smoke_test.py` step 0 and `deploy/retriever.py::CompassRetriever._verify_files` both
check `template.py`'s sha256 against the manifest *before* anything loads. So the moment
item 16 edits `template.py`, check.sh steps 6 and 10 fail — **ran**:

```
deploy.retriever.BundleIntegrityError: template.py sha256 32eb85c19ae0 != manifest
a5254caebb54; the bundle has been modified
```

There is no green state between "code final" and "re-frozen". The intent of the ordering was
kept: all of item 16 that does not need the bundle was finished and tested first (59 tests
passing), then the bundle was re-frozen **once**, then checksums verified once.
`smoke_test.py` was not touched and no expected value in it was rebaselined.

---

## Finding 3 — the re-freeze flips the proof chain, and only the operator can re-close it

A full `src/freeze_deploy.py` run is not possible here and would be the wrong tool: it
re-encodes the target vectors and rewrites the measured latency and R@1 figures, and its
inputs are absent — **ran**: `runs/bge-small_nn0_t0.10`, `out/targets_full.json`,
`retrieval_queries.json` and `out/qx_task2_paired.json` all MISSING.

The narrow re-freeze used freeze_deploy's *own* `sha256` and `proof_chain` functions, with
an assertion that only `template.py` moved. The entire manifest diff is four lines — **ran**:

| field | before | after |
|---|---|---|
| `files["template.py"].sha256` | `a5254caebb54a699…` | `32eb85c19ae0450f…` |
| `files["template.py"].bytes` | 5498 | 7073 |
| `proof_chain…["template.py"].sha256_now` | `a5254caebb54a699…` | `32eb85c19ae0450f…` |
| `proof_chain…["template.py"].ast_identical_modulo_docstrings` | **`true`** | **`false`** |

That flip is the honest signal and it is new: `template.py` now differs from the bundle the
tracked serving-machine report certifies (commit `6416094`) by *code*, not just docstrings.
Per the manifest's own `what_this_means`, re-closing the chain requires running
`deploy/smoke_test.py` on the serving machine and committing its report. That cannot be done
from this machine.

---

## Finding 4 — a latent landmine that would have bitten item 18

`deploy/retriever.py` rebinds `sys.modules["compass_deploy_template"]` at import time
(`_template = _load_template(ROOT)`) — the same name `pipeline/retrieve.py::load_template`
caches under. So importing the real bundle *replaces* the template module, and two
`Modality` members with the same value can be different objects in one process. The first
test run failed on exactly this. Enum identity across that boundary is not a property this
codebase has.

`RetrievalRecord` is already safe by design: it snapshots the *value* as a string, which is
why `RequestSnapshot` deliberately holds no reference to the template.
`tests/test_modality.py::test_the_record_stores_modality_as_a_string_not_an_enum` pins it, so
a scorer written for item 18 comparing `rec.request.modality == "self_report"` cannot be
broken by load order.

---

## The test (brief §2)

`tests/test_modality.py`, 71 tests. It pins retrieval **outputs** on a fixed corpus and a
fixed request set, at full precision, across every enum value: query string, `nearest_key`,
`hit.key`, `best_cos`, `margin`, `margin_12`, `abstained`, and R@1, with the threshold
pinned at `0.729476`.

The request set is 31 rows: the 7 canaries (5 abstaining, 2 resolving), 15 pre-registered
positives, and every pre-registered row whose top cosine ties.

Those tie rows matter. **ran**, scanning all 224 positives through the deployed bundle: 9
rows tie at rank 1, and rows 72 and 73 come back from `search` in *opposite* orders, which is
why `pipeline/retrieve.py::retrieve` resolves a tie by lowest target id. The first draft of
the fixed set contained **zero** ties — **ran**: `rows with a rank-1 tie: 0 of 22` — so the
tie-break, one of the exact channels the brief names, was untested. `TIE_ROWS` fixes that,
with an anti-vacuity test asserting the set really does contain ties.

### Seeded failure, both directions

Whole file each time, never a `-k` selector, `__pycache__` cleared between runs.

- **Seed 1** — modality rendered into `to_query()`, and re-frozen so the failure was not
  merely an integrity error. **ran**: `43 failed, 26 passed`. String test, fake test, intake
  test and all six real-bundle modality tests red.
- **Seed 2** — modality perturbing only the tie-break in `pipeline/retrieve.py`, query
  untouched. **ran**: `6 failed, 64 passed` — and *only* the real-bundle output test caught
  it. The byte-equality test passed; the fake-retriever test passed. The brief's §2 point
  demonstrated: `'residence location city'` rendered identically while `nearest_key` moved
  `m1:Q81 → m1:Q82`.

Both seeds reverted. **ran**: `grep -rn SEEDED` shows only three pre-existing hits in
`tests/test_contamination_surface.py`, and the restored `template.py` sha matches the
manifest (`MATCH: True`).

The real-bundle tests use `pytest.importorskip("torch")`, so `tests/` stays runnable where
the bundle is not installable (`AGENTS.md` §Testing Patterns). Here torch is present, so they
genuinely run inside check.sh step 2; **ran**, the added cost is about 30 s.

Modality is also pinned to survive `pipeline/artefact.py::_redact_record` — it is a closed
vocabulary, never wording, so it comes through redaction intact. Without that, item 18 would
read `unknown` for every instrument-sourced side and could not tell a declaration from a
redaction.

---

## Contamination

**UNVERIFIED by execution.** `benchmark.contamination_check` cannot run in this clone —
**ran**: `ModuleNotFoundError: No module named 'benchmark.prevalence_key'` — exactly as
`STATE.md` records; it is a phase-2 step in compass-score.

Structurally the edits are outside the scanned surface: `tests/test_contamination_surface.py:42`
gives `SCANNED = ("curated", "env", "agent")` and **ran**, no changed file sits under any of
them; `agent/schema.py` is untouched; and **ran**, none of the five `ACCEPTANCE_MARKERS`
(`2836`, `PM2.5`, `NO2`, `WQS`, `MAPSCorps`) appears in any code or test file written for
item 16 or 17. (They appear in this report, at the repo root, which is outside `SCANNED`
and loaded by nothing.)

That is a structural argument, not a clean run. The check must be run in compass-score before
any benchmark run.

### Publication-boundary disclosure

This report crossed the boundary later written into `AGENTS.md` §Publication Boundary,
which did not exist when it was first pushed. The operator's decision was
yes-with-limits: the material stays, the history is not rewritten, and the exposure is
disclosed rather than erased. Recorded here by window and count.

| commit | author date | commit date |
|---|---|---|
| `e6d9e79` | 2026-09-07T14:24:20-05:00 | 2026-09-07T14:24:20-05:00 |
| `e45b2eb` | 2026-09-07T21:50:27-05:00 | 2026-09-07T21:50:27-05:00 |

`e45b2eb` is the corrected form and `e6d9e79` is superseded, but a superseded commit
stays fetchable, so both are exposure. The two differ only in the "Commit state"
paragraph, which carries no key material, so their counts are equal by construction.

What crossed, by category, identical in both:

| category | count |
|---|---|
| term paired with its inventory status | 6 |
| term paired with an expected / analogue / resolved key | 1 |
| per-row cosine attached to a named term | 0 |
| PMID paired with inventory content | 0 |

Nothing is enumerated here on purpose: a list of the pairings would be a compact
restatement of the rows it describes, which is the thing the boundary withholds. The
enumeration is in the withheld companion under `run/`, which is gitignored and matches
`*.withheld.md` in `.git/info/exclude`.

**Window end state: open-ended.** Both commits are on the public `ralph-loop` branch and
remain fetchable. Per `README.md` §What is withheld, history persists "until the operator
rewrites it or makes the repository private"; neither was chosen, so the window has a
start and no end.

**The limit of this claim.** What is established is that the material was publicly
fetchable from 2026-09-07. Whether anything retrieved it is NOT established and cannot be
established from here: `benchmark/contamination_check.py` scans files, not weights. This
disclosure is a time window someone can compare against a model's training cutoff. It is
not a finding that no contamination occurred, and it must not be read as one.

The mechanical guard added alongside this disclosure,
`tests/test_publication_surface.py`, detects key-shaped material by SHAPE rather than by
a term list. It does not catch a term paired with a status when no key token is nearby —
which is the shape of the 6 pairings above. Its green state means no key-shaped material
crossed, never that no row-level material crossed.

---

## The scope question for the operator (brief §4)

No `Level` enum was added. Reporting it as asked.

Every figure in this section is **per the brief** and **UNVERIFIED in this tree**: phase 3
has not been run here, and cannot be — `TIER_STATE.md` records that tier assignment needs the
inventory and `inventory/case_map.json`, both barred from this clone, so it is an operator
step in compass-score.

Of the 18 refusal failures across 6 distinct rows:

- **2 rows (14 sides)** — EHR myocardial infarction and stroke resolving to the self-report
  item for the same condition. Modality. Item 16 covers these.
- **4 rows (4 sides)** — neighborhood alienation, neighborhood unsafety, census-tract SES,
  and the WQS disadvantage index. Every one an **area-level** measure resolved to a
  **participant-level** item.

Those four are n42, not modality: n42 substitutes individual for area, modality substitutes
self-report for measured. A `Modality` enum leaves all four invisible in the output.

The two options are equally implementable and the choice is the operator's: item 16 becomes
two enums under identical carried-not-rendered treatment, or it stays scoped to modality and
a sibling item opens for level. If two enums, the test file generalises cheaply — the
parametrisation already covers two carried fields and a third costs one more axis.

Either way the headline objection applies to level as well: nothing in `posed_pairs.json` can
declare it, and `read_cases` refuses a fourth field.

---

## The premise worth flagging (brief §5)

The argument that a caller-declared modality is viable rather than aspirational rests on the
24-of-24 pre-registered result — the class being fully predictable from the request. On real
inventory, phase 3's tier C scored modality analogue resolution at **1 of 8 sides, 0.125
[0.022, 0.471]**. Both figures are **per the brief** and **UNVERIFIED in this tree**, for the
reason given in the section above.

This is probably not fatal to item 16, because caller-declared modality does not require the
*retriever* to predict the class. But "fully predictable" is doing load-bearing work in the
justification and the replication behind it is 8 sides.

---

## Out of scope, untouched

- **Item 18.** `MODALITY_MISMATCH_AVAILABLE` is still `False` in `benchmark/tiered_score.py`,
  with its blocker string unchanged.
- **Item 19's published figures.**
- **The 0.854 / 0.963 refusal-denominator question.**

## Commit state

This report was written and pushed before the code it describes, which was backwards: the
reviewable artefact sat in the working tree while the narrative about it was in history.
Corrected 2026-09-07. The item 16 and 17 changes are now committed, in the order the work
was done:

| commit | what |
|---|---|
| `5f1dc67` | Carry modality on the request and the record, never rendered. **Red on its own** — editing the shipped `template.py` breaks check.sh steps 6 and 10 until the bundle is re-frozen. |
| `6f6508e` | Re-freeze the bundle: `template.py`'s checksum, and the proof chain flipping `ast_identical_modulo_docstrings` to `false`. Green restored. |

The split is deliberate even though no green state exists between the two, so history shows
the order rather than a single squashed change. Anyone bisecting across `5f1dc67` should
expect `BundleIntegrityError`, not a regression.

The serving-machine re-close described under Finding 3 remains **outstanding**.
