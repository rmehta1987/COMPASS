# STATE
D1: narrow   (brief default; operator's 2026-09-04 answer was unreadable ("sdfsdfss") — override here if wrong)
D2: branch = ralph-loop   (cut from main at 265241d, pushed 2026-09-04)
build: 3dc8415eccfe
last green: c5c8317   (VERIFIED 2026-09-04 by ./check.sh, GREEN, mypy counted 59 through colour)
note: check.sh omits 4 contamination checks by construction (contamination_check,
      input_leakage, scorability, tier_gate) — they import prevalence_key.py,
      which lives on scoring-key. They run in item 15 phase 2 only. A green
      check.sh does NOT mean contamination is covered.
      unearned_assertions.py is NOT among them and runs normally.
note: the brief's "four test FILES" is incomplete. Four further TESTS import the
      key inside their bodies and fail on any single-branch clone; check.sh
      --deselects them by explicit node id (same spirit as one-path-per-file):
        tests/test_catalogue.py::test_no_index_position_reads_as_a_withheld_figure
        tests/test_specifier.py::test_contamination_check_passes_offline
        tests/test_specifier.py::test_the_check_actually_catches_a_planted_leak
        tests/test_specifier.py::test_the_refusal_prompt_and_schema_carry_no_study_content
      They also run in phase 2 only.
note: fixtures/negative_requests.json does not exist anywhere (operator, 2026-09-04).
      Only src/ (retrieval experiments) and a smoke_test hint read it; nothing in
      check.sh needs it.
data placed in compass-gen (all gitignored): raw/ (public download), deploy/model/
      (sha match), deploy/targets.json (regenerated, sha 22b0c37a… matches manifest),
      benchmark/fixtures/ (retrieval_queries sha 8999c803… matches), run/ (from
      compass-gen-artifacts.tar.gz, 2026-09-04; screened: no key files inside).

note: item 15 precondition VERIFIED 2026-09-04 in compass-score only (never here): scoring-key present on the remote and fetched there. claude CLI 2.1.260 authenticated (one-word haiku call returned OK).
note: WORDING TENSION for items 11 and 15 (found at item 8). A funnel pair's
      requests are built from the construct's stem, so those RetrievalRecords
      carry withheld instrument wording in request.construct_text and query
      (marked RequestSnapshot.source == "instrument"). The specifier's own
      records already carry quoted_wording (VariableRef; Cited needs it byte for
      byte), which is why run/ is gitignored. The brief's item 15 phase 1 says
      "commit, push" the artefacts, but the remote is public and the instrument
      is withheld. Item 11/15 must either redact wording (keys + sha256 of the
      text, verifiable by anyone holding the dictionary) before committing, or
      move artefacts out of band with only their checksums committed. Decision
      is the operator's; the loop will default to redaction at item 11 and say so.

## items
- [x] 1  check.sh v1
- [x] 2  RetrievalRecord dataclass (pipeline/retrieval_record.py)
- [x] 3  retrieval adapter (pipeline/retrieve.py; --reproduce = 0.643)
- [x] 4  adapter step in check.sh (step 6)
- [x] 5  unmeasured_stratum flag (pipeline/strata.py, Hit.unmeasured_stratum)
- [x] 6  pipeline/canary.py C1–C3 (check.sh step 7)
- [x] 7  user intake (pipeline/intake.py; canaries run through it)
- [x] 8  auto intake (pipeline/auto_intake.py; check.sh step 8)
- [x] 9  estimability gate + --allow-unestimable (pipeline/gate.py; check.sh step 9)
- [x] 10 specifier takes RetrievalRecord (PairLike; pipeline/resolved_pair.py)
- [x] 11 specifier emits the record (pipeline/artefact.py; redact() is the committable form)
- [x] 12 ledger append (pipeline/ledger.py; verify() is the denominator check)
- [x] 13 output artefact schema (pipeline/causal_structure.py, pipeline/hypothesis.py)
- [x] 13a critique seam + GenerationEnv (pipeline/hypothesis.py, pipeline/generation_env.py)
- [x] 14 DAG validators (pipeline/validators.py)
- [ ] 15 baseline score, once, on a tag — split 2026-09-04 after items 1-14, one commit each:
  - [x] 15a pipeline/run.py: frame under D1=narrow -> gate --allow-unestimable -> auto_intake -> ResolvedPair -> specify (PairLike) -> validators -> HypothesisRecord (redacted) -> ledger; artefacts under artefacts/<run_id>/ (a NEW tracked dir: out/, run/, runs/, parked/ are gitignored); end-to-end test on ScriptedBackend, no model
  - [x] 15b benchmark/baseline_score.py: takes artefact paths only, refuses any artefact whose GenerationEnv is missing or not clean_for_scoring, match rule = hypothesis outcome construct in the paper's outcome_keys_on_record(pmid) AND exposure construct resolved from the paper's exposure_terms through the deployed retriever (EXPOSURE_KEYS in scorability.py is empty by design; the exposure side has terms only); reports match rate N/M, ledger denominator, GenerationEnv, strata, plus contamination_check / input_leakage / unearned_assertions verdicts; key modules imported lazily so its unit tests run here on an injected key table
  - [x] 15c phase 1 live run in compass-gen: frame = medication + reproductive_hormonal exposures x chronic_condition outcomes through the funnel (D1 narrow); time ONE pair at k=5 on claude-haiku-4-5 first, then M = min(live frame, what fits ~6 h wall clock) as a seeded (seed 0) deterministic subset, M recorded in the ledger; commit + push artefacts, stamp GenerationEnv after the push, tag baseline-<dictionary hash>-<run_id> · MEASURED 2026-09-04 (`python -m pipeline.run measure --frame-only`): enumerated 18540, live 16138 (seed 0) — far above ~6 h at any plausible per-pair time, so M is a seeded subset, never the frame · TIMED 2026-09-04: one pair (m2:Q9.105 -> m2:Q5.19, seed 0) at k=5 on claude-haiku-4-5 took 41 min wall clock 11:33:20-12:14:16 (5 sequential samples of 25-33 tool calls each + a transduction call each); ~6 h / 41 min = 8.8, so M = 8 (~5.5 h, headroom for variance); the timing record was DISCARDED by validator:temporality (three blocking critiques: two asserted mediators and one descendant_of_exposure under a cross-sectional design), so the baseline's emitted count may be small — that is the pipeline's answer, not a defect to fix here; timing run moved out of the tree (scratchpad), never committed · LAUNCHED 2026-09-04 12:16: `python -u -m pipeline.run b1-20260904 --limit 8 --seed 0 --k 5 --allow-unestimable`, artefacts/b1-20260904/, log in the session scratchpad; on completion: commit + push artefacts, stamp, commit + push, tag baseline-3dc8415eccfe-b1-20260904 · OPERATOR NOTE: sample-level concurrency (one backend per sample, unique log suffix) would cut per-pair time ~5x but touches agent/specifier.py + agent/cli_backend.py (Lane A, user amendment); asked 2026-09-04, APPROVED by the operator the same day and landed as amendment A1 (specify(workers), ClaudeCliBackend.fork, --workers default 5) · run b1-20260904 was STOPPED 5 min in and its partial artefacts deleted (never committed) so the baseline is generated by the tree it is stamped with · RE-TIMED 2026-09-04 with --workers 5: the same pair (m2:Q9.105 -> m2:Q5.19) took 7.5 min wall clock 12:28:58-12:36:31 (five samples at once; ~40 s of that is one-off model/frame loading) and this time its record was EMITTED (sample variation, not a code change: same validators); ~6 h / 7.5 min = 48, so M = 48; timing2 moved to the scratchpad, never committed · LAUNCHED 2026-09-04 12:38: `python -u -m pipeline.run b2-20260904 --limit 48 --seed 0 --k 5 --workers 5 --allow-unestimable`, artefacts/b2-20260904/, log b2-20260904.log in the session scratchpad, expected to finish ~18:40; on completion: commit + push artefacts, stamp, commit + push, tag baseline-3dc8415eccfe-b2-20260904 · b1-20260904 never existed as a run: stopped and deleted before any row (see A1) · b2-20260904 DIED 14:29 at pair 16/48: one sample's claude -p exited 1, empty stderr, the driver let it propagate (ATTEMPTS.md, 15c attempt 1); 15 rows (10 emitted, 5 discarded), no summary, moved to the scratchpad, never committed · attempt 2: driver retries a pair once then records backend_error and continues (landed, see PROGRESS) · RELAUNCHED 2026-09-04 ~14:55 as b3-20260904, same command with --limit 48, expected ~7 h at the observed 8.7 min/pair, log b3-20260904.log in the scratchpad; on completion: verify ledger, commit + push artefacts, stamp, commit + push, tag baseline-3dc8415eccfe-b3-20260904
  - [ ] 15d phase 2 in /home/mehta5/compass-score — INPUTS FIXED 2026-09-04: `git fetch origin ralph-loop` + `git fetch origin tag baseline-3dc8415eccfe-b3-20260904-stamped`, checkout that tag (d73676a); artefacts/b3-20260904/*.json minus summary.json (39 files, 28 of them the ledger's emitted set — the harness takes the emitted set only, so pass the ledger's emitted artefacts, not the 11 discarded ones); `python -m benchmark.baseline_score --sha 703a1779c8bad8c1e6a829a24bf2bdc15361f3c9 <paths>`; the unsuffixed tag baseline-3dc8415eccfe-b3-20260904 is a slip pointing at the unstamped parent (ATTEMPTS.md) and must not be used; BASELINE.md is a *.md file and .gitignore does not ignore it (full clone, wide refspec, scoring-key fetched at 215ee9e; prevalence_key.py 685 lines, leak_facts.py 412 lines present; content not read): checkout the tag, run the harness, commit the four numbers as artefacts/<run_id>/BASELINE.md on ralph-loop; never regenerate; halt on a contamination verdict
## PARKED
(item · three attempts · why)
## DEFERRED (operator, 2026-09-04: "we will do it later")
- D3 effort/thinking pin: the Specifier's `claude -p` runs haiku with thinking ON at the CLI's default effort, unpinned anywhere (probe 2026-09-04: a one-word call returned a thinking block, 35 of 42 output tokens; sealed settings.json pins nothing; ~/.claude/settings.json sets effortLevel only for opus/sonnet/fable). After 15d: (a) pass an explicit --effort in agent/cli_backend.py and stamp it into the run identity (Lane A, user amendment); (b) A/B on the same seeded ~10-pair subset at two levels: wall clock, samples surviving the gate, validator discards, harness match rate — indicative only at that n. Not to be touched during the baseline.
