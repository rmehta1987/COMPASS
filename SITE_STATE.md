# SITE STATE
tier: A                (decided — real runs, pseudonymised targets)
branch: site           (never compass-gen; Pages enabled at item 14 only)
clone: /home/mehta5/compass-site  (--single-branch main from GitHub, cut at 265241d;
       deploy/model/ copied from the operator's clone, sha-verified by retriever.py at load;
       deploy/targets.json and the dictionary are read from the operator's clone by path,
       never copied here — see site/tools/*.py for the env vars)
last green: 17eef4c   (VERIFIED 2026-09-04 by ./site-check.sh on that sha, GREEN)
check: ./site-check.sh
note: main's .gitignore excludes *.json — site/artefacts is un-ignored (item 1)
      and step 6 asserts every loaded artefact is tracked.
note: the brief's figure table needed two corrections before item 4 (see SITE_PROGRESS.md):
      R@1 0.567 / 0.643 are query-template arms S and I of ONE model on ONE machine
      (out/smoke_report_x86_64_Wright.json, run 2026-09-03), not two architectures;
      the n42 false accept is committed only as a bare score (0.731576, no key, no margin)
      in that report's threshold.I.knife_edge_negatives_within_0.003 — item 4 re-runs it.
      AUROC 0.719 traces only to a withdrawn artefact (QUERY_EXPANSION.md) and is dropped.
note: compass-gen/STATE.md (7ef75fa) marks pipeline items 11 and 13 landed as CODE; no
      run has produced the new artefact yet (see BLOCKED). Re-checked 2026-09-04.

## items
- [x] 1  strip fabricated figures; un-ignore site/artefacts; panels PLACEHOLDER
- [x] 2  site-check.sh (six steps; site/tools/plant.py proves each red, 13 plantings)
- [x] 3  all data in site/artefacts/*.json; page fetches, never inlines
- [x] 4  real retriever runs → site/artefacts/runs.json (run site-20260904T213836Z; map in run/site/, ignored)
- [x] 5  Retriever panel (runs.json + absence.json; tool log, record, candidates, limitation)
- [x] 6  Intake panel (fields, rendered query, covered-instance drop; no tool calls)
- [x] 7  Funnel panel (funnel.json from pipeline.gate in the generation clone)
- [x] 10 Score panel (score.json: GenerationEnv stamp of the generation clone, gated)
- [x] 11 measurement section (measurements.json: five-encoder sweep parsed from arm_hybrid_e_D.md §2; shipped arms S/I, threshold and latency from the tracked smoke report)
- [x] 12 PNG export (SVG foreignObject → canvas → PNG; no library)
- [x] 13 download page source (live DOM + embedded artefacts; opens from file://)
- [ ] 14 deploy (Pages workflow; enabling Pages is the operator's action)

## BLOCKED
8  specifier panel — the pipeline loop's baseline run (its item 15). Its items 11 and 13
   landed as code (7ef75fa) but no run has emitted a SpecifierArtefact; the August runs
   under compass-gen/run/ are the older schema and carry wording and keys in free prose.
   When a redacted artefact exists: pseudonymise keys with the run map, copy in as JSON.
9  record panel — the same run; a HypothesisRecord is only produced by it.

## PARKED
(item · three attempts · why)
