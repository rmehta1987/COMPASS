# STATE
D1: narrow   (brief default; operator's 2026-09-04 answer was unreadable ("sdfsdfss") — override here if wrong)
D2: branch = ralph-loop   (cut from main at 265241d, pushed 2026-09-04)
build: 3dc8415eccfe
last green: dccfdbb   (VERIFIED 2026-09-04 by ./check.sh, GREEN)
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

## items
- [x] 1  check.sh v1
- [x] 2  RetrievalRecord dataclass (pipeline/retrieval_record.py)
- [ ] 3  retrieval adapter
- [ ] 4  adapter step in check.sh
- [ ] 5  unmeasured_stratum flag
- [ ] 6  pipeline/canary.py C1–C3
- [ ] 7  user intake
- [ ] 8  auto intake
- [ ] 9  estimability gate + --allow-unestimable
- [ ] 10 specifier takes RetrievalRecord
- [ ] 11 specifier emits the record
- [ ] 12 ledger append
- [ ] 13 output artefact schema
- [ ] 13a critique seam + GenerationEnv
- [ ] 14 DAG validators
- [ ] 15 baseline score, once, on a tag (phase 2 in compass-score; scoring-key is on the remote at 215ee9e)
## PARKED
(item · three attempts · why)
