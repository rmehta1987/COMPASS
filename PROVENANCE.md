# PROVENANCE — where every headline number comes from

The repository is public and the survey instrument is withheld (`README.md`), so most
score artifacts under `out/`, every checkpoint under `runs/`, and every fixture live only
on the training machine (`spark-2500`, DGX Spark GB10, aarch64). This file is the bridge:
for each headline figure, the artifact that produced it, that artifact's sha256 as
measured on 2026-09-03, the command that regenerates it, the tracked file (if any) that
reproduces the figure inside the public tree, and the commit that recorded it.

Rule for reading the reports: a path in a **link** is tracked here and resolves. A path in
plain `backticks` may be tracked or may exist only on the training machine; the
training-machine ones that carry a headline figure are listed below with checksums, and
`git ls-files` is the authority on what is tracked.

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
| abstention threshold, arms S and F | `min_cos` 0.729476; 43/44 negatives rejected; AUROC 0.9823 (S) / 0.9867 (F) | `out/char_task3_calibration.json` (`python src/char_report.py`, arm S), `out/qx_task3_abstention.json` (`python src/qx_abstain.py`, arms S/P/F) | `5cfd9438c2e1dcb7`, `221dbc4946fd2f67` | smoke report `acceptance.S/F.negatives_rejected`, `auroc`, `threshold.S/F` | [3304990](https://github.com/rmehta1987/COMPASS/commit/33049904b54785110ec362231327f8fbb4eae2bb) |
| abstention, arm I (shipped) | 43/44 at the shipped `min_cos`; AUROC 0.9874 | measured only by the smoke test | — | smoke report `acceptance.I` | [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) |
| threshold knife edge | 0.729476 is the rounded score of fixture row 68 (incorrect); tau* = 0.731902 under single-query encoding on the Spark, 0.729476 on Wright | `out/smoke_report_aarch64_spark-2500.json` (Spark, untracked; regenerated 2026-09-04, sha `40eaec27b4e3d0ba`) | — | smoke report `threshold.S.knife_edge_*`; `deploy/manifest.json::abstention.knife_edge` | [4b8abee](https://github.com/rmehta1987/COMPASS/commit/4b8abeebf7b12d6e2c870ec775b745b084195c95) |
| GPU/CPU parity | 1 of 224 top-1 disagreements (row 107), max vector delta 4.06e-7 | `out/final_bge-small_ft.json` (`python src/finalize.py`) | `fd9e0a3defb783f6` | `deploy/manifest.json::device.why` | — |
| Arm vs x86 vector delta | max 2.94e-7, top-1 agreement 224/224 | — | — | smoke report `reencode` | [da317d6](https://github.com/rmehta1987/COMPASS/commit/da317d602738ca6752d9f8264accdd4a2ffac64e) |
| target vectors | 1,353 x 384 fp32, bit-identical across re-freezes on the Spark | [`deploy/target_vectors.safetensors`](deploy/target_vectors.safetensors) | `941dd61a8ea17f2d` | tracked | [e446cf8](https://github.com/rmehta1987/COMPASS/commit/e446cf83de0026bc40db17dd2eedabe02155ece7) |
| target set | 1,353 targets, 1,066 constructs, hash `3dc8415eccfe` | `out/targets_full.json` = `deploy/targets.json` (`python src/compass_build.py --dictionary dictionary.json --out out/targets_full.json`) | `22b0c37a90696f4e` | `deploy/manifest.json::corpus`; wording, so not tracked | — |

## Latency, and the one figure to stop quoting

| figure | value | regime | machine, threads | source |
|---|---|---|---|---|
| **2.94 ms/row** | batched: 224 queries encoded together, wall clock divided by rows | **not per-call latency** | `spark-2500`, default threads | `out/ft_bge-small_nn0_t0.10.json::cost.query_ms_per_row` (sha `7c469036f443d156`) |
| 18.3 ms | isolated, one query per forward pass | per-call | `spark-2500`, default 20 threads | `out/final_bge-small_ft.json::cpu_query_ms_isolated` (sha `fd9e0a3defb783f6`), `RESULTS.md` §7 |
| 44.03 ms | isolated | per-call | `spark-2500`, pinned 4 threads | `out/smoke_report_aarch64_spark-2500.json::latency` (training machine; regenerated 2026-09-04 against the current manifest, template sha `a5254caebb54a699…`, report sha `40eaec27b4e3d0ba`; the 2026-09-03 run against the previous bundle measured 44.04). The freeze script re-measures the same quantity on every freeze into `deploy/manifest.json::device.query_ms_isolated_single_at_pinned_threads`; read that key rather than a copy, it moves by a few tenths per run. |
| 13.06 ms | isolated | per-call | `Wright`, pinned 4 threads | [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json)`::latency`; also `manifest::device.serving_reference.query_ms_isolated_single` |
| 12.88 / 13.30 / 13.41 / 14.24 / 23.76 ms, median 13.41 | isolated, five earlier runs recorded by the operator on 2026-09-03; the 13.06 above is a sixth, later run | per-call | `Wright`, pinned 4 threads | `deploy/manifest.json::device.serving_reference.query_ms_isolated_single_runs` (recorded as a constant in `src/freeze_deploy.py`) |
| corpus encode, 1,353 targets, batch 64 | 19.2 s Spark at default threads; 21.1 s Spark at 4 threads (2026-09-04 report; 21.0 on 2026-09-03); about 21 s at the current freeze; 57.9 s Wright at 4 threads | — | as stated | `out/final_bge-small_ft.json::cpu_encode_all_targets_s`; Spark smoke report `reencode.wall_s`; `manifest::measured.cpu_encode_all_targets_s`; Wright smoke report `reencode.wall_s` |

Every prose report that once quoted 2.94 ms as per-query latency now labels it batched
and cites this table. Two places keep the bare figure by design: `BRIEF_ensemble.md`
(a brief recorded verbatim; it carries an editorial note) and the artifact key
`encode_ms_per_query_1_draw` in `out/fusion_task4_rewriter.json`, whose name is wrong and
whose value is the batched one.

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

`origin/main` sat at 6416094, before the withdrawal, until this branch was merged into it
on 2026-09-04; until then all four were tracked at the tip of the public default branch.
They remain reachable in history: `deploy/targets.json` from e446cf8, the three `out/`
artifacts from 73f796b and 8f1d9fb, until the operator rewrites history or makes the
repository private.

## The bundle's proof chain

The tracked serving-machine report, [`out/smoke_report_x86_64_Wright.json`](out/smoke_report_x86_64_Wright.json),
certifies the bundle at commit [6416094](https://github.com/rmehta1987/COMPASS/commit/64160949c3570e729805e99611af5243ad0e8115).
Since then three hashed bundle files changed, without a code change to the retriever:

| file | at 6416094 | now | nature of the change |
|---|---|---|---|
| `deploy/retriever.py` | `24ccefb4bffdbeb1` | see manifest | docstring bullets added; AST identical once docstrings are dropped |
| `deploy/template.py` | `9c78d0b0bb0139a3` | see manifest | docstring note added; AST identical once docstrings are dropped |
| `deploy/smoke_test.py` | `98606ca8760a46b5` | see manifest | docstring line, a comment, and the step-0 hint (its message strings and the condition selecting it now also cover a missing `targets.json`); this runs only after integrity has already failed. No assertion, threshold, expectation or scoring code changed. |

`deploy/manifest.json::proof_chain` recomputes this comparison at every freeze, with the
AST check, so a report proving an older bundle is never presented as proving the current
one. The current bundle was proven on the Spark on 2026-09-04 against this manifest
(`out/smoke_report_aarch64_spark-2500.json`, template sha `a5254caebb54a699…`, report sha `40eaec27b4e3d0ba`,
training machine; the freeze script does not run the test itself, the operator does).
**A serving-machine re-run against the current manifest is pending**; committing its report
re-closes the chain.

## Every `out/` artifact the four reports cite

Measured on the training machine on 2026-09-04; `tracked` means `git ls-files` lists it.

| artifact | sha256 (first 16) | bytes | where |
|---|---|---|---|
| `out/char_pos_bge-small_ft.json` | `7cbc5554a445d571` | 284,688 | training-machine |
| `out/char_task1_phrasing.json` | `a9fb551270fb15e1` | 15,779 | training-machine |
| `out/char_task2_negatives.json` | `0ac94dcf565135f8` | 14,412 | training-machine |
| `out/char_task3_calibration.json` | `5cfd9438c2e1dcb7` | 195,306 | training-machine |
| `out/char_task4_strata.json` | `3653b16f2339d09a` | 25,230 | training-machine |
| `out/diag_qwen3-06b_dtype_from_config.json` | `8aeb751787ba61b7` | 87,314 | training-machine |
| `out/final_bge-small_frozen.json` | `f5fa5f3c889fe102` | 553 | training-machine |
| `out/final_bge-small_ft.json` | `fd9e0a3defb783f6` | 707 | training-machine |
| `out/final_embgemma_ft.json` | `fc3de327d2b70298` | 555 | training-machine |
| `out/finalize.log` | `38d24729ab6cbd11` | 845 | training-machine |
| `out/final_mxbai_ft.json` | `85a3e05d699ece71` | 548 | training-machine |
| `out/frozen_bge-base.json` | `426d909bbac5a580` | 87,286 | training-machine |
| `out/frozen_bge-small.json` | `0a6282f0b262cb91` | 87,302 | training-machine |
| `out/frozen_e5-base.json` | `1022e33a398fcff2` | 87,241 | training-machine |
| `out/frozen_embgemma.json` | `f281b19ece7eecb9` | 87,302 | training-machine |
| `out/frozen_granite-s2.json` | `232ff5e5978fb288` | 87,239 | training-machine |
| `out/frozen_gte-mbert.json` | `47058779ff7d5b98` | 87,219 | training-machine |
| `out/frozen_mxbai-l1.json` | `7efda8f985efe70b` | 87,361 | training-machine |
| `out/frozen_nomic-v15.json` | `ad7e42255c1782e9` | 87,252 | training-machine |
| `out/frozen_qwen3-06b.json` | `be02d4922c7725ff` | 87,290 | training-machine |
| `out/frozen_qwen35-08b.json` | `03dfd17e63c94d73` | 87,494 | training-machine |
| `out/frozen_sweep.log` | `1585c44eb504ca14` | 5,459 | training-machine |
| `out/ft_bge-small_nn0_t0.05.json` | `3660d7d9bb9de373` | 87,243 | training-machine |
| `out/ft_bge-small_nn0_t0.10.json` | `7c469036f443d156` | 87,238 | training-machine |
| `out/ft_bge-small_nn0_t0.15.json` | `6c1cdaa6e4759747` | 87,234 | training-machine |
| `out/ft_bge-small_nn0_t0.20.json` | `3b9191073eeb0b95` | 87,270 | training-machine |
| `out/ft_bge-small_nn4_t0.02.json` | `13ef9759d67bc516` | 87,230 | training-machine |
| `out/ft_bge-small_nn4_t0.05.json` | `aa277fa7fbc6301e` | 87,237 | training-machine |
| `out/ft_bge-small_nn4_t0.10.json` | `808833cfb8a8ebb1` | 87,225 | training-machine |
| `out/ft_bge-small_nn8_t0.05.json` | `a41ec8fbfe11bd6c` | 87,235 | training-machine |
| `out/ft_bge-small_nn8_t0.10.json` | `707f2cfbf48b2f5b` | 87,233 | training-machine |
| `out/ft_embgemma_nn0_t0.10.json` | `803bb70b56e63db0` | 87,154 | training-machine |
| `out/ft_mxbai_nn0_t0.05.json` | `3956907ded23218e` | 87,191 | training-machine |
| `out/ft_mxbai_nn0_t0.10.json` | `5bbc89f9afba4a47` | 87,179 | training-machine |
| `out/fusion_sims_pos.pt` | `8fc65d8fbc00c25a` | 1,225,505 | training-machine |
| `out/fusion_task1_overlap.json` | `0808bb02944a39f6` | 259,092 | training-machine |
| `out/fusion_task2_rules.json` | `f206e84f3d3c2824` | 32,493 | tracked |
| `out/fusion_task3_abstention.json` | `eb6d7884c3427b56` | 23,778 | tracked |
| `out/fusion_task4_rewriter.json` | `22851b64a584ab84` | 29,924 | tracked |
| `out/gate_full_stem_dash_option.json` | `df9ed3b0375c15b8` | 87,275 | training-machine |
| `out/gate_full_stem_option_dup.json` | `7a63f8023f2d0100` | 87,348 | training-machine |
| `out/gate_full_stem_option.json` | `9378791386edc44e` | 87,277 | training-machine |
| `out/gate_full_verbatim.json` | `d635c46ee9aa7f98` | 87,257 | training-machine |
| `out/mrl_qwen35_128.json` | `3ba0418d57cbc93f` | 87,461 | training-machine |
| `out/mrl_qwen35_256.json` | `79c3ee6b8a19e15c` | 87,480 | training-machine |
| `out/mrl_qwen35_512.json` | `fb771d0900d424e1` | 87,437 | training-machine |
| `out/mrl_qwen35_768.json` | `1b3a0121b96b67a9` | 87,482 | training-machine |
| `out/negatives_absence_check.json` | `6c01f9e8fe13b0db` | 2,986 | training-machine |
| `out/nomic.log` | `975dc5fb018c3387` | 695 | training-machine |
| `out/qx_preregistration.json` | `b979ee957fc85f02` | 72,082 | tracked |
| `out/qx_task2_paired.json` | `913736170edb6e83` | 138,119 | training-machine |
| `out/qx_task3_abstention.json` | `221dbc4946fd2f67` | 49,339 | training-machine |
| `out/qx_task4_corpus_size.json` | `470b21be9625d29c` | 22,229 | tracked |
| `out/recheck_frozen_mxbai-l1.json` | `07eb05e906610ff9` | 87,390 | training-machine |
| `out/refp32.log` | `6b5dad86018cfadd` | 2,514 | training-machine |
| `out/report_table.json` | `032b05516ee0b048` | 12,711 | training-machine |
| `out/rewrites_negatives.json` | `233f0e89f00081f1` | 14,524 | tracked |
| `out/rewrites_positives.json` | `e922eea959a08059` | 57,893 | tracked |
| `out/round2.log` | `fccf205b4714e120` | 6,086 | training-machine |
| `out/score_gate_dup.json` | `742c55975ad62329` | 81,042 | training-machine |
| `out/score_gate_stem_dash_option.json` | `83b2399878e27ac5` | 80,992 | training-machine |
| `out/score_gate_stem_option.json` | `bf9f5d2454307bcf` | 80,995 | training-machine |
| `out/score_gate_verbatim.json` | `020df5346ed5e83d` | 80,977 | training-machine |
| `out/smoke_report_aarch64_spark-2500.json` | `40eaec27b4e3d0ba` | 10,185 | training-machine |
| `out/smoke_report_x86_64_Wright.json` | `f42f4e0131708e56` | 10,198 | tracked |
| `out/targets_1241.json` | `f9922f1b6b0468db` | 869,883 | training-machine |
| `out/targets_full.json` | `22b0c37a90696f4e` | 940,840 | training-machine |
| `out/training_pairs.json` | `e32ad01a1c5c208b` | 1,778,194 | training-machine |

| `out/char_pos_bge-small_frozen.json` | `81a12be2e4335ea5` | 283,626 | training-machine |
| `out/char_neg_bge-small_ft.json` | `d91fc1286a0c5c7b` | 38,929 | training-machine |
| `out/char_neg_bge-small_frozen.json` | `3cb195593babfab6` | 38,739 | training-machine |
| `out/sweep1.log` | `a926b5b1758ee508` | 1,234 | training-machine |
| `out/sweep2.log` | `cbd99afb2b377b67` | 3,520 | training-machine |
| `out/sweep3.log` | `8b8d7dacaf57fa91` | 6,401 | training-machine |
| `out/sweep4.log` | `c17db1508be66493` | 13,289 | training-machine |
| `out/sweep5.log` | `a683d01df616105d` | 3,519 | training-machine |
| `out/sweep6.log` | `9865aada9d159f9b` | 954 | training-machine |
| `out/sweep7.log` | `5fda4a9ee934f191` | 1,978 | training-machine |

The last ten rows expand the glob citations `out/char_pos_*.json`, `out/char_neg_*.json` and `out/sweep*.log`.

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
