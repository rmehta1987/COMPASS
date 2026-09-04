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
  designable-WITH-instrument check. It exists nowhere; build it first.
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
