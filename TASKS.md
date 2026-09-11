# TASKS.md — open backlog
Open work only; merged history is `CHANGELOG.md`, rules `AGENTS.md`, design limits
`DESIGN.md` §7. Read every count from the module owning it, never here. Acceptance is
testable; seed its failure first.

## Open — the C12 chain
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
- **C6 — redesign the recall probe, run it once.** BLOCKED on C12. The existing probe is
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
  ruling, and reproduces every calibration row's verdict. C6 itself stays BLOCKED on C12.
- **C13 — prune published pairs from the generation frame.** BLOCKED on C12. Filter at
  `generate/funnel.py::s2_prune` on the key's construct-key pairs, never in a prompt.
  VERIFIED none is in the current frame, so it binds only once the frame widens. ACCEPT: a
  seeded published pair is pruned.
- **C21 — does model ranking predict REDISCOVERY?** BLOCKED on C12, which alone does not
  unblock it: no rediscovery scorer exists anywhere. `agent/specifier.py::_rank`'s
  docstring claims no skill on SOUNDNESS; say which claim you test. ACCEPT, staged: (i) a
  `benchmark/` rediscovery metric with tests, scoring a protocol against a key row; (ii)
  ≥1 CONFIRMED pair with k samples; (iii) a named correlation statistic, k and pair count
  fixed BEFORE the run. Cross-family is not optional (`DESIGN.md` §8); rewriting `_rank`
  is a user-level amendment.

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

- **C32 — the marker scan fires on a candidate INDEX.** Found 2026-09-10, the first
  finding the 0d fix made observable: until the deferred imports landed,
  `benchmark.contamination_check` could not run outside the scoring clone at all, so this
  had never been seen. `MARKERS` holds 69 tokens, 28 of them purely numeric; exactly one,
  `1092`, falls in 1..1353, which is the candidate-index range
  `agent/prompt_contract.py` numbers its offers with. The retrieval prompt therefore
  contains the literal `"index": 1092` and the scan reports a marker in the
  model-visible surface. It is a FALSE POSITIVE today and the only non-withheld failure
  in the whole suite (`tests/test_specifier.py::test_contamination_check_passes_offline`).
  The mechanism is general: any numeric marker <= the corpus size collides, and offering
  candidates by index is a Hard Constraint, so neither side can simply give way.
  🛑 Do not "fix" it by deleting `1092` from `MARKERS` — the marker set is re-derived, not
  inherited (`AGENTS.md` §Contamination Practice), and dropping a real published figure to
  silence a scan is the failure mode the section exists to prevent.
  ACCEPT: the scan distinguishes a marker in CONTENT from a marker in structural
  scaffolding it emitted itself, with a seeded failure proving it still fires when `1092`
  appears in a wording rather than an index; and the suite's only non-withheld failure
  clears.

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
- **T4 — `--system-prompt` in place of `--append-system-prompt`.** `agent/cli_backend.py`
  appends, so the Specifier reasons inside Claude Code's persona. UNVERIFIED whether
  replacing it breaks MCP tool-calling. ACCEPT: one cheap Haiku call under it invoking
  `mcp__compass__resolve_variable`.
- **T7 — scheduler and frame.** Nothing orders the live pairs,
  `generate/live_specifier.py` hardcodes one, and the frame is an unauthored list
  comprehension in both drivers (`generate/funnel.py`) that sets every reported
  denominator. ACCEPT: a named, hashed frame walked in enumeration order — value-based
  priority is a second selection effect. An m2×m2 frame would make it scorable.
- **C28 — `_rank` pays a record to adjust a wrong key rather than disclose a gap**
  (user-level, not a lane's). Its covariate-count term ranks a wrong-construct adjustment
  above a gap filed in `sought_covariates`; pre-existing, not from C24. The honest sample
  recovers only via an `EXCLUDED_ROLES` role fitting none, and `_rank` is under a Hard
  Constraint and an AST test.
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

## Deferred by the user, 2026-08-28
- C8 offline literature corpus; C9 retrieval tools as post-generation annotation; C10
  define or drop `judge_predicate`. Read `references/PRIOR_ART_CONTAMINATION.md` before
  reopening — the designs are settled there, with three claims body-reading withdrew. If
  C9 reopens, its conditions are in `DESIGN.md` §6.

## Known-open defects, no task yet
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
