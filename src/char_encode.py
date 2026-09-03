"""Re-encode a checkpoint on CPU and dump a per-row characterisation artifact.

`compass_score.py` records `cos_gold` and `cos_top` but not the runner-up, so
the top1-minus-top2 margin -- the quantity BRIEF task 3 asks for -- cannot be
recovered from its output. This script re-encodes and records the full top-k
neighbourhood per row, for the positive fixture and for the held-out negative
fixture alike.

Conventions (pooling, query prefix, document prefix, target-text rendering) are
imported from `compass_score.py`, never re-declared here, so this cannot drift
from the numbers in RESULTS.md.

    python src/char_encode.py --model bge-small --weights runs/bge-small_nn0_t0.10 \
        --targets out/targets_full.json --fixture retrieval_queries.json \
        --label bge-small_ft --out out/char_pos_bge-small_ft.json

A fixture whose schema starts "retrieval_negative" carries no gold key; rank and
correctness are omitted for it and only the cosine geometry is recorded.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from compass_score import MODELS, target_text, encode, load_dense

EXPECTED_HASH = "3dc8415eccfe"
TOPK = 10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--model", default="bge-small", choices=sorted(MODELS))
    ap.add_argument("--weights", type=Path, default=None)
    ap.add_argument("--target-text", default="stem_option_dup")
    ap.add_argument("--label", default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--save-vectors", type=Path, default=None)
    a = ap.parse_args()

    T = json.loads(a.targets.read_text())
    if T["dictionary_version_hash"] != EXPECTED_HASH:
        raise SystemExit(f"targets built from {T['dictionary_version_hash']}, "
                         f"expected {EXPECTED_HASH}")
    targets = T["targets"]

    fx = json.loads(a.fixture.read_text())
    rows = fx["queries"] if isinstance(fx, dict) else fx
    schema = fx.get("schema", "") if isinstance(fx, dict) else ""
    negatives = schema.startswith("retrieval_negative")

    cfg = MODELS[a.model]
    src = str(a.weights) if a.weights else cfg["repo"]
    tok_kw = dict(trust_remote_code=cfg["trc"])
    mdl_kw = dict(trust_remote_code=cfg["trc"], dtype=torch.float32,
                  **cfg.get("extra", {}))
    if not a.weights:                       # pin the same revision as the sweep
        tok_kw["revision"] = cfg["rev"]
        mdl_kw["revision"] = cfg["rev"]
    tok = AutoTokenizer.from_pretrained(src, **tok_kw)
    tok.padding_side = cfg["pad"]
    model = AutoModel.from_pretrained(src, **mdl_kw).to("cpu").eval()

    dense = None
    if cfg.get("dense"):
        dense = [w for w in load_dense(a.weights if a.weights else cfg["dense"])]

    t0 = time.time()
    D = encode([cfg["d_prefix"] + target_text(t, a.target_text) for t in targets],
               tok, model, cfg["pool"], 256, "cpu", dense=dense)
    encode_s = time.time() - t0
    Q = encode([cfg["q_prefix"] + r["query"] for r in rows],
               tok, model, cfg["pool"], 64, "cpu", dense=dense)

    by_key = {m: t["target_id"] for t in targets for m in t["members"]}
    sims = Q @ D.T
    order = sims.argsort(dim=-1, descending=True)
    rank_of = order.argsort(dim=-1)

    out_rows = []
    for i, r in enumerate(rows):
        topk = [int(x) for x in order[i, :TOPK]]
        rec = {
            "row": i,
            "query": r["query"],
            "cos_top1": float(sims[i, topk[0]]),
            "cos_top2": float(sims[i, topk[1]]),
            "margin_12": float(sims[i, topk[0]] - sims[i, topk[1]]),
            "top1_target": targets[topk[0]]["target_id"],
            "top1_key": targets[topk[0]]["canonical_key"],
            "top1_construct": targets[topk[0]]["construct_key"],
            "top1_module": targets[topk[0]]["module"],
            "top1_stem": targets[topk[0]]["stem"],
            "top1_option": targets[topk[0]]["option"],
            "topk_keys": [targets[j]["canonical_key"] for j in topk],
            "topk_cos": [round(float(sims[i, j]), 6) for j in topk],
        }
        if negatives:
            rec["negative_id"] = r.get("id")
            rec["domain"] = r.get("domain")
        else:
            gid = by_key.get(r["key"])
            if gid is None:                  # gold excluded from the target set
                rec.update(gold_key=r["key"], gold_target=None, rank=None,
                           correct=None, unreachable=True)
                out_rows.append(rec)
                continue
            g = targets[gid - 1]
            rec.update(
                gold_key=r["key"], gold_target=gid,
                gold_construct=g["construct_key"], gold_module=g["module"],
                gold_stem=g["stem"], gold_option=g["option"],
                gold_fold_size=g["fold_size"],
                gold_folded=g["fold_size"] > 1,
                gold_multi_option=bool(g["siblings"]),
                gold_n_siblings=len(g["siblings"]),
                rank=int(rank_of[i, gid - 1]) + 1,
                cos_gold=float(sims[i, gid - 1]),
                correct=int(rank_of[i, gid - 1]) == 0,
                right_construct=targets[topk[0]]["construct_key"] == g["construct_key"],
                unreachable=False,
            )
        out_rows.append(rec)

    rep = {
        "schema": "compass_characterisation/1",
        "label": a.label or a.model,
        "model": a.model, "source": src,
        "revision": None if a.weights else cfg["rev"],
        "target_text": a.target_text,
        "pool": cfg["pool"], "q_prefix": cfg["q_prefix"], "d_prefix": cfg["d_prefix"],
        "padding_side": cfg["pad"], "dtype": "float32",
        "device": "cpu",
        "fixture": str(a.fixture), "fixture_schema": schema,
        "fixture_kind": "negative" if negatives else "positive",
        "dictionary_version_hash": T["dictionary_version_hash"],
        "n_targets": len(targets), "n_rows": len(rows),
        "embed_dim": int(D.shape[1]),
        "topk_recorded": TOPK,
        "cost": {"target_encode_s": round(encode_s, 1)},
        "rows": out_rows,
    }
    if not negatives:
        ok = [r for r in out_rows if not r["unreachable"]]
        rep["recall_at1"] = round(sum(r["correct"] for r in ok) / len(ok), 4)
        rep["n_rows_scored"] = len(ok)
        print(f"{rep['label']}  R@1 {rep['recall_at1']}  "
              f"({sum(r['correct'] for r in ok)}/{len(ok)})")
    else:
        print(f"{rep['label']}  {len(out_rows)} negative rows, no gold")
    a.out.write_text(json.dumps(rep, indent=1))
    if a.save_vectors:
        a.save_vectors.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"D": D, "dictionary_version_hash": T["dictionary_version_hash"],
                    "target_text": a.target_text, "model_source": src,
                    "device_computed_on": "cpu",
                    "target_ids": [t["target_id"] for t in targets]},
                   a.save_vectors)
    print(f"  encode {encode_s:.1f}s  dim {rep['embed_dim']}  -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
