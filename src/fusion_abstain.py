"""Task 3: what phrasing fusion does to the abstention mechanism.

deploy/ ships min_cos = 0.729476, which rejects 43 of 44 held-out negatives for
0.9 recall points at AUROC 0.982 (CHARACTERISATION.md sec 3). Under max_cos
fusion every score inflates -- four draws instead of one -- INCLUDING the
negatives. The threshold cannot survive unchanged and the separation may narrow.
This measures both.

Four configurations, because the comparison is only honest in the last one:

  A single_vs_single        1 draw each side. Must reproduce sec 3 exactly, or
                            nothing below is trustworthy.
  B fixture4_vs_neg1        4 fixture phrasings for positives, 1 query for the
                            negatives. This is the comparison the brief warns
                            about: four draws against one INFLATES the positive
                            side only, so it is optimistic about separation. It
                            is reported to size that optimism, not to be
                            believed.
  C fixture4_vs_negrw4      4 fixture phrasings vs query + 3 generated rewrites.
                            Draw counts match; the SOURCES still do not -- the
                            fixture phrasings were written from the gold wording,
                            the negative rewrites from the request.
  D rewrite4_vs_rewrite4    query + 3 generated rewrites on BOTH sides, from one
                            prompt that never knew which set a request came from.
                            This is the deployable configuration and the only
                            symmetric one. Its positive R@1 is also the honest
                            answer to task 4.

Two fusion rules are carried, because they fail in opposite directions:
max_cos (the task-2 winner; inflates every score) and mean_cos (does not
inflate, and had the best R@10 in task 2).

Thresholds are selected on POSITIVES ONLY -- candidate taus are drawn from the
positive scores alone, so the 44 negatives cannot influence the choice even
through the candidate grid. They report.

    python src/fusion_abstain.py --out out/fusion_task3_abstention.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from fusion_eval import encode_queries, load_deploy       # noqa: E402

SHIPPED_TAU = 0.729476


# ------------------------------------------------------------------ statistics

def auroc(pos, neg):
    """Mann-Whitney U with ties counted as half. No scipy in this venv."""
    if not pos or not neg:
        return None
    allv = sorted([(v, 0) for v in pos] + [(v, 1) for v in neg])
    ranks, i = {}, 0
    vals = [v for v, _ in allv]
    r = [0.0] * len(vals)
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[i]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[k] = avg
        i = j + 1
    rsum = sum(r[k] for k in range(len(allv)) if allv[k][1] == 0)
    n1, n2 = len(pos), len(neg)
    return round((rsum - n1 * (n1 + 1) / 2) / (n1 * n2), 4)


def pct(v, p):
    s = sorted(v)
    return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))], 4)


def dist(v):
    if not v:
        return {"n": 0}
    return {"n": len(v), "p10": pct(v, .10), "p50": pct(v, .50), "p90": pct(v, .90),
            "min": round(min(v), 4), "max": round(max(v), 4),
            "mean": round(sum(v) / len(v), 4)}


def sweep(pos_scores, pos_correct, neg_scores):
    """Sweep tau over the POSITIVE scores only. Semantics identical to
    src/char_report.py::sweep -- answered when score >= tau, precision =
    correct/answered, recall = correct/n_positives, rejection = negatives
    below tau -- except that the candidate grid excludes the negatives, so they
    cannot influence the selection even through the grid."""
    total = len(pos_scores)
    pts = []
    for tau in sorted({round(s, 6) for s in pos_scores}):
        ansi = [i for i, s in enumerate(pos_scores) if s >= tau]
        cor = sum(pos_correct[i] for i in ansi)
        prec = cor / len(ansi) if ansi else None
        rec = cor / total
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
        pts.append({"tau": tau, "n_answered": len(ansi),
                    "coverage": round(len(ansi) / total, 4),
                    "precision": round(prec, 4) if prec is not None else None,
                    "recall": round(rec, 4), "f1": round(f1, 4),
                    "negatives_rejected": round(
                        sum(1 for s in neg_scores if s < tau) / len(neg_scores), 4)})
    best = max(pts, key=lambda p: p["f1"])
    allrej = [p for p in pts if p["negatives_rejected"] == 1.0]
    p90 = [p for p in pts if p["precision"] is not None
           and p["precision"] >= 0.90 and p["n_answered"] >= 10]
    return {
        "max_f1": best,
        "at_all_negatives_rejected": min(allrej, key=lambda p: p["tau"]) if allrej else None,
        "at_precision_0.90": min(p90, key=lambda p: p["tau"]) if p90 else None,
        "n_candidate_taus": len(pts),
    }


def at_tau(pos_scores, pos_correct, neg_scores, tau):
    ansi = [i for i, s in enumerate(pos_scores) if s >= tau]
    cor = sum(pos_correct[i] for i in ansi)
    return {"tau": round(tau, 6), "n_answered": len(ansi),
            "coverage": round(len(ansi) / len(pos_scores), 4),
            "precision": round(cor / len(ansi), 4) if ansi else None,
            "recall": round(cor / len(pos_scores), 4),
            "negatives_rejected": round(
                sum(1 for s in neg_scores if s < tau) / len(neg_scores), 4),
            "negatives_admitted": sum(1 for s in neg_scores if s >= tau)}


# ----------------------------------------------------------------------- driver

def fused(sims, rule):
    """sims: (n_draws, n_targets). Returns (score_vector,) for the fused rule."""
    if rule == "max_cos":
        return sims.max(dim=0).values
    if rule == "mean_cos":
        return sims.mean(dim=0)
    raise ValueError(rule)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--negatives", type=Path,
                    default=Path("fixtures/negative_requests.json"))
    ap.add_argument("--rw-pos", type=Path, default=Path("out/rewrites_positives.json"))
    ap.add_argument("--rw-neg", type=Path, default=Path("out/rewrites_negatives.json"))
    ap.add_argument("--neg-artifact", type=Path,
                    default=Path("out/char_neg_bge-small_ft.json"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    r = load_deploy(a.deploy.resolve())
    D = r.D.double()
    targets = r.targets
    by_key = {m: t["target_id"] for t in targets for m in t["members"]}

    pos_rows = json.loads(a.fixture.read_text())["queries"]
    neg_rows = json.loads(a.negatives.read_text())["queries"]
    rwp = {x["row"]: x["rewrites"] for x in json.loads(a.rw_pos.read_text())["rewrites"]}
    rwn = {x["row"]: x["rewrites"] for x in json.loads(a.rw_neg.read_text())["rewrites"]}

    # encode every distinct string once
    texts, index = [], {}

    def tid(s):
        if s not in index:
            index[s] = len(texts)
            texts.append(s)
        return index[s]

    pos_single = [[tid(x["query"])] for x in pos_rows]
    item_of = defaultdict(list)
    for i, x in enumerate(pos_rows):
        item_of[x["key"]].append(i)
    pos_fixture4 = [[tid(pos_rows[j]["query"]) for j in item_of[x["key"]]]
                    for x in pos_rows]
    pos_rw4 = [[tid(x["query"])] + [tid(s) for s in rwp.get(i, [])]
               for i, x in enumerate(pos_rows)]
    neg_single = [[tid(x["query"])] for x in neg_rows]
    neg_rw4 = [[tid(x["query"])] + [tid(s) for s in rwn.get(i, [])]
               for i, x in enumerate(neg_rows)]

    V = encode_queries(r, texts).double()
    S = V @ D.T                                          # (n_distinct, 1353)
    gold = [by_key[x["key"]] - 1 for x in pos_rows]

    def evaluate(draws_pos, draws_neg, rule):
        ps, pc, pr = [], [], []
        for k, dr in enumerate(draws_pos):
            sc = fused(S[dr], rule)
            top = int(sc.argmax())
            ps.append(float(sc[top]))
            order = sc.argsort(descending=True)
            rk = int((order == gold[k]).nonzero()[0, 0]) + 1
            pr.append(rk)
            pc.append(1 if rk == 1 else 0)
        ns = [float(fused(S[dr], rule).max()) for dr in draws_neg]
        return ps, pc, pr, ns

    CONFIGS = [
        ("A_single_vs_single", pos_single, neg_single,
         "1 draw each side. Reproduces CHARACTERISATION.md sec 3."),
        ("B_fixture4_vs_neg1", pos_fixture4, neg_single,
         "4 draws for positives, 1 for negatives. ASYMMETRIC AND OPTIMISTIC -- "
         "reported to size the bias, not to be believed."),
        ("C_fixture4_vs_negrw4", pos_fixture4, neg_rw4,
         "Draw counts match (4 vs 4); sources do not -- fixture phrasings come "
         "from the gold wording, negative rewrites from the request."),
        ("D_rewrite4_vs_rewrite4", pos_rw4, neg_rw4,
         "Symmetric and deployable: query + 3 generated rewrites on both sides "
         "from one prompt blind to which set a request came from."),
    ]

    out = {}
    for name, dp, dn, note in CONFIGS:
        out[name] = {"note": note,
                     "n_draws_positive": len(dp[0]), "n_draws_negative": len(dn[0])}
        for rule in ("max_cos", "mean_cos"):
            if name == "A_single_vs_single" and rule == "mean_cos":
                continue                                  # identical to max_cos
            ps, pc, pr, ns = evaluate(dp, dn, rule)
            sw = sweep(ps, pc, ns)
            corr = [ps[i] for i in range(len(ps)) if pc[i]]
            inco = [ps[i] for i in range(len(ps)) if not pc[i]]
            out[name][rule] = {
                "positive_R@1": round(sum(pc) / len(pc), 4),
                "positive_R@5": round(sum(x <= 5 for x in pr) / len(pr), 4),
                "positive_R@10": round(sum(x <= 10 for x in pr) / len(pr), 4),
                "score_distribution": {
                    "positives_all": dist(ps), "positives_correct": dist(corr),
                    "positives_incorrect": dist(inco), "negatives": dist(ns)},
                "auroc_positives_all_vs_negatives": auroc(ps, ns),
                "auroc_positives_correct_vs_negatives": auroc(corr, ns),
                "auroc_correct_vs_incorrect_positives": auroc(corr, inco),
                "overlap": {
                    "negatives_above_positive_p50": sum(
                        1 for x in ns if x > pct(ps, .50)),
                    "negatives_above_positive_p10": sum(
                        1 for x in ns if x > pct(ps, .10)),
                    "negatives_above_positive_max": sum(1 for x in ns if x > max(ps))},
                "rederived_threshold_positives_only": sw,
                "at_shipped_tau_0.729476": at_tau(ps, pc, ns, SHIPPED_TAU),
                "hardest_negatives": sorted(
                    [{"id": neg_rows[i].get("id"), "domain": neg_rows[i].get("domain"),
                      "adjacency": neg_rows[i].get("adjacency"),
                      "query": neg_rows[i]["query"], "fused_cos": round(ns[i], 4)}
                     for i in range(len(ns))], key=lambda d: -d["fused_cos"])[:6],
            }

    base = out["A_single_vs_single"]["max_cos"]
    shipped = json.loads(Path("out/char_task3_calibration.json").read_text())["bge-small_ft"]
    parity = {
        "reproduced_max_f1_tau": base["rederived_threshold_positives_only"]["max_f1"]["tau"],
        "shipped_max_f1_tau": shipped["sweep_cos_top1"]["max_f1"]["tau"],
        "reproduced_negatives_rejected":
            base["rederived_threshold_positives_only"]["max_f1"]["negatives_rejected"],
        "shipped_negatives_rejected":
            shipped["sweep_cos_top1"]["max_f1"]["negatives_rejected"],
        "reproduced_auroc_all_vs_neg": base["auroc_positives_all_vs_negatives"],
        "reproduced_R@1": base["positive_R@1"],
    }
    ok = (abs(parity["reproduced_max_f1_tau"] - SHIPPED_TAU) < 1e-4
          and abs(parity["reproduced_R@1"] - 0.567) < 0.005)

    rep = {
        "schema": "compass_fusion_abstention/1",
        "question": ("Does phrasing fusion destroy the absence-detection "
                     "mechanism? Under max_cos every score inflates, negatives "
                     "included."),
        "disqualifying_criterion_recorded_before_running": (
            "Absence detection at AUROC 0.982 is worth more than 25 R@1 points in "
            "an autonomous pipeline, because the model cannot detect its own "
            "errors (AUROC 0.640, precision 0.90 unreachable). If fusion collapses "
            "the positive/negative separation, that is disqualifying regardless of "
            "what it does to R@1."),
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "deploy_guards": "checksums + dictionary hash + row-order verified at load",
        "shipped_tau": SHIPPED_TAU,
        "threshold_policy": (
            "Candidate taus are drawn from the 224 POSITIVE fused scores only. "
            "The 44 negatives never enter the selection, not even as grid points "
            "(stricter than src/char_report.py, whose grid was the union). They "
            "report."),
        "n_positive_rows": len(pos_rows), "n_negative_rows": len(neg_rows),
        "n_distinct_strings_encoded": len(texts),
        "rewrite_source_positives": str(a.rw_pos),
        "rewrite_source_negatives": str(a.rw_neg),
        "parity_vs_characterisation_sec3": parity,
        "parity_ok": ok,
        "configs": out,
    }
    a.out.write_text(json.dumps(rep, indent=1))

    if not ok:
        print("!! PARITY WARNING: config A does not reproduce sec 3")
    print(f"parity A: tau {parity['reproduced_max_f1_tau']} vs shipped "
          f"{parity['shipped_max_f1_tau']}, neg-rej "
          f"{parity['reproduced_negatives_rejected']} vs "
          f"{parity['shipped_negatives_rejected']}, "
          f"AUROC {parity['reproduced_auroc_all_vs_neg']}, "
          f"R@1 {parity['reproduced_R@1']}\n")
    hdr = (f"{'config':<24}{'rule':<10}{'R@1':>6}{'negP50':>8}{'negMax':>8}"
           f"{'posP10':>8}{'AUROC':>7}{'tau*':>8}{'rej@tau*':>9}{'rec@tau*':>9}"
           f"{'rej@ship':>9}")
    print(hdr)
    for name, _, _, _ in CONFIGS:
        for rule in ("max_cos", "mean_cos"):
            if rule not in out[name]:
                continue
            c = out[name][rule]
            d = c["score_distribution"]
            m = c["rederived_threshold_positives_only"]["max_f1"]
            print(f"{name:<24}{rule:<10}{c['positive_R@1']:>6}"
                  f"{d['negatives']['p50']:>8}{d['negatives']['max']:>8}"
                  f"{d['positives_all']['p10']:>8}"
                  f"{c['auroc_positives_all_vs_negatives']:>7}"
                  f"{m['tau']:>8.4f}{m['negatives_rejected']:>9}"
                  f"{m['recall']:>9}"
                  f"{c['at_shipped_tau_0.729476']['negatives_rejected']:>9}")
    print(f"\n-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
