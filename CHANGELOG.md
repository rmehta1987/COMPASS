# CHANGELOG

What landed, newest first. Nothing here is a task; the open backlog is `TASKS.md`.

- **History only, never doctrine.** Hoist any rule, trap or measured limit a merged task
  left behind into `AGENTS.md`, `DESIGN.md` or `TASKS.md`; a line here only points at it.
- Never restate a ratchet, ceiling, count or hash below; name its owning module instead.
- Treat a merge sha as the anchor, not the evidence: open the commit or the primary before
  repeating what a line here says a task did.
- **Shas quoted in entries dated before 2026-09-03 belong to the private pre-publication
  history** and do not resolve in the public repository (the pipeline mirror is the orphan
  commit b3d818d plus one follow-up; the retrieval tree's root is d0ff436). Open the
  primary instead.

---

## 2026-09-14

Phase 1 of the refocus: make the two progress signals mean something. Landed in three
commits, then corrected in three more after an adversarial review found two of the three
original claims unenforced. Counts, ceilings and the guarded-test ratchet are read from
their owning modules, never from here.

- **The contamination gate's exit status splits three ways** (`8c5f0fd`, enforced in
  `bec33d1`), so it can be read in the clone where prompts are edited rather than being
  permanently red there: clean-and-complete, a section FAILED, or none failed and one or
  more SKIPPED for a withheld answer key. A failure always outranks a skip.
  `--require-complete` demands that every section ran and `--live` implies it, because a
  pre-benchmark gate cannot accept "I could not see everything" — review found a `--live`
  run reporting merely-incomplete with both answer-key scans unrun and no seal probe
  scored. The run prints which gate it applied; before, a skipping run's output was
  byte-identical whichever status it returned. Semantics and status constant:
  `benchmark/contamination_check.py::EXIT_INCOMPLETE`; pinned against the literal in
  `tests/test_contamination_skip.py`, because asserting `rc == EXIT_INCOMPLETE` was
  self-referential and let the whole split revert with a green suite.
- **C32 closed — the marker scan tells a figure the surface CARRIES from a position the
  harness GENERATED** (`de559e9`, bounded in `b795dee`). Numeric markers at or below the
  offered-candidate count collide with a position, so the retrieval prompt's `index` field
  made the scan report a marker. No marker was pruned; the scan was partitioned.
  `benchmark/contamination_check.py::_without_harness_indices` reproduces in the scanner
  the `1..n` invariant `agent/prompt_contract.py::SelectionContract.__post_init__` already
  enforces, and fails CLOSED on anything else. The first version was unbounded and
  swallowed a PMID, a published analytic n and a newline form anywhere in any surface. The
  exempted character count is printed beside `surface_hash`, which is computed before the
  mask.
- **The suite is green where the work happens** (`3c187af`, corrected in `7d74e0f`). Tests
  needing `benchmark/prevalence_key.py` or `benchmark/leak_facts.py` now SKIP behind
  guards in `tests/withheld.py`, whose skippable set comes from the gate's own
  `WITHHELD_MODULES` so the two cannot drift; it was 47 failed, and 45 of those were this.
  Review then found 11 of the guarded tests carried assertions answerable WITHOUT the key
  — including the only assertion in the tree that the word "platform" is absent from the
  model-visible surface — so those are split, and the guard's own use is ratcheted in
  `tests/test_withheld.py::GUARD_CEILING`. A module-level `pytestmark` is banned: no
  decorator count can see one, and `AGENTS.md`'s falling-test-count stop condition is
  blind to a skip by construction.
- **The seal's manifest now names the config directory the sealed child actually reads.**
  `agent/sealed.py::config_dir` resolved `COMPASS_CLAUDE_CONFIG_DIR` else `~/.claude` and
  never consulted the inherited `CLAUDE_CONFIG_DIR`, while `SealedWorktree.run` builds the
  child environment as `{**os.environ, ...}` — so whatever the caller's shell exported won,
  and Claude Code's enterprise install exports one. The manifest, `_claude_md_sources` and
  `reachable_skills` therefore audited a directory the run never opened. Measured on the
  training machine before the fix: two skills reported reachable in a directory the child
  did not read, none in the one it did. The seal was tighter than claimed, so nothing
  leaked — but a manifest is the seal's only honest output, and describing the wrong
  directory reads as a finding. Resolution order is now the child's own, run behaviour is
  unchanged, and the guarantee is pinned implementation-independently: the manifest must
  equal what `run` hands the child
  (`tests/test_specifier.py::test_the_manifest_names_the_config_dir_the_child_actually_reads`).
- **A test whose verdict moved with the operator's shell** (`3c187af`).
  `tests/test_specifier.py::test_without_the_override_the_seal_behaves_exactly_as_before`
  asserted `"CLAUDE_CONFIG_DIR" not in seen`, conflating "the seal added it" with "it is
  there at all" — `SealedWorktree.run` builds the child environment from `os.environ`, and
  Claude Code's enterprise install exports that variable. Now asserted against the
  parent's value, paired with a test that the opt-in override beats an inherited one. It
  surfaced a real defect in the seal's MANIFEST, left open as a user decision:
  `TASKS.md` §Known-open defects.

## 2026-09-03

- **Two trees merged into one public repository** (2ede8f7). The pipeline mirror was
  published from an orphan branch without the instrument (b3d818d); the retrieval
  experiments (`src/`, `deploy/`, `RESULTS.md`, `CHARACTERISATION.md`, `FUSION.md`,
  `QUERY_EXPANSION.md`) were `main`. `README.md` maps both and lists what is withheld;
  `PROVENANCE.md` maps every retrieval figure to its artifact and commit. Name collisions:
  `build.py` is the dictionary builder; arm E's target builder is `build_targets.py`
  (1,352) beside `src/compass_build.py` (1,353, one free-text row apart).
- **The fine-tuned retriever was ported to the x86 serving machine and proven there**
  (e446cf8, da317d6, 4b8abee, 31a096d): `deploy/smoke_test.py` reproduces R@1 0.567 /
  0.643 to the digit on both machines; threads pinned to 4; the query template ships in
  the bundle; `deploy/manifest.json::device.serves` names Wright.
- **Four artifacts withdrawn from git** for quoting instrument wording per row
  (`deploy/targets.json`, `out/fusion_task1_overlap.json`, `out/qx_task2_paired.json`,
  `out/qx_task3_abstention.json`); merged to `main` on 2026-09-04, until which `main`
  tracked them at its tip. They remain in history (73f796b, 8f1d9fb, e446cf8) until the
  operator rewrites it. Residual wording scan: `README.md` §What is
  withheld.
- Corrections recorded rather than silently replaced: the 2.94 ms/query figure was
  batched throughput, not latency (`PROVENANCE.md`); the shipped threshold is a knife edge
  (`CHARACTERISATION.md` §3); `arm_hybrid_e_D.md` §6 and `docs/arm-e-results.md` §8 argued
  against fine-tuning before it was measured at +0.192 (dated notes in place); the two
  arm-E scripts are not byte-identical to their artifact-producing versions
  (`pyproject.toml`).

---

## 2026-09-02

- **The build hash covers the rules, not a version string.** `build.py::_rule_fingerprint`
  puts the six regexes' patterns, the shape table, the mojibake markers and five parsing
  functions' source into the hashed payload. Editing a rule now moves `version_hash` on
  its own; `BUILD_RULES_VERSION` is a label. Every module-level function is hashed or in
  `_NOT_HASHED` with a reason, `build` and `read_module` being declared gaps. The stop
  condition in `AGENTS.md` moved with it.
- **Identifier tiers and `roster_family_size` are columns.** Nothing distinguished a
  participant's name from a cancer variable; nothing said how many roster members share a
  question, so a consumer in `benchmark/` derived it while a prompt in `agent/` named it.
  Counts and the tier boundary live in `checks.py`, never here.
- **The build's assertions split into structural and snapshot groups** and moved to
  `checks.py`, which takes a loaded dictionary — asking whether the checks pass no longer
  requires a write. Most of what was called an invariant is a drift detector; the two now
  print apart because a structural failure is a bug and a snapshot failure is a question.
- **The mechanical gate reads tool outcomes.** `agent/specifier.py::_gate` compared tool
  NAMES, so an errored `check_access` satisfied it. Now a required call must have
  succeeded and named a key of the pair. The measurement over `run/logs/` is in the
  commit; do not repeat it from here.
- **A prose resolver has a benchmark** (`benchmark/resolver_eval.py`), keyed on dictionary
  keys rather than the bare `qid` the ported harness used, with wording cited at render
  time rather than frozen. Three prompt arms, all scanned.
- **A model-visible surface can be a typed record** (`agent/prompt_contract.py`): the
  model selects an index, the harness resolves the key and binds the wording. Reasons and
  prior art in `docs/adr/003-index-selection.md`.

## 2026-09-01

- **The doc surface consolidated to five files**: `AGENTS.md` (rules), `DESIGN.md` (what
  the system is), `TASKS.md` (open backlog), `CHANGELOG.md` (history) and `CLAUDE.md`
  (Claude Code only). *(Superseded by the 2026-09-03 merge, which added `README.md`,
  `PROVENANCE.md` and the retrieval reports; `DESIGN.md` §1 is current.)*
  `PROMPT_CONTAMINATION_SESSION.md` and `NEXT_SESSION.md` were folded into them and
  deleted, with four superseded handoffs; they are recoverable only from the private
  history (`7c1ad88`), not from this repository.
- Two rules came out of it and are now enforced by the split: no document restates a
  number a module owns (`AGENTS.md` §Testing Patterns), and a merged item leaves its rule
  in `AGENTS.md`/`DESIGN.md`, never in the changelog line that records it.
- `/compass-contam` no longer restates `AGENTS.md` or carries state of its own, and the
  three modules that cited the retired session doc were re-anchored.

- **The low-confidence search path now says browse, not stop** (`8f9884f`). Fewer searches
  and calls, correctness unmoved — a strategy result, not an accuracy one; rule in
  `AGENTS.md` §Verification Discipline.
- **A test that asserted the corpus of the morning it was written now derives it**
  (`c871b4f`): the field working had turned it red; rule in `AGENTS.md` §Testing Patterns.
- **`env/` network rule scoped** (`8042f4d`); rule in `AGENTS.md` §Hard Constraints.
- **A bare variable key is unrepresentable** (`49da51b`, merged `b29bcd3`, `70b3883`; the
  live record that prompted it is saved at `c4282c2`); rule in `AGENTS.md`
  §Hard Constraints.
- **Every prompt's variable list is derived from its body**, not declared beside it
  (`9d9c983`, merged `7c1ad88`).

## 2026-08-31

- **C22 — `search_variables` shrunk by deleting per-call prose, not the scorer**
  (`d6a83da`). Ablated through the evaluator, pure BM25 fell under the recall floors, so
  the idf-coverage apparatus stayed. `check_access` lost its dead `measures` parameter.
- **The C22 gate landed first**: `benchmark/retrieval_eval.py` (`2d8f071`, merged
  `ab6e84f`), then a cold critic's hardening (`afc99ca`) pinning what a correct hit MEANS,
  so a looser collapse cannot mint recall. Ratchets and the collapse pin:
  `tests/test_retrieval_eval.py`.
- Fixture bias and the embedding/RRF/rapidfuzz gate ban: `AGENTS.md` §Testing Patterns.
- **C23 — tool `SCHEMAS` generated from pydantic argument models** (`b559c9a`, merged
  `7c7e2c8`). Undescribed parameters went to zero and a wrong argument name now names the
  parameter the tool wanted. The accepted-set rule is in `AGENTS.md` §Hard Constraints.
- **C24 — a record can say "I sought this covariate and found no key"**: `agent/schema.py`
  gained `UnresolvedCovariate` and `ProtocolSpecification.sought_covariates` (`7a8b0f7`,
  merged `0624dda`). No new `BlockedOn` member, deliberately — reason in `AGENTS.md`
  §Hard Constraints.
- **C24 cold-critic remediation** (`0b41239`, `669c836`, `8ad3919`, merged `d84a484`):
  dedup stopped discarding the disclosing sample and now tie-breaks on a pure function of
  the record; three key-guard evasions closed (case, spacing, dropped module prefix).
- 🛑 Never quote the C24 merge message's stated mechanism: it is wrong and immutable. Both
  reachable primaries are corrected; the defect is in `TASKS.md` §Known-open defects.
- **C25 — `browse_variables`** (`a8d7abf`), with every page sampled into the contamination
  scan, and the prevalence scan stopped reading question ids as published figures
  (`76309b1`, merged `f93bb61`). Both rules: `AGENTS.md` §Contamination Practice.
- **C26 precondition (1) closed** — `contamination_check` now reads
  `build/dictionary.json` and re-probes the recorded instrument-content exclusions every
  run (`4648e45`, critic repair `8dbaf86`, recorded `089c44d`).
- Preconditions (2) and (3) stay open in `TASKS.md`; the three patterns its critic
  surfaced (AST over `getsource`, `searchable_text` alone, per-module probe floor) are in
  `AGENTS.md` §Testing Patterns.
- **C20 superseded by C22.** Its `env/` half — per-hit scoring and named misses — is
  merged at `1ff998e` with critic repair `c7ca3b6`; criterion (b) is no longer the goal,
  and the measured reason it is unreachable inside `env/` is a known limit in `DESIGN.md`
  §7.
- **`env/` no-model rule lifted to a user-granted, ratcheted exception** (`e0edffd`); rule
  and grant list in `AGENTS.md` §Hard Constraints.
- **Both lint ceilings lowered** to the count measured on the merged tree (`73e55b4`);
  direction rule in `AGENTS.md` §Code Standards.

## 2026-08-30

- **C18 — unaided-specifiability harness and pilot merged** (`82216de`), with the
  withholding itself controlled through one log file and negative/positive control pairs
  (`8566e96`), plus model-free re-partition (`675c475`).
- The sweep is NOT run (`TASKS.md` §Open — not blocked on C12); the flag-rate limit that
  bounds what C6 may do with the output is in `DESIGN.md` §7.

## 2026-08-28

- **C1 — `MARKERS` extended to the full bibliography** with two false positives removed by
  re-running rather than inheriting the set (`95ac70e`).
- **C2 — `benchmark/input_leakage.py`** added as a static, model-free check section with
  firing positive controls (`130803f`).
- **C3 — the second call's prompt surfaces brought into the scan** (`20397b0`), captured
  by driving the emission path rather than hand-listing it. C1/C2/C3 merged `ebe0cc0`.
- **C4 — the refusal path wired** (`caebd03`, merged `d424acf`): a live decline carrying
  evidence from both required tools, plus an over-refusal control that refuses nothing on
  a specifiable pair.
- **C5 — the calibration set landed with its answerable control arm** (`979c3ac`, merged
  `1dc03a2`), sized so refusal rate and over-refusal rate share a denominator.
- **C7 — the vocabulary-overlap tier metric was deliberately NOT built** (`2c690bb`): both
  post-cutoff papers have outcomes with no content word in the instrument, so the check
  could not fail. `benchmark/tier_gate.py::assert_gate_clear` enforces the precondition
  instead; the standing rule is in `DESIGN.md` §6.
- **C11 — a record may no longer state a response coding** (`bafcf7c`, merged `e825e68`,
  tripwire inverted `64c7f2b`); every gated pattern requires a numeral. Its corpus is thin
  in a way its count hides — `TASKS.md` §Known-open defects carries it.
- **C14 — `no_signed_derivation` dropped from the calibration set** (`456d4af`). Re-adding
  rule: `DESIGN.md` §6.
- **C15 — a refusal may not cite a call that contradicts it** (`158c868`).

## 2026-08-26 / 08-27

- **Five environment leaks closed**, the fifth a cohort recruitment figure that sat in a
  convention, was served by a tool and reached a saved record's `prior_work` (`e23cc9b`,
  merged `c4da689`). It passed the marker scan and the provenance check honestly.
- The residual control that follows is in `DESIGN.md` §5.3.
- **Scorability computed rather than asserted** (`05f6315`); the refute/confirm rule is in
  `DESIGN.md` §6. Read status from `benchmark/scorability.py::status_counts`.
