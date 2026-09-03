"""Task 2: leave-one-out phrasing fusion, measured on the existing fixture.

The 224-row fixture holds 56 gold items x 4 phrasings. Treat the other three
phrasings of an item as if a query rewriter had produced them: encode all four,
retrieve against the same 1,353 frozen target vectors, fuse the four result
lists, and score against the unchanged gold rule on the unchanged 224-row
denominator.

Everything is driven through the SHIPPED deploy/ bundle -- its checksum and
dictionary-hash guards run on load, its frozen CPU-computed vectors are the
document side, and its tokeniser / CLS pooling / query prefix / fp32 / max-len
are read from its manifest. Nothing here re-declares a convention, and the
`single` control must reproduce R@1 0.567 or the script refuses to continue.

    python src/fusion_eval.py --out out/fusion_task2_rules.json

WHAT THIS MEASURES, AND WHAT IT DOES NOT
----------------------------------------
1. All four phrasings of an item produce the SAME fused ranking, so all four of
   its rows share one outcome. The 224-row denominator is 56 items counted four
   times each: the effective sample is 56, not 224. Wilson intervals below are
   computed on n=56 for that reason, and the per-item k/4 histogram collapses to
   {0/4, 4/4} by construction -- see `fused_histogram_is_degenerate`.
2. The fixture's four phrasings were each generated INDEPENDENTLY FROM THE GOLD
   WORDING. A real rewriter sees only the user's query. So each sibling phrasing
   carries information about the gold that a rewriter could not have, and every
   number here is an OPTIMISTIC ceiling for task 4, not a forecast of it.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))

RRF_K = 60


# ------------------------------------------------------------------ fusion rules

def fuse(sims: torch.Tensor, rule: str, own: int) -> torch.Tensor:
    """sims: (n_phrasings, n_targets) float64 cosine matrix for ONE item.

    Returns a (n_targets,) score vector, higher = better, whose descending
    argsort is the fused ranking.
    """
    if rule == "single":
        return sims[own].clone()
    if rule == "max_cos":
        return sims.max(dim=0).values
    if rule == "mean_cos":
        return sims.mean(dim=0)

    # rank-based rules: rank 1 = best, per phrasing
    order = sims.argsort(dim=-1, descending=True)
    ranks = order.argsort(dim=-1).double() + 1.0            # (n_phrasings, n_targets)

    if rule == "rrf":
        return (1.0 / (RRF_K + ranks)).sum(dim=0)
    if rule == "min_rank":
        # primary key: best rank across phrasings. tie-break: highest cosine.
        # Encoded as a single descending score so one argsort does both:
        #   score = -min_rank + (max_cos + 1) / 4   in [-1353.0, -0.5]
        # max_cos+1 is in [0, 2] so the tie-break term is in [0, 0.5) and can
        # never bridge a whole rank. float64 resolves 1e-9 at this magnitude.
        return -ranks.min(dim=0).values + (sims.max(dim=0).values + 1.0) / 4.0
    if rule == "oracle_best_phrasing":
        # Not a deployable rule. Ceiling only: the best single phrasing, chosen
        # with knowledge of the gold. Implemented as min_rank with the tie-break
        # decided in gold's favour -- handled by the caller, which passes the
        # gold id; here we return min_rank with no tie-break.
        return -ranks.min(dim=0).values
    raise ValueError(rule)


def rank_of(score: torch.Tensor, gold_idx: int) -> int:
    order = score.argsort(descending=True)
    return int((order == gold_idx).nonzero()[0, 0]) + 1


# ---------------------------------------------------------------- small helpers

def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def rank_stats(ranks):
    if not ranks:
        return {"n": 0}
    s = sorted(ranks)
    n = len(s)
    return {
        "n": n,
        "R@1": round(sum(r <= 1 for r in s) / n, 4),
        "R@5": round(sum(r <= 5 for r in s) / n, 4),
        "R@10": round(sum(r <= 10 for r in s) / n, 4),
        "rank_p50": s[int(0.5 * (n - 1))],
        "rank_p90": s[min(n - 1, int(0.9 * n))],
        "rank_max": s[-1],
        "rank_mean": round(sum(s) / n, 2),
    }


def load_deploy(root: Path):
    """Load the shipped bundle with ALL guards on. Returns (retriever, targets, D)."""
    sys.path.insert(0, str(root))
    from retriever import CompassRetriever          # noqa: E402
    r = CompassRetriever(root, verify_checksums=True)
    return r


@torch.no_grad()
def encode_queries(r, texts, batch=64):
    out = []
    for i in range(0, len(texts), batch):
        out.append(r.encode_queries(texts[i:i + batch]))
    return torch.cat(out)


def domain_of(target, keywords):
    stem = (target.get("stem") or "").lower()
    for name, pat in keywords:
        if re.search(pat, stem):
            return name
    return "unclassified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--pos", type=Path,
                    default=Path("out/char_pos_bge-small_ft.json"),
                    help="committed single-query artifact, used as a parity check")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--save-sims", type=Path, default=None,
                    help="write the 224 x 1353 cosine matrix for task 3 / task 4")
    a = ap.parse_args()

    from char_strata import DOMAIN_KEYWORDS

    r = load_deploy(a.deploy.resolve())
    targets = r.targets
    D = r.D.double()
    by_key = {m: t["target_id"] for t in targets for m in t["members"]}

    fx = json.loads(a.fixture.read_text())
    rows = fx["queries"]

    t0 = time.time()
    Q = encode_queries(r, [x["query"] for x in rows]).double()
    encode_s = time.time() - t0
    sims_all = Q @ D.T                                     # (224, 1353)

    # ---- parity: the single-query control must reproduce the committed artifact
    prev = json.loads(a.pos.read_text())["rows"]
    order = sims_all.argsort(dim=-1, descending=True)
    rank_all = order.argsort(dim=-1)
    single_rank, mismatch = [], 0
    for i, row in enumerate(rows):
        gid = by_key[row["key"]]
        rk = int(rank_all[i, gid - 1]) + 1
        single_rank.append(rk)
        if rk != prev[i]["rank"]:
            mismatch += 1
    single_r1 = sum(x == 1 for x in single_rank) / len(single_rank)
    parity = {
        "single_query_R@1_from_deploy_bundle": round(single_r1, 4),
        "committed_artifact_R@1": json.loads(a.pos.read_text())["recall_at1"],
        "rows_with_differing_rank": mismatch,
        "max_abs_cos_delta_vs_artifact": round(max(
            abs(float(sims_all[i, by_key[rows[i]['key']] - 1]) - prev[i]["cos_gold"])
            for i in range(len(rows))), 9),
    }
    if abs(single_r1 - 0.567) > 0.0045 or mismatch:
        raise SystemExit(
            f"PARITY FAILED: single-query control gives R@1 {single_r1:.4f} with "
            f"{mismatch} rank mismatches against {a.pos}. The brief's decision rule "
            f"says stop here -- every fusion number would be measured against a "
            f"control that is not the shipped system.")

    # ---- group rows into items, preserving fixture order
    item_rows = defaultdict(list)
    for i, row in enumerate(rows):
        item_rows[row["key"]].append(i)
    items = list(item_rows.items())
    if any(len(v) != 4 for _, v in items):
        raise SystemExit("not every item has exactly 4 phrasings")

    RULES = ["single", "max_cos", "min_rank", "mean_cos", "rrf"]
    per_row = {rule: [0] * len(rows) for rule in RULES}
    per_item_out = []

    for key, idxs in items:
        gid = by_key[key]
        S = sims_all[idxs]                                  # (4, 1353)
        rec = {"gold_key": key, "gold_target": gid,
               "single_ranks": [single_rank[i] for i in idxs],
               "single_k_at1": sum(single_rank[i] == 1 for i in idxs)}
        for rule in RULES:
            if rule == "single":
                for i in idxs:
                    per_row[rule][i] = single_rank[i]
                rec["rank_single"] = min(single_rank[i] for i in idxs)
                continue
            score = fuse(S, rule, own=0)
            rk = rank_of(score, gid - 1)
            for i in idxs:
                per_row[rule][i] = rk
            rec[f"rank_{rule}"] = rk
        # the oracle: does ANY phrasing put gold at rank 1
        rec["oracle_hit"] = int(any(single_rank[i] == 1 for i in idxs))
        per_item_out.append(rec)

    n_items = len(items)
    oracle_hits = sum(x["oracle_hit"] for x in per_item_out)
    oracle_r1 = oracle_hits / n_items

    results = {}
    for rule in RULES:
        st = rank_stats(per_row[rule])
        # item-level view: for every fused rule all 4 rows share an outcome
        item_ranks = ([x[f"rank_{rule}"] for x in per_item_out] if rule != "single"
                      else None)
        st["item_level"] = (rank_stats(item_ranks) if item_ranks else
                            {"n": n_items,
                             "R@1_items_with_all_4_correct": round(
                                 sum(1 for x in per_item_out
                                     if x["single_k_at1"] == 4) / n_items, 4)})
        k = sum(1 for x in per_row[rule] if x == 1)
        st["wilson95_R@1_on_n56_items"] = (
            wilson(sum(1 for x in item_ranks if x == 1), n_items) if item_ranks
            else wilson(round(k / 4), n_items))
        st["recovery_fraction_of_oracle_gap"] = round(
            (st["R@1"] - single_r1) / (oracle_r1 - single_r1), 4)
        results[rule] = st

    results["oracle_best_phrasing_per_item"] = {
        "n": len(rows), "R@1": round(oracle_r1, 4),
        "note": ("CEILING, not a rule. Counts an item correct when ANY of its 4 "
                 "phrasings puts gold at rank 1. Equals min_rank fusion with the "
                 "rank-1 tie always broken in gold's favour."),
        "items_hit": oracle_hits, "n_items": n_items,
        "wilson95_R@1_on_n56_items": wilson(oracle_hits, n_items),
        "recovery_fraction_of_oracle_gap": 1.0,
    }

    best_rule = max((x for x in RULES if x != "single"),
                    key=lambda x: results[x]["R@1"])

    # ---- did mass move, or did partial items become differently partial?
    single_hist = Counter(x["single_k_at1"] for x in per_item_out)
    transition = []
    for k in range(5):
        grp = [x for x in per_item_out if x["single_k_at1"] == k]
        transition.append({
            "single_k_at1": k, "n_items": len(grp),
            "now_correct_under_" + best_rule: sum(
                1 for x in grp if x[f"rank_{best_rule}"] == 1),
            "now_rank<=10": sum(1 for x in grp if x[f"rank_{best_rule}"] <= 10),
            "rank_p50": (sorted(x[f"rank_{best_rule}"] for x in grp)[len(grp) // 2]
                         if grp else None),
        })

    zero_of_four = [
        {"gold_key": x["gold_key"], "single_ranks": x["single_ranks"],
         **{f"rank_{ru}": x[f"rank_{ru}"] for ru in RULES if ru != "single"}}
        for x in per_item_out if x["single_k_at1"] == 0]

    # ---- strata, using the committed classifier
    by_id = {t["target_id"]: t for t in targets}
    dom = {}
    for i, row in enumerate(rows):
        dom.setdefault(domain_of(by_id[by_key[row["key"]]], DOMAIN_KEYWORDS),
                       []).append(i)
    strata = {}
    for name, idxs in sorted(dom.items()):
        strata[name] = {"n_rows": len(idxs),
                        "n_items": len({rows[i]["key"] for i in idxs})}
        for rule in RULES:
            rs = [per_row[rule][i] for i in idxs]
            strata[name][rule] = {"R@1": round(sum(x == 1 for x in rs) / len(rs), 4),
                                  "R@10": round(sum(x <= 10 for x in rs) / len(rs), 4)}
        oi = [x for x in per_item_out
              if any(rows[i]["key"] == x["gold_key"] for i in idxs)]
        strata[name]["oracle_R@1"] = round(
            sum(y["oracle_hit"] for y in oi) / len(oi), 4) if oi else None

    decision = ("BUILD the rewriter (task 4)" if results[best_rule]["R@1"] >= 0.70
                else "DO NOT build the rewriter (task 4)"
                if results[best_rule]["R@1"] <= 0.63 else
                "AMBIGUOUS: between the brief's two thresholds (0.63 / 0.70)")

    rep = {
        "schema": "compass_phrasing_fusion/1",
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "deploy_manifest_hash": r.manifest["dictionary_version_hash"],
        "deploy_guards": "checksums + dictionary hash + row-order verified at load",
        "dtype": "float32 model load (deploy manifest); fp64 for the cosine algebra",
        "n_rows": len(rows), "n_items": n_items,
        "n_targets": len(targets),
        "parity_check": parity,
        "effective_sample_size_note": (
            "Every fused rule scores all 4 phrasings of an item identically, so "
            "the 224-row denominator is 56 items counted 4x. R@1 on 224 rows "
            "equals the fraction of the 56 items retrieved. Wilson intervals are "
            "computed on n=56."),
        "ceiling_is_optimistic_note": (
            "The 3 sibling phrasings were generated independently FROM THE GOLD "
            "WORDING (retrieval_queries.json::generator). A rewriter at inference "
            "sees only the query. These numbers bound task 4 from above."),
        "rrf_k": RRF_K,
        "rules": results,
        "best_deployable_rule": best_rule,
        "decision_rule_recorded_before_running": (
            "<0.63 => fusion does not exploit the disjointness, do not build the "
            "rewriter. >0.70 => build it. Between => ambiguous."),
        "decision": decision,
        "fused_histogram_is_degenerate": {
            "single_query_k_at1_histogram": dict(sorted(single_hist.items())),
            "why": ("Under any fused rule an item's 4 rows share one ranking, so "
                    "its k/4 can only be 0 or 4. The informative version is the "
                    "transition table below: which single-query buckets the fused "
                    "rule rescues."),
            "fused_k_at1_histogram": {
                "0": n_items - sum(1 for x in per_item_out
                                   if x[f"rank_{best_rule}"] == 1),
                "4": sum(1 for x in per_item_out if x[f"rank_{best_rule}"] == 1)},
            "transition_from_single_bucket": transition,
        },
        "items_at_0_of_4_under_single": zero_of_four,
        "strata": strata,
        "cost": {"query_encode_s_224_rows": round(encode_s, 2),
                 "ms_per_query_single": round(encode_s / len(rows) * 1000, 2),
                 "ms_per_query_4_phrasings_encode_only": round(
                     encode_s / len(rows) * 4000, 2)},
        "per_item": per_item_out,
        "per_row_rank": {rule: per_row[rule] for rule in RULES},
    }
    a.out.write_text(json.dumps(rep, indent=1))
    if a.save_sims:
        torch.save({"sims": sims_all.float(), "keys": [x["key"] for x in rows],
                    "queries": [x["query"] for x in rows]}, a.save_sims)

    print(f"parity: single R@1 {parity['single_query_R@1_from_deploy_bundle']} "
          f"vs artifact {parity['committed_artifact_R@1']}, "
          f"{parity['rows_with_differing_rank']} rank mismatches, "
          f"max |dcos| {parity['max_abs_cos_delta_vs_artifact']:.2e}")
    print(f"\n{'rule':<12} {'R@1':>7} {'R@5':>7} {'R@10':>7} "
          f"{'p50':>5} {'p90':>5} {'max':>5}  {'recovery':>9}")
    for rule in RULES + ["oracle_best_phrasing_per_item"]:
        s = results[rule]
        print(f"{rule:<12} {s['R@1']:>7} {s.get('R@5','-'):>7} "
              f"{s.get('R@10','-'):>7} {s.get('rank_p50','-'):>5} "
              f"{s.get('rank_p90','-'):>5} {s.get('rank_max','-'):>5}  "
              f"{s['recovery_fraction_of_oracle_gap']:>9}")
    print(f"\nbest deployable rule: {best_rule}   decision: {decision}")
    print("\ntransition from single-query k/4 bucket:")
    for t in transition:
        print(f"  {t['single_k_at1']}/4  n={t['n_items']:<3} -> correct "
              f"{t['now_correct_under_' + best_rule]:<3} rank<=10 {t['now_rank<=10']:<3} "
              f"p50 {t['rank_p50']}")
    print("\nstrata (R@1 single -> best rule -> oracle):")
    for name, s in sorted(strata.items(), key=lambda kv: kv[1]["n_rows"], reverse=True):
        print(f"  {name:<22} n={s['n_rows']:<4} {s['single']['R@1']:>6} -> "
              f"{s[best_rule]['R@1']:>6} (R@10 {s[best_rule]['R@10']:>6}) "
              f"oracle {s['oracle_R@1']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
