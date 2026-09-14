# TASKS.md — open backlog
Open work only; merged history is `CHANGELOG.md`, rules `AGENTS.md`, design limits
`DESIGN.md` §7. Read every count from the module owning it, never here. Acceptance is
testable; seed its failure first.

## Open — the worked rediscovery, n=1–3

> **BLOCKED 2026-09-14, and not on anyone's effort.** MEASURED that day in the scoring
> clone, `benchmark.scorability.scorability_report()`: **10 REFUTED, 0 CONFIRMED, 6
> UNDETERMINED**. Every refutation is on the OUTCOME side — nine `outcome_not_in_the_
> instrument`, one `outcome_absent_from_instrument`. The cohort's published work measures
> serum assays, biomarkers, measured blood pressure, a metabolome and biospecimen
> participation. A two-column questionnaire carries none of those, and `clinical`, `lab`
> and `ehr` are declared and EMPTY (`env/tools.py::registry_coverage`).
>
> Three papers have a CONFIRMED outcome and exactly one blocker,
> `exposure_key_column_missing`: 36065817, 37252073, 36702470. **That blocker overstates
> them.** All three exposures are area-level, and all three are false survivors of the
> word test that `benchmark/scorability.py`'s own docstring already names. VERIFIED
> 2026-09-14 with `search_variables` on each exposure term: the best hits are the
> survey-link question, drinking-water source, caregiver status and the UChicago Medical
> Center items — no survey key exists to paste. Their real blocker is `linked:`, declared
> EMPTY and blocked on `area_measure_inventory`, a study-team delivery of the same class
> as the Qualtrics exports (§Blocked on a person).
>
> So **no reachable row exists today**, and pasting one is not the unblock. Read this
> beside §PARKED: C12 is not parked because nobody got to it, it is parked because the
> instrument and the bibliography do not overlap on both sides of any single paper.
> Re-run the command above before acting on this; it is a measurement, not a doctrine.

- **T2-rows — paste 1–3 rows into `benchmark/scorability.py::EXPOSURE_KEYS`.** 🛑 USER
  ONLY. **Do not start this until the finding above is overturned by measurement.** No agent writes a row and no agent reads a paper to check one; the key FORM is
  settled and reopening it is a user conversation. Pick papers whose exposure and outcome
  plainly sit in the codebook. The scaffolding is built and waiting: `python -m
  benchmark.rediscovery` runs C12's ACCEPT criterion over the column — every asserted key
  resolves live `unique` through `env/tools.py::resolve_variable` — and names the key that
  failed; `--pmid P --record F` prints the paper's recorded design beside a
  `ProtocolSpecification`, field by field. ACCEPT: `validate_exposure_keys` returns
  nothing, and `status_counts` reports a non-zero `confirmed` in the scoring clone.
- T2 is the manuscript's worked example and the demo. It is NOT the rediscovery metric:
  that is C21 stage (i) and stays PARKED below. The side-by-side emits no total on
  purpose — a match rate over a design line's method token and a `model_spec.form` has no
  defensible denominator.
- Read `benchmark/design_quality.py` every iteration meanwhile. It needs no key, no paper
  and no expert, and it is a dashboard and not a gate: no floor, no ratchet, no exit code
  tied to a number. Its first reading is in `CHANGELOG.md`; never quote a number from
  there, re-run it.

## Open — retrieval, in order

*Scope note (2026-09-03):* the items below concern the pipeline's **lexical** index
(`env/tools.py::search_variables`). A fine-tuned embedding retriever now ships separately
in `deploy/` (R@1 0.567, 0.643 templated; `RESULTS.md` §10) and is not governed by these
items; its open questions are in `CHARACTERISATION.md` §7.

`build.py` is CLOSED. No open items there: the dictionary is correct, identifier tiers
landed, `version_hash` covers the rules, the checks are split, and `roster_family_size`
is computed where construct identity is owned. Findings are cheap to produce in a fully
documented, fully hashed file; that is a property of its auditability, not evidence of
open work. A finding earns an item only if it can change a number the project
publishes or blocks a downstream stage.

- **R3 — `retrieval_text` as a new column.** Additive: `searchable_text` stays
  byte-identical to `question_text`, so the 224-row fixture, the gold rule and the FTS
  index are all untouched until R9 switches. VERIFIED read-only: the fixture stores only
  `key`, `text`, `query` (`benchmark/retrieval_eval.py::QueryRow`) and the index reads one
  named field (`env/tools.py::_load`). ACCEPT: `question_text` unchanged for all 2,804
  rows; `searchable_text` unchanged; `retrieval_text` differs from `question_text` for
  every grid sub-item.
- **R9 — switch the index to `retrieval_text` and re-baseline.** BLOCKED on R3. Its whole
  effect is a recall delta against an unchanged gold set, so it lands alone. 🛑 CARRY THIS
  IN: 60 of the 224 fixture rows carry `#` in the identifier and 44 of those, across 11
  gold keys, are roster repeats whose ONLY discriminator is a leaked piped reference of
  the form `- 1_Q16.9#1 - 1 -`. If `retrieval_text` drops it, the index loses a
  discriminator the gold rule still demands and recall falls for reasons unrelated to
  retrieval. Either preserve a member discriminator or the delta is uninterpretable.
- **R5 — strip piped identifiers from `stem_text`.** LAST, with its own re-baseline. It is
  not a column addition: `stem_text` reaches `agent/specifier.py::user_prompt`, two tool
  returns (`env/tools.py::resolve_variable`, `get_item_group`), every browse construct
  label, and pins in three test files. It moves `surface_hash`.

## Open — the website's backbone
*Added 2026-09-10. The operator's framing: the website is the product and this pipeline is
its backbone; a user prompts it like a chat assistant, and the reasoning model is meant to
separate the query into the schema before retrieving. Placement and priority in this file
are the operator's. `serve/` lives on the unmerged branch `worktree-serve-endpoint` and is
named in neither this file nor `CHANGELOG.md`; the site's* Ask the pipeline *flow
(`compass-site:site/index.html::askResolver` → `POST /api/pair`, no `k`) depends on it.*

- **C29 — one pool cannot carry a multi-construct request; split before retrieving.**
  `serve/api.py::_role_candidates` passes the researcher's whole sentence as
  `RetrievalRequest(construct=request)` and `_pair` offers that single pool to every role.
  MEASURED (`out/pool_coverage.json`, `src/pool_coverage.py`, 2026-09-10, parity-gated on
  single-construct R@20 0.942): at `_pair`'s own k=20 the pool carries **every** construct
  the request names in **32 of 100** composed requests — 0.600 at one exposure × one
  outcome, **0.167** at 1×2, **0.000** at 2×2. A construct alone is in the top 20 on
  **94.2%** of the 224 rows and on **65%** inside a multi-construct sentence. k=40, the
  handler's clamp ceiling, still fails 53 of 100. Two mechanisms, both live: one construct
  takes the pool and another is absent entirely (67 of 68 failures), or the blended vector
  matches neither (1 of 68). The fixture is composed to FAVOUR one ranking and inherits
  `retrieval_queries.json::KNOWN_BIAS`, so 0.32 is an upper bound.
  C29-B RESTATED 2026-09-11 (loop item 10), counted from `out/pool_coverage.json`: 60 of
  those 100 requests (30 1×2, 20 2×1, 10 2×2) are shapes no single record carries; under
  C30's convention each is N records, one per pair. The figure governing `_pair` as it
  ships is the 1×1 row: **0.600 shared against 0.825 oracle, on 40 requests** (24 and 33
  of 40). 0.32 is the all-shapes joint; quote it only with that beside it.
  WAS THE BLOCKER (resolved 2026-09-11 by the measurement below), a request-set problem before a code problem: **split
  accuracy is unmeasured and the oracle does not bound it.** `out/pool_coverage.json`'s
  split arms split on the fixture's own phrases — a perfect decomposition — and are a
  CEILING (0.71 at k=20, same total budget), read as `FUSION.md` §2 reads its 0.821 row.
  A wrong split has no shared pool to fall back on and fails silently; today both
  constructs sit in one list a human is already confirming (`_pair`'s `not_a_selection`).
  Weigh against it: `run/serve/jobs/123623-280426.json` shows the un-split pool resolving
  BOTH anchors correctly at k=20, the exposure at rank 15 over fourteen higher-scoring
  items — the model already decomposes, by index, against real vocabulary, and a
  pre-retrieval splitter names a construct blind.
  ACCEPT, staged: (i) a split fixture of request sentences with known exposure and outcome
  keys, authored WITHOUT sight of the gold wording — no oracle in the measurement
  (`AGENTS.md` §Testing Patterns) — reporting gold-excluded beside recall; (ii) end-to-end
  coverage under a real splitter reported against `out/pool_coverage.json`'s shared row
  (0.32; 0.600 at 1×1) and its oracle row (0.71; 0.825 at 1×1), not against `out/fusion_pool_depth.json`'s 0.942,
  which is a MARGINAL; (iii) the split prompt joins `model_visible_surface` and
  `benchmark.contamination_check` re-runs; (iv) the prompt held fixed and shown stable
  under one wording perturbation (`AGENTS.md` §Verification Discipline).
  C29-C MEASURED 2026-09-11 (loop item 11; the operator authorised building the splitter
  that day). Contract `64e29fd` (`agent/prompt_contract.py::parse_split`: every entry is
  the request's own words, in order), `/api/pair`'s opt-in `split` `2e63781`, harness
  `762b733` (`benchmark/split_coverage.py`). ACCEPT: (i) DONE. 399 questions written by a
  session that never saw the instrument; keys assigned afterwards by a second session in
  compass-score (the operator's two-session protocol). 303 left the denominator because a
  phrase has no instrument item; 96 scored (51 1×1, 24 1×2, 16 2×1, 5 2×2). (ii) DONE, as
  `docs/loop-prompt.md` rewords it: all three arms on the SAME requests in the SAME run,
  never against the biased fixture's 0.32 / 0.71. VERIFIED `python -m
  benchmark.split_coverage`, k=20, claude-haiku-4-5 splitter: shared **39/96**, real split
  **70/96**, oracle **71/96**. By shape (shared / split / oracle): 1×1 0.588 / 0.824 /
  0.843; 1×2 0.208 / 0.583 / 0.583; 2×1 0.125 / 0.688 / 0.688; 2×2 0.400 / 0.600 / 0.600.
  Split harm (shared covered, split lost) **5**, gain 36. 4 of the 5 are perfect splits
  whose narrower per-phrase queries lost an item the oracle also misses, so at most 1 is a
  wrong split. The route accepted 398 of 399 splits (1 unsplittable). (iii) DONE,
  `64e29fd`. (iv) DONE: under one paraphrase of the guidance, identical coverage (70/96),
  84 of 96 identical splits, 96 of 96 accepted. Caveats: one run, no seed; the labeler
  gave ONE key per phrase, so coverage is a lower bound; the author had broad topic hints.
  Artifacts outside the clone, `loop-snapshots/`: `split_coverage_2026-09-11.json`
  (sha256 2e58e9ad…), `split_replies_2026-09-11.json`, `clean_split_requests_2026-09-11.json`,
  and the `_perturbed` pair; the fixture is also at untracked `fixtures/clean_split_requests.json`.
  STILL OPEN, and the operator's: `split` is off by default on the site's route. Turning
  it on is a ship decision under FUSION §6's signed "ship nothing" recommendation.
- C29 makes **C17 bigger, not smaller**: a splitter is a third model in one run and
  `agent/schema.py::Provenance.model_id` is one string.
- **C29a — `absent` is defined as a claim the route cannot support.** Not blocked; smaller
  than C29 and independent of it. `agent/prompt_contract.py::VariableSelection` documents
  the verdict as *"the codebook does not measure this"* while `RETRIEVAL_GUIDANCE` scopes
  the question to *"the survey codebook below"* — the k shown. C29's measurement says the
  pool is missing a named construct 35% of the time at k=20, so the endpoint can report
  *the cohort does not measure X* when it does. ACCEPT: a pool miss and an instrument
  absence are distinguishable in the response, and the surface change re-runs
  `benchmark.contamination_check`.
  DONE 2026-09-10 (loop item 6). `absent` is defined on the items listed, not the
  codebook, in `VariableSelection`, `RETRIEVAL_GUIDANCE` and
  `benchmark/resolver_eval.py::CriticVerdict`; both `serve/` prose routes return
  `absent_scope`, naming the k shown and saying the instrument was not searched.
  RE-BASELINE: `benchmark/resolver_eval.py`'s critic prompt changed with it, so no
  resolver_eval result from before this commit is comparable to one after. None is
  quoted in any document (searched 2026-09-10); the next run is the new baseline.

- **C30 — N outcomes are N records. DECIDED 2026-09-10 by the operator: the convention
  reading, not the schema amendment.** A request naming one exposure against N outcomes
  (or M exposures) is N×M records, one per enumerated pair, produced by the loop that
  already exists (`generate/funnel.py::run` → `s1_enumerate(exposures, outcomes)`). It is
  never one widened record. Recorded in `DESIGN.md` §2.
  Why not widen: every per-record quantity is bound to one outcome.
  `agent/schema.py::ProtocolSpecification.canonical_form` emits `"outcome"` as a scalar,
  `record_hash` hashes that dict, and every saved record carries the hash in its FILENAME,
  `run/superseded/` pins included; `_falsifier_is_detectable` checks one
  `falsifier_threshold` against one outcome's detectability curve; the expected direction
  is one pair's. Widening makes each of those per-outcome, which is N records inside one.
  The full schema-reading analysis (six fields, the two `isinstance` holes widening would
  open) is in `git show 934aebe:TASKS.md` if the question is ever reopened.
  STILL OPEN, and small: no record names its siblings or the request it came from.
  Siblings are grouped by the shared exposure anchor (`canonical_form()["exposure"]`,
  equivalently the `protocol_id` prefix before `_to_`) within the one run or `serve/`
  ticket that produced them. Splitting a prose request into its N pairs is C29-C's
  splitter, not this item.

- **C31 — `serve/`'s request-shaping defects, in the one part of the module no test
  reaches.** Found by adversarial review 2026-09-10; each re-checked by running it against
  the live dictionary `3dc8415eccfe`. `tests/test_serve_redaction.py` carries 55 tests and
  exercises `_specify`, `_canonical_key`, `_int_arg`, `Handler`, `build_server` and
  `_refuse_unsafe_site_dir`, so this is a hole in a COVERED module: `_pair`, `_resolve`,
  `_role_candidates` and `_pin_keys_from_prose` are never invoked by any test.
  (a) `_pin_keys_from_prose` assigns roles by WORD ORDER — it zips `("exposure",
  "outcome")` against keys in the order they appear, and nothing enforces the docstring's
  assumption. *"is `m3:Q4.2` predicted by `m2:Q5.8`"* returns the outcome labelled
  exposure, with **no retrieval and no model call**, in ~0.02 s, carrying `reason: "the
  request named this key, so it was not inferred"`.
  (b) A third key in the prose is silently dropped (`zip(..., strict=False)`).
  (c) `role` is passed into `RetrievalRequest` but `deploy/template.py::to_query` never
  renders it, while `_role_candidates`'s docstring says the request *is* framed by role.
  `_pair` also discards the `surface` `_role_candidates` built and recomputes it.
  ACCEPT: a test per item, each seeded red first; (a) and (b) either enforced or the
  docstring corrected to what the code does.

## Blocked on a person, not a task

- **The two Qualtrics exports — response options and survey flow.** Without them
  estimability, denominators, power and every semantic validator are unbuildable. All
  2,804 rows carry null for the six fields that would hold them (`checks.py`,
  `NULL_BY_CONSTRUCTION`). Do not build around it and do not simulate it.

## Open — not blocked on C12
- **C16 — prose entry with a confirmation step.** Not blocked; must not delay C12. A model
  resolves the free text; `env/tools.py::search_variables` is the control arm, not the
  resolver. Its rules are in `AGENTS.md` §Contamination Practice. ACCEPT:
  enumeration-built and prose-built prompts are byte-identical
  (`agent/specifier.py::user_prompt`).
  RECONCILED with C29, the operator's decision of 2026-09-10: ONE resolver, the website's
  route (the deployed retriever's pool from `serve/api.py::_role_candidates`, then one
  `VariableSelection` call), and ONE control arm, `search_variables`.
  `benchmark/resolver_eval.py` measures that route: the `deployed` pool arm and
  `evaluate_single` (`--live --single`). VERIFIED 2026-09-11, claude-haiku-4-5, all 22
  rows, one call per row, no seed so not reproducible: deployed **20/22** correct, the
  lexical control **17/22**. The difference is three derive rows (GQ014, GQ015, GQ017);
  both arms named one item on GQ021, the wording printed in three modules. Upper bounds
  under the fixture's `KNOWN_BIAS`, n=22, one run: a direction, not an accuracy. The
  k-shortlist procedure (`evaluate`) stays as a measured alternative, not a second
  resolver. Reports kept outside the clone, `loop-snapshots/resolver_eval_single_*`.
- C16 second acceptance: `benchmark/input_leakage.py` scans a SUBMITTED prompt with a
  red-turning positive control; its `environment_supplied` currently rests on enumeration
  choosing the pair.
- **C17 — provenance for a run with two models.** BLOCKED on C16.
  `agent/schema.py::Provenance.model_id` is one string and the Haiku pin covers the
  Specifier, not a resolver, so a larger resolver is legitimate and a record hiding it is
  not. ACCEPT: a record whose resolver differs from its specifier fails validation unless
  both are named.
- **C19 — persist the repair channel.** A record can carry a value no tool in its log
  returned — observed live with `get_derivation` never called, enforced only by
  `agent/schema.py::DerivationRef._matches_the_signature_it_names`. ACCEPT: the rejected
  transduction or a `provenance` repair count is persisted, and a test traces every value
  to log or repair.
- **C27 — a failed seal probe must not score as evidence of a good seal.**
  `agent/sealed.py::SealedWorktree.run` raises only on a non-zero return code and never
  checks `is_error`, so an exit-0 CLI error lets "I cannot answer that." score `clean`.
  ACCEPT: `run` checks `is_error` as `agent/cli_backend.py::_run` does and an errored
  probe never scores `clean`, seeded with three error strings.
- **C18 sweep unrun** (pilot only). `rescore`/`--repartition` re-derives the partition
  from persisted records with no model call, so its threshold is revisable for free.
  ACCEPT: a sweep run with the threshold fixed before it.
  PRE-REGISTERED 2026-09-11, committed before any sweep call (loop): threshold
  `min_specifiable` = **1 of k = 5** responses (the module default, the pilot's value);
  model claude-haiku-4-5; rubric `694100e1ea900ddb`; frame `m3q16_x_m2q5` (digest
  `241d604e339a`, all 256 live pairs) on dictionary `3dc8415eccfe`; both controls and the
  withholding check. Command: `python -m benchmark.unaided_specifiability --controls
  --verify-withholding --pilot 256 --out run/unaided_sweep_2026-09-11`. Another
  threshold may be reported only as a `--repartition` beside this one, never instead.
- **T4 — `--system-prompt` in place of `--append-system-prompt`.** `agent/cli_backend.py`
  appends, so the Specifier reasons inside Claude Code's persona. UNVERIFIED whether
  replacing it breaks MCP tool-calling. ACCEPT: one cheap Haiku call under it invoking
  `mcp__compass__resolve_variable`.
- **T7 — scheduler and frame.** Nothing orders the live pairs,
  `generate/live_specifier.py` hardcodes one, and the frame is an unauthored list
  comprehension in both drivers (`generate/funnel.py`) that sets every reported
  denominator. ACCEPT: a named, hashed frame walked in enumeration order — value-based
  priority is a second selection effect. An m2×m2 frame would make it scorable.
- **C28 — RESOLVED 2026-09-11, user amendment.** `_rank`'s covariate-count term paid a
  record for adjusting for a wrong-construct key over one that filed the gap in
  `sought_covariates`. The term is removed. The user asked three independent reviews
  (enterprise account, opus) whether `sought_covariates` should become a term instead. All
  three said no: it is prose nothing checks, so "more gaps rank higher" picks padding and
  "fewer rank higher" rebuilds C28. The fix is neutral, not a win: the two records now tie,
  and the hash picks one.
- **C28 follow-ups the reviews found, VERIFIED in the code 2026-09-11.** (a) RESOLVED:
  `specify`'s dedup kept the first seed when two same-hash samples recorded equally many
  gaps, which is seed order. (b) RESOLVED (`02cf793`): `generate/live_specifier.py` copied
  the first same-hash attempt's tool log, audit and repairs beside the saved record, which
  was the wrong sample's when a disclosing twin beat a silent one. (c) RESOLVED, user
  decision: `_disclosure` was a raw count, so a padded twin beat an honest one, and the
  loser was dropped. Now `specifier::_twin_order` decides: any gap beats none, the count
  does not matter, then a hash of the record's content. Every losing twin is parked.
- **C33 — `len(blocked_on)` ascending still charges disclosures other than gaps.**
  User-level. LEFT AS IS by the user, 2026-09-11, after three independent reviews
  (enterprise account, opus). All three said to drop the blocker count AND the `status`
  term, leaving `_rank` = access, `n_source`, hash. Checked in the code:
  - The environment writes one blocker, `outcome_prevalence_unconfirmed`, on every record,
    so it separates nothing. Every other member is the model's.
  - `n_source` is `unknown` on both `estimate_n` branches, so today the blocker count is
    the only term that separates designs.
  - `blocked_on` and `falsifier_threshold` are outside `canonical_form`, so twins that
    differ only in what they admit go to `_twin_order` and are not charged. The count
    bites only when an admission comes with a canonical difference: clustering at the
    community area plus its design-effect blocker, or `unreliable_coding` plus
    `response_coding`.
  - Dropping only the count would leave `status` as a yes/no penalty on any admission.
    It is hidden today because every record is `draft`, and it would return the day the
    counts arrive.
  - No test varies `blocked_on` under `_rank`. `AGENTS.md` and `agent/schema.py` give
    this term as a reason for "no `BlockedOn` member for disclosure", so a change must
    reword both.
  - Seed 1 claimed the access gate is the bigger lever. Wrong: `check_access` counts at
    most three places against a budget of 3, so it refers only on an unknown key.
- **C34 — leaving out a numeric falsifier threshold dodges a blocker and the only
  quantitative check** (from the C33 reviews, not yet checked end to end). With no
  `falsifier_threshold`, `_falsifier_is_detectable` does not run, and
  `_a_threshold_on_an_unknown_n_discloses_it` forces nothing. The prompt says "An unstated
  threshold is honest" (`agent/specifier.py`). The two records are twins, so neither is
  charged at rank, but nothing rewards stating the checkable one.
- **C26 — the offline concept-synonym column. LAST and gated.** An offline pass labels
  each wording as a second FTS5 column. Precondition (2) UNMET: the scan catches quotation
  and a label is paraphrase, so a planted framing must turn it RED in the same commit.
- C26 precondition (3) UNMET: `build.py::BUILD_RULES_VERSION` must bump with the column,
  since the hash omits entry content.
- C26 open question for the operator: `env/tools.py::browse_variables` may already have
  closed the flagship case at zero cost, leaving only the largest module. A model-authored
  label is neither study-team-sourced nor a design choice, so no
  `benchmark/unearned_assertions.py::PROVENANCE_TIERS` tier or `origin` value fits
  (`DESIGN.md` §5.2). Bring a measured benefit and a re-runnable benchmark.

## PARKED — the full-bibliography key and its chain
Parked by the operator on 2026-09-14. **Nothing here is cancelled and nothing is
deleted**; the apparatus stays intact and unparking means filling the key. The reason is
scope, not doubt: C12 was scoped to the FULL bibliography and fenced as user-only, so four
items sat behind an artifact no session could produce while the project had no progress
signal it could read in the meantime. The n=1–3 worked rediscovery above replaces it as the
live item and `benchmark/design_quality.py` replaces it as the iteration measurement.
**While parked, nothing below blocks anything.**

Parked with it, and for the same reason plus one of its own: **expert ratings**, the third
tier of the 2026-09-14 three-tier evaluation decision. The operator has no access to domain
experts until much later, which is why the dashboard exists.

### The chain, as it stood when it was parked
- **C12 — the held-out answer key over the full bibliography**, `benchmark/` only; the
  binding constraint on everything scorable. Blocker:
  `benchmark/scorability.py::EXPOSURE_KEYS` is empty. 🛑 Its key FORM is settled by the
  user — explicit `unknown` plus a named blocker; reopening is a user conversation, not a
  lane decision.
- C12 consequences to inherit: `status_counts` unmoved, C6 has no scorable pair, C21 gains
  a second blocker.
- C12 slices: `benchmark/prevalence_key.py` (role-tagged rows, no exposure field) and
  `benchmark/cohort_papers.py` (one design line each). Owed per paper: covariates, model
  form, method tokens, n, tier, and the partition of `DESIGN.md` §6. ACCEPT: every paper
  has a key row carrying that tag, no asserted key fails to resolve live via
  `env/tools.py::resolve_variable`, and `status_counts` recomputes from the module.
- **C6 — redesign the recall probe, run it once.** PARKED WITH C12. The existing probe is
  unidentified: its fingerprint list is shared with at least two other papers and is a
  public municipal data menu, and its framing phrase is the paper's title. ACCEPT:
  published-outcome arms vs same-region controls of equal or higher literature density,
  plus a cue-wording ablation, arms fixed first (`agent/sealed.py::score`).
- C6 is ONE-SHOT — run it last, before the `linked:` registry is populated; population
  destroys its refusal arms and `benchmark/calibration_set.py`'s `registry_empty` arm. The
  `clinical`/`lab`/`ehr` arms survive.
- C6 second blocker: `benchmark/unaided_specifiability.py::NOT_SPECIFIABLE` conflates
  "needs the instrument" with "no coherent design at all", so C6's arms need a
  designable-WITH-instrument check. BUILT 2026-09-11 (loop): 
  `benchmark/unaided_specifiability.py::with_instrument` splits `NOT_SPECIFIABLE`
  into `NEEDS_INSTRUMENT` and `NO_COHERENT_DESIGN` using
  `benchmark/calibration_set.py::_evaluate`, the calibration set's own environment
  ruling, and reproduces every calibration row's verdict. C6 itself stays parked with C12.
- **C13 — prune published pairs from the generation frame.** PARKED WITH C12. Filter at
  `generate/funnel.py::s2_prune` on the key's construct-key pairs, never in a prompt.
  VERIFIED none is in the current frame, so it binds only once the frame widens. ACCEPT: a
  seeded published pair is pruned.
- **C21 — does model ranking predict REDISCOVERY?** PARKED WITH C12, which alone would not
  unblock it: no rediscovery scorer exists anywhere. `agent/specifier.py::_rank`'s
  docstring claims no skill on SOUNDNESS; say which claim you test. ACCEPT, staged: (i) a
  `benchmark/` rediscovery metric with tests, scoring a protocol against a key row; (ii)
  ≥1 CONFIRMED pair with k samples; (iii) a named correlation statistic, k and pair count
  fixed BEFORE the run. Cross-family is not optional (`DESIGN.md` §8); rewriting `_rank`
  is a user-level amendment.

## Deferred by the user, 2026-08-28
- C8 offline literature corpus; C9 retrieval tools as post-generation annotation; C10
  define or drop `judge_predicate`. Read `references/PRIOR_ART_CONTAMINATION.md` before
  reopening — the designs are settled there, with three claims body-reading withdrew. If
  C9 reopens, its conditions are in `DESIGN.md` §6.

## Known-open defects, no task yet
- **`EXPOSURE_KEYS`'s implemented type cannot express its own settled key form.** C12
  records the form as "explicit `unknown` plus a named blocker", and
  `benchmark/scorability.py::EXPOSURE_KEYS` is `dict[str, tuple[str, ...]]` — a bare key
  tuple with no slot for either. So a paper whose exposure the instrument provably cannot
  carry has no way to say so, and reads as an unfilled row. Changing the form is a user
  conversation, not a lane decision.
- **`scorability.py` refutes an outcome on evidence it has no counterpart for on the
  exposure side.** `OUTCOME_NOT_IN_THE_INSTRUMENT` comes from the prevalence key's
  `instrument_region`; the exposure side has no such column, so the strongest thing it can
  ever say is `EXPOSURE_KEY_COLUMN_MISSING` — "nobody filled this in" — for an exposure
  that is not in the instrument at all. MEASURED 2026-09-14: this is exactly why three
  unreachable papers present as one paste from CONFIRMED. Same class of defect as the
  `outcome_key_unresolved` -> `KEY_DOES_NOT_RESOLVE` rename the file already records.
- **`agent/schema.py::ProtocolSpecification` cannot express a population restriction.**
  None of its 22 fields, and none of `ModelSpec`'s three, carries a restriction, stratum
  or subgroup. A design stated for one subpopulation can only be adjusted for, not
  restricted to — and for race specifically the category cannot even be named, because
  `response_options` is null on all 2,804 entries (`checks.py::NULL_BY_CONSTRUCTION`), so
  naming one would trip `_no_response_coding_is_asserted`. Surfaced 2026-09-14 by a real
  request; no task yet because the fix interacts with Phase 3's `study_design` field.
- Three unbound or vacuous guarantees, all in `DESIGN.md` §7:
  `estimability.exposure_contrast`, `agent/registry.py::RETRIEVAL_TOOLS`, and
  `env/tools.py::search_variables`' OR-decomposition.
- `agent/schema.py::RefusalReason.access_gate_refused` is unreachable:
  `env/tools.py::check_access` returns only `pass|refer`. Kept deliberately; C15 makes it
  unclaimable.
- `agent/schema.py::RefusalReason.no_contrast_definable` is unreachable:
  `get_contrast_convention` has no failing branch. Kept deliberately, same as above.
- `run/`, `build.py` (with `tests/test_dictionary.py` and `tests/test_code_standards.py`),
  `raw/`, `parked/`, `references/` and `agent/__init__.py` are in no lane assignment
  (`AGENTS.md` §Parallel Lanes); `build.py` owns one of the two stop conditions.
- The lane report `benchmark/cohort_papers.py` cites as the home of design detail is in
  neither tree nor history, though C12's exposure column needed it.
- `tests/test_specifier.py::test_excluded_variables_do_not_consume_access_budget` cannot
  fail as named — two non-location keys, no exclusions. Replacement:
  `tests/test_env_tools.py::test_no_tool_accepts_a_parameter_it_ignores`.
- `benchmark/contamination_check.py::check_seal_config` checks what the seal denies, never
  that `agent/sealed.py::SealedWorktree.base_argv` carries no `--mcp-config`.
- **No test drives a contamination section that can actually SKIP.**
  `tests/test_contamination_skip.py` plants its skips on `check_provenance`, which imports
  nothing and can never raise `ModuleNotFoundError`. The only two sections that really
  skip are `check_no_platform_name_in_surface` and `check_no_prevalence_figure_in_surface`.
  The status logic is well covered; the real skip PATH is not, so moving either import to
  module scope would break it with every test green. Pre-existing, inherited from the
  2026-09-10 tests. ACCEPT: one test that lets a genuinely-skipping section raise for
  real, seeded by wrapping its import.
- **`tests/test_contamination_skip.py::test_require_complete_does_not_turn_a_clean_run_red`
  cannot go red** under the current shape of `main()`: `require_complete` is read only
  inside `if skipped:`. It guards a future implementation that errors on the flag, which is
  worth something, but it is not a measurement of today's code.
- **A failing case was rewritten to match the code rather than pinned.**
  `test_without_the_override_the_seal_behaves_exactly_as_before` was red on 2026-09-14 and
  was rewritten; `AGENTS.md` §Testing Patterns says pin a failing case, never delete it,
  and it moves to `run/superseded/` and stays under test. No `xfail` was left behind. The
  defect it was pointing at is now fixed and covered, so nothing is unenforced — but the
  rule was not followed, and `run/superseded/` is itself untracked (see the dead-reference
  row above). Decide whether that rule survives Phase 5 in its current form.
- **`tests/withheld.py` pulls the whole `contamination_check` import graph into
  `tests/test_scorability.py`** to read one `frozenset` of two strings. That module imports
  `agent.prompt_contract`, `agent.specifier`, `agent.registry`, `benchmark.resolver_eval`,
  `benchmark.retrieval_eval` and more at module scope, so an import-time error in a Lane A
  file now turns every `tests/test_scorability.py` test into a collection error. It is also
  the coupling `benchmark/scorability.py`'s deferred imports exist to avoid. ACCEPT:
  `WITHHELD_MODULES` moves to a leaf module both can read, with the gate importing it.
- **The scanned `retrieval_prompt` is not the shape production sends.** The scan renders
  the whole catalogue with no per-key `facts`; `serve/api.py::_role_candidates` sends a
  top-k pool with `module` and `roster_family_size` on every candidate. So the marker
  scan's partition between exempt positions and scanned typed facts is validated on a
  shape that never ships. Pre-existing scan-fidelity gap, now load-bearing for the C32
  exemption. ACCEPT: the surface renders one production-shaped pool beside the catalogue.
- `surface_hash` is computed and never asserted; the operator has decided it should be
  deleted outright. ACCEPT: `benchmark/contamination_check.py::main` does not compute it.
- The C24 commit messages state a false mechanism ("hash order picks the survivor"); the
  selector was seed order via `setdefault`. Primaries corrected, messages immutable
  (`0b41239`).
- *(private history: neither branch nor sha below exists in the public repository)* Keep
  `lane-b-referent` unmerged: its hard target filter measured negative recall@20 and
  dropped the gold item on ~10% of queries (UNVERIFIED here; measured in-lane, three
  runs), and one `continue` in `lane-b-referent:env/tools.py::_hit_referent` is untested.
- `lane-honest-miss` holds `64c7bd2` worth salvaging; its `3933ecb` is UNREVIEWED WIP
  carrying a real finding, schema docstrings shipping a paper count.
- The saved-record corpus is effectively one pair, so anything measured over
  `tests/test_contamination_surface.py::_valid_records` has a denominator of one design.
- `benchmark/unaided_specifiability.py`'s flag rate misleads (`DESIGN.md` §7).
