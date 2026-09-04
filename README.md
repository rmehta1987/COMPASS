# COMPASS — code and documentation

**Two trees, one public repository, one rule.** The rule: the survey instrument
is never tracked here, in any form. This repository is public
(https://github.com/rmehta1987/COMPASS).

| tree | where | what |
|---|---|---|
| Pipeline mirror | `agent/` `env/` `generate/` `benchmark/` `mcp/` `tests/` `curated/` `docs/` `references/` `.claude/`, `build.py` `checks.py` `build_targets.py` `encode_and_score.py` `pyproject.toml`, `AGENTS.md` `CLAUDE.md` `DESIGN.md` `TASKS.md` `CHANGELOG.md` `COMPASS.md`, `arm_hybrid_e_D.md` | The specifier pipeline and its arm C16/D/E/hybrid measurement reports. Published from an orphan branch on 2026-09-03 ([b3d818d](https://github.com/rmehta1987/COMPASS/commit/b3d818d2f9cbf4aa93fd9d911a6f042acd2ce889)) so no codebook-bearing history is reachable from it. |
| Retrieval experiments | `src/`, `deploy/`, `RESULTS.md` `CHARACTERISATION.md` `FUSION.md` `QUERY_EXPANSION.md` `BRIEF_*.md` `PROVENANCE.md`, tracked artifacts `out/fusion_task{2,3,4}_*.json` `out/qx_preregistration.json` `out/qx_task4_corpus_size.json` `out/rewrites_*.json` `out/smoke_report_x86_64_Wright.json`, `fixtures/negative_expansion_fields.json` | The frozen and fine-tuned embedding retriever measured on the Spark (Arm, GB10), its CPU deployment bundle, and the acceptance test that proves the bundle on another machine. |

Merged 2026-09-03 ([2ede8f7](https://github.com/rmehta1987/COMPASS/commit/2ede8f741b21b9f4d8b8a4bf23e2a6435a7ccd2d)).
`CHANGELOG.md` has the entry; `PROVENANCE.md` maps every retrieval figure to its artifact,
checksum, command and commit. Where the two trees name the same thing differently:

- `build.py` is the pipeline's **dictionary** builder (raw codebooks to
  `build/dictionary.json`, version hash `3dc8415eccfe`). Every retrieval report's
  "dictionary build at `3dc8415eccfe` unchanged" refers to that hash.
- `build_targets.py` is arm E's target builder: 1,352 targets since the free-text fix of
  2026-09-02 (1,241 before it, the denominator of `docs/arm-e-results.md` and
  `docs/arm-e-configs.md`). The retrieval work's `src/compass_build.py` emits 1,353; the
  one extra is `m2:Q785~2`, a free-text companion row (`RESULTS.md` §1).
- Construct counts differ by fold rule: `checks.py` asserts 1,080 distinct constructs for
  the pipeline's grouping; `src/compass_build.py` folds to 1,066 (`RESULTS.md` §1). Same
  dictionary, two collapse rules; neither is wrong.
- `encode_and_score.py` is arm E's frozen-encoder driver. It has been edited since it
  produced `arm_e.medcpt_a.json` (`arm_hybrid_e_D.md` §7), so it is **not** byte-identical
  to that version; the retrieval work's `src/compass_score.py` supersedes it for everything
  in `RESULTS.md`.
- `arm_hybrid_e_D.md` §6 and `docs/arm-e-results.md` §8 argued fine-tuning was unpromising
  or unmeasurable; `RESULTS.md` §4 then measured it at +0.192 R@1. Both reports carry a
  dated note at that point rather than a silent edit.
- `COMPASS.md` is a specimen output card from an earlier dictionary build
  (`8573993d8450`), kept as an example and marked as such.

## The deployed retriever

`deploy/` is the fine-tuned `bge-small` retriever: argmax cosine over 1,353 precomputed
target vectors, CPU-only, no LLM call, plus the instances-only query template. Nine files,
137.2 MB; five are tracked here. `deploy/manifest.json` records every convention (query
prefix, CLS pooling, fp32, 4 threads, abstention threshold) and the sha256 of every shipped
file; `deploy/retriever.py` asserts them at load and raises rather than warns.
`deploy/smoke_test.py` proves a port: it exits 0 only if the 224-row fixture reproduces, to
the digit, R@1 0.567 without the template, 0.643 with the pre-registered template (arm F),
and 0.643 / R@10 0.938 with the instances-only template that ships (arm I), plus 43/44
negatives rejected in each arm. It passed on the Spark (aarch64; report on the training
machine) and on the x86 serving machine Wright
([`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json), commits
[da317d6](https://github.com/rmehta1987/COMPASS/commit/da317d602738ca6752d9f8264accdd4a2ffac64e),
[4b8abee](https://github.com/rmehta1987/COMPASS/commit/4b8abeebf7b12d6e2c870ec775b745b084195c95)).

Two files the bundle needs are not tracked and must be copied from the training
machine (step 0 of the smoke test says how): `deploy/model/` (133.5 MB, over
GitHub's file limit) and `deploy/targets.json` (the question wording).

Runtime dependencies are undeclared in `pyproject.toml` (it has no `[project]` table):
the retriever needs `torch`, `transformers` 5.x and `safetensors`; the pipeline's tests and
`benchmark/` need `pytest`, `mypy`, `ruff` and `pydantic`. Versions used are in
`PROVENANCE.md` §Machines.

## What is withheld, and why

| withheld | reason |
|---|---|
| `module_{1,2,3}_codebook_full.csv`, `raw/`, `dictionary.json` | The COMPASS survey instrument: 3,222 codebook lines of question wording, including direct-identifier items (name, phone, email, address). Not cleared for public release. |
| `build/` | The instrument in JSON form, generated by `build.py`. Hash `3dc8415eccfe`. |
| `benchmark/fixtures/`, `retrieval_queries.json`, `fixtures/negative_requests.json` | Fixtures storing gold item wording verbatim. (`fixtures/negative_expansion_fields.json` is tracked: hand-authored template fields, no instrument wording.) |
| `targets.json`, `deploy/targets.json`, `out/targets_*.json`, `arm_e*.json` | Selection targets and per-row results carrying stem and option wording. |
| `out/fusion_task1_overlap.json`, `out/qx_task2_paired.json`, `out/qx_task3_abstention.json` | Per-row retrieval artifacts that quote gold stems; withdrawn from git on 2026-09-03. Their figures are in `FUSION.md`, `QUERY_EXPANSION.md` and the tracked smoke report; checksums in `PROVENANCE.md`. **They remain in `main`'s history from e446cf8 until the operator rewrites it or makes the repository private.** |
| `run/`, `runs/`, `out/` otherwise | Run records, tool logs, checkpoints and score artifacts (`PROVENANCE.md` lists the cited ones with checksums). |
| `benchmark/prevalence_key.py` | The held-out answer key for outcome prevalence. |
| `tests/resolver_eval_v2.jsx` | A browser harness with ~508 candidate wordings frozen inline. |
| `references/astro_agents_reference.pdf`, `asttroagent.png` | Third-party paper and figure, not republished. |
| `deploy/model/` | 133.5 MB fine-tuned checkpoint, over GitHub's file limit; not wording. |

**Consequence:** a fresh clone cannot build the dictionary, cannot run the retrieval or
resolver evaluations, cannot import the three `benchmark/` modules that import the withheld
key (`scorability.py`, `input_leakage.py`, `contamination_check.py`), and cannot re-freeze
`deploy/`. Of the six commands in `AGENTS.md` §Verify current state only `ruff check .`
runs here. A clone can run the deployed retriever and its acceptance test once the two
files above are copied.

**Residual, measured on this tree** by `python src/wording_scan.py` on 2026-09-03
(distinct eight-word runs from any `dictionary.json` string found in a tracked text file):
**169 runs across 20 of 128 files**.
The largest are `build.py` (45); `CHARACTERISATION.md` (17); `agent/schema.py` (15); `out/qx_preregistration.json` (15). They are fragments in parsing rules, quoted example stems, option
labels used as template instances and pinned fixtures, not the instrument. Before the
2026-09-03 withdrawals the same scan found about 8,700, of which `deploy/targets.json`
alone was 8,388.

## Provenance

Every figure in `RESULTS.md`, `CHARACTERISATION.md`, `FUSION.md`, `QUERY_EXPANSION.md` and
`arm_hybrid_e_D.md` was measured against dictionary build `3dc8415eccfe`; `docs/arm-e-*.md`
figures are on that build's pre-fix 1,241-target subset and say so. `PROVENANCE.md` carries
the artifact, checksum, command and commit for each retrieval figure, and the latency table
that replaces the batched 2.94 ms/query figure. Commit shas quoted inside the pipeline
documents (`AGENTS.md`, `TASKS.md`, `CHANGELOG.md`) belong to the private pre-publication
history and do not resolve here; the public history starts at b3d818d.
