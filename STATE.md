# STATE
D1: narrow   (brief default; operator's 2026-09-04 answer was unreadable ("sdfsdfss") — override here if wrong)
D2: branch = ralph-loop   (cut from main at 265241d, pushed 2026-09-04)
build: 3dc8415eccfe
last green: 9f23165   (VERIFIED 2026-09-04 by ./check.sh, GREEN)
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
- [ ] 10 specifier takes RetrievalRecord
- [ ] 11 specifier emits the record
- [ ] 12 ledger append
- [ ] 13 output artefact schema
- [ ] 13a critique seam + GenerationEnv
- [ ] 14 DAG validators
- [ ] 15 baseline score, once, on a tag (phase 2 in compass-score; scoring-key is on the remote at 215ee9e)
## PARKED
(item · three attempts · why)
