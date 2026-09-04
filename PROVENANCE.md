# PROVENANCE — where every headline number comes from

The repository is public and the survey instrument is withheld (`README.md`), so most
score artifacts under `out/`, every checkpoint under `runs/`, and every fixture live only
on the training machine (`spark-2500`, DGX Spark GB10, aarch64). This file is the bridge:
for each headline figure, the artifact that produced it, that artifact's sha256 as
measured on 2026-09-03, the command that regenerates it, the tracked file (if any) that
reproduces the figure inside the public tree, and the commit that recorded it.

Rule for reading the reports: a path in a **link** is tracked here and resolves; a path
in plain `backticks` is on the training machine and is listed below.

## Machines

| name | role | hardware | software |
|---|---|---|---|
| `spark-2500` | trains, freezes, re-encodes | DGX Spark GB10, 20-core Arm CPU, SM12.1 GPU | Python 3.12.3, torch 2.14.0+cu130, transformers 5.16.1, safetensors 0.8.0 |
| `Wright` | serves (`deploy/manifest.json::device.serves`) | x86_64, 14 cores, WSL2 | Python 3.12.3, torch 2.14.0+cpu, transformers 5.16.1 |

## The shipped retriever

| figure | value | artifact (training machine) | sha256 (first 16) | tracked counterpart | commit |
|---|---|---|---|---|---|
| fine-tuned checkpoint | `runs/bge-small_nn0_t0.10/model.safetensors`, 133,462,128 bytes | same | `c111521c05cc65ca` | [`deploy/manifest.json`](deploy/manifest.json) `files["model/model.safetensors"]`; re-hashed on both machines, [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json) `integrity` | [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) |
| training run | 13,528 pairs, 3 epochs, bs 64, lr 2e-5, t 0.10, seed 20260903, 109 s on GPU | `runs/bge-small_nn0_t0.10/compass_train_meta.json` | — | `deploy/manifest.json::encoder` | — |
| R@1 / R@5 / R@10, no template | 0.567 / 0.862 / 0.920, rank p50 1, p90 9, max 82 | `out/ft_bge-small_nn0_t0.10.json` (`python src/compass_score.py --model bge-small --weights runs/bge-small_nn0_t0.10 ...`) | `7c469036f443d156` | [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json) `acceptance.S`; asserted by [`deploy/smoke_test.py`](deploy/smoke_test.py) | [da317d6](https://github.com/rmehta1987/COMPASS/commit/da317d602738ca6752d9f8264accdd4a2ffac64e) |
| R@1 / R@5 / R@10, arm F (population + instances) | 0.6429 / 0.8884 / 0.942, p90 6, max 61 | `out/qx_task2_paired.json` (`python src/qx_paired.py`) | `913736170edb6e83` | smoke report `acceptance.F` | [8f1d9fb](https://github.com/rmehta1987/COMPASS/commit/8f1d9fbb45c8356c9cf2de989596cd4a568f1c34) |
| R@1 / R@5 / R@10, arm I (instances only, **shipped**) | 0.6429 / 0.8884 / 0.9375, p90 7, max 61 | measured only by the smoke test (post-hoc revision of arm F) | — | smoke report `acceptance.I`; `deploy/manifest.json::template.r_at1_224_rows` | [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) |
| abstention threshold | `min_cos` 0.729476; 43/44 negatives rejected in every arm; AUROC 0.9823 (S) / 0.9867 (F) / 0.9874 (I) | `out/char_task3_calibration.json` (`python src/char_report.py`), `out/qx_task3_abstention.json` (`python src/qx_abstain.py`) | `5cfd9438c2e1dcb7`, `221dbc4946fd2f67` | smoke report `acceptance.*.negatives_rejected`, `auroc`, `threshold.*` | [3304990](https://github.com/rmehta1987/COMPASS/commit/33049904b54785110ec362231327f8fbb4eae2bb) |
| threshold knife edge | 0.729476 is the rounded score of fixture row 68 (incorrect); tau* = 0.731902 under single-query encoding on the Spark, 0.729476 on Wright | `out/smoke_report_aarch64_spark-2500.json` (Spark, untracked: `1f516889c1fd3ff4`) | — | smoke report `threshold.S.knife_edge_*`; `deploy/manifest.json::abstention.knife_edge` | [4b8abee](https://github.com/rmehta1987/COMPASS/commit/4b8abeebf7b12d6e2c870ec775b745b084195c95) |
| GPU/CPU parity | 1 of 224 top-1 disagreements (row 107), max vector delta 4.06e-7 | `out/final_bge-small_ft.json` (`python src/finalize.py`) | `fd9e0a3defb783f6` | `deploy/manifest.json::device.why` | — |
| Arm vs x86 vector delta | max 2.94e-7, top-1 agreement 224/224 | — | — | smoke report `reencode` | [da317d6](https://github.com/rmehta1987/COMPASS/commit/da317d602738ca6752d9f8264accdd4a2ffac64e) |
| target vectors | 1,353 x 384 fp32, bit-identical across re-freezes on the Spark | [`deploy/target_vectors.safetensors`](deploy/target_vectors.safetensors) | `941dd61a8ea17f2d` | tracked | [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) |
| target set | 1,353 targets, 1,066 constructs, hash `3dc8415eccfe` | `out/targets_full.json` = `deploy/targets.json` (`python src/compass_build.py --dictionary dictionary.json --out out/targets_full.json`) | `22b0c37a90696f4e` | `deploy/manifest.json::corpus`; wording, so not tracked | — |

## Latency, and the one figure to stop quoting

| figure | value | regime | machine, threads | source |
|---|---|---|---|---|
| **2.94 ms/row** | batched: 224 queries encoded together, wall clock divided by rows | **not per-call latency** | `spark-2500`, default threads | `out/ft_bge-small_nn0_t0.10.json::query_ms_per_row` |
| 18.3 ms | isolated, one query per forward pass | per-call | `spark-2500`, default 20 threads | `out/final_bge-small_ft.json`, `RESULTS.md` §7 |
| 43.6 to 44.3 ms | isolated | per-call | `spark-2500`, pinned 4 threads | `deploy/manifest.json::device.query_ms_isolated_single_at_pinned_threads` |
| 12.88 / 13.30 / 13.41 / 14.24 / 23.76 ms, median 13.41 | isolated, five runs | per-call | `Wright`, pinned 4 threads | `deploy/manifest.json::device.serving_reference` |
| corpus encode | 18.2 to 21.2 s Spark; 53.7 to 59.6 s Wright | 1,353 targets, batch 64 | as above | manifest `measured`, smoke reports `reencode.wall_s` |

Every document that once quoted 2.94 ms as per-query latency has been corrected to cite
this table.

## Frozen baselines (RESULTS.md section 3)

| artifact | sha256 (first 16) | dtype provenance |
|---|---|---|
| `out/frozen_bge-small.json` (R@1 0.375) | `0a6282f0b262cb91` | fp32 by repo declaration, `out/frozen_sweep.log` |
| `out/frozen_granite-s2.json` (0.312) | — | fp32 re-run `out/refp32.log`; bf16 first pass 0.263 in `out/round2.log` |
| others | — | `RESULTS.md` §3 dtype audit table |

## Fixtures

| file | rows | sha256 (first 16) | tracked? |
|---|---|---|---|
| `retrieval_queries.json` | 224 positives, gold keys | `8999c80317cdbf56` | no: gold wording |
| `fixtures/negative_requests.json` | 44 negatives | `cc84aceacb580319` | no |
| [`fixtures/negative_expansion_fields.json`](fixtures/negative_expansion_fields.json) | template fields for the 44 | — | yes |
| [`out/qx_preregistration.json`](out/qx_preregistration.json) | both sets with template renderings, frozen before scoring | — | yes: the smoke test's only fixture |

## Artifacts withdrawn from git on 2026-09-03

Withdrawn because they quote instrument wording per row; figures survive in the reports
and in the smoke report. Commit [2ede8f7](https://github.com/rmehta1987/COMPASS/commit/2ede8f741b21b9f4d8b8a4bf23e2a6435a7ccd2d).

| file | sha256 (first 16) | bytes | figures live in |
|---|---|---|---|
| `deploy/targets.json` | `22b0c37a90696f4e` | 940,840 | `deploy/manifest.json::corpus`, `files["targets.json"]` |
| `out/fusion_task1_overlap.json` | `0808bb02944a39f6` | 259,092 | `FUSION.md` §1 |
| `out/qx_task2_paired.json` | `913736170edb6e83` | 138,119 | `QUERY_EXPANSION.md` §2, smoke report `acceptance.F` |
| `out/qx_task3_abstention.json` | `221dbc4946fd2f67` | 49,339 | `QUERY_EXPANSION.md` §3, smoke report `threshold` |

These files remain reachable in the repository's history from e446cf8 onward until the
operator rewrites it or makes the repository private.

## Commits

| commit | what |
|---|---|
| [3304990](https://github.com/rmehta1987/COMPASS/commit/33049904b54785110ec362231327f8fbb4eae2bb) | phrasing ensemble measured, not shipped (FUSION.md) |
| [8f1d9fb](https://github.com/rmehta1987/COMPASS/commit/8f1d9fbb45c8356c9cf2de989596cd4a568f1c34) | query-expansion template passes its pre-registered rule (QUERY_EXPANSION.md) |
| [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) | CPU port: template shipped, smoke test, threads pinned, dtype audit |
| [da317d6](https://github.com/rmehta1987/COMPASS/commit/da317d602738ca6752d9f8264accdd4a2ffac64e) | x86 acceptance run on Wright |
| [4b8abee](https://github.com/rmehta1987/COMPASS/commit/4b8abeebf7b12d6e2c870ec775b745b084195c95) | knife-edge check accepts either candidate |
| [31a096d](https://github.com/rmehta1987/COMPASS/commit/31a096d046b44ff9badd2ea7b76f154e34b60280) | Wright named as serving machine, latency spread recorded |
| [6416094](https://github.com/rmehta1987/COMPASS/commit/64160949c3570e729805e99611af5243ad0e8115) | x86 report renamed to the code's default |
| [cbb165e](https://github.com/rmehta1987/COMPASS/commit/cbb165ebb003288c2bdf67cd70a832fffc7a599f) | freeze script keeps the serving keys |
| [b3d818d](https://github.com/rmehta1987/COMPASS/commit/b3d818d2f9cbf4aa93fd9d911a6f042acd2ce889) | pipeline mirror published from an orphan branch |
| [2ede8f7](https://github.com/rmehta1987/COMPASS/commit/2ede8f741b21b9f4d8b8a4bf23e2a6435a7ccd2d) | merge, reconciled |
