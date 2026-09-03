"""Tasks 1-3 of the characterisation brief, as three committed JSON artifacts.

  task 1  per-item phrasing consistency: of each gold item's 4 phrasings, how
          many land at rank 1. The aggregate R@1 cannot distinguish a model that
          is reliable on some items and blind on others from one that is a coin
          flip on every item; these are different products.
  task 2  top-1 cosine on the held-out negative set against the same statistic
          on the 224 real rows. If they separate there is an abstention
          threshold; if they overlap the model is confidently wrong on requests
          for data that does not exist.
  task 3  calibration: cosine and top1-minus-top2 margin against correctness,
          the precision/recall curve as a threshold sweeps, the F1-maximising
          threshold, and the threshold at which precision reaches 0.90.

Inputs are the artifacts written by src/char_encode.py, never re-encoded here.

    python src/char_report.py --outdir out
"""
from __future__ import annotations

import argparse, json, statistics as st
from collections import Counter, defaultdict
from pathlib import Path

POS_FT = "char_pos_bge-small_ft.json"
POS_FZ = "char_pos_bge-small_frozen.json"
NEG_FT = "char_neg_bge-small_ft.json"
NEG_FZ = "char_neg_bge-small_frozen.json"


def pct(xs, q):
    """Nearest-rank percentile, same convention as compass_score.subset_stats."""
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 4)


def _binom_ref(p, n_items, trials=4):
    """Expected item counts if each phrasing succeeded independently at rate p."""
    from math import comb
    return {f"{k}_of_4": round(n_items * comb(trials, k) * p ** k * (1 - p) ** (trials - k), 1)
            for k in range(trials + 1)}


def dist(xs):
    return {"n": len(xs), "p10": pct(xs, 0.10), "p50": pct(xs, 0.50),
            "p90": pct(xs, 0.90),
            "min": round(min(xs), 4) if xs else None,
            "max": round(max(xs), 4) if xs else None,
            "mean": round(st.fmean(xs), 4) if xs else None}


# ------------------------------------------------------------------- task 1

def task1(ft, fz):
    out = {"schema": "char_phrasing_consistency/1",
           "question": "of each gold item's 4 phrasings, how many are retrieved at rank 1",
           "n_items": None, "models": {}}
    per_model = {}
    for name, rep in (("bge-small_frozen", fz), ("bge-small_ft", ft)):
        g = defaultdict(list)
        for r in rep["rows"]:
            g[r["gold_key"]].append(r)
        scores = {k: sum(1 for r in v if r["correct"]) for k, v in g.items()}
        for k, v in g.items():
            assert len(v) == 4, f"{k} has {len(v)} phrasings, expected 4"
        hist = Counter(scores.values())
        n = len(scores)
        out["n_items"] = n
        per_model[name] = scores
        out["models"][name] = {
            "recall_at1": rep["recall_at1"],
            "rank1_hits": sum(scores.values()),
            "n_rows": rep["n_rows_scored"],
            "histogram": {f"{s}_of_4": hist[s] for s in range(5)},
            "histogram_frac": {f"{s}_of_4": round(hist[s] / n, 3) for s in range(5)},
            "items_at_least_3_of_4": hist[3] + hist[4],
            "items_at_most_1_of_4": hist[0] + hist[1],
            # a coin-flip model would concentrate mass in the middle; a reliable
            # model with enumerable blind spots pushes mass to both ends
            "mass_at_extremes_0_or_4": round((hist[0] + hist[4]) / n, 3),
            # reference shape: if every phrasing succeeded independently with
            # probability = the model's own R@1, the histogram would be
            # Binomial(4, R@1). Observed mass ABOVE this at 0/4 and 4/4 and
            # BELOW it at 2/4 means outcomes cluster by ITEM -- the model is
            # reliable on some items and blind on others rather than a coin
            # flip on every query.
            "binomial_reference": _binom_ref(rep["recall_at1"], n),
            "excess_over_binomial": {
                f"{s}_of_4": round(hist[s] - _binom_ref(rep["recall_at1"], n)[f"{s}_of_4"], 1)
                for s in range(5)},
        }
    fzs, fts = per_model["bge-small_frozen"], per_model["bge-small_ft"]
    trans = Counter((fzs[k], fts[k]) for k in fzs)
    out["transition_frozen_to_ft"] = {
        f"fz{a}_ft{b}": trans[(a, b)] for a in range(5) for b in range(5)
        if trans[(a, b)]}
    out["items_improved"] = sum(1 for k in fzs if fts[k] > fzs[k])
    out["items_unchanged"] = sum(1 for k in fzs if fts[k] == fzs[k])
    out["items_regressed"] = sum(1 for k in fzs if fts[k] < fzs[k])
    return out, per_model


def blind_spots(ft, scores_ft, scores_fz, targets):
    """The 0/4 and 1/4 items: gold key, one phrasing, and what won instead."""
    g = defaultdict(list)
    for r in ft["rows"]:
        g[r["gold_key"]].append(r)
    rows = []
    for k, s in sorted(scores_ft.items(), key=lambda kv: (kv[1], kv[0])):
        if s > 1:
            continue
        rs = g[k]
        ex = next((r for r in rs if not r["correct"]), rs[0])
        rows.append({
            "gold_key": k, "phrasings_at_rank1": s,
            "frozen_phrasings_at_rank1": scores_fz[k],
            "gold_module": rs[0]["gold_module"],
            "gold_stem": rs[0]["gold_stem"],
            "gold_option": rs[0]["gold_option"],
            "gold_fold_size": rs[0]["gold_fold_size"],
            "gold_n_siblings": rs[0]["gold_n_siblings"],
            "best_rank_over_4_phrasings": min(r["rank"] for r in rs),
            "worst_rank_over_4_phrasings": max(r["rank"] for r in rs),
            "example_phrasing": ex["query"],
            "example_rank": ex["rank"],
            "example_top1_key": ex["top1_key"],
            "example_top1_stem": ex["top1_stem"],
            "example_top1_option": ex["top1_option"],
            "example_top1_same_construct": ex["right_construct"],
        })
    return rows


# ------------------------------------------------------------------- task 2

def task2(pos, neg, label):
    P = [r for r in pos["rows"] if not r["unreachable"]]
    N = neg["rows"]
    pc = [r["cos_top1"] for r in P]
    nc = [r["cos_top1"] for r in N]
    pm = [r["margin_12"] for r in P]
    nm = [r["margin_12"] for r in N]

    def sep(a, b):
        """P(random positive scores above random negative), ties at 0.5 = AUROC."""
        if not a or not b:
            return None
        wins = sum((x > y) + 0.5 * (x == y) for x in a for y in b)
        return round(wins / (len(a) * len(b)), 4)

    by = {}
    for field, key in (("adjacency", "adjacency"), ("register", "register"),
                       ("domain", "domain")):
        grp = defaultdict(list)
        for r in N:
            grp[r.get(key) or "?"].append(r["cos_top1"])
        by[field] = {k: dist(v) for k, v in sorted(grp.items())}
    # adjacency/register live in the fixture, not the encode artifact; join them
    return {
        "schema": "char_negative_separation/1",
        "label": label,
        "n_positive_rows": len(P), "n_negative_rows": len(N),
        "cos_top1": {"positives_all": dist(pc),
                     "positives_correct": dist([r["cos_top1"] for r in P if r["correct"]]),
                     "positives_incorrect": dist([r["cos_top1"] for r in P if not r["correct"]]),
                     "negatives_all": dist(nc)},
        "margin_12": {"positives_all": dist(pm),
                      "positives_correct": dist([r["margin_12"] for r in P if r["correct"]]),
                      "positives_incorrect": dist([r["margin_12"] for r in P if not r["correct"]]),
                      "negatives_all": dist(nm)},
        "separation_auroc": {
            "cos_top1_positives_all_vs_negatives": sep(pc, nc),
            "cos_top1_positives_correct_vs_negatives": sep([r["cos_top1"] for r in P if r["correct"]], nc),
            "margin_12_positives_all_vs_negatives": sep(pm, nm),
            "margin_12_positives_correct_vs_negatives": sep([r["margin_12"] for r in P if r["correct"]], nm),
        },
        "overlap_cos_top1": {
            "negatives_above_positive_p10": sum(1 for x in nc if x > pct(pc, 0.10)),
            "negatives_above_positive_p50": sum(1 for x in nc if x > pct(pc, 0.50)),
            "negatives_above_positive_max": sum(1 for x in nc if x > max(pc)),
            "positive_correct_below_negative_p90": sum(
                1 for r in P if r["correct"] and r["cos_top1"] < pct(nc, 0.90)),
            "positive_correct_below_negative_max": sum(
                1 for r in P if r["correct"] and r["cos_top1"] < max(nc)),
            "range_positives": [round(min(pc), 4), round(max(pc), 4)],
            "range_negatives": [round(min(nc), 4), round(max(nc), 4)],
        },
        "negatives_cos_top1_by": by,
        "negatives_highest_cos": sorted(
            [{"id": r.get("negative_id"), "domain": r.get("domain"),
              "query": r["query"], "cos_top1": round(r["cos_top1"], 4),
              "margin_12": round(r["margin_12"], 4),
              "top1_key": r["top1_key"], "top1_stem": r["top1_stem"],
              "top1_option": r["top1_option"]} for r in N],
            key=lambda d: -d["cos_top1"])[:10],
    }


# ------------------------------------------------------------------- task 3

def sweep(P, N, field):
    """Threshold sweep over the observed score range.

    A row is ANSWERED when score >= tau. Precision = correct / answered.
    Recall = correct / all 224 positives (coverage-weighted accuracy, so
    abstaining costs recall). Negative rejection = fraction of the held-out
    negatives that fall below tau, i.e. correctly abstained on.
    """
    total = len(P)
    cand = sorted({round(r[field], 6) for r in P} | {round(r[field], 6) for r in N})
    pts = []
    for tau in cand:
        ans = [r for r in P if r[field] >= tau]
        cor = sum(1 for r in ans if r["correct"])
        prec = cor / len(ans) if ans else None
        rec = cor / total
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
        rej = sum(1 for r in N if r[field] < tau) / len(N) if N else None
        pts.append({"tau": tau, "n_answered": len(ans),
                    "coverage": round(len(ans) / total, 4),
                    "precision": round(prec, 4) if prec is not None else None,
                    "recall": round(rec, 4), "f1": round(f1, 4),
                    "negatives_rejected": round(rej, 4) if rej is not None else None})
    best_f1 = max(pts, key=lambda p: p["f1"])
    # lowest tau (=> highest recall) that still reaches precision 0.90
    p90 = [p for p in pts if p["precision"] is not None and p["precision"] >= 0.90
           and p["n_answered"] >= 10]
    at_p90 = min(p90, key=lambda p: p["tau"]) if p90 else None
    # lowest tau that rejects every negative
    allrej = [p for p in pts if p["negatives_rejected"] == 1.0]
    at_allrej = min(allrej, key=lambda p: p["tau"]) if allrej else None
    return {
        "field": field, "n_thresholds": len(pts),
        "no_threshold_baseline": {"coverage": 1.0,
                                  "precision": round(sum(r["correct"] for r in P) / total, 4),
                                  "recall": round(sum(r["correct"] for r in P) / total, 4)},
        "max_f1": best_f1,
        "at_precision_0.90": at_p90,
        "at_all_negatives_rejected": at_allrej,
        "curve": pts,
    }


def task3(pos, neg, label):
    P = [r for r in pos["rows"] if not r["unreachable"]]
    N = neg["rows"]
    return {
        "schema": "char_calibration/1", "label": label,
        "n_positive_rows": len(P), "n_negative_rows": len(N),
        "cos_top1_by_correctness": {
            "correct": dist([r["cos_top1"] for r in P if r["correct"]]),
            "incorrect": dist([r["cos_top1"] for r in P if not r["correct"]]),
        },
        "margin_12_by_correctness": {
            "correct": dist([r["margin_12"] for r in P if r["correct"]]),
            "incorrect": dist([r["margin_12"] for r in P if not r["correct"]]),
        },
        "separation_auroc_correct_vs_incorrect": {
            "cos_top1": _auroc([r["cos_top1"] for r in P if r["correct"]],
                               [r["cos_top1"] for r in P if not r["correct"]]),
            "margin_12": _auroc([r["margin_12"] for r in P if r["correct"]],
                                [r["margin_12"] for r in P if not r["correct"]]),
        },
        "sweep_cos_top1": sweep(P, N, "cos_top1"),
        "sweep_margin_12": sweep(P, N, "margin_12"),
    }


def _auroc(a, b):
    if not a or not b:
        return None
    return round(sum((x > y) + 0.5 * (x == y) for x in a for y in b) / (len(a) * len(b)), 4)


# ---------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", type=Path, default=Path("out"))
    ap.add_argument("--targets", type=Path, default=Path("out/targets_full.json"))
    ap.add_argument("--negatives-fixture", type=Path,
                    default=Path("fixtures/negative_requests.json"))
    a = ap.parse_args()
    L = lambda n: json.loads((a.outdir / n).read_text())
    ft, fz, nft, nfz = L(POS_FT), L(POS_FZ), L(NEG_FT), L(NEG_FZ)

    # join the fixture's adjacency/register labels onto the encode artifacts
    meta = {r["id"]: r for r in json.loads(a.negatives_fixture.read_text())["queries"]}
    for rep in (nft, nfz):
        for r in rep["rows"]:
            m = meta[r["negative_id"]]
            r["adjacency"], r["register"] = m["adjacency"], m["register"]

    targets = json.loads(a.targets.read_text())["targets"]

    t1, per = task1(ft, fz)
    t1["blind_spots_fine_tuned"] = blind_spots(
        ft, per["bge-small_ft"], per["bge-small_frozen"], targets)
    (a.outdir / "char_task1_phrasing.json").write_text(json.dumps(t1, indent=1))

    t2 = {"schema": "char_negative_separation_pair/1",
          "negative_fixture": str(a.negatives_fixture),
          "bge-small_ft": task2(ft, nft, "bge-small_ft"),
          "bge-small_frozen": task2(fz, nfz, "bge-small_frozen")}
    (a.outdir / "char_task2_negatives.json").write_text(json.dumps(t2, indent=1))

    t3 = {"schema": "char_calibration_pair/1",
          "bge-small_ft": task3(ft, nft, "bge-small_ft"),
          "bge-small_frozen": task3(fz, nfz, "bge-small_frozen")}
    (a.outdir / "char_task3_calibration.json").write_text(json.dumps(t3, indent=1))

    # ---- console summary
    print("=== TASK 1  per-item phrasing consistency (n_items="
          f"{t1['n_items']}) ===")
    print(f"{'phrasings@1':>12s} {'frozen':>14s} {'fine-tuned':>14s}")
    for s in range(5):
        k = f"{s}_of_4"
        f_, t_ = t1["models"]["bge-small_frozen"], t1["models"]["bge-small_ft"]
        print(f"{s:>10d}/4 {f_['histogram'][k]:8d} items {t_['histogram'][k]:8d} items")
    for n in ("bge-small_frozen", "bge-small_ft"):
        m = t1["models"][n]
        print(f"  {n:20s} R@1 {m['recall_at1']}  >=3/4: {m['items_at_least_3_of_4']}"
              f"  <=1/4: {m['items_at_most_1_of_4']}")
    print(f"  items improved/unchanged/regressed: {t1['items_improved']}/"
          f"{t1['items_unchanged']}/{t1['items_regressed']}")

    for name in ("bge-small_ft", "bge-small_frozen"):
        print(f"\n=== TASK 2  negative separation -- {name} ===")
        d = t2[name]
        for f in ("cos_top1", "margin_12"):
            print(f"  {f}")
            for k in ("positives_all", "positives_correct", "positives_incorrect",
                      "negatives_all"):
                x = d[f][k]
                print(f"    {k:22s} n={x['n']:3d}  p10 {x['p10']}  p50 {x['p50']}  p90 {x['p90']}")
        print(f"  AUROC cos pos-all vs neg   "
              f"{d['separation_auroc']['cos_top1_positives_all_vs_negatives']}")
        print(f"  AUROC cos pos-correct vs neg "
              f"{d['separation_auroc']['cos_top1_positives_correct_vs_negatives']}")
        o = d["overlap_cos_top1"]
        print(f"  overlap: {o['negatives_above_positive_p50']}/{d['n_negative_rows']} "
              f"negatives score above positive p50; "
              f"{o['positive_correct_below_negative_p90']} correct positives below negative p90")
        print(f"  ranges: positives {o['range_positives']}  negatives {o['range_negatives']}")

        print(f"\n=== TASK 3  calibration -- {name} ===")
        c = t3[name]
        print(f"  AUROC correct-vs-incorrect: cos {c['separation_auroc_correct_vs_incorrect']['cos_top1']}"
              f"   margin {c['separation_auroc_correct_vs_incorrect']['margin_12']}")
        for f in ("sweep_cos_top1", "sweep_margin_12"):
            s = c[f]
            print(f"  {f}")
            b = s["no_threshold_baseline"]
            print(f"    no threshold      cov {b['coverage']}  prec {b['precision']}  rec {b['recall']}")
            m = s["max_f1"]
            print(f"    max F1  tau={m['tau']:.4f}  cov {m['coverage']}  prec {m['precision']}"
                  f"  rec {m['recall']}  F1 {m['f1']}  neg-rej {m['negatives_rejected']}")
            p = s["at_precision_0.90"]
            print(f"    prec>=0.90        " + (f"tau={p['tau']:.4f}  cov {p['coverage']}  "
                  f"prec {p['precision']}  rec {p['recall']}  neg-rej {p['negatives_rejected']}"
                  if p else "UNREACHABLE at n_answered>=10"))
            r = s["at_all_negatives_rejected"]
            print(f"    all neg rejected  " + (f"tau={r['tau']:.4f}  cov {r['coverage']}  "
                  f"prec {r['precision']}  rec {r['recall']}" if r else "UNREACHABLE"))
    print("\n-> out/char_task1_phrasing.json  out/char_task2_negatives.json  "
          "out/char_task3_calibration.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
