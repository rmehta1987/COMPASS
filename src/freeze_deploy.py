"""Freeze the shipped retriever into a self-contained, CPU-only deploy/ bundle.

The model does not need to live on the Spark. 33M params, 2.94 ms/query on CPU,
19 s to encode the whole corpus -- there is no reason to couple the retriever to
a shared box running vLLM, Ollama, Redis and Postgres.

What gets recorded rather than inferred, because each one is easy to lose and
each one silently changes the answers:

  * dictionary_version_hash  -- asserted at load, FAILS (never warns)
  * target_text rendering    -- `stem_option_dup`, worth +8.0 R@1 over the
                                obvious `stem_option` (out/gate_full_*.json)
  * query prefix             -- BGE's "Represent this sentence for searching
                                relevant passages: "; omitting it is silent
  * pooling                  -- CLS, not mean
  * padding side, dtype, max sequence lengths
  * device                   -- CPU, pinned; see the parity note in the manifest

    python src/freeze_deploy.py --checkpoint runs/bge-small_nn0_t0.10 --out deploy
"""
from __future__ import annotations

import argparse, hashlib, json, shutil, sys, time
from pathlib import Path

import torch
from safetensors.torch import save_file

sys.path.insert(0, str(Path(__file__).parent))
from compass_score import MODELS, target_text, encode

EXPECTED_HASH = "3dc8415eccfe"
MODEL_KEY = "bge-small"
TARGET_TEXT = "stem_option_dup"
CKPT_FILES = ("model.safetensors", "config.json", "tokenizer.json",
              "tokenizer_config.json")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=Path, default=Path("runs/bge-small_nn0_t0.10"))
    ap.add_argument("--targets", type=Path, default=Path("out/targets_full.json"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--calibration", type=Path,
                    default=Path("out/char_task3_calibration.json"))
    ap.add_argument("--out", type=Path, default=Path("deploy"))
    ap.add_argument("--threads", type=int, default=4,
                    help="pinned torch thread count, recorded in the manifest; "
                         "latency is measured at this setting")
    ap.add_argument("--smoke-report", type=Path, default=Path("out/smoke_report.json"),
                    help="deploy/smoke_test.py report; if present, the shipped "
                         "instances-only R@1 is copied into manifest['template']")
    ap.add_argument("--qx-paired", type=Path, default=Path("out/qx_task2_paired.json"))
    a = ap.parse_args()

    import platform
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(a.threads)

    T = json.loads(a.targets.read_text())
    if T["dictionary_version_hash"] != EXPECTED_HASH:
        raise SystemExit(f"targets built from {T['dictionary_version_hash']}, "
                         f"expected {EXPECTED_HASH}")
    targets = T["targets"]
    cfg = MODELS[MODEL_KEY]
    root = a.out
    (root / "model").mkdir(parents=True, exist_ok=True)

    # ---- checkpoint: copy the safetensors weights + tokenizer, no conversion
    for f in CKPT_FILES:
        src = a.checkpoint / f
        if not src.exists():
            raise SystemExit(f"missing {src}")
        shutil.copy2(src, root / "model" / f)

    # ---- target vectors, computed ON CPU (the serving device), fp32
    tok = AutoTokenizer.from_pretrained(str(root / "model"))
    tok.padding_side = cfg["pad"]
    model = AutoModel.from_pretrained(str(root / "model"),
                                      dtype=torch.float32).to("cpu").eval()
    t0 = time.time()
    D = encode([cfg["d_prefix"] + target_text(t, TARGET_TEXT) for t in targets],
               tok, model, cfg["pool"], 256, "cpu")
    encode_s = time.time() - t0
    save_file({"target_vectors": D.contiguous()}, str(root / "target_vectors.safetensors"))
    shutil.copy2(a.targets, root / "targets.json")

    # ---- prove the frozen bundle reproduces the measured number
    fx = json.loads(a.fixture.read_text())
    rows = fx["queries"] if isinstance(fx, dict) else fx
    Q = encode([cfg["q_prefix"] + r["query"] for r in rows],
               tok, model, cfg["pool"], 64, "cpu")
    by_key = {m: t["target_id"] for t in targets for m in t["members"]}
    sims = Q @ D.T
    top1 = sims.argmax(dim=-1)
    hits = sum(1 for i, r in enumerate(rows)
               if by_key.get(r["key"]) == int(top1[i]) + 1)
    r_at1 = round(hits / len(rows), 4)
    cos_top1 = sims.max(dim=-1).values

    cal = json.loads(a.calibration.read_text())["bge-small_ft"]["sweep_cos_top1"]
    f1max, allrej = cal["max_f1"], cal["at_all_negatives_rejected"]

    # ---- isolated single-query latency AT THE PINNED THREAD COUNT. The 2.94 ms
    # figure elsewhere in this project is query_ms_per_row from a BATCHED scoring
    # run (out/ft_bge-small_nn0_t0.10.json); it is not what a caller sees.
    qtexts = [cfg["q_prefix"] + r["query"] for r in rows]
    for q in qtexts[:8]:
        encode([q], tok, model, cfg["pool"], 64, "cpu")
    t1 = time.time()
    for q in qtexts:
        encode([q], tok, model, cfg["pool"], 64, "cpu")
    query_ms = (time.time() - t1) / len(qtexts) * 1000
    machine = f"{platform.node()} {platform.machine()} {platform.platform()}"

    # ---- shipped-contract figures: pre-registered arm F from the paired artifact,
    # instances-only (arm I) from the smoke test's report when it has been run
    qx = json.loads(a.qx_paired.read_text())["overall"] if a.qx_paired.exists() else None
    smoke = json.loads(a.smoke_report.read_text()) if a.smoke_report.exists() else None
    arm_I = (smoke or {}).get("acceptance", {}).get("I")

    # Bytecode caches are machine-specific: checksumming one would make the
    # integrity check fail on any machine but this one.
    files = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name == "manifest.json":
            continue
        if p.suffix == ".pyc" or "__pycache__" in p.parts:
            continue
        files[str(p.relative_to(root))] = {"sha256": sha256(p),
                                           "bytes": p.stat().st_size}

    manifest = {
        "schema": "compass_retriever_deploy/1",
        "frozen": "2026-09-03",
        "what_this_is": (
            "The shipped COMPASS variable retriever: fine-tuned bge-small, argmax "
            "cosine over 1,353 precomputed target vectors, no LLM call. CPU-only."),

        "dictionary_version_hash": EXPECTED_HASH,
        "dictionary_hash_policy": (
            "retriever.py ASSERTS this hash against targets.json at load and "
            "raises. It does not warn: a stale vector file returns wrong answers "
            "silently, which is worse than not starting."),

        "encoder": {
            "base_repo": "BAAI/bge-small-en-v1.5",
            "base_revision": cfg["rev"],
            "fine_tuned_from": str(a.checkpoint),
            "training_config": "nn0, t=0.10 (in-batch negatives only, temp 0.10)",
            "params_m": cfg["params"],
            "embed_dim": int(D.shape[1]),
            "format": "safetensors, CPU-loadable, fp32",
        },
        # every one of these is a silent-wrong-answer if it drifts
        "conventions": {
            "pooling": cfg["pool"],
            "query_prefix": cfg["q_prefix"],
            "document_prefix": cfg["d_prefix"],
            "target_text_rendering": TARGET_TEXT,
            "target_text_rendering_definition": (
                "f'{stem} {option}' when the target has an option, else "
                "f'{stem} {stem}' -- the stem is DUPLICATED when there is no "
                "option. See src/compass_score.py::target_text."),
            "target_text_rendering_why": (
                "+8.0 R@1 over `stem_option` on the full 1,353-target / 224-row "
                "set (0.375 vs 0.295, out/gate_full_stem_option_dup.json vs "
                "out/gate_full_stem_option.json). The gain is almost entirely in "
                "folded-family recall (0.304 vs 0.089): duplicating the stem is "
                "what makes a roster representative retrievable at all."),
            "padding_side": cfg["pad"],
            "dtype": "float32",
            "max_len_document": 256,
            "max_len_query": 64,
            "normalise": "L2, both sides; score is a dot product = cosine",
            "selection": "argmax over all 1,353 target vectors",
        },
        "device": {
            "pinned": "cpu",
            "why": (
                "The fine-tuned checkpoint has exactly one GPU/CPU top-1 "
                "disagreement in 224 rows -- row 107, 'primary method used to get "
                "to work', max |vector delta| 4.06e-7 "
                "(out/final_bge-small_ft.json). Not a bug, but that query is the "
                "hardest row in every report in this project, so the flip lands "
                "exactly where device parity matters. CPU-only serving avoids it "
                f"and costs little: {query_ms:.1f} ms per isolated query at "
                f"{a.threads} threads, {encode_s:.1f}s to encode the whole corpus."),
            "vectors_computed_on": "cpu",
            "threads": a.threads,
            "threads_why": (
                "retriever.py calls torch.set_num_threads with this value unless the "
                "caller overrides it. Unpinned thread counts make latency "
                "unreproducible across machines with different core counts."),
            "query_ms_isolated_single_at_pinned_threads": round(query_ms, 2),
            "latency_measured_on": machine,
            "latency_note": (
                "One query per forward pass, fp32, warm. The 2.94 ms/query quoted in "
                "RESULTS.md is query_ms_per_row from a BATCHED 224-row scoring run "
                "(out/ft_bge-small_nn0_t0.10.json) and is not per-call latency; "
                "src/finalize.py's isolated figure on the training machine was 18.3 ms. "
                "Re-measure on the serving machine with deploy/smoke_test.py step 6."),
        },
        "corpus": {
            "n_targets": len(targets),
            "n_constructs": T["n_constructs"],
            "n_multi_option": T["n_multi_option"],
            "n_folded_family": T["n_folded_family"],
            "targets_file": "targets.json",
            "vectors_file": "target_vectors.safetensors",
            "vector_row_order": "row i is target_id i+1, ascending; asserted at load",
        },
        "measured": {
            "recall_at1_224_row_fixture": r_at1,
            "reproduces_out_ft_bge-small_nn0_t0.10_json": r_at1 == 0.567,
            "cpu_encode_all_targets_s": round(encode_s, 1),
            "cos_top1_min_over_fixture": round(float(cos_top1.min()), 4),
            "cos_top1_max_over_fixture": round(float(cos_top1.max()), 4),
        },
        "abstention": {
            "default_min_cos": f1max["tau"],
            "how_chosen": (
                "Threshold maximising F1 over the 224 POSITIVE rows only "
                "(out/char_task3_calibration.json). The 44-row held-out negative "
                "set was then used to report, not to select: it rejects 43/44 "
                "absent-construct requests at this threshold."),
            "at_default": {
                "coverage": f1max["coverage"], "precision": f1max["precision"],
                "recall": f1max["recall"],
                "negatives_rejected": f1max["negatives_rejected"]},
            "stricter_option": {
                "min_cos": allrej["tau"],
                "note": "rejects 44/44 negatives, but costs 4.5 more recall points",
                "coverage": allrej["coverage"], "precision": allrej["precision"],
                "recall": allrej["recall"]},
            "what_it_does_NOT_do": (
                "This threshold detects ABSENT constructs (AUROC 0.982 positives "
                "vs negatives). It does NOT detect a wrong pick among present "
                "constructs: cosine separates correct from incorrect top-1 at "
                "AUROC 0.640 only, and precision 0.90 is unreachable at any "
                "threshold. Do not read a returned result as verified."),
            "not_independently_validated": (
                "The threshold is derived from a model-authored negative set. It "
                "needs the study-team-authored request set to confirm."),
            "threshold_grid": (
                "Candidates are the distinct top-1 scores of the 224 positives "
                "(221 values). F1 over positives is piecewise constant between "
                "positive scores, so this candidate set is exhaustive: no denser "
                "grid can find a different optimum, only the same plateau. "
                "deploy/smoke_test.py step 5 re-derives it exhaustively and over a "
                "20,001-point dense grid and reports the plateau on every run."),
            "knife_edge": {
                "finding": (
                    "The shipped value is the 6-dp rounding of an INCORRECT positive's "
                    "top-1 score (fixture row 68, 'electronic nicotine delivery "
                    "frequency', gold m3:Q6.3). Encoded in a batch of 64 that row "
                    "scores 0.729475981, 1.9e-8 BELOW the threshold, and is refused; "
                    "encoded alone, as retriever.select() does, it scores "
                    "0.729476045, 4.5e-8 ABOVE, and is answered (wrongly). Under "
                    "single-query serving the F1 optimum by the same rule is "
                    "therefore the next candidate, 0.731902, in every arm; "
                    "F1(shipped) is 0.0013 to 0.0015 below it: one row. Recall is "
                    "identical at both values."),
                "not_changed_because": (
                    "one row of F1 is not material, 0.7295 is cited across every "
                    "document, and 0.731902 is itself the exact score of a CORRECT "
                    "positive (row 212), so it is the same knife-edge on the other "
                    "side. Changing the operating point is the operator's call."),
                "robust_alternative": {
                    "min_cos": 0.73174,
                    "why": (
                        "midpoint of the 3.3e-4 window (0.731576, 0.731902]: above the "
                        "one surviving negative under the templated arms (n42, "
                        "'neighborhood income level', 0.731576) and below the correct "
                        "positive at 0.731902, with 1.6e-4 of margin each side, about "
                        "2,000x the observed encoding jitter. At this value recall is "
                        "unchanged in every arm, row 68 is refused, and the templated "
                        "arms reject 44/44 negatives instead of 43/44."),
                    "caveat": "chosen with sight of the 44 negatives, which the "
                              "shipped value was not; confirm on the study-team set.",
                },
            },
        },
        "template": {
            "file": "template.py",
            "what": "[population] construct [timeframe][: instance, ...] -- "
                    "RetrievalRequest.to_query(); pure string concatenation, no "
                    "model call. Re-exported by retriever.py as RetrievalRequest / "
                    "VariableRole, with search_request() and select_request().",
            "shipped_contract": "INSTANCES ONLY. Leave population=None (its default).",
            "why_it_ships": (
                "Forgetting the template is a silent loss: pre-registered arm F "
                "measured R@1 0.643 against 0.567 without it "
                "(out/qx_task2_paired.json, 62 of 224 rows changed, item-clustered "
                "bootstrap CI excluding zero)."),
            "population_slot": {
                "status": "POST-HOC REVISION of pre-registered arm F, which rendered "
                          "population + instances. The revision is to leave the "
                          "population slot unused.",
                "measured": "net -1 row on the 17 rows it touched: R@1 0.647 -> 0.588 "
                            "(+2, -3). QUERY_EXPANSION.md section 2a.",
                "mechanism": "the roster noun pulls the query toward the roster "
                             "block's OTHER question about the same cancer, at "
                             "margins down to 0.0001",
                "held_out_confirmation": "the study-team-authored request set; "
                                         "until then the revision is unconfirmed",
            },
            "r_at1_224_rows": {
                "no_template_S": qx["S"]["R@1"] if qx else 0.567,
                "preregistered_F_population_and_instances": qx["F"]["R@1"] if qx else 0.6429,
                "shipped_I_instances_only": arm_I["R@1_4dp"] if arm_I else None,
                "shipped_I_measured_by": "deploy/smoke_test.py arm I" if arm_I else
                                         "not yet measured: run deploy/smoke_test.py, then re-freeze",
            },
        },
        "known_limitations": [
            "R@1 0.567 on a fixture whose queries were written by a model that saw "
            "the gold wording, by the same generator family as the 13,528 training "
            "pairs. An unknown share of the +0.192 over frozen bge-small is "
            "register alignment. The lexical-leakage reading was measured and does "
            "not survive: item-level Spearman -0.023 (permutation p 0.87), R@1 by "
            "query/gold overlap quartile 0.482 / 0.554 / 0.643 / 0.589, "
            "non-monotonic, flat within every query-length stratum. FUSION.md "
            "section 1; RESULTS.md section 9.",
            "Recall is not uniform: residence/commute R@1 0.062 (n=16) and sleep "
            "0.000 (n=4) against cancer_history 0.613 (n=80). "
            "out/char_task4_strata.json.",
            "The 224-row fixture contains no SES/employment, insurance/access, "
            "cancer-screening or demographics row, so recall on those four strata "
            "is unmeasured, not good. out/char_task4_strata.json.",
            "10 of 56 gold items are retrieved on 0 of their 4 phrasings and 9 on "
            "1 of 4. out/char_task1_phrasing.json lists them with an example "
            "phrasing each; these are the documented blind spots.",
        ],
        "provenance": {
            "score_artifact": "out/ft_bge-small_nn0_t0.10.json",
            "parity_artifact": "out/final_bge-small_ft.json",
            "characterisation": ["out/char_task1_phrasing.json",
                                 "out/char_task2_negatives.json",
                                 "out/char_task3_calibration.json",
                                 "out/char_task4_strata.json"],
            "rendering_ablation_full_corpus": [
                f"out/gate_full_{m}.json" for m in
                ("stem_option_dup", "stem_option", "stem_dash_option", "verbatim")],
            "negative_fixture": "fixtures/negative_requests.json",
            "training_meta": str(a.checkpoint / "compass_train_meta.json"),
            "template_paired_artifact": "out/qx_task2_paired.json",
            "template_abstention_artifact": "out/qx_task3_abstention.json",
            "preregistration_fixture": "out/qx_preregistration.json (tracked; the "
                                       "only fixture deploy/smoke_test.py needs)",
            "cpu_port_acceptance_test": "deploy/smoke_test.py",
        },
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1))

    print(f"deploy bundle -> {root}")
    print(f"  dictionary hash      {EXPECTED_HASH} (asserted at load)")
    print(f"  targets / dim        {len(targets)} / {int(D.shape[1])}")
    print(f"  rendering            {TARGET_TEXT}")
    print(f"  CPU encode-all       {encode_s:.1f}s at {a.threads} threads")
    print(f"  isolated query       {query_ms:.2f} ms at {a.threads} threads ({machine})")
    print(f"  instances-only R@1   {arm_I['R@1_4dp'] if arm_I else 'not yet measured'}")
    print(f"  R@1 from bundle      {r_at1}  "
          f"(matches out/ft_bge-small_nn0_t0.10.json: {r_at1 == 0.567})")
    print(f"  default min_cos      {f1max['tau']:.4f}  "
          f"(coverage {f1max['coverage']}, rejects "
          f"{f1max['negatives_rejected']:.0%} of negatives)")
    tot = sum(v["bytes"] for v in files.values())
    print(f"  {len(files)} files, {tot/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
