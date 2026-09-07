# TIER ATTEMPTS
Failures and the approach that produced them, so no approach is retried.
Three attempts on one item then PARKED, with all three named.

(no failed attempt yet)

## Resolved premises — recorded so they are not re-litigated

- BLOCKER 1 of the earlier TIER_STATE (for_harness.json unreachable) is
  RESOLVED, and not by fetching scoring-key. The operator published the two
  files as the orphan branch `handoff-public` (dcd80da), which shares no
  history with scoring-key, so the fetch brings no inventory blob,
  no case_map.json and no prevalence_key.py into .git. check.sh step 0 was
  re-run after the fetch: scoring-key unreachable, no key file in the tree.
- BLOCKER 2 of the earlier TIER_STATE (this branch has no three-state
  vocabulary, so items 2 and 5 would need inventory/schema.py hand-copied) is
  DISSOLVED by the current brief, not by copying anything. The tiered scorer
  reads inventory rows as JSON data, takes `status_values` and
  `modality_values` from handoff/for_harness.json at run time, and pins
  `schema_version` (item 4) so a schema change raises instead of being read
  under stale field names. No schema module is copied; benchmark/paper_inventory.py
  keeps its own two-state types for mode 2 and is not touched.
- BLOCKER 3 (the handoff carries no covariate rows, no per-pair triples) is
  UNCHANGED and still correct as a constraint: nothing here hardcodes the 96
  keyed covariate rows or the 95 triples. The modal set is computed at run
  time from the fake inventory's keyed covariate rows (10a) and the per-paper
  direction weighting is exercised on the fakes (11a).
