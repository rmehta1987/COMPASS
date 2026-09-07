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
- item 3 · 0808eef · pipeline/pose_terms.py poses TERMS; one run directory per
  opaque case id; read_cases raises on a leaked field; an abstaining anchor
  spends no model call. 929 -> 944 tests.
- item 6 · 955ee3e (+2c353a6 import sort) · anchor resolution at construct
  level; the fixture gained a member key so the key/construct seeding is not
  vacuous.
- item 7 · 40f15df · refusal on an unreachable anchor, split into refused at
  retrieval / by the specifier / approximated; only unreachable sides count.
- item 8 · 588cee5 · analogue resolution scored; the modality_mismatch half
  reports None and raises if switched on unwired. Attempt 1 reset on red.
- item 9 · 2def6e7 · covariate recall over recoverable rows with exclusions.
- item 10 · d56aaed · modal set computed at run time, margin reported; no
  variable-key literal may appear in the module.
- item 11 · e558660 · direction weighted per paper, with the per-pair rate,
  the concentration and the majority base rate beside it.
- item 12 · d64132d · tiers A and B render as case studies in counts; an empty
  tier reads UNMEASURED and prints no figure (14a).
- item 13 · f4e4d20 · tiers C and D render as rates with 95% Wilson intervals
  and n on every line; the margin and the per-paper direction rate are marked
  not-a-proportion and print their counts.
- item 14 · db959a2 · report assembly: provenance, the residual limitation,
  the targets, attrition, then the tiers. assemble() scores only emitted
  records. End-to-end test drives the real driver into the real scorer.
- item 15 prep · afccaf9 · the case index is written after every case and
  --skip-recorded reuses a completed one (b2/b4 outage history).
- item 16 · ad0faa8 · attrition by cause, unresolved anchors split by side,
  near misses against a stated band, denominator printed.
- DRY RUN 2026-09-06 (tiered-dry-20260906, no model call): 95 cases, 67 of 190
  sides resolve, 10 cases resolve on BOTH sides. Not a defect: most posed
  exposures (PM2.5 and similar) are linked spatial measures the instrument
  does not hold, which is what tiers C and D are made of.
- item 15 · 11c03f4 · LIVE RUN tiered-20260906, claude-haiku-4-5, k=5,
  workers=5, --allow-unestimable, 2026-09-06 22:11-01:5x: 95 cases posed,
  9 emitted, 1 refused (c075), 85 unresolved_anchor (both sides 38, exposure
  only 37, outcome only 10; 18 abstaining sides within 0.05 of the threshold).
  No case was discarded by a validator. attrition.json written.
- item 15 stamp · 9e862b4 · stamped at 11c03f4 after the push, tree_clean
  true, key_present false; tagged posed-3dc8415eccfe-tiered-20260906. The
  first stamp read tree_clean=False (untracked b4/b5/dry run directories) and
  was discarded, not accepted.
- post-run · ed49ff3 · the case-id test was seeded against the real artefacts
  and failed twice over: fragile to a sha256 hex collision, and blind to a
  case id reaching the prompt through a stem. Both closed.
