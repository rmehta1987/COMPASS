# COMPASS — code and documentation

A partial mirror: **source and documentation only**. The study instrument and the
run records are deliberately absent, so this tree does not run end to end.

## What is here

`agent/` `env/` `benchmark/` `generate/` `mcp/` `tests/` `curated/`,
`build.py` `checks.py` `build_targets.py` `encode_and_score.py`, the design and
operating documents (`AGENTS.md`, `DESIGN.md`, `TASKS.md`, `CHANGELOG.md`,
`COMPASS.md`), and the measurement reports under `docs/` and
`arm_hybrid_e_D.md`.

## What is withheld, and why

| withheld | reason |
|---|---|
| `module_{1,2,3}_codebook_full.csv`, `raw/` | The COMPASS survey instrument — 3,222 codebook lines of question wording, including direct-identifier items (name, phone, email, address). Not cleared for public release. |
| `build/` | Generated from `raw/` by `build.py`; it is the instrument in JSON form. Gitignored upstream. Build hash `3dc8415eccfe`. |
| `benchmark/fixtures/` | The retrieval and resolver fixtures store gold item wording verbatim. |
| `targets.json`, `arm_e*.json` | Arm E's selection targets and per-row results carry `question_text` and option wording. |
| `run/` | 69 live run records and 33 tool logs from headless model runs. |
| `benchmark/prevalence_key.py` | The held-out answer key for outcome prevalence. Its figures come from published papers, but keeping the key out of a public repo is the point of the control. |
| `tests/resolver_eval_v2.jsx` | A browser harness with ~508 candidate wordings frozen inline. |

**Consequence:** a fresh clone cannot build the dictionary, cannot run the
retrieval or resolver evaluations, and cannot import
`benchmark/contamination_check.py`, `scorability.py`, `tier_gate.py`,
`unearned_assertions.py` or `input_leakage.py`, which import the withheld key.
The reports under `docs/` and `arm_hybrid_e_D.md` carry the measured numbers.

**Residual:** 42 eight-word runs of instrument wording survive inside source
docstrings, examples and pinned test fixtures across nine files. They are
fragments of generic demographic and screening items, not the instrument.

## Provenance

Every reported figure was measured against build `3dc8415eccfe`.
`arm_hybrid_e_D.md` carries the reproduce commands, the model revisions and the
known bias that bounds every number in it.
