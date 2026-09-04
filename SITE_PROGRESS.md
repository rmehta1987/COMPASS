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

## 2026-09-04 — item 3
- stages.json + index.json; the script holds no data. First run of the check on the new
  page caught "step 1" in a JS comment — the digit rule reads comments too. Reworded.

## 2026-09-04 — item 4
- `site/tools/run_examples.py` ran `deploy/retriever.py` on four requests (spark-2500,
  aarch64, torch 2.14, 4 threads; run id in runs.json provenance). Public artefact
  `site/artefacts/runs.json`; private map and raw hits under `run/site/<run_id>/`.
- The n42 false accept reproduces: templated query scores 0.731576, gap above the
  shipped threshold +0.0021, top-two margin 0.0279, domain ses_employment, level
  individual. This is the first record of that case WITH its target (the smoke report
  holds the bare score). The key is on the private side only.
- The absent example scores 0.5986 with its instance appended and abstains; the resolved
  examples score 0.8835 (roster-folded target, fold 20) and 0.7413.
- The check refused the first artefact: the manifest's `how_chosen` prose carries fixture
  counts, and copying prose is retyping. Replaced with a figure-free summary and a
  pointer to the manifest key.
- Latency here is ~45 ms/query, consistent with the manifest's Spark figure at four
  pinned threads; the artefact says so and does not call it the serving figure.

## 2026-09-04 — item 5
- Retriever panel renders from runs.json: the search/select tool log with the run id,
  the record (pseudonym, domain, level, cosine, threshold and gap, abstention, margin,
  fold, option position, query time with machine, targets scored with dictionary hash),
  the ten candidates, and for the abstaining example the absence check (absence.json,
  re-run of src/verify_negatives.py: five domains, zero matches). The false-accept note
  is prose in requests.json with no figures; the figures beside it are the run's.
- The check refused the first version for the code's own small integers (`,1)` flags,
  `examples[0]`, `>=0`, `>1`). Removed rather than allowlisted: boolean flags,
  destructuring, and no fold comparison. The allowlist did not grow.
- The Run bar matches a typed request against the committed requests only; anything else
  renders NO COMMITTED RUN with the text verbatim. No score is ever synthesised.

## 2026-09-04 — item 6
- Intake panel: the RetrievalRequest fields, the rendered query, which instances the
  template dropped as already covered (the first example drops its instance, which is
  the covered rule at work), population unset by contract, and the template's sha from
  the run's bundle record. Tool calls: none, and the panel says so.

## 2026-09-04 — item 7
- funnel.json is built by `capture_pipeline_state.py`, which imports the generation
  clone's `pipeline` package read-only and calls `worked_frame()` and `gate()` exactly as
  `python -m pipeline.gate` does; only counts, marker names and export names cross into
  the public artefact (the raw capture under run/site/ carries stems and keys).
- Real output: enumerated 384, pruned 128, live 256, gate passed 0, blocked 256, every
  pair `blocked_no_metadata` on the two missing exports, `n_source` unknown.

## 2026-09-04 — item 10
- score.json: `pipeline.generation_env.stamp()` run against the generation clone:
  key_present false, key_fetchable false, branch ralph-loop, clean tree, sha recorded.
  Status gated; estimable denominator 0 (from the funnel capture); two reasons listed.

## 2026-09-04 — items 7 and 10, process slip
- Both commits were made while the console showed RED. Cause: the check ran before
  `git add`, so step 6 saw untracked artefacts, and `| tail -1` returned tail's exit
  code, not the check's. Re-ran unpiped on cf37207: GREEN. Rule from AGENTS.md
  ("never piped") applies to site-check.sh too; recorded in SITE_ATTEMPTS.md.

## 2026-09-04 — item 11
- `build_measurements.py` parses the five sweep rows out of arm_hybrid_e_D.md §2 by
  column, never retyping, and reads the shipped arms S and I, the threshold block and
  latency from out/smoke_report_x86_64_Wright.json (tracked, run 2026-09-03). The sweep's
  own JSONs are withheld; the artefact and the page both say the document is the record.
- The footer is rendered from data: parameter count, serving latency, gate counts,
  AUROC and negatives rejected. The wrong-pick AUROC is named as absent, not quoted.
- Placement: below the stage rail, as the brief asks.

## 2026-09-04 — item 12
- Save panel as PNG: the panel is cloned into an SVG foreignObject with the page's own
  stylesheet, serialised, loaded as a data: image and drawn to a canvas at the device
  pixel ratio. No library, no server, no external resource. `Download this record as
  JSON` (the current example plus every artefact's provenance) and the PNG button render
  on every panel; the headless harness exercises both handlers.
- The offline check flagged the two W3C namespace identifiers. They are names an SVG node
  carries, never fetched; offline.py now allows exactly those two strings and says why.
- A first attempt committed on a red check because a heredoc split the `&&` chain; reset
  to 8e3fd4d and redone. State files are now edited before the check, never after.
- Not verified in a real browser from this machine (no display): the harness proves the
  code path runs without exception, not that the raster is faithful. UNVERIFIED visually.

## 2026-09-04 — item 13
- Download this page: serialises the live DOM and embeds every loaded artefact as a JSON
  script that `load()` prefers over fetch. The mockup's version would have shown
  "Artefacts did not load" when opened from disk. The saved file is one HTML file.

## 2026-09-04 — items 8 and 9 (blocked, re-verified)
- Read `pipeline/artefact.py` (redact() replaces wording with sha256 digests, keeps keys)
  and listed `run/` in the generation clone: only August specifier runs in the old
  schema, whose `selection_rationale`, tool-log `log` strings and `quoted_wording` carry
  instrument wording and keys in prose. No SpecifierArtefact or HypothesisRecord has been
  emitted; that is the baseline run, pipeline item 15, still open. The two panels now say
  exactly that, with status `blocked · no run yet`, and show no invented output.

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
