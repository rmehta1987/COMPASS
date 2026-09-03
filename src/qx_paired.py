"""Task 2: the paired experiment -- short query vs template-expanded query,
same row, same gold, single retrieval each through the shipped deploy/ bundle.

    python src/qx_paired.py --out out/qx_task2_paired.json

Three arms, all read from the pre-registration artifact so the strings scored
are exactly the strings frozen before scoring:

  S  the row's own query, unchanged. Must reproduce out/char_pos_bge-small_ft.json
     row for row (R@1 0.567) or the script stops.
  P  template with population only.            diagnostic
  F  template in full (population + instances). PRIMARY -- the decision rule
                                                 recorded in the pre-registration
                                                 applies to F vs S.

The script refuses to run if src/query_expand.py's sha256 differs from the one
in the pre-registration, or if re-rendering the template gives different
strings: a template edited after registration is a different experiment.

Statistics: every delta carries an item-clustered bootstrap 95% CI (56 items
resampled, not 224 rows; same routine and seed as src/fusion_rewriter.py),
the paired flip table, and exact McNemar for comparison only -- McNemar treats
four correlated phrasings as four draws and is too narrow.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from fusion_eval import encode_queries, load_deploy, wilson        # noqa: E402
from fusion_rewriter import cluster_bootstrap, mcnemar_exact        # noqa: E402
from phrase_overlap import content_words                            # noqa: E402
from char_strata import domain_of                                   # noqa: E402
from query_expand import fields_from_target, sha256_file            # noqa: E402

ARMS = ["S", "P", "F"]
LENGTH_STRATA = ((1, 2, "1-2 words"), (3, 3, "3 words"), (4, 99, "4+ words"))


def rank_stats(ranks):
    s = sorted(ranks)
    n = len(s)
    return {"n": n,
            "R@1": round(sum(r == 1 for r in s) / n, 4),
            "R@5": round(sum(r <= 5 for r in s) / n, 4),
            "R@10": round(sum(r <= 10 for r in s) / n, 4),
            "rank_p50": s[int(0.5 * (n - 1))], "rank_p90": s[min(n - 1, int(0.9 * n))],
            "rank_max": s[-1]}


def paired(base, other, idxs, item_of_row):
    """Flip table + clustered CI for rows `idxs`, other vs base."""
    gained = [i for i in idxs if other[i] == 1 and base[i] != 1]
    lost = [i for i in idxs if other[i] != 1 and base[i] == 1]
    unchanged = len(idxs) - len(gained) - len(lost)
    pairs = defaultdict(list)
    for i in idxs:
        pairs[item_of_row[i]].append((1 if base[i] == 1 else 0, 1 if other[i] == 1 else 0))
    d = (sum(other[i] == 1 for i in idxs) - sum(base[i] == 1 for i in idxs)) / len(idxs)
    return {"n_rows": len(idxs), "n_items": len(pairs),
            "delta_R@1": round(d, 4),
            "cluster_bootstrap_95CI_delta_R@1": cluster_bootstrap(dict(pairs)),
            "gained": len(gained), "lost": len(lost), "unchanged": unchanged,
            "gained_rows": gained, "lost_rows": lost,
            "mcnemar_exact_p_two_sided": round(mcnemar_exact(len(gained), len(lost)), 5),
            "mcnemar_note": "comparison only: treats four correlated phrasings of an "
                            "item as four independent draws and is too narrow"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--prereg", type=Path, default=Path("out/qx_preregistration.json"))
    ap.add_argument("--pos", type=Path, default=Path("out/char_pos_bge-small_ft.json"))
    ap.add_argument("--task2-fusion", type=Path, default=Path("out/fusion_task2_rules.json"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    # ---- the template must be the registered one
    PR = json.loads(a.prereg.read_text())
    tpl = Path(__file__).parent / "query_expand.py"
    if sha256_file(tpl) != PR["template_sha256"]:
        raise SystemExit(f"src/query_expand.py sha256 {sha256_file(tpl)[:12]} != registered "
                         f"{PR['template_sha256'][:12]}. A template edited after "
                         f"registration needs its own held-out confirmation; refusing.")

    r = load_deploy(a.deploy.resolve())
    D = r.D.double()
    by_key = {m: t for t in r.targets for m in t["members"]}
    rows = json.loads(a.fixture.read_text())["queries"]
    if len(rows) != len(PR["positives"]):
        raise SystemExit("pre-registration and fixture disagree on row count")

    # re-render and compare with the frozen strings
    q = {"S": [], "P": [], "F": []}
    for i, x in enumerate(rows):
        p = PR["positives"][i]
        if p["query"] != x["query"] or p["gold_key"] != x["key"]:
            raise SystemExit(f"row {i}: pre-registration does not match the fixture")
        rq = fields_from_target(x["query"], by_key[x["key"]])
        if rq.to_query() != p["expanded_F"] or rq.to_query(with_instances=False) != p["expanded_P"]:
            raise SystemExit(f"row {i}: template re-render differs from the registered string")
        q["S"].append(x["query"]); q["P"].append(p["expanded_P"]); q["F"].append(p["expanded_F"])

    gold = [by_key[x["key"]]["target_id"] - 1 for x in rows]
    sims, ranks, top1, cos_gold = {}, {}, {}, {}
    for arm in ARMS:
        V = encode_queries(r, q[arm]).double()
        S = V @ D.T
        order = S.argsort(dim=-1, descending=True)
        rk = order.argsort(dim=-1)
        sims[arm] = S
        ranks[arm] = [int(rk[i, gold[i]]) + 1 for i in range(len(rows))]
        top1[arm] = [(int(order[i, 0]), float(S[i, order[i, 0]])) for i in range(len(rows))]
        cos_gold[arm] = [float(S[i, gold[i]]) for i in range(len(rows))]

    # ---- parity: arm S must reproduce the committed artifact row for row
    prev = json.loads(a.pos.read_text())["rows"]
    mismatch = [i for i in range(len(rows)) if ranks["S"][i] != prev[i]["rank"]]
    s_r1 = sum(x == 1 for x in ranks["S"]) / len(rows)
    parity = {"arm_S_R@1": round(s_r1, 4), "committed_artifact_R@1": 0.567,
              "rows_with_differing_rank": len(mismatch),
              "max_abs_cos_gold_delta": round(max(abs(cos_gold["S"][i] - prev[i]["cos_gold"])
                                                  for i in range(len(rows))), 9)}
    if round(s_r1, 3) != 0.567 or mismatch:
        raise SystemExit(f"PARITY FAILED: arm S R@1 {s_r1:.4f}, {len(mismatch)} rank "
                         f"mismatches. The brief says stop.")

    # ---- bookkeeping
    item_of_row = [x["key"] for x in rows]
    item_rows = defaultdict(list)
    for i, k in enumerate(item_of_row):
        item_rows[k].append(i)
    all_idx = list(range(len(rows)))

    gold_doc = []
    for x in rows:
        t = by_key[x["key"]]
        gold_doc.append(content_words(f"{t['stem'] or ''} {t['option'] or ''}", True))
    n_content = {arm: [len(content_words(s, True)) for s in q[arm]] for arm in ARMS}
    n_shared = {arm: [len(content_words(q[arm][i], True) & gold_doc[i]) for i in all_idx]
                for arm in ARMS}
    short_idx = [i for i in all_idx if n_content["S"][i] <= 2]
    changed = {arm: [i for i in all_idx if q[arm][i] != q["S"][i]] for arm in ("P", "F")}

    def lex(idxs, arm):
        return {"mean_content_words": round(sum(n_content[arm][i] for i in idxs) / len(idxs), 3),
                "mean_shared_words_with_gold": round(sum(n_shared[arm][i] for i in idxs) / len(idxs), 3),
                "rows_with_zero_shared": sum(1 for i in idxs if n_shared[arm][i] == 0)}

    def block(idxs, label):
        out = {"label": label, "n_rows": len(idxs),
               "n_items": len({item_of_row[i] for i in idxs})}
        for arm in ARMS:
            out[arm] = rank_stats([ranks[arm][i] for i in idxs])
            out[arm]["lexical"] = lex(idxs, arm)
            out[arm]["rows_changed_vs_S"] = sum(1 for i in idxs if q[arm][i] != q["S"][i])
        for arm in ("P", "F"):
            out[f"paired_{arm}_vs_S"] = paired(ranks["S"], ranks[arm], idxs, item_of_row)
        return out

    overall = block(all_idx, "all 224 rows")
    subgroup = block(short_idx, "rows whose ORIGINAL query has 1-2 content words")
    changed_only = {arm: block(changed[arm], f"rows whose query changed under {arm}")
                    for arm in ("P", "F") if changed[arm]}

    # ---- R@1 by resulting query-length stratum: does the gradient reproduce?
    by_len = {}
    for arm in ARMS:
        by_len[arm] = []
        for lo, hi, name in LENGTH_STRATA:
            idxs = [i for i in all_idx if lo <= n_content[arm][i] <= hi]
            by_len[arm].append({"stratum": name, "n": len(idxs),
                                "R@1": round(sum(ranks[arm][i] == 1 for i in idxs) / len(idxs), 4)
                                if idxs else None,
                                "R@10": round(sum(ranks[arm][i] <= 10 for i in idxs) / len(idxs), 4)
                                if idxs else None})
    # rows that MOVED stratum under F: their R@1 before/after, by origin stratum
    moved = []
    for lo, hi, name in LENGTH_STRATA:
        idxs = [i for i in all_idx if lo <= n_content["S"][i] <= hi and n_content["F"][i] > hi]
        if idxs:
            moved.append({"from_stratum": name, "n_rows_moved_up": len(idxs),
                          "R@1_S": round(sum(ranks["S"][i] == 1 for i in idxs) / len(idxs), 4),
                          "R@1_F": round(sum(ranks["F"][i] == 1 for i in idxs) / len(idxs), 4),
                          "mean_content_words_after": round(
                              sum(n_content["F"][i] for i in idxs) / len(idxs), 2)})

    # ---- strata by domain (committed classifier on the gold stem)
    dom = defaultdict(list)
    for i, x in enumerate(rows):
        dom[domain_of(by_key[x["key"]]["stem"])].append(i)
    fusion = json.loads(a.task2_fusion.read_text()) if a.task2_fusion.exists() else None
    strata = {}
    for name, idxs in sorted(dom.items(), key=lambda kv: -len(kv[1])):
        s = {"n_rows": len(idxs), "n_items": len({item_of_row[i] for i in idxs}),
             "rows_changed_under_F": len([i for i in idxs if q["F"][i] != q["S"][i]])}
        for arm in ARMS:
            s[arm] = {"R@1": round(sum(ranks[arm][i] == 1 for i in idxs) / len(idxs), 4),
                      "R@10": round(sum(ranks[arm][i] <= 10 for i in idxs) / len(idxs), 4)}
        if fusion and name in fusion["strata"]:
            s["fusion_task2_max_cos_R@1_for_reference"] = fusion["strata"][name]["max_cos"]["R@1"]
        strata[name] = s

    # ---- the items at 0/4 under S
    k_at1 = {k: sum(ranks["S"][i] == 1 for i in idxs) for k, idxs in item_rows.items()}
    zero_of_four = []
    for k, idxs in item_rows.items():
        if k_at1[k] == 0:
            zero_of_four.append({
                "gold_key": k, "ranks_S": [ranks["S"][i] for i in idxs],
                "ranks_F": [ranks["F"][i] for i in idxs],
                "now_k_at1_F": sum(ranks["F"][i] == 1 for i in idxs),
                "expansion_touched_it": any(q["F"][i] != q["S"][i] for i in idxs),
                "population": PR["positives"][idxs[0]]["population"],
                "instances": PR["positives"][idxs[0]]["instances"]})
    hist_S = Counter(k_at1.values())
    hist_F = Counter(sum(ranks["F"][i] == 1 for i in idxs) for idxs in item_rows.values())

    # ---- worked examples
    def ex(i, arm):
        t1 = r.targets[top1[arm][i][0]]
        return {"row": i, "gold_key": rows[i]["key"], "query": q["S"][i],
                "expanded": q[arm][i], "rank_S": ranks["S"][i], f"rank_{arm}": ranks[arm][i],
                "top1_after": {"key": t1["canonical_key"], "stem": (t1["stem"] or "")[:100],
                               "option": t1["option"], "cos": round(top1[arm][i][1], 4)},
                "cos_gold_S": round(cos_gold["S"][i], 4),
                f"cos_gold_{arm}": round(cos_gold[arm][i], 4)}
    pf = overall["paired_F_vs_S"]
    examples = {"gained_F": [ex(i, "F") for i in pf["gained_rows"]],
                "lost_F": [ex(i, "F") for i in pf["lost_rows"]]}

    # ---- POST HOC, not pre-registered: decompose the changed rows by what the
    # template added and whether the instance shared a word with the query.
    # Written after the results above were seen; reported to characterise the
    # mechanism, and carries no decision weight.
    def grp(idxs, label):
        if not idxs:
            return {"label": label, "n_rows": 0}
        return {"label": label, "n_rows": len(idxs),
                "n_items": len({item_of_row[i] for i in idxs}),
                "R@1_S": round(sum(ranks["S"][i] == 1 for i in idxs) / len(idxs), 4),
                "R@1_F": round(sum(ranks["F"][i] == 1 for i in idxs) / len(idxs), 4),
                "gained": sum(1 for i in idxs if ranks["F"][i] == 1 and ranks["S"][i] != 1),
                "lost": sum(1 for i in idxs if ranks["F"][i] != 1 and ranks["S"][i] == 1),
                "mean_shared_S": round(sum(n_shared["S"][i] for i in idxs) / len(idxs), 3),
                "mean_shared_F": round(sum(n_shared["F"][i] for i in idxs) / len(idxs), 3),
                "rows": [{"row": i, "gold_key": rows[i]["key"], "query": q["S"][i],
                          "expanded": q["F"][i], "rank_S": ranks["S"][i], "rank_F": ranks["F"][i]}
                         for i in idxs]}
    pop_only = [i for i in all_idx if q["P"][i] != q["S"][i] and q["F"][i] == q["P"][i]]
    with_inst = [i for i in all_idx if q["F"][i] != q["P"][i]]
    inst_disjoint, inst_overlap = [], []
    for i in with_inst:
        inst_words = set()
        for s in PR["positives"][i]["instances"]:
            inst_words |= content_words(s, True)
        (inst_overlap if inst_words & content_words(q["S"][i], True) else inst_disjoint).append(i)
    # Hand-judged, after reading the 45 instance rows: the rows whose query
    # names NO option-specific concept -- only the generic word "cancer" -- so
    # the option label did not restate the request, it supplied the
    # discriminator outright. Rule applied: the query contains no word,
    # abbreviation or lay synonym for the option's specific concept.
    # ("chest pain condition" -> Angina and "lymphoid cancer" -> NHL are counted
    # as naming it; "sibling cancer" -> Breast cancer is not.)
    handed = [i for i in with_inst
              if rows[i]["key"] in ("m2:11_Q16.8#1_3", "m2:8_Q16.8#1_1")
              and not (content_words(q["S"][i], True) & {"breast", "bladder"})]
    kept = [i for i in all_idx if i not in set(handed)]
    kept_short = [i for i in short_idx if i not in set(handed)]
    sensitivity = {
        "rule": ("exclude rows whose ORIGINAL query names no option-specific concept "
                 "(only the generic 'cancer'), so the option label supplied the "
                 "discriminator rather than restating it. Hand-judged after the "
                 "results were seen; the row list is below so it can be disputed."),
        "excluded_rows": [{"row": i, "gold_key": rows[i]["key"], "query": q["S"][i],
                           "rank_S": ranks["S"][i], "rank_F": ranks["F"][i]} for i in handed],
        "all_rows_minus_excluded": paired(ranks["S"], ranks["F"], kept, item_of_row),
        "subgroup_1_2_words_minus_excluded": paired(ranks["S"], ranks["F"], kept_short, item_of_row),
    }
    post_hoc = {
        "status": "POST HOC -- computed after the pre-registered results were read; "
                  "characterises the mechanism, decides nothing",
        "sensitivity_excluding_discriminator_supplied_rows": sensitivity,
        "population_only_added": grp(pop_only, "population added, no instance"),
        "instance_added_sharing_a_content_word_with_the_query": grp(
            inst_overlap, "instance added; at least one of its content words was already "
                          "in the query (light-stemmed)"),
        "instance_added_sharing_no_content_word_with_the_query": grp(
            inst_disjoint, "instance added; NONE of its content words was in the query -- "
                           "the option label supplied a discriminator the request lacked"),
    }

    # ---- the pre-registered decision
    ci = pf["cluster_bootstrap_95CI_delta_R@1"]
    excludes_zero = ci[0] > 0 or ci[1] < 0
    decision = ("SHIPS (subject to task 3): CI excludes zero and delta > +0.05"
                if excludes_zero and pf["delta_R@1"] > 0.05 else
                "DOES NOT SHIP: CI excludes zero but delta <= +0.05"
                if excludes_zero else
                "DOES NOT SHIP: CI on delta R@1 contains zero")

    rep = {
        "schema": "compass_query_expansion_paired/1",
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "deploy_manifest_hash": r.manifest["dictionary_version_hash"],
        "deploy_guards": "checksums + dictionary hash + row-order verified at load",
        "dtype": "float32 model load (deploy manifest); fp64 for the cosine algebra",
        "preregistration": {"file": str(a.prereg), "template_sha256": PR["template_sha256"],
                            "negative_fields_sha256": PR["negative_fields_sha256"],
                            "strings_rerendered_and_identical": True},
        "retrieval": "single query per row per arm; no fusion, no ensemble",
        "n_rows": len(rows), "n_items": len(item_rows), "n_targets": len(r.targets),
        "parity_check": parity,
        "arms": PR["arms"],
        "decision_rule_recorded_before_running": PR["decision_rule_recorded_before_running"],
        "decision": decision,
        "overall": overall,
        "subgroup_1_2_content_words": subgroup,
        "changed_rows_only": changed_only,
        "R@1_by_resulting_query_length": by_len,
        "rows_that_moved_up_a_length_stratum_under_F": moved,
        "strata": strata,
        "item_k_at1_histogram": {"S": dict(sorted(hist_S.items())),
                                 "F": dict(sorted(hist_F.items()))},
        "items_at_0_of_4_under_S": zero_of_four,
        "examples": examples,
        "post_hoc_decomposition_of_changed_rows": post_hoc,
        "per_row": [{"row": i, "gold_key": rows[i]["key"], "query": q["S"][i],
                     "expanded_P": q["P"][i], "expanded_F": q["F"][i],
                     "rank_S": ranks["S"][i], "rank_P": ranks["P"][i], "rank_F": ranks["F"][i],
                     "cos_top1_S": round(top1["S"][i][1], 6),
                     "cos_top1_P": round(top1["P"][i][1], 6),
                     "cos_top1_F": round(top1["F"][i][1], 6),
                     "n_content_S": n_content["S"][i], "n_content_F": n_content["F"][i],
                     "n_shared_S": n_shared["S"][i], "n_shared_F": n_shared["F"][i]}
                    for i in all_idx],
    }
    a.out.write_text(json.dumps(rep, indent=1, ensure_ascii=False))

    print(f"parity: arm S R@1 {parity['arm_S_R@1']}  {parity['rows_with_differing_rank']} "
          f"rank mismatches  max|dcos| {parity['max_abs_cos_gold_delta']:.2e}")
    for name, b in (("ALL", overall), ("1-2 WORDS", subgroup)):
        print(f"\n{name}  n={b['n_rows']} rows / {b['n_items']} items")
        print(f"  {'arm':<4}{'R@1':>7}{'R@5':>7}{'R@10':>7}{'cw':>6}{'shared':>8}{'chg':>5}"
              f"{'dR@1':>8}{'gain':>6}{'lost':>6}{'McN p':>8}  95% CI (items)")
        for arm in ARMS:
            s = b[arm]
            p = b.get(f"paired_{arm}_vs_S", {})
            print(f"  {arm:<4}{s['R@1']:>7}{s['R@5']:>7}{s['R@10']:>7}"
                  f"{s['lexical']['mean_content_words']:>6}"
                  f"{s['lexical']['mean_shared_words_with_gold']:>8}{s['rows_changed_vs_S']:>5}"
                  + (f"{p['delta_R@1']:>8}{p['gained']:>6}{p['lost']:>6}"
                     f"{p['mcnemar_exact_p_two_sided']:>8}  {p['cluster_bootstrap_95CI_delta_R@1']}"
                     if p else ""))
    print("\nR@1 by resulting query length:")
    for arm in ARMS:
        print(f"  {arm}: " + "  ".join(f"{x['stratum']} n={x['n']} R@1={x['R@1']}"
                                        for x in by_len[arm]))
    print("\nstrata (S -> P -> F, R@1; F R@10):")
    for name, s in strata.items():
        print(f"  {name:<22} n={s['n_rows']:<4} {s['S']['R@1']:>6} -> {s['P']['R@1']:>6} -> "
              f"{s['F']['R@1']:>6}  (@10 {s['F']['R@10']})  changed {s['rows_changed_under_F']}")
    print(f"\nitems at 0/4 under S: {len(zero_of_four)}; now correct on >=1 phrasing under F: "
          f"{sum(1 for z in zero_of_four if z['now_k_at1_F'] > 0)}")
    print("\npost hoc decomposition of changed rows (S -> F R@1):")
    for k, g in post_hoc.items():
        if isinstance(g, dict) and g.get("n_rows"):
            print(f"  {k:<58} n={g['n_rows']:<3} items={g['n_items']:<3} "
                  f"{g['R@1_S']} -> {g['R@1_F']}  (+{g['gained']} -{g['lost']})")
    s = sensitivity["all_rows_minus_excluded"]
    print(f"  sensitivity: minus {len(handed)} discriminator-supplied rows -> "
          f"dR@1 {s['delta_R@1']} CI {s['cluster_bootstrap_95CI_delta_R@1']} "
          f"(+{s['gained']} -{s['lost']}, n={s['n_rows']})")
    s = sensitivity["subgroup_1_2_words_minus_excluded"]
    print(f"               1-2 words minus them -> dR@1 {s['delta_R@1']} "
          f"CI {s['cluster_bootstrap_95CI_delta_R@1']} (+{s['gained']} -{s['lost']}, n={s['n_rows']})")
    print(f"\nDECISION: {decision}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
