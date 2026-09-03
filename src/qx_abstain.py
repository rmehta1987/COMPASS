"""Task 3: what template expansion does to the abstention mechanism.

    python src/qx_abstain.py --out out/qx_task3_abstention.json

FUSION.md sec 3 sized the error of expanding positives but not negatives at 34
points of apparent rejection. So here the SAME template is applied to the 44
held-out negatives, with the fields a specifier would have for a construct
that does not exist (fixtures/negative_expansion_fields.json, frozen in the
pre-registration), and both sides are compared arm for arm:

  S  own query both sides.         Must reproduce CHARACTERISATION.md sec 3:
                                   tau 0.729476, 43/44 rejected, AUROC 0.9823.
  P  population only, both sides.
  F  full template, both sides.    PRIMARY.

Thresholds are selected on the 224 POSITIVES ONLY (candidate taus drawn from
positive scores alone, as src/fusion_abstain.py does). Negatives report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fusion_eval import encode_queries, load_deploy                       # noqa: E402
from fusion_abstain import SHIPPED_TAU, at_tau, auroc, dist, pct, sweep   # noqa: E402
from query_expand import fields_from_negative, fields_from_target, sha256_file  # noqa: E402

ARMS = ["S", "P", "F"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--negatives", type=Path, default=Path("fixtures/negative_requests.json"))
    ap.add_argument("--neg-fields", type=Path,
                    default=Path("fixtures/negative_expansion_fields.json"))
    ap.add_argument("--prereg", type=Path, default=Path("out/qx_preregistration.json"))
    ap.add_argument("--calib", type=Path, default=Path("out/char_task3_calibration.json"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    PR = json.loads(a.prereg.read_text())
    tpl = Path(__file__).parent / "query_expand.py"
    if sha256_file(tpl) != PR["template_sha256"] or sha256_file(a.neg_fields) != PR["negative_fields_sha256"]:
        raise SystemExit("template or negative fields differ from the pre-registration; refusing")

    r = load_deploy(a.deploy.resolve())
    D = r.D.double()
    by_key = {m: t for t in r.targets for m in t["members"]}
    pos_rows = json.loads(a.fixture.read_text())["queries"]
    neg_rows = json.loads(a.negatives.read_text())["queries"]
    nf = {x["id"]: x for x in json.loads(a.neg_fields.read_text())["fields"]}

    qp = {"S": [], "P": [], "F": []}
    for i, x in enumerate(pos_rows):
        rq = fields_from_target(x["query"], by_key[x["key"]])
        qp["S"].append(x["query"]); qp["P"].append(rq.to_query(with_instances=False))
        qp["F"].append(rq.to_query())
        if qp["F"][-1] != PR["positives"][i]["expanded_F"]:
            raise SystemExit(f"positive row {i} differs from the registered string")
    qn = {"S": [], "P": [], "F": []}
    for i, x in enumerate(neg_rows):
        rq = fields_from_negative(x, nf)
        qn["S"].append(x["query"]); qn["P"].append(rq.to_query(with_instances=False))
        qn["F"].append(rq.to_query())
        if qn["F"][-1] != PR["negatives"][i]["expanded_F"]:
            raise SystemExit(f"negative {x['id']} differs from the registered string")

    gold = [by_key[x["key"]]["target_id"] - 1 for x in pos_rows]
    out = {}
    for arm in ARMS:
        Sp = encode_queries(r, qp[arm]).double() @ D.T
        Sn = encode_queries(r, qn[arm]).double() @ D.T
        ps = [float(Sp[i].max()) for i in range(len(pos_rows))]
        pc = [1 if int(Sp[i].argmax()) == gold[i] else 0 for i in range(len(pos_rows))]
        ns = [float(Sn[i].max()) for i in range(len(neg_rows))]
        ntop = [int(Sn[i].argmax()) for i in range(len(neg_rows))]
        sw = sweep(ps, pc, ns)
        corr = [ps[i] for i in range(len(ps)) if pc[i]]
        inco = [ps[i] for i in range(len(ps)) if not pc[i]]
        tau_star = sw["max_f1"]["tau"]
        adj = {}
        for lab in ("clean", "adjacent"):
            idx = [i for i, x in enumerate(neg_rows) if x["adjacency"] == lab]
            adj[lab] = {"n": len(idx),
                        "rejected_at_shipped_tau": sum(1 for i in idx if ns[i] < SHIPPED_TAU),
                        "rejected_at_rederived_tau": sum(1 for i in idx if ns[i] < tau_star),
                        "max": round(max(ns[i] for i in idx), 4)}
        reg = {}
        for lab in ("technical", "lay"):
            idx = [i for i, x in enumerate(neg_rows) if x["register"] == lab]
            reg[lab] = {"n": len(idx),
                        "rejected_at_shipped_tau": sum(1 for i in idx if ns[i] < SHIPPED_TAU),
                        "p50": pct([ns[i] for i in idx], .5)}
        out[arm] = {
            "positive_R@1": round(sum(pc) / len(pc), 4),
            "n_positive_rows_changed": sum(1 for i in range(len(pos_rows)) if qp[arm][i] != qp["S"][i]),
            "n_negative_rows_changed": sum(1 for i in range(len(neg_rows)) if qn[arm][i] != qn["S"][i]),
            "score_distribution": {"positives_all": dist(ps), "positives_correct": dist(corr),
                                   "positives_incorrect": dist(inco), "negatives": dist(ns)},
            "auroc_positives_all_vs_negatives": auroc(ps, ns),
            "auroc_positives_correct_vs_negatives": auroc(corr, ns),
            "auroc_correct_vs_incorrect_positives": auroc(corr, inco),
            "overlap": {"negatives_above_positive_p50": sum(1 for x in ns if x > pct(ps, .5)),
                        "negatives_above_positive_p10": sum(1 for x in ns if x > pct(ps, .1)),
                        "negatives_above_positive_max": sum(1 for x in ns if x > max(ps))},
            "rederived_threshold_positives_only": sw,
            "at_shipped_tau_0.729476": at_tau(ps, pc, ns, SHIPPED_TAU),
            "at_rederived_tau": at_tau(ps, pc, ns, tau_star),
            "negatives_by_adjacency": adj,
            "negatives_by_register": reg,
            "hardest_negatives": sorted(
                [{"id": neg_rows[i]["id"], "adjacency": neg_rows[i]["adjacency"],
                  "query": qn[arm][i], "cos": round(ns[i], 4),
                  "nearest": r.targets[ntop[i]]["canonical_key"],
                  "nearest_stem": (r.targets[ntop[i]]["stem"] or "")[:90]}
                 for i in range(len(ns))], key=lambda d: -d["cos"])[:8],
            "per_negative": [{"id": neg_rows[i]["id"], "query": qn[arm][i], "cos": round(ns[i], 6),
                              "nearest": r.targets[ntop[i]]["canonical_key"]}
                             for i in range(len(ns))],
            "per_positive_top1_cos": [round(x, 6) for x in ps],
            "per_positive_correct": pc,
        }

    # parity against CHARACTERISATION sec 3
    base = out["S"]
    shipped = json.loads(a.calib.read_text())["bge-small_ft"]["sweep_cos_top1"]["max_f1"]
    parity = {"reproduced_tau": base["rederived_threshold_positives_only"]["max_f1"]["tau"],
              "shipped_tau": shipped["tau"],
              "reproduced_negatives_rejected": base["rederived_threshold_positives_only"]["max_f1"]["negatives_rejected"],
              "shipped_negatives_rejected": shipped["negatives_rejected"],
              "reproduced_auroc": base["auroc_positives_all_vs_negatives"],
              "reproduced_R@1": base["positive_R@1"]}
    ok = (abs(parity["reproduced_tau"] - SHIPPED_TAU) < 1e-4 and
          abs(parity["reproduced_R@1"] - 0.567) < 0.0005 and
          parity["reproduced_negatives_rejected"] == parity["shipped_negatives_rejected"])
    if not ok:
        raise SystemExit(f"PARITY FAILED on arm S: {parity}")

    F = out["F"]
    ship_rej = F["at_shipped_tau_0.729476"]["negatives_admitted"]
    which = ("threshold survives unchanged: the shipped tau rejects the same 43/44 under F"
             if ship_rej <= 1 else
             "threshold must be re-derived ONCE and frozen: the shipped tau admits "
             f"{ship_rej}/44 expanded negatives; tau* re-derived on positives only is "
             f"{F['rederived_threshold_positives_only']['max_f1']['tau']} and rejects "
             f"{F['at_rederived_tau']['negatives_rejected']} at recall "
             f"{F['at_rederived_tau']['recall']}. Because the template is deterministic "
             "this re-derivation happens once, unlike a rewriter's.")

    rep = {
        "schema": "compass_query_expansion_abstention/1",
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "shipped_tau": SHIPPED_TAU,
        "threshold_policy": "candidate taus drawn from the 224 positive scores only; "
                            "negatives never select, they report",
        "symmetry": "the same template, with specifier-side fields, is applied to both "
                    "sides in every arm; no arm expands positives without expanding negatives",
        "preregistration": {"template_sha256": PR["template_sha256"],
                            "negative_fields_sha256": PR["negative_fields_sha256"]},
        "n_positive_rows": len(pos_rows), "n_negative_rows": len(neg_rows),
        "parity_vs_characterisation_sec3": parity, "parity_ok": ok,
        "which_case_applies_under_F": which,
        "arms": out,
    }
    a.out.write_text(json.dumps(rep, indent=1, ensure_ascii=False))

    print(f"parity S: tau {parity['reproduced_tau']} rej {parity['reproduced_negatives_rejected']} "
          f"AUROC {parity['reproduced_auroc']} R@1 {parity['reproduced_R@1']}\n")
    print(f"{'arm':<4}{'R@1':>6}{'negP10':>8}{'negP50':>8}{'negP90':>8}{'negMax':>8}"
          f"{'AUROC':>8}{'tau*':>9}{'rej@tau*':>9}{'rec@tau*':>9}{'rej@ship':>9}{'adm@ship':>9}")
    for arm in ARMS:
        c = out[arm]
        d = c["score_distribution"]["negatives"]
        m = c["rederived_threshold_positives_only"]["max_f1"]
        print(f"{arm:<4}{c['positive_R@1']:>6}{d['p10']:>8}{d['p50']:>8}{d['p90']:>8}{d['max']:>8}"
              f"{c['auroc_positives_all_vs_negatives']:>8}{m['tau']:>9.4f}"
              f"{m['negatives_rejected']:>9}{m['recall']:>9}"
              f"{c['at_shipped_tau_0.729476']['negatives_rejected']:>9}"
              f"{c['at_shipped_tau_0.729476']['negatives_admitted']:>9}")
    print(f"\nF hardest negatives:")
    for h in out["F"]["hardest_negatives"][:5]:
        print(f"  {h['cos']:.4f} {h['id']} [{h['adjacency']}] {h['query']!r} -> {h['nearest']}")
    print(f"\n{which}\n-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
