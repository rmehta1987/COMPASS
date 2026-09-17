# REPRODUCIBILITY — what a clone of this repository can re-run, and what it cannot

Scope: the **static site** under `site/` and the artifacts it loads. For the retrieval
tree's headline figures, their checksums and the commits that recorded them, read
[`PROVENANCE.md`](PROVENANCE.md) — this file does not repeat it. For what is withheld and
why, `README.md` §What is withheld.

**The page prints no run stamps.** That is deliberate, and this file is the reason: a
reader who wants to know where a figure came from is asked to come here rather than have
a dictionary hash and a tree sha printed under every panel. Each artifact still carries
its own provenance block; nothing below is retyped from the page.

## The short answer

| you are in | you can run | you cannot |
|---|---|---|
| a public clone | `ruff check .`, the six site checks except `no_instrument`, `python deploy/smoke_test.py` (per `README.md`) | rebuild any artifact under `site/artifacts/`; `pytest`, `mypy` and `pydantic` are undeclared |
| the training machine | every check, and the builders marked **training** below | rebuild `funnel.json`, `score.json`, `absence.json` (see the gap at the bottom) |

`no_instrument` needs the built dictionary and exits 2 without it rather than passing
vacuously, which is the intended behaviour, not a failure.

## Every artifact the page loads

`site/artifacts/index.json` lists them; this table adds who writes each one and from
what. "withheld" means the input is excluded by `.gitignore` or is not in the public
tree, so the artifact cannot be regenerated there at all.

| artifact | written by | reads | runs where |
|---|---|---|---|
| `index.json` | nobody — maintained by hand | — | anywhere |
| `stages.json` | nobody — maintained by hand | — | anywhere |
| `runs.json` | [`site/tools/run_examples.py`](site/tools/run_examples.py) | `deploy/` (tracked), the built dictionary and `src/char_strata.py`; writes the private half to `run/site/` | **training** |
| `measurements.json` | [`site/tools/build_measurements.py`](site/tools/build_measurements.py) | `arm_hybrid_e_D.md` §2, [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json) and `deploy/manifest.json` — all tracked — plus `out/char_task4_strata.json`, **withheld** | **training** |
| `metrics.json` | [`site/tools/build_metrics.py`](site/tools/build_metrics.py) | the scoring clone's own run directory, a **separate clone** that is not part of this repository | scoring clone only |
| `roc.json` | [`site/tools/build_roc.py`](site/tools/build_roc.py) | `out/char_pos_bge-small_ft.json`, `out/char_neg_bge-small_ft.json`, `out/char_task2_negatives.json`, `out/char_task3_calibration.json` — all **withheld** — plus `deploy/manifest.json` | **training** |
| `funnel.json` | [`site/tools/build_state_artifacts.py`](site/tools/build_state_artifacts.py) | `run/site/pipeline_state.json`, `run/site/negatives_absence_check.json` | **nowhere, today** |
| `score.json` | same | same | **nowhere, today** |
| `absence.json` | same | same | **nowhere, today** |

## The Metrics tab, figure by figure

Everything on that panel comes from three artifacts. Its two retrieval figures are the
ones a reviewer is most likely to quote, so they get named sources rather than a blanket
statement.

| what the page shows | artifact | how it was obtained |
|---|---|---|
| top-1 accuracy, both AUROCs, both curves, the operating point, the score spread | `roc.json` | computed by `build_roc.py` from the per-row characterisation of the shipped fine-tuned encoder. Each area is **asserted against the figure already published for the same pair** in `out/char_task2_negatives.json` and `out/char_task3_calibration.json`, and every figure in `scores` is re-derived from the rows and asserted against the same summary, so a disagreement fails the build rather than shipping a quieter second number |
| the fixture's shape — entries, phrasings, folded families | `roc.json::fixture` | derived from the rows, with uniformity asserted: the build stops if the entries do not all carry the same number of phrasings |
| the encoder sweep, the arms table, the threshold row, the by-topic bars | `measurements.json` | parsed, never retyped, from `arm_hybrid_e_D.md` §2 and the tracked smoke report; the by-topic rows come from the withheld `out/char_task4_strata.json` and are cross-checked against the three topics `deploy/manifest.json::known_limitations` names |
| the ceiling, the cohort bibliography, the scored run's counts | `metrics.json` | transcribed by `build_metrics.py` from the scoring clone's own `BASELINE.md`, `summary.json` and ledger |

### What re-runs here, and what only repeats

Two figures on that panel were **re-executed** on 2026-09-16 by
`python deploy/smoke_test.py`: arm S's `R@1 0.567` and `auroc 0.9823`, together with
`43 of 44` negatives rejected, and the fresh rank vector agreed with
`out/char_pos_bge-small_ft.json` row for row, which is what re-derives `127 of 224`.

The score spread in "why one score does those two jobs so differently" is **repeated, not
re-run**: those six values come from characterisation runs dated 2026-09-02/03. They are
now cross-checked against the rows at build time, which catches a stale or mismatched
input, but the underlying run has not been repeated.

The threshold row's figures are **machine-dependent at the fourth decimal**. The tracked
x86 report and this aarch64 machine disagree on whether the shipped `min_cos` is the
F1-maximising value, because the shipped value sits on a knife-edge row at the
nine-decimal boundary; `PROVENANCE.md` records both readings under "threshold knife
edge". The page names no machine for that row. That is an open question, not a settled
convention.

## Declared gap: three artifacts nothing can rebuild

`funnel.json`, `score.json` and `absence.json` are written by `build_state_artifacts.py`
from `run/site/pipeline_state.json` and `run/site/negatives_absence_check.json`. Neither
input is present on the training machine any more — `run/site/` holds only a dated
capture directory with the private run halves — and `run/` is gitignored, so they are in
no clone either. **Those three artifacts are currently reproducible nowhere.** They are
the committed record and there is nothing to check them against.

This is declared rather than closed. Anyone regenerating them has to re-capture the
pipeline state first.

A consequence, recorded here because it explains a hand edit: `score.json`'s
`scored_run_note` used to tell the reader that the scored run's tree and run id were on
the Metrics tab. They were printed there until the panel was rewritten, and the page now
prints no run stamps by design. The sentence was corrected in `build_state_artifacts.py`
and, because that builder cannot run, in the artifact directly.

## Checking this file

`tests/test_reproducibility_doc.py` requires every artifact in
`site/artifacts/index.json` and every `site/tools/build_*.py` to be named here, so a new
artifact or a new builder cannot appear without a row. It cannot check that a row is
*true* — that is on whoever changes a builder.
