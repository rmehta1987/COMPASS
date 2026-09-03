# AGENTS.md
Operating rules, model-agnostic. Document roles: `DESIGN.md` §1.

## Source of Truth
- Authority: built dictionary + code (`agent/ env/ generate/ benchmark/`) > `AGENTS.md` >
  `DESIGN.md` > `TASKS.md` > `CHANGELOG.md` > `CLAUDE.md` (last, deliberately) >
  `.claude/projects/-home-rmeht-Projects-COMPASS/memory/` (Claude-only; others ignore it).
- Not a total order — no-peer domains: instrument → `build/dictionary.json`; bibliography
  → `benchmark/cohort_papers.py`; prior art → `references/PRIOR_ART_CONTAMINATION.md`;
  what code *does*, never what it *should* → module + tests; open work → `TASKS.md`;
  history → `CHANGELOG.md`.
- Cite `doc §N` for prose and `path::symbol` for code, never line numbers.
- A doc line, memory hook, handoff sentence or subagent report is an INDEX, not evidence:
  open the primary before asserting a load-bearing claim or seeding a subagent.
- Operator pushback triggers a primary re-read, not a reversal; never flip unchecked.

## Hard Constraints [never violate]
- `codebook.csv` in the project root is not project data. Never read it.
- 🛑 `env/` may never make a network call — the leak channel the argument rests on. The ban
  is on `env/` code CALLING out, not on a closure holding such a package (`8042f4d`).
- That check is literal-import regex: transitive blindness is CORRECT scoping, not a hole;
  `aiohttp`, `litellm` or an `importlib` call still passes — rule binding, test partial
  (`tests/test_specifier.py::test_env_never_touches_the_network`). `env/` is stdlib-only.
- `env/` may load a model only on a grant in `tests/test_specifier.py::ENV_MODEL_GRANTS`;
  only the user extends it. If retrieval needs an embedding, ask.
- A grant needs all four, reviewer-judged: vendored pinned weights, deterministic output,
  inspectable text for the surface scan, logged disagreement with the lexical order.
- No participant data and no analysis executed — estimability, never soundness.
- `agent/registry.py::build_registry(mode)` builds every tool dict; `mode` has no default.
- Never invent an n: `env/tools.py::estimate_n` returns null + `unknown` + a blocker.
- `agent/schema.py` docstrings are prompt text via `model_json_schema()`: no design,
  exposure, outcome, paper count, cohort figure or prevalence there.
- Every response-coding gate pattern must require a numeral: absence-prose names none.
- The model never chooses what happens next: `agent/specifier.py::_rank` is a pure
  function of the record, AST-tested against backend, score, judge and rating references.
- Changing `_rank`, a Hard Constraint or its AST test is a user amendment, not a lane's.
- No `BlockedOn` member for disclosure: `_rank` sorts on `len(blocked_on)` ASCENDING,
  ranking an honest record below a silent twin. Denylist and its size: `agent/schema.py`.
- `sought_covariates` sits OUTSIDE `canonical_form`, so silent and disclosing records hash
  identically; dedup tie-breaks on the record, never seed order.
- Paper content never enters `curated/`, `env/`, an `agent/` docstring or a prompt;
  study-team-sourced instrument metadata may — `DESIGN.md` §5.2.
- Conventions stay `authored-unconfirmed`; only the user upgrades one, in writing.
- The in-pipeline Specifier is `claude-haiku-4-5`, the proxy for the 8–27B target
  (`generate/live_specifier.py`); never swap in a larger model to pass a run.
  `agent/cli_backend.py::ClaudeCliBackend` defaults to sonnet, so pass it explicitly.
- A bare key is unrepresentable: `Cited` needs the wording, `env/labels.py::cite` is its
  only maker, and it raises `CitationUnavailable` rather than citing empty (`49da51b`).
- Wording is `question_text` byte for byte — never rebuilt from stem + subitem, never
  collapsed, roster prefix never stripped (`49da51b`).
- A prompt's variable list is parsed from its body by the `string.Formatter` that renders
  it (`agent/specifier.py::PromptTemplate`); never a second list.
- Accepted tool args = advertised fields ∪ real signature (`agent/registry.py::SCHEMAS`).
- `build.py` hashes files + the rule fingerprint + n, not entries: any column, regex,
  shape-table or parsing-function change moves `version_hash` on its own.
  `BUILD_RULES_VERSION` is a label now, not the provenance.
- Every module-level function in `build.py` is hashed or in `_NOT_HASHED` with a reason;
  `build` and `read_module` are DECLARED GAPS — they decide rows and are excluded so a
  refactor does not move the hash.
- A key never reaches a model as a string it must copy back: `agent/prompt_contract.py`
  offers candidates by index and resolves the index itself. Three model tiers read one
  delimiter rule three ways before this existed.

## Verification Discipline
- Legend: VERIFIED = re-executed, with date and command. INHERITED = from an earlier
  review, unchecked — design rationale, never citable as a result.
- Measure it, cite it, or tag it UNVERIFIED — conversation and throwaway estimates too.
- Report as *ran* (command + real output) or *per the doc*; anything else is UNVERIFIED.
- "Could not detect X" is never "X is absent": without a positive control the word is
  *untested*, and `benchmark/contamination_check.py::MARKERS` catches quotation only.
- Never report a live run as working without showing the record beside its own tool log.
- Cite prior work as prior work; never cite this project's inconclusive runs as support.
- An unstated denominator is not a number: give the glob, filter and definition. A shell
  glob drops dotfiles `pathlib.Path.glob` keeps; `run/logs/` is untracked.
- An eval whose result moves with its instruction wording is not a measurement.
- Report the effect measured: an n=6 arm moving tool strategy is not accuracy (`8f9884f`).

## Testing Patterns
- Write the test in the same commit as the guarantee; an unenforced guarantee is this
  codebase's recurring defect (`f9ba07e`).
- Prefer a check whose red state names a defect, not a changed number: split on the
  property records carry, keep counts one-sided, never pin today's corpus (`c871b4f`).
- Seeded failure: break the behaviour and confirm red before landing it.
- Fix the fixture, not the rule — unless you *show* it wrong, by measurement.
- Pin a failing case, never delete it: it moves to `run/superseded/` and stays under test.
- Assert wiring with an AST `Call` node, not an `inspect.getsource` substring (`8dbaf86`).
- Key anti-vacuity probes per partition, with a floor per partition (`8dbaf86`).
- Scan `searchable_text` alone, and collapse whitespace first — codebooks break phrases.
- Read every ratchet, ceiling, floor, count and hash from the owning module or test.
- Direction: test count may only rise; lint ceilings only fall; recall floors only rise.
- Retrieval gate `benchmark/retrieval_eval.py`; ratchets and the collapse pin in
  `tests/test_retrieval_eval.py` (hit rule: `env/tools.py::_ROSTER_INDEX`).
- If that pin reddens it is telling the truth: re-derive the floors, never adjust the pin.
- Fixture queries saw each gold wording (`benchmark/fixtures/retrieval_queries.json`):
  recall is an UPPER BOUND, cross-method comparison indicative only — `KNOWN_BIAS`.
- Embedding, RRF and rapidfuzz runs need `numpy`/`sentence-transformers`, absent from
  `pyproject.toml`: unreproducible here, and never an acceptance gate.
- No oracle in the measurement: a filter or facet experiment takes its input from the
  query alone, never the gold item's label, and reports gold-excluded beside recall.
- `tests/test_search_scoring.py` ratchets age-query recall: red only when it worsens.
- A truncating default is a cutoff, not a preference: say what a small value costs
  (`tests/test_specifier.py::test_the_limit_parameter_says_what_a_small_limit_costs`).
- Run the suite before `git commit`, never piped — a pipe returns `tail`'s exit code.
- `rm -rf __pycache__` after restoring a seeded mutation — a block move fools `.pyc`.

## Contamination Practice
- Run `benchmark.contamination_check` after editing a prompt, a convention, an
  `agent/schema.py` docstring or `env/tools.py`; `--live` before any benchmark run.
- Read a red section by meaning: `every registry tool sampled` = an unscanned tool return;
  `markers` / `prevalence figures` / `survey platform` = paper content is model-reachable;
  `held-out registry unreachable` = an answer key reached a tool path.
- `surface_hash` is printed, never asserted; never stop on a moved hash.
- Capture the scanned surface by driving the emission path (`model_visible_surface`).
- Re-run a marker set, never inherit one: an outcome can also be instrument content.
- Sample every page of a browse-shaped tool: `check_tool_coverage` is blind to dead ends.
- `check_no_prevalence_figure_in_surface` takes `Q` on its left boundary; verify it still
  fires on prose, sentence-start, parenthesised and proportion forms.
- Writing a convention that reflects a paper's reasoning: stop and tell the user instead.
- Never name a paper to avoid in a prompt; control by selection, in Python (`s2_prune`).
- An agent reading paper content for a key or probe is itself a channel: it also authors
  `curated/`, docstrings and prompts. Apply `DESIGN.md` §5.2 to your own writing.
- A prose resolver returns CANDIDATES with wording, never one key, and refuses to start
  unconfirmed at n=1; its prompt and schema join `model_visible_surface`.
- An externally-posed record carries `screened_from=0` and `externally_posed` selection,
  never enters a benchmark denominator; log the lexical ranker's disagreement.

## Parallel Lanes
- Lanes run in their own `git worktree`. Assign every file to exactly one lane, including
  what it must NOT touch; anything unlisted is unassigned — assign it before dispatch.
- Cross-lane collisions are semantic; git catches none. Re-measure at merge, never trust
  either branch's numbers. Three instances: `9ee7cb7`, `bed8f0b`, `6160b99`.
- Two lanes lowering one ratchet: neither value is right; re-derive on merge (`73e55b4`).
- Before accepting a lane's report, run the suite, `ruff`, `mypy` and the contamination
  check in its worktree yourself, and re-derive its load-bearing claims.
- Cold critic on a different model family from the builder; re-derive its claims too. A
  critic's "does not reproduce" is a claim, not a result.
- Build orchestration is not runtime orchestration — no model drives `agent/specifier.py`.
- Cost is not a constraint: never skip a live run to save money, and do not ask to spend.
### Roles
| role | model |
|---|---|
| Orchestrator, Lane A (specifier core), Lane B (environment) | `claude-opus-5` |
| Lane C (funnel, drivers) | `claude-sonnet-5` |
| Cold critic after each merge | `claude-fable-5` |
| In-pipeline Specifier and seal probes | `claude-haiku-4-5` |

- Files: A = `agent/specifier.py schema.py tool_authority.py cli_backend.py backends.py
  prompt_contract.py`;
  B = `curated/ env/ benchmark/ mcp/ agent/sealed.py agent/registry.py build.py checks.py`;
  C = `generate/
  agent/RUNNING.md`. `tests/` follow their module; anything unlisted is unassigned.

## Code Standards
- `ruff` and `mypy` config: `pyproject.toml` (`google`, `E W F I UP B ANN D RUF`).
- Google-style docstrings on every public module, class and function: summary, blank line,
  `Args:` / `Returns:` / `Raises:`. Every parameter and return annotated.
- Inline comments explain *why*, never *what* — see `env/tools.py::_load`.
- Read `RUFF_CEILING` and `MYPY_CEILING` from `tests/test_code_standards.py`, never a
  document; they may only go down, raising one is a review failure, new files are clean.

## Efficiency and Commits
- Use `rg` for search; scope with `git status --short` before rereading files.
- Read paper bodies for load-bearing claims; exclude references and appendices.
- Do not build what exists: before writing retrieval, ranking, parsing or schema code, say
  which of `sqlite3`, `pydantic` or the built dictionary you reuse and why not. A
  disposition, not a gate: it rules out hand-rolled idf floors that measured worse.
- One logical change per commit; the message records the failure the change prevents.

## Verify current state
```bash
./.venv/bin/python -m pytest tests/ -q
./.venv/bin/ruff check .
./.venv/bin/mypy
./.venv/bin/python build.py | head -1
./.venv/bin/python -m benchmark.retrieval_eval
./.venv/bin/python -m benchmark.contamination_check
```
- Run all six from the repo root, paste real output, and trust no number in any document.
- Two stop conditions, only these: the test count FELL, or the build hash moved off
  `3dc8415eccfe`. A grown test count and a moved `surface_hash` are progress.
- The build hash is now a function of the RULES, not of a version string
  (`build.py::_rule_fingerprint`), so it moves whenever a regex, the shape table,
  a parsing function's source or a column changes. Moving it deliberately is
  allowed and is a user amendment; the pin lives once, in
  `tests/test_dictionary.py::BUILD_HASH`, with its history beside it.
