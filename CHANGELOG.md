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

## 2026-09-24

- **C18 — the pre-registered sweep read against its registration and recorded**
  (`6416ecd`). It ran in the loop clone, which the withholding control's
  `tool_log_path` names. Its window and HEAD are recorded nowhere (`provenance.date` is a
  day), and are re-derived from that clone's reflog and file mtimes: 2026-09-11
  12:38–16:56, started at `10f22b0` (HEAD reached `a6251a3` during the run), after
  `4322e57` and `9214b28` fixed the tool-log path and the seal. Every value the files
  record matches (`min_specifiable` 1 of 5,
  `claude-haiku-4-5`, rubric `694100e1ea900ddb`, dictionary `3dc8415eccfe`, both controls,
  withholding `ok`). The frame digest is not recorded; re-derived, it is
  `241d604e339a`, and the 256 records are exactly its live pairs. 63 of 256 frame pairs
  were flagged, and 193 form the arm pool. Re-scoring the persisted records reproduces
  the partition. 159 of the 193 are five-of-five refusals, which bounds C6
  (`DESIGN.md` §7).
- **The retrieval prompt is scanned in the shape serve sends, facts and all** (`9312c3a`,
  `18a1295`). The marker scan rendered `retrieval_prompt` only over the facts-free
  catalogue, so the C32 index exemption was validated on a shape that never ships.
  `retrieval_prompt:pool` now renders beside it: keys from the retriever's target list,
  facts from the dictionary. `tests/test_contamination_surface.py` reads serve's fact
  shape by AST and checks each value against what serve would attach. The comparison
  found three keys where serve's `roster_family_size` is not the dictionary's
  (`TASKS.md`). An absent `deploy/targets.json` fails the gate and its tests loudly,
  like the other gitignored files it reads; SKIP stays reserved for withheld modules.
- **The endpoint enumerates named frames only, and names the frame it used** (`9c2cbdd`,
  C41(a)). `_enumerate` built its sides with its own comprehension, so an endpoint count
  carried no frame and no digest. The frame scan missed this because it flagged only
  constant prefixes. Custom sides that match no frame are now refused.
- **An endpoint job keeps its repair history** (`565f873`, C19 residue). The job record
  reuses the driver's `save_repairs`, so a derivation value the validator supplied
  through a repair has a visible source, and the trace runs over it.
- **A keyed contamination section can no longer read `ok` without its key.** Every skip
  test planted its skip on `check_provenance`, which imports nothing. Wrapping the
  platform scan's `leak_facts` import in `try/except ModuleNotFoundError: return []`
  kept the tests green and made the gate print `ok    survey platform named in surface`
  for a scan that ran on nothing. Now `tests/test_contamination_skip.py` withholds every
  key through `sys.modules`, so this holds in the scoring clone too. It then drives the
  three sections that read one, directly and through `main`'s own table, and requires
  SKIP, never `ok`. An AST scan pins `_KEY_READERS`, in both directions, to every
  function under the gate that imports a key with an import statement (`from` or
  plain); a dynamic `importlib` import escapes it — rule binding, test partial. The same audit found a second route to the
  same false `ok`: `benchmark/input_leakage.py::scan_frame` read the prevalence key per
  prompt, so an empty frame never touched it. It now reads the key once before its loop.
  Seeded red, each over the whole file: the platform wrap, the same wrap on
  `_prevalence_tokens`, the read moved back into the loop, and an undeclared key reader.
- **The `--live` scorer is under the same test, and its gap was a full pass.**
  `_live_run_without_the_scorer` replaced `SealedWorktree.verify` with a stub that
  raises, so `agent/sealed.py::score` never ran without its key. Seeded with
  `try/except ModuleNotFoundError: return CLEAN, []` around its `leak_facts` import:
  every probe printed `ok`, the run printed `clean`, and `--live` exited 0, with every
  other test green. `tests/test_contamination_skip.py` now runs the real `verify` and
  `score` with only the model call faked and the keys withheld, and requires
  `SKIP  live seal probes` and exit 1; `score` joins `_KEY_READERS`, whose scan now
  covers `agent/sealed.py`.

`TASKS.md` reconciled against the code. Seven items had landed and were still listed as
open; they move here, each with the commit that closed it. Nothing below is new work.

- **C17 — provenance for a run with two models** (`3676ded`, 2026-09-11). TASKS said
  "BLOCKED on C16". The Haiku pin covers the Specifier, not a resolver, so a larger
  resolver is legitimate and a record hiding it is not (`benchmark/resolver_eval.py` and
  `tests/test_resolver_eval.py` cite this as "`TASKS.md` C17").
  `agent/schema.py::Provenance` gained `models`, keyed by
  `ModelStage` (resolver, splitter), and `anchors_proposed_by`; a record whose anchors a
  model proposed fails validation unless its resolver is named. The splitter half is
  built in the schema but stamped by no route — open under C29 in `TASKS.md`.
- **C19 — persist the repair channel** (`b869c85`, 2026-09-10).
  `agent/specifier.py::untraced_derivation_values` traces each derivation value to its
  log or a kept repair, and `generate/live_specifier.py` writes `.repairs.json` beside
  each record. The `serve/` job record is not extended — open as "C19 residue".
- **C27 — a failed seal probe no longer scores clean** (`d188f76`, 2026-09-10).
  `agent/sealed.py::SealedWorktree.run` raises `SealedRunError` on an exit-0 `is_error`;
  seeded with the three strings in `tests/test_specifier.py::_CLI_ERROR_RESULTS`.
- **T4 — `--system-prompt` replaces `--append-system-prompt`** (`d1eaf30`, 2026-09-10).
  TASKS still said UNVERIFIED; the commit records the live Haiku check (a canary word
  from the system prompt, and `resolve_variable` called through MCP), and a test pins
  both calls' argv.
- **T7 — one named, hashed frame, walked in enumeration order** (`a058c35`, `f82e7ed`,
  2026-09-11). `generate/funnel.py::Frame`, `FRAMES`, `walk`;
  `tests/test_funnel.py::test_no_driver_builds_the_frame_by_hand`. The endpoint still
  builds its own sides, which that test cannot see — open as C41(a).
- **C29a — `absent` is a claim about the list shown, not the codebook** (`5202762`,
  2026-09-10). `VariableSelection`, `RETRIEVAL_GUIDANCE` and
  `benchmark/resolver_eval.py::CriticVerdict` define it on the items listed; both
  `serve/` prose routes return `absent_scope`. Its re-baseline rule moved to C16 in
  `TASKS.md`, which is where resolver_eval results are quoted.
- **C28 — `_rank`'s covariate-count term removed** (user amendment, 2026-09-11). It paid a
  record for adjusting for a wrong-construct key over one that filed the gap in
  `sought_covariates`. Three independent reviews (enterprise account, opus) said
  `sought_covariates` must not become a term instead: it is prose nothing checks, so "more
  gaps rank higher" picks padding and "fewer rank higher" rebuilds C28. The fix is
  neutral, not a win: the two records tie and the hash picks one. Follow-ups: (a) dedup
  no longer keeps the first seed on a tie, and (c) `agent/specifier.py::_twin_order`
  replaced the raw `_disclosure` count — any gap beats none, the count does not matter,
  then a content hash; every losing twin is parked (`6030450`). (b) the live driver
  copies the selected twin's own tool log, audit and repairs (`02cf793`).

The finite list a five-seed review left behind, landed and closed. Two real defects with
external consequence, two Hard Constraints that were held by prose, and one claim
converted from blocked to weaker-and-true. The DONE CONDITION was written down before the
work started and is honoured: this line of work is complete for agents, and what remains
is in `TASKS.md` §Only the operator.

- **Redaction keyed on the FIELD NAME, and five route names were not on the list**
  (`a74c773`). `serve/api.py` sends `stem_text` as `exposure_stem` / `outcome_stem` and
  `cite().wording` as `pinned_wording` / `exposure_wording` / `outcome_wording`, and
  wording under five words is invisible to the run rule. Driven over the socket on a
  default bind, `/api/enumerate` returned a direct-identifier stem verbatim with zero
  redaction marks. The fix is content-based, so the name no longer decides, and the gated
  list is now DERIVED from the emitting routes by AST rather than hand-kept.
- **The site-dir guard did not know its own outputs** (`9634447`). A run directory left
  inside `--site-dir` by an earlier session cleared both checks; 200 on the pseudonym map
  and on an unscrubbed job record, measured. The coverage test runs the two writers and
  requires every path they leave to be a named marker.
- **Two guarantees were held by comments** (`620a3cf`, `4dd4808`). "No `BlockedOn` member
  for disclosure" and the order of `_side`'s branches both survived a positive control
  with the suite green. Neither constraint changed; both now have tests whose red state
  names the member or the paper.
- **The rediscovery claim has a bound every clone can re-derive** (`4dd4808`).
  `scorability.py::key_free_ceiling` replaces a figure measurable in one clone only, and
  `TASKS.md` §Open quotes it instead of repeating the irreproducible one.
- **Five stale pointers, one of which misrouted `/loop`** (`c62cc0f`), and `serve/` and
  `site/` are no longer UNASSIGNED in §Parallel Lanes.

C31 closes, and the website can drive the pipeline. The three defects below all sat in
`serve/api.py`, all stopped the hand-off from a proposal to a run, and none had a test.
Two were found by running the site's own flow end to end rather than by reading code; the
third was found by the test written to protect the second. Every fix was seeded red
against the whole file first.

- **`/api/pair` and `/api/resolve` issued tickets nobody could poll.** `do_POST` gated on
  `route.startswith("/api/specify")`, which also caught `/api/specify/status` — the one
  route the two cheap proposal routes share. On a default bind a proposal was therefore
  accepted, spent its model call, returned a ticket, and every poll of it answered 403:
  the site's *Ask the pipeline* flow was dead in the shape that reads as "the server is
  broken" rather than "this route is off". The prefix match was the bug, because it made
  one flag govern routes whose costs differ by an order of magnitude. Tickets now carry
  their own kind and the gate reads that; the operator chose this over gating the
  proposal routes too, so proposing anchors stays cheap and separately available.
  `/api/specify` itself is refused exactly as before, and its reasoning is unchanged.
  An UNLABELLED record — one written before kinds existed, read back off disk — resolves
  to the refused kind, so age cannot weaken a spending gate.

- **A proposed key was not a key the Specifier would take.** `_canonical_key` matched
  only construct keys, while `/api/pair` proposes whatever the retriever offered, and that
  is the sub-item `key` field. MEASURED over `deploy/targets.json`: of the 1,353 offerable
  keys, **407 were sub-item keys refused with a 400** before any model call — the whole
  `derive` path, and the site's own demo request among them. The mapping needed no
  inference, since `deploy/retriever.py::_hit` already returns `construct_key` beside
  `key`. A sub-item key is now translated to its construct and the translation is
  REPORTED, following the case fix's own precedent; it is reported in its OWN field,
  because it changes the request's grain rather than naming the construct the caller
  already meant, and `key_case_corrected` would have said something false beside it.
  `Unresolvable` still fires, still before any model call, for a key naming nothing.

- **`State.enable_specify` defaulted to `True` while its own docstring said "off".**
  Found by the test written to prove the 403 above was not weakened: it got a live
  Specifier run instead. `main` has always passed the flag explicitly, so no deployed
  endpoint was affected — but every other constructor got the expensive route enabled.
  This is the unenforced-guarantee shape `AGENTS.md` names as the recurring defect, and
  the rule it now follows is the one `build_registry(mode)` already followed: a flag that
  spends the operator's seat does not default to permissive.

- **C31 (a), (b) and (c) are all done, and C31's own text was stale.** Corrected by
  measurement 2026-09-15: it claimed `_pair`, `_resolve`, `_role_candidates` and
  `_pin_keys_from_prose` were "never invoked by any test" (12, 2, 9 and 7 references),
  and it pinned a test count for `tests/test_serve_redaction.py` that was already wrong
  when written — read that count from the file, never from a document.
  (a) and (b) had already taken the docstring route. (c) was reported as untested and is
  not: `test_the_role_never_reaches_the_encoder` already pins that `to_query` never
  renders `role`, and `_role_candidates`'s docstring already states it. What survived of
  (c) was the dead `surface` — built on every call, read by nothing, and not a forgotten
  optimisation but a trap: it carries the framing for the role it was CALLED with, while
  `_pair` offers ONE pool to both roles, so reusing it would ask "which item serves as
  the EXPOSURE here?" and file the answer as the outcome. Removed, with the per-role
  framing pinned instead. The helper's documented return also named a key (`candidates`)
  that no caller could index.

- **The page came in-tree, and `CHANGELOG.md` did not say so** (`0606136`, 29 files,
  5,884 insertions). `site/` was named ZERO times here and `serve/` once, while the line
  in `TASKS.md` §C29 that cites this entry is about the page MOVE. `--site-dir` had
  defaulted to `/home/mehta5/compass-site/site`, the only copy of the page that existed,
  so `python -m serve.api` exited 2 on any box but one and the endpoint could not be
  started from a clean checkout. The page is now `site/` here, `--site-dir` defaults to
  it, and the pair of defaults is checked against `_refuse_unsafe_site_dir` by a test,
  because a `site/` inside the repository sits one directory from `build/dictionary.json`.
  The `compass-site` clone keeps 80 commits of its own history that were NOT brought over
  (`README.md`) and has no `serve/`, so it could never have run the endpoint.

- Live confirmation, 2026-09-15, both defects driven end to end on a private port and
  reported beside the server's own log: a default bind polled a pair ticket to `done`
  (HTTP 200 throughout, `kind: pair` on disk) while `/api/specify` still answered 403;
  and the exact key that run proposed, `m3:Q16.1_2`, was then accepted by `/api/specify`
  and came back `1 specified` with `key_subitem_to_construct` reporting the translation
  and `key_case_corrected` null. Both runs are `externally_posed` with `screened_from: 0`
  and enter no benchmark denominator.

---

## 2026-09-14

C35 decided and C36 landed: the answer key for a paper's design arrow left this clone,
grew types, and became the only reader for design. The rows themselves are still the
operator's and still unwritten — `TASKS.md` C36 carries what is open.

- **C35 — an area-measure exposure is explicitly out of scope, not unfilled**
  (`5cafa88`, implemented in `f6d25f8`). Four answers were on record and they were
  different claims about what the benchmark measures, so nothing downstream could be
  built while it was open. The operator chose C now / B later, plus a third status
  rather than forcing the case onto REFUTED or UNDETERMINED. Answer D — confirm on the
  descriptor alone — stays forbidden by name, and `design_anchor.validate_design_key`
  refuses it: a key nothing resolves is the word-presence failure in a new costume. The
  verdict vocabulary and its ranking are in `benchmark/scorability.py`'s docstring; the
  rule is there, never here.
- **C36 — `benchmark/design_key.py`, withheld, with typed anchors** (`6e09750`,
  `d87e0e5`, `5228e45`, `f6d25f8`). The column it replaces lived in
  `benchmark/scorability.py` in the clone where prompts, `agent/schema.py` docstrings
  and `env/tools.py` are edited, and that was safe only while it was empty: the first
  row would have made the editing clone the clone holding the rediscovery answers. The
  shape and the validator stayed visible in `benchmark/design_anchor.py` so every claim
  about them is testable where the code is written; only the ROWS are withheld.
  `Anchor` carries `term`, `kind`, `key` and `blocked_on` — the three facts a bare key
  tuple lost, each with a recorded cost in `TASKS.md` — and fails closed on every
  illegal combination.
- **Both sides read one table, and the prevalence key stops being a second design
  authority** (`f6d25f8`). Its four design-shaped accessors moved to
  `benchmark/prevalence_rows.py` with their tests; the scoring path imports neither them
  nor the key, and a test fails if either import reappears. That is C36's own strongest
  objection to itself — two keys that can disagree about one paper are worse than one
  key with a blank cell — mitigated by enforcement rather than care. Three filed defects
  close with it: the type that could not express its own settled key form, the exposure
  side having no way to say the instrument does not carry it, and
  `key_does_not_resolve`'s remaining overload.
- **Two rules landed TIGHTER than C36 proposed, both conservative.** CONFIRMED needs
  every term on a side answered rather than any one resolving key, and one term may
  still carry several keys — the operator's decided depression row is why, and a
  validator that refused repeated terms had to be corrected in `5228e45` because it made
  that row unrepresentable.
- **`tests/withheld.py` gained the direction nothing checked** (`d87e0e5`). A guard
  naming a module nobody withholds was caught; a withheld module with NO guard was not,
  and that leaves every test needing it red rather than skipped — the permanently-red
  suite that module exists to end. Both directions are asserted now, as two tests.
- The guarded-test ratchet moved down. Read it from
  `tests/test_withheld.py::GUARD_CEILING`, never from here.
- Corrected a line that cited a tree-wide null as item-level evidence (`d6946c1`).
  `branch_dependency` is null on every entry by construction, and the draft that used it
  had read the field off a tool return that does not carry it at all — `.get` answering
  None for the wrong reason.

Phase 2 of the refocus: a measurement that runs without an answer key or a domain expert,
and the scaffolding for a worked rediscovery up to the rows the operator owns. Every
number below is a first reading for the record, not a floor — re-run the module, never
quote a figure from here.

- **`benchmark/design_quality.py` — a groundedness dashboard over the pipeline's own
  records** (`c8c681f`). Every other measurement in `benchmark/` was blocked on somebody
  else's artifact, so "is this getting better" had no answer. This reads what is already
  computed: validation as the filter, `agent/schema.py::REFUSAL_EVIDENCE` /
  `REFUSAL_OUTCOMES` for which lookups a refusal needs, `env/tools.py::resolve_variable`
  for live key resolution, and `unaided_specifiability::with_instrument` for the
  instrument split. `agent/specifier.py::_rank` is untouched. A dashboard and not a gate:
  no floor, no ratchet, no exit code tied to a number, because the corpus is whatever has
  been run and a threshold over it would pin today's corpus.
- Three reporting rules it exists to keep, each with a seeded mutation behind it. The
  denominator is printed and not implied — every glob match gets a disposition and the
  listing names it, because `pathlib.Path.glob` keeps the dotfiles a shell `run/*.json`
  drops and `run/` holds pinned failing records saved as dotfiles for exactly that
  reason. An empty denominator renders `--`, never `0%`. And a refusal with no tool log
  beside it is `unmeasurable`, never a failure.
- The one that needed a third state: a cited `registry_coverage` call. The log always
  records `ok` and the specifier stamps the emptiness it read out of the payload, so
  equality with the cited outcome fails on an honest refusal while presence-only would
  claim a check that did not happen. `CALLED` is neither, and is reported separately.
- **`benchmark/rediscovery.py` — C12's ACCEPT criterion made runnable, and the
  side-by-side** (`1e59dc8`). `--validate` resolves every asserted `EXPOSURE_KEYS` key
  live and names the key that failed; `--pmid P --record F` prints a paper's recorded
  design beside a `ProtocolSpecification`, field by field, assembled from the three places
  the project already keeps that content and storing none of it. It is NOT a rediscovery
  score — that is `TASKS.md` C21 stage (i) — and emits no total: two key columns compare
  mechanically, everything else reports `REVIEW`. Four comparison states, not two, and the
  unreadable-column branch survived the first seeding pass green, which is precisely the
  case the distinction exists for. Exit 2 when the outcome key is withheld, 1 on a
  complaint; a failure outranks an incomplete run. Named in
  `contamination_check.py::check_holdout_not_reachable`.
- **The C12 chain is PARKED, not cancelled** (`TASKS.md` §PARKED). Four items sat behind
  an artifact no session could produce, while nothing measured progress in the meantime.
  The apparatus is intact and unparking means filling the key; expert ratings are parked
  with it. The n=1–3 worked rediscovery is the live item in their place.
- `tests/test_withheld.py::GUARD_CEILING` caught the first attempt at the
  count-moves-when-a-row-lands test: two more guarded tests is two more pieces of coverage
  leaving the clone where prompts are edited. The claim is split three ways instead, and
  only the middle link is guarded.

**The rediscovery benchmark has no reachable pair, and that is a measurement now.**
Run 2026-09-14 in the scoring clone, `benchmark.scorability.scorability_report()`:
10 REFUTED / 0 CONFIRMED / 6 UNDETERMINED over the 16-paper bibliography, every
refutation on the OUTCOME side. The cohort's published work measures assays, biomarkers,
blood pressure, a metabolome and biospecimen participation; the instrument is a
two-column questionnaire and `clinical`, `lab` and `ehr` are declared EMPTY. Three papers
present as one exposure key from CONFIRMED and are not: their exposures are area-level,
they are the false survivors `scorability.py`'s docstring already names, and
`search_variables` on each term returns the survey-link question and the drinking-water
item. Recorded in `TASKS.md` §Open — the worked rediscovery, with the two defects it
exposed (`EXPOSURE_KEYS` cannot express its own settled key form; the exposure side has
no `instrument_region` counterpart, so its strongest blocker understates an absent
construct as an unfilled cell). Never quote these counts — re-run the report.

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
