# DESIGN.md
What the system is. Operating rules: `AGENTS.md`. Open work: `TASKS.md`.

- COMPASS asks whether a model can specify a defensible epidemiological design from a
  survey instrument alone, and separately whether it is doing that or recalling papers.
- Input is one enumerated exposure–outcome pair; output is a protocol — exposure, outcome,
  covariates split adjusted/excluded/undetermined, model form, falsification threshold
  (`agent/schema.py::ProtocolSpecification`). No analysis is ever executed and no
  participant data exists: the system computes **estimability**, never soundness.

## 1. Related Documents
| Document | Role |
|---|---|
| `AGENTS.md` | Operating rules, model-agnostic |
| `CLAUDE.md` | Claude Code overrides only |
| `TASKS.md` | Open backlog |
| `CHANGELOG.md` | Merged history |
| `references/PRIOR_ART_CONTAMINATION.md` | Contamination and retrieval prior art |
| `benchmark/cohort_papers.py` | The cohort bibliography, held out from the tools |

- The `## N.` numbers are stable IDs: append-only, never renumbered. Cite prose `doc §N`,
  code `path::symbol`, never line numbers.
- `AGENTS.md` wins on a rule, the owning module or test on a number; never trust a doc.

## 2. Core decisions
- **Two model calls, never one.** Call 1 reasons in unconstrained prose with tools; call 2
  transduces into the schema and adds no facts (`agent/specifier.py`). It pays the
  INHERITED format tax: 8–27B models lose 4–10 points doing both at once (§8).
- **Python orchestrates; the model never chooses what happens next** — not the pair, the
  sample count, the stopping point, nor the winner.
- **The environment is the instrument**: every key a record names must come back from a
  tool; untooled facts do not belong in a record (`agent/tool_authority.py`).
- **Refusal is a first-class output**: an unresolvable pair yields `NotSpecifiable`, never
  a fabricated protocol. Until it can, schema pressure and recall are indistinguishable.
- **Unknowable quantities are admitted, not invented**: no analytic n, response coding or
  unverifiable prevalence — null plus a blocker (`benchmark/unearned_assertions.py`).
- **Contamination is measured, not asserted clean**: three routes, only one closes (§5).

## 3. Architecture
```
enumeration (Python) -> one pair
  call 1  REASON     unconstrained prose, tools, bounded loop; every fact enters here
  gate    MECHANICAL did the log hold the calls a defensible record needs? no model
  call 2  TRANSDUCE  schema-constrained; sees its reasoning and the log; adds nothing
  authority MECHANICAL  overwrites environment-computed fields, rejects contradictions
  validate + repair -> k samples -> dedup by record_hash -> selection -> parked/
```

- Keep `agent/specifier.py::_rank` a pure function of the record; a test AST-parses it
  against any backend, score, judge or rating reference. A model ranking its own outputs
  on soundness has no measured skill, and a same-family judge inflates its own kin.
- The gate reads OUTCOMES, not names: a required call counts only if it succeeded and
  named a key of the pair under specification. Replaying the logs in `run/logs/`, one run
  in twelve had asserted a detectable effect from a tool that only ever errored.
- Where a model must name an instrument item, it names an INDEX and the harness resolves
  it (`agent/prompt_contract.py`). A delimited line plus prose describing how to parse it
  is a parser specification, and three model tiers parsed one such rule three ways.
- A model may signal that it needs more evidence; it may not decide whether it gets any.
  `benchmark/resolver_eval.py::grant_samples` is a pure function of the run.

### 3.1 Module map
| Module | Role |
|---|---|
| `build.py` | Codebooks -> `build/dictionary.json`; deterministic, rules hashed |
| `checks.py` | The build's assertions, split into structural and snapshot groups |
| `generate/funnel.py` | Enumerate, prune, estimability, tag; owns `enumerated` |
| `agent/specifier.py` | The two calls, the mechanical gate, k-sampling, `_rank` |
| `agent/schema.py` | Schema + validators. Its docstrings are prompt text — §5.1 |
| `agent/tool_authority.py` | Overwrites env fields from the log; writes `screened_from` |
| `agent/sealed.py` | Disposable `mkdtemp` cwd; cuts memory, settings, plugins, state |
| `agent/cli_backend.py` | Headless `claude -p` over MCP; withholds built-in tools |
| `env/tools.py` | The environment tools. No network; a model only on operator grant |
| `env/labels.py` | Binds each key to its verbatim wording; `cite()` is the only maker |
| `agent/registry.py` | `build_registry(mode)` — the one construction site for a toolset |
| `mcp/compass_server.py` | Tools over stdio JSON-RPC; logs calls WITH return values |
| `agent/prompt_contract.py` | A model-visible surface as a typed record; selection by index |
| `benchmark/` | Held-out keys, contamination check, `benchmark/retrieval_eval.py` gate |
| `benchmark/resolver_eval.py` | Scores a prose resolver: k shortlists, one critic, 3 arms |
| `benchmark/leak_facts.py` | Seal-probe key; platform spellings; the §7 contest |

## 4. The instrument, and what it does not contain
- The instrument is the module codebooks, exported two-column: question id and question
  text. Module list `build.py`; entry and construct counts `build/dictionary.json`.
- Null across every entry, therefore unassertable: response options, value labels, value
  types, missing codes, measurement level, branch dependency.
- No participant count exists; `occurrence_count` counts question-id repeats. Hence most
  of the rules: a stated response scale, analytic n or prevalence asserts what the
  environment cannot supply — the class `benchmark/unearned_assertions.py` enumerates.

## 5. Contamination model
Three routes by which a published analysis reaches the model. **Only one closes.**

- **Route 1, environment** — our own tools, conventions, prompts. Scan the ASSEMBLED
  surface (`benchmark/contamination_check.py::model_visible_surface`), every tool's return
  value included: tool output is made at call time, invisible to grep.
- **Route 2, pretraining** — closed by no pipeline choice. A sealed elicitation battery
  found no declarative recall on `claude-haiku-4-5` (`agent/sealed.py::verify`); that
  bounds what a model will *say*, not what tilts its designs, and "could not detect" is
  not "absent".
- **Route 3, retrieval at inference** — withhold tools at the process boundary with
  `--allowed-tools` and `--strict-mcp-config` (`agent/cli_backend.py`), not by convention.

### 5.1 Docstrings in `agent/schema.py` are prompt text
- `model_json_schema()` copies class docstrings into `description` fields pasted verbatim
  into transduction; one told every transduce call what the benchmark held. Guard:
  `tests/test_schema.py::test_the_transduce_schema_carries_no_study_content`.

### 5.2 The line
- **Instrument metadata** — what the cohort measured, registry contents, cohort size — may
  enter the environment if study-team sourced, so provenance is auditable.
- 🛑 **Design choices** — the pairing, the adjustment set, model form, a realised n, a
  reported prevalence — are what the benchmark measures; they never enter `curated/`,
  `env/`, an `agent/` docstring or a prompt.
- **A paper-derived bound may never set the environment's floor.** Per
  `benchmark/unearned_assertions.py::PROVENANCE_TIERS`: theory-derived values may set one
  anywhere; general-literature and cohort-paper values are `benchmark/`-only.

### 5.3 What the automated checks cannot do
- Markers catch quotation, not paraphrase: a convention written from a paper's reasoning
  with its numbers removed passes every check. **"Clean" is not "uncontaminated."**
- The residual control is a human re-reading every curated sentence against the paper
  record; nothing automates it, and one figure passed both scans honestly (`e23cc9b`).

## 6. Benchmark design
- **Rediscovery, not novelty**: input is a published pair, the key that paper's realised
  design, the score what the system recovers from instrument and conventions alone.
- A published pair is not disqualified; having ground truth, it is the only scorable kind.
- **Partition the answer key**: environment-forced fields (clustering per convention,
  `analytic_n` null because `estimate_n` says so) versus paper-free ones (covariate set,
  model form beyond default, the paper's n). Agreement on the first carries zero recall
  information; only the second can.
- Extend `benchmark/prevalence_key.py::IDENTIFICATION_VALUES`, never a second vocabulary,
  and filter rows by `role` before treating one as outcome evidence.
- **Never report a single "percent of design recovered" figure**: it conflates instrument
  reasoning with recall and is uninterpretable.
- Refute from the instrument; confirm only from a key that resolves live through
  `env/tools.py::resolve_variable` (`benchmark/scorability.py`). Word presence is not
  construct presence.
- The calibration set is the only ground truth that cannot have been memorised: the
  *instrument* confirms the pair unanswerable, so no paper holds its answer.
- Never drop its answerable arm — refusing everything scores perfectly without it. Arm
  sizes, ratio and dropped categories: the `benchmark/calibration_set.py` docstring.
- **Doubt a date-cutoff tier gap.** Run Duan et al.'s vocabulary-overlap diagnostic (arXiv
  2402.07841 §4) first: it tests temporal shift, never membership.
- Report no tier number until `benchmark/tier_gate.py::assert_gate_clear` passes.
- Treat `benchmark/cohort_papers.py` as a LOWER bound, never a census: paywalled,
  Methods-only and differently-labelled papers stay invisible, and `KNOWN_DUPLICATES`
  makes the size entries, not ids in the wild. Read the size there, never here.
- Re-derive every tier assignment built before 2026-08-27
  (`benchmark/cohort_papers.py::uninventoried`): most entries were unknown to any prior
  exclusion list.
- If retrieval is ever built: a frozen date-filtered build artefact, never a runtime
  search, after transduction, generation-mode only — settled in
  `references/PRIOR_ART_CONTAMINATION.md`, read before reopening.
- That mode boundary is load-bearing: the benchmark is rediscovery, so a prior-work critic
  in benchmark mode flags every scorable pair (`agent/registry.py::build_registry`).

## 7. Known limits
- **`estimability.exposure_contrast` is bound to no tool**: `agent/tool_authority.py`
  never references it, so a record can assert a contrast the environment never returned.
  Not an environment-forced field for §6's partition until bound.
- **The corpus binds harder than contamination.** Read refuted/confirmed/undetermined from
  `benchmark/scorability.py::status_counts`; no contamination fix repairs it.
- Refuted rests on a recorded fact — the key puts the outcome outside the questionnaire,
  or no token of one side is in the instrument. Confirmed needs a key resolving live on
  both sides, so nothing confirms until `benchmark/scorability.py::EXPOSURE_KEYS` is
  filled. That module's docstring records papers the naive word test admits wrongly.
- **A frontier-model run is not evidence about the target**: no grammar enforcement
  through the CLI, no format tax. Never cite Haiku results for 8–27B models.
- **The blocking external dependency is the module co-completion counts.** Without them
  every pair is `estimability=unknown`, `n_source` only `unknown`, nothing reaches
  `ready_for_review`, and `_rank` falls through to covariate count then hash.
- Outcome frequencies are the second ask of the study team; one delivery clears both.
- **The survey platform is contested**: the operator states one platform, a cohort paper's
  Methods another. Ask; assert neither (`benchmark/leak_facts.py`).
- **Lexical retrieval cannot bridge caller vocabulary to instrument wording** ("age" ->
  "birthday"): recall, not ranking, is the binding half, and the honest best lexical match
  is often the wrong item (ratchets: `tests/test_search_scoring.py`).
- Bridging it is semantics, so the remedy is an agent-side rewrite stage OUTSIDE `env/` —
  a second model in the pipeline, `TASKS.md` C16/C17. Do not re-litigate by argument.
- **`env/tools.py::search_variables` silently OR-decomposes a phrase**, so 'green space'
  can return a phone-number item; read the decomposition before any "zero hits, therefore
  absent".
- **Benchmark-mode withholding is vacuous**: no member of
  `agent/registry.py::RETRIEVAL_TOOLS` exists, so `generation − benchmark` is empty and
  its test passes without testing. Building any of them makes it real.
- **C18's flag rate is not a contamination rate** and must never be reported as one: with
  no ground truth it filters on "produced a complete design", not "answered correctly".
- Its `contrast` and `model_form` are closed lexical lists, so an unusual estimator misses
  into `not_specifiable_unaided` — the expensive direction for a subtraction filter
  (`benchmark/unaided_specifiability.py::RUBRIC`).
- Retrieval recall measured here is an upper bound (`AGENTS.md` §Testing Patterns).

## 8. Open questions
- Whether the Specifier may consult a curated literature corpus *while designing*, or only
  have a finished design annotated against it. Our raw material is the questionnaire,
  which argues annotate-after (`references/PRIOR_ART_CONTAMINATION.md`).
- Whether a location-bearing variable parked in `excluded_variables` stays exempt from the
  access budget (`env/tools.py::check_access`): the exemption is deliberate, since
  penalising disclosure suppresses it, but unconditional.
- Whether the response-scale detector graduates from advisory to a gate, on what set size.
- Minimal-agent versus multi-agent. INHERITED evidence favours minimal; the one datum the
  other way is external prior work reported as an association,
  `references/PRIOR_ART_CONTAMINATION.md` §"Calibration for expectations". Not ours.
- Two INHERITED data points with no code home, never re-verified here: same-family
  judge/specifier pairs carry +0.076 excess error agreement (basis for a cross-family
  critic), and the format tax behind the two-call design (§2). Rationale, never a result.
- VERIFIED 2026-08-28: Qwen3 publishes no knowledge cutoff on its model card or technical
  report, so no date-based holdout is constructible on it.
