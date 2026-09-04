# SITE PROGRESS

## 2026-09-04 — item 1
- Wrote site/index.html from the mockup with every figure removed. Two numeric tokens
  remain outside CSS: `initial-scale=1` (viewport) and `i+1` (rail index). Neither is
  a measurement. Verified with a regex over the file with `<style>` stripped.
- `.gitignore`: `!site/artefacts/*.json` after the `!curated/**/*.json` line;
  `git check-ignore site/artefacts/x.json` now returns nothing.
- Every panel renders a PLACEHOLDER block with one line saying what it will show.
- Dropped from the mockup, never to return without an artefact: the resolved example
  (key, cosines, roster fold), the household-size example, the PM2.5 cosine, the n42
  key and margin, the footer figures (parameter count, latency, AUROCs, fixture size),
  the dictionary hash, the nav links to nowhere.

## 2026-09-04 — item 2
- `./site-check.sh` runs six stdlib checks under `site/tools/`; `plant.py` copies the site,
  plants one violation per check (13 in all: page literal, artefact without provenance,
  figure retyped in a string, five instrument words, a variable key, dead anchor, missing
  fetch target, stray close tag, script syntax error, external script, font @import, fetch
  to a host, untracked artefact) and requires a non-zero exit from each. Ran: all 13 red.
- First real catch, before any planting: the tools' own docstrings carried an example
  variable key and step 2 refused them. The example is now built at run time.
- Step 2 exits 2 without the dictionary; it never passes vacuously. The dictionary is read
  by path from the operator's clone (COMPASS_DICTIONARY), never copied into this clone.
- Data contract fixed here so items 3–11 agree: the page loads `artefacts/index.json`,
  which lists every other artefact under `files`; every artefact carries a `provenance`
  object with `source` and one of `run_id` / `commit` / `frozen`; figures are JSON
  numbers, never digits inside prose strings (request text excepted).

### Figure trace (done before item 1; primaries opened, not summaries)
| figure | primary | run id | verdict |
|---|---|---|---|
| R@1 0.567 (arm S, no template) / 0.643 (arm I, shipped template) | out/smoke_report_x86_64_Wright.json acceptance.S/.I; mirrored in deploy/manifest.json | Wright 2026-09-03 | real; ONE model, ONE machine, two query arms |
| AUROC 0.9874 (absent-construct detection, arm I), 43/44 negatives rejected | same report acceptance.I | Wright 2026-09-03 | real |
| AUROC 0.719 (detecting own wrong pick) | QUERY_EXPANSION.md only; out/qx_task3_abstention.json withdrawn | none | dropped |
| 1,353 targets; dict 3dc8415eccfe; 33M params | deploy/manifest.json corpus/encoder | frozen 2026-09-04 | real |
| min_cos 0.729476 (display 0.7295), positives-only grid | manifest abstention; smoke report threshold.I | Wright 2026-09-03 | real |
| 13.06 ms per query | smoke report latency (Wright, 4 threads) | Wright 2026-09-03 | real; machine-specific |
| n42 false accept at 0.731576 | smoke report threshold.I.knife_edge_negatives_within_0.003 | Wright 2026-09-03 | score only; key/margin come from item 4's rerun |
| "margin 0.0021" | not a field: 0.731576 − 0.729476 | — | recomputed as gap above threshold |
| PM2.5 abstention; five domains absent | out/char_neg_bge-small_ft.json (untracked), src/verify_negatives.py (tracked) | — | rerun at item 4 |
| five-architecture table | arm_hybrid_e_D.md §2 (tracked); arm_e2.*.json withheld and not on this machine | measured 2026-09-02/03 | traced to the document; item 11 says so |
| 13,528 training pairs | PROVENANCE.md → runs/…/compass_train_meta.json (withheld) | — | doc-only; not shown unless the manifest carries it |
