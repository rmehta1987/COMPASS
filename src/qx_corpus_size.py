"""Task 4 (optional): corpus-size sensitivity of the shipped configuration.

    python src/qx_corpus_size.py --out out/qx_task4_corpus_size.json

A SENSITIVITY CURVE, NOT A BENCHMARK. Fewer distractors makes retrieval
mechanically easier, so R@1 rises as the corpus shrinks and that rise is an
artifact of the smaller pool. The curve's use is extrapolation: how much a new
module would cost.

Sampling is BY CONSTRUCT (construct_key): a construct's options are never split
across the boundary, so near-duplicate siblings stay together. The 56 gold
items' constructs are always retained -- the whole construct, options and all,
so within-construct confusions are preserved at every level. The remaining
constructs are sampled uniformly without replacement to make the pool up to
the requested fraction of all 1,066 constructs; 20 seeds per level.

Arm S (the shipped single query) is the curve asked for. Arm F (the registered
template) is scored on the same pools as a secondary line, because it costs
nothing and shows whether the expansion's effect depends on pool size.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from fusion_eval import encode_queries, load_deploy     # noqa: E402

LEVELS = (0.4, 0.6, 0.8, 1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--prereg", type=Path, default=Path("out/qx_preregistration.json"))
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    r = load_deploy(a.deploy.resolve())
    D = r.D.double()
    T = r.targets
    by_key = {m: t for t in T for m in t["members"]}
    rows = json.loads(a.fixture.read_text())["queries"]
    PR = json.loads(a.prereg.read_text())
    gold = torch.tensor([by_key[x["key"]]["target_id"] - 1 for x in rows])

    ck_of = [t["construct_key"] for t in T]
    constructs = sorted(set(ck_of))
    members = defaultdict(list)
    for i, ck in enumerate(ck_of):
        members[ck].append(i)
    gold_ck = sorted({ck_of[int(g)] for g in gold})
    others = [c for c in constructs if c not in set(gold_ck)]

    sims = {"S": encode_queries(r, [x["query"] for x in rows]).double() @ D.T,
            "F": encode_queries(r, [p["expanded_F"] for p in PR["positives"]]).double() @ D.T}

    def score(mask):
        out = {}
        for arm, S in sims.items():
            Sm = S.masked_fill(~mask, float("-inf"))
            g = Sm[torch.arange(len(rows)), gold]
            rank = (Sm > g[:, None]).sum(dim=1) + 1
            out[arm] = {"R@1": float((rank == 1).double().mean()),
                        "R@5": float((rank <= 5).double().mean()),
                        "R@10": float((rank <= 10).double().mean())}
        return out

    curve = []
    for lvl in LEVELS:
        n_want = round(lvl * len(constructs))
        n_extra = max(0, n_want - len(gold_ck))
        per_seed = []
        for seed in range(a.seeds if lvl < 1.0 else 1):
            rng = random.Random(20260903 + seed)
            pick = set(gold_ck) | set(rng.sample(others, n_extra))
            mask = torch.zeros(len(T), dtype=torch.bool)
            for c in pick:
                mask[members[c]] = True
            sc = score(mask)
            per_seed.append({"seed": seed, "n_constructs": len(pick),
                             "n_targets": int(mask.sum()), **sc})
        agg = {"fraction_of_constructs": lvl, "n_constructs": n_want,
               "n_seeds": len(per_seed),
               "n_targets_mean": round(st.mean(p["n_targets"] for p in per_seed), 1)}
        for arm in ("S", "F"):
            for k in ("R@1", "R@5", "R@10"):
                v = [p[arm][k] for p in per_seed]
                agg[f"{arm}_{k}"] = {"mean": round(st.mean(v), 4),
                                     "sd": round(st.pstdev(v), 4) if len(v) > 1 else 0.0,
                                     "min": round(min(v), 4), "max": round(max(v), 4)}
        agg["per_seed"] = per_seed
        curve.append(agg)

    full = curve[-1]
    if round(full["S_R@1"]["mean"], 3) != 0.567:
        raise SystemExit(f"100% pool does not reproduce 0.567: {full['S_R@1']}")

    # slope per 100 targets, S arm, from the 40% and 100% points
    def slope(k):
        x0, x1 = curve[0]["n_targets_mean"], curve[-1]["n_targets_mean"]
        y0, y1 = curve[0][f"S_{k}"]["mean"], curve[-1][f"S_{k}"]["mean"]
        return round((y1 - y0) / (x1 - x0) * 100, 4)

    rep = {
        "schema": "compass_corpus_size_sensitivity/1",
        "read_this_first": ("A sensitivity curve, not a benchmark. R@1 rises as the pool "
                            "shrinks because there are fewer distractors; the number at "
                            "40% is not a result about the model. Use: extrapolate the "
                            "cost of adding a module."),
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "sampling": ("by construct_key, options never split; the 56 gold items' "
                     f"constructs ({len(gold_ck)} distinct) always retained whole; "
                     "remaining constructs sampled uniformly without replacement; "
                     f"{a.seeds} seeds per level below 100%"),
        "n_constructs_total": len(constructs), "n_targets_total": len(T),
        "n_gold_constructs_always_kept": len(gold_ck),
        "curve": curve,
        "linear_slope_S_per_100_targets_40_to_100pct": {k: slope(k) for k in ("R@1", "R@5", "R@10")},
    }
    a.out.write_text(json.dumps(rep, indent=1))
    print(f"{'frac':>5}{'ncon':>6}{'ntgt':>8}{'S R@1':>16}{'S R@5':>9}{'S R@10':>9}"
          f"{'F R@1':>16}{'F R@10':>9}")
    for c in curve:
        print(f"{c['fraction_of_constructs']:>5}{c['n_constructs']:>6}{c['n_targets_mean']:>8}"
              f"{c['S_R@1']['mean']:>8} ±{c['S_R@1']['sd']:<6}{c['S_R@5']['mean']:>9}"
              f"{c['S_R@10']['mean']:>9}{c['F_R@1']['mean']:>8} ±{c['F_R@1']['sd']:<6}"
              f"{c['F_R@10']['mean']:>9}")
    print(f"slope S per +100 targets: {rep['linear_slope_S_per_100_targets_40_to_100pct']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
