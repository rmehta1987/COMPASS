# TIER PROGRESS
One line per landed item, newest last. A line here means the gate was green
at that commit, not that the component was measured: every phase-1 acceptance
is against the fakes.

- prereq · 6779b78 · the two operator inputs landed from the orphan branch
  handoff-public (dcd80da): posed_pairs.json 95 rows x {case_id, exposure,
  outcome}, handoff/for_harness.json. scoring-key stays unreachable here.
- item 1 · 4a6986d · check.sh step 11 runs benchmark/tiered_score.py
  --self-check; MATRIX declares the 6 x 4 report with 19 scoreable cells.
  Seeded red twice (broken import; dropped row) before landing. 903 -> 908 tests.
- item 4 · 0ccc446 · load_handoff pins dictionary_version_hash (against
  build/version.json, not a restated constant), schema_version and tier_rule;
  HandoffMismatch raises. check.sh step 11 loads it. An AST test forbids any
  assertion against the real tier_counts in this clone. 915 -> 924 tests.
- item 5 · 39ded44 · side_state/tier_of/tiers_of implement confident_anchor;
  the both-modality shape raises UnclassifiablePaper rather than being binned.
  Correct on all five fakes; the bare-status reading moves exactly fE.
  924 -> 929 tests.
