"""Deployment checks for a chosen encoder.

1. Precompute target vectors on the device we will query from, keyed to the
   dictionary build hash.
2. Assert GPU- and CPU-computed vectors give identical top-1 for all 224 rows.
   Small numeric differences shift the argmax on exactly the near-duplicate
   pairs that matter, so this is checked, not assumed.
3. Measure CPU query latency with nothing else running, and report disk size.
"""
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from compass_score import MODELS, target_text, encode, load_dense, load

EXPECTED_HASH = "3dc8415eccfe"


def build_vectors(src, cfg, targets, rows, device, tt, weights=None):
    tok = AutoTokenizer.from_pretrained(src, trust_remote_code=cfg["trc"])
    tok.padding_side = cfg["pad"]
    model = AutoModel.from_pretrained(src, trust_remote_code=cfg["trc"],
                                      **(cfg.get("extra") or {})).to(device).eval()
    dense = None
    if cfg.get("dense") and not weights:
        dense = [w.to(device) for w in load_dense(cfg["dense"])]
    D = encode([cfg["d_prefix"] + target_text(t, tt) for t in targets],
               tok, model, cfg["pool"], 256, device, dense=dense)
    Q = encode([cfg["q_prefix"] + r["query"] for r in rows],
               tok, model, cfg["pool"], 64, device, dense=dense)
    return D, Q, tok, model, dense


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--weights", type=Path, default=None)
    ap.add_argument("--target-text", default="stem_option_dup")
    ap.add_argument("--out-vectors", type=Path, required=True)
    ap.add_argument("--out-report", type=Path, required=True)
    ap.add_argument("--label", default=None)
    a = ap.parse_args()

    T, rows = load(a.targets, a.fixture, EXPECTED_HASH)
    targets = T["targets"]
    cfg = MODELS[a.model]
    src = str(a.weights) if a.weights else cfg["repo"]

    # --- CPU is the deployment device: build the vectors we will ship --------
    t0 = time.time()
    Dc, Qc, tok, model, dense = build_vectors(src, cfg, targets, rows, "cpu",
                                              a.target_text, a.weights)
    cpu_encode_s = time.time() - t0

    # --- isolated CPU query latency -----------------------------------------
    qtexts = [cfg["q_prefix"] + r["query"] for r in rows]
    for _ in range(2):                       # warm up
        encode(qtexts[:8], tok, model, cfg["pool"], 64, "cpu", dense=dense)
    t1 = time.time()
    for q in qtexts:
        encode([q], tok, model, cfg["pool"], 64, "cpu", dense=dense)
    cpu_q_ms = (time.time() - t1) / len(qtexts) * 1000
    del model

    top1_cpu = (Qc @ Dc.T).argmax(dim=-1)

    # --- same vectors on GPU, then compare argmax ---------------------------
    gpu_ok, agree, n_dis, dis = None, None, None, []
    if torch.cuda.is_available():
        Dg, Qg, *_ = build_vectors(src, cfg, targets, rows, "cuda",
                                   a.target_text, a.weights)
        top1_gpu = (Qg @ Dg.T).argmax(dim=-1)
        same = (top1_cpu == top1_gpu)
        agree = float(same.float().mean())
        n_dis = int((~same).sum())
        gpu_ok = bool(n_dis == 0)
        for i in (~same).nonzero().flatten().tolist():
            dis.append({"row": i, "query": rows[i]["query"],
                        "cpu_top": targets[int(top1_cpu[i])]["canonical_key"],
                        "gpu_top": targets[int(top1_gpu[i])]["canonical_key"]})
        max_cos_delta = float((Dc - Dg.cpu()).abs().max())
    else:
        max_cos_delta = None

    a.out_vectors.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"D": Dc, "dictionary_version_hash": T["dictionary_version_hash"],
                "model_source": src, "target_text": a.target_text,
                "device_computed_on": "cpu",
                "target_ids": [t["target_id"] for t in targets]}, a.out_vectors)

    disk = 0
    if a.weights:
        disk = sum(f.stat().st_size for f in Path(a.weights).rglob("*") if f.is_file())

    rep = {
        "label": a.label or a.model, "model": a.model, "source": src,
        "dictionary_version_hash": T["dictionary_version_hash"],
        "n_targets": len(targets), "n_rows": len(rows),
        "embed_dim": int(Dc.shape[1]),
        "cpu_encode_all_targets_s": round(cpu_encode_s, 1),
        "cpu_query_ms_isolated": round(cpu_q_ms, 2),
        "gpu_cpu_top1_identical": gpu_ok,
        "gpu_cpu_top1_agreement": agree,
        "gpu_cpu_top1_disagreements": n_dis,
        "disagreement_rows": dis[:20],
        "max_abs_vector_delta_gpu_vs_cpu": max_cos_delta,
        "checkpoint_disk_bytes": disk,
        "checkpoint_disk_mb": round(disk / 1e6, 1),
        "vectors_file": str(a.out_vectors),
    }
    a.out_report.write_text(json.dumps(rep, indent=1))
    print(f"{rep['label']}")
    print(f"  dim {rep['embed_dim']}  targets {len(targets)}")
    print(f"  CPU encode-all {rep['cpu_encode_all_targets_s']}s   "
          f"CPU query (isolated) {rep['cpu_query_ms_isolated']} ms")
    print(f"  GPU-vs-CPU top-1 identical: {gpu_ok}  "
          f"(agreement {agree}, disagreements {n_dis})")
    print(f"  max |vec delta| gpu-cpu {max_cos_delta}")
    print(f"  checkpoint {rep['checkpoint_disk_mb']} MB -> {a.out_vectors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
