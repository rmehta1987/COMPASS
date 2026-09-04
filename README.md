# scoring-key

This branch holds the held-out answer keys drawn from the sixteen published
papers — `benchmark/prevalence_key.py` (41 outcome-prevalence rows) and
`benchmark/leak_facts.py` (15 seal-probe facts, including sixteen papers'
realised analytic n) — kept off the working branch so that they are unreachable
while hypotheses are generated and reachable only when committed artefacts are
scored.

**Merging this branch into the working branch invalidates every subsequent
baseline score**, because the generation phase would then have had the answer key
on its own branch; it is an orphan branch with no shared history precisely so
that `git merge scoring-key` conflicts loudly instead of fast-forwarding quietly.

## Notes

- Restore for scoring by checking these files into a tree that already has the
  scorers; do not merge. `leak_facts.py` imports `benchmark.cohort_papers`, which
  stays on the working branch, so this branch is deliberately not self-importable.
- Provenance of the prevalence figures: paper-derived, so they do not move with
  the dictionary build. But every row carries `instrument_region` and 18 rows
  carry `instrument_key`; all 18 resolved against build `3dc8415eccfe` when this
  branch was cut (2026-09-04). A build that renumbers keys can strand those two
  fields even though the figures survive.
- `key_present` and `key_fetchable` are separate: `git fetch` puts these blobs in
  `.git` and `git show scoring-key:benchmark/prevalence_key.py` then reads them
  without a checkout. Do not fetch this branch into a generation tree.
