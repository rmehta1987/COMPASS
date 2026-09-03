"""Task 4, in the reduced form task 3 forced into existence.

The brief gates task 4 on task 2 passing, and task 2 FAILED its own decision
rule (best fixture-phrasing fusion recovered 22.8% of the oracle gap, under the
~25% floor). So no rewriter is being built as a deployable component: deploy/ is
untouched and its threshold is unchanged.

But task 3 could not be answered honestly without one. Comparing four-phrasing
positives against one-phrasing negatives inflates only the positive side, and
the brief itself flags that as optimistic. Making it symmetric requires running
the SAME rewriter over both sets -- which means the 224 positives went through a
real rewriter, and the measurement task 4 asks for exists as a by-product. This
script reports it, with the paired tests that decide whether the difference is
real, rather than leaving a suggestive delta in a table.

    python src/fusion_rewriter.py --out out/fusion_task4_rewriter.json

Reported against three references: the shipped single-query argmax (0.567), the
leave-one-out fixture-phrasing fusion of task 2, and the 0.821 oracle.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics as st
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from fusion_eval import encode_queries, load_deploy, wilson, domain_of  # noqa: E402

SHIPPED_R1 = 0.567
ORACLE_R1 = 0.8214


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p for a paired flip table. b = gained, c = lost.
    Exact rather than chi-square because the discordant count here is small."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def cluster_bootstrap(pairs, n_iter=20000, seed=20260903):
    """Percentile CI for the paired R@1 difference, RESAMPLING ITEMS not rows.

    The 224 rows are 56 gold items x 4 phrasings and outcomes cluster hard by
    item (CHARACTERISATION.md sec 1: +8.0 excess at 0/4, +8.2 at 4/4 against a
    binomial reference). A row-level bootstrap would understate the interval by
    treating four correlated rows as four independent draws.
    """
    import random
    rng = random.Random(seed)
    keys = sorted(pairs)
    diffs = []
    for _ in range(n_iter):
        pick = [pairs[keys[rng.randrange(len(keys))]] for _ in range(len(keys))]
        rows = [r for grp in pick for r in grp]
        diffs.append(sum(b for _, b in rows) / len(rows)
                     - sum(a for a, _ in rows) / len(rows))
    diffs.sort()
    return [round(diffs[int(0.025 * n_iter)], 4), round(diffs[int(0.975 * n_iter)], 4)]


def measure_latency(queries, model="claude-haiku-4-5", n=5, timeout=120):
    """Per-request wall time for ONE rewriter call, unbatched -- the deployed
    shape. The batched figure in out/rewrites_*.json amortises 8 requests per
    call and is not what a single interactive request would pay."""
    from gen_paraphrases import PROMPT_TEMPLATE
    ts = []
    for q in queries[:n]:
        prompt = PROMPT_TEMPLATE.format(n=3, items=f"- id: 1\n  request: {q}")
        t0 = time.time()
        try:
            subprocess.run(["claude", "-p", "--model", model, "--allowed-tools", ""],
                           input=prompt, capture_output=True, text=True,
                           timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        ts.append(time.time() - t0)
    return ts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--rw-pos", type=Path, default=Path("out/rewrites_positives.json"))
    ap.add_argument("--task2", type=Path, default=Path("out/fusion_task2_rules.json"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--latency-n", type=int, default=5)
    a = ap.parse_args()

    from char_strata import DOMAIN_KEYWORDS

    r = load_deploy(a.deploy.resolve())
    D = r.D.double()
    by_key = {m: t["target_id"] for t in r.targets for m in t["members"]}
    by_id = {t["target_id"]: t for t in r.targets}

    rows = json.loads(a.fixture.read_text())["queries"]
    RW = json.loads(a.rw_pos.read_text())
    rw = {x["row"]: x["rewrites"] for x in RW["rewrites"]}
    task2 = json.loads(a.task2.read_text())

    texts, index = [], {}

    def tid(s):
        if s not in index:
            index[s] = len(texts)
            texts.append(s)
        return index[s]

    draws = [[tid(x["query"])] + [tid(s) for s in rw.get(i, [])]
             for i, x in enumerate(rows)]
    n_enc = time.time()
    V = encode_queries(r, texts).double()
    enc_s = time.time() - n_enc
    S = V @ D.T
    gold = [by_key[x["key"]] - 1 for x in rows]

    def ranks_for(rule):
        out = []
        for k, dr in enumerate(draws):
            sc = (S[dr].max(dim=0).values if rule == "max_cos" else
                  S[dr].mean(dim=0) if rule == "mean_cos" else None)
            if rule == "min_rank":
                sims = S[dr]
                rk = sims.argsort(dim=-1, descending=True).argsort(dim=-1).double() + 1
                sc = -rk.min(dim=0).values + (sims.max(dim=0).values + 1) / 4
            if rule == "rrf":
                sims = S[dr]
                rk = sims.argsort(dim=-1, descending=True).argsort(dim=-1).double() + 1
                sc = (1.0 / (60 + rk)).sum(dim=0)
            if rule == "single":
                sc = S[dr[0]]
            order = sc.argsort(descending=True)
            out.append(int((order == gold[k]).nonzero()[0, 0]) + 1)
        return out

    RULES = ["single", "max_cos", "mean_cos", "min_rank", "rrf"]
    rk = {ru: ranks_for(ru) for ru in RULES}
    base = rk["single"]

    def stats(v):
        s = sorted(v)
        n = len(s)
        return {"R@1": round(sum(x == 1 for x in s) / n, 4),
                "R@5": round(sum(x <= 5 for x in s) / n, 4),
                "R@10": round(sum(x <= 10 for x in s) / n, 4),
                "rank_p50": s[int(.5 * (n - 1))], "rank_p90": s[min(n - 1, int(.9 * n))],
                "rank_max": s[-1]}

    item_of = defaultdict(list)
    for i, x in enumerate(rows):
        item_of[x["key"]].append(i)

    results = {}
    for ru in RULES:
        v = rk[ru]
        gained = [i for i in range(len(v)) if v[i] == 1 and base[i] != 1]
        lost = [i for i in range(len(v)) if v[i] != 1 and base[i] == 1]
        pairs = {k: [(1 if base[i] == 1 else 0, 1 if v[i] == 1 else 0) for i in idxs]
                 for k, idxs in item_of.items()}
        s = stats(v)
        s["delta_R@1_vs_single"] = round(s["R@1"] - stats(base)["R@1"], 4)
        s["paired_flips"] = {
            "gained": len(gained), "lost": len(lost),
            "mcnemar_exact_p_two_sided": round(mcnemar_exact(len(gained), len(lost)), 5),
            "note": ("Rows are clustered in 56 items of 4; McNemar treats them as "
                     "independent and so is anti-conservative. The item-clustered "
                     "bootstrap CI beside it is the one to read."),
        }
        s["cluster_bootstrap_95CI_delta_R@1"] = cluster_bootstrap(pairs)
        s["wilson95_R@1_rows_n224_optimistic"] = wilson(
            sum(x == 1 for x in v), len(v))
        s["recovery_fraction_of_oracle_gap"] = round(
            (s["R@1"] - SHIPPED_R1) / (ORACLE_R1 - SHIPPED_R1), 4)
        s["vs_task2_same_rule_fixture_phrasings"] = task2["rules"][ru]["R@1"]
        s["examples_gained"] = [
            {"query": rows[i]["query"], "gold_key": rows[i]["key"],
             "rank_single": base[i], "rewrites": rw[i]} for i in gained[:6]]
        s["examples_lost"] = [
            {"query": rows[i]["query"], "gold_key": rows[i]["key"],
             "rank_fused": v[i], "rewrites": rw[i]} for i in lost[:6]]
        results[ru] = s

    best = max((x for x in RULES if x != "single"), key=lambda x: results[x]["R@1"])

    # strata under the best rule
    dom = defaultdict(list)
    for i, x in enumerate(rows):
        dom[domain_of(by_id[by_key[x["key"]]], DOMAIN_KEYWORDS)].append(i)
    strata = {}
    for name, idxs in sorted(dom.items()):
        strata[name] = {
            "n_rows": len(idxs),
            "single_R@1": round(sum(base[i] == 1 for i in idxs) / len(idxs), 4),
            f"{best}_R@1": round(sum(rk[best][i] == 1 for i in idxs) / len(idxs), 4),
            f"{best}_R@10": round(sum(rk[best][i] <= 10 for i in idxs) / len(idxs), 4),
            "task2_fixture_fusion_R@1": task2["strata"].get(name, {}).get(
                task2["best_deployable_rule"], {}).get("R@1"),
        }

    lat = measure_latency([x["query"] for x in rows], n=a.latency_n)
    gen = RW["generation_cost"]

    rep = {
        "schema": "compass_rewriter_fusion/1",
        "status": ("MEASURED, NOT BUILT. Task 2 failed its decision rule "
                   "(22.8% of the oracle gap recovered, floor 25%), so no "
                   "rewriter was integrated. deploy/ is unmodified and its "
                   "threshold is unchanged. These numbers exist because task 3's "
                   "symmetric abstention comparison required running a real "
                   "rewriter over the positives as well as the negatives."),
        "model_under_test": "bge-small fine-tuned (nn0, t=0.10), deploy/ bundle",
        "rewriter": {
            "generator": RW["generator"], "route": RW["generator_route"],
            "prompt_sha256_16": RW["prompt_sha256_16"],
            "n_rewrites_per_request": RW["n_rewrites_requested"],
            "blind_to_positive_or_negative": True,
            "prompt_design_note": (
                "Asked for concrete instances, explicit timeframes and plain "
                "question wording -- i.e. LONGER and MORE SPECIFIC restatements. "
                "The brief motivated this as moving toward the instrument's "
                "register; out/fusion_task1_overlap.json says the mechanism is "
                "not lexical alignment with the gold (coverage does not predict "
                "correctness, rho 0.09, p 0.17) but query informativeness (shared "
                "content-word COUNT does, rho 0.186, p 0.005). Same prescription, "
                "corrected rationale."),
        },
        "references": {
            "shipped_single_query_R@1": SHIPPED_R1,
            "task2_fixture_phrasing_fusion_best": {
                "rule": task2["best_deployable_rule"],
                "R@1": task2["rules"][task2["best_deployable_rule"]]["R@1"]},
            "oracle_best_phrasing_per_item_R@1": ORACLE_R1,
        },
        "n_rows": len(rows), "n_items": len(item_of),
        "rules": results,
        "best_rule": best,
        "why_the_best_rule_differs_from_task2": (
            "Task 2 (fixture phrasings) was won by max_cos; here max_cos is the "
            "WORST fused rule and mean_cos wins. The inputs differ in kind: the "
            "fixture's phrasings were each written from the gold wording under a "
            "'do not copy distinctive phrases' instruction, so all four are "
            "independent and roughly equally good, and taking the maximum is "
            "safe. A rewriter's three outputs are derived from the query and some "
            "are wrong -- max_cos then promotes whatever spurious target a bad "
            "rewrite scored highest on, while averaging suppresses it. This also "
            "means task 2 is NOT a clean ceiling for task 4 rule-by-rule: for "
            "mean_cos the generated rewrites beat the fixture phrasings "
            f"({results['mean_cos']['R@1']} vs "
            f"{task2['rules']['mean_cos']['R@1']})."),
        "strata": strata,
        "cost": {
            "llm_call_per_request": 1,
            "unbatched_latency_s": {
                "n_sampled": len(lat),
                "mean": round(st.mean(lat), 2) if lat else None,
                "median": round(st.median(lat), 2) if lat else None,
                "min": round(min(lat), 2) if lat else None,
                "max": round(max(lat), 2) if lat else None},
            "batched_generation_observed": gen,
            "encode_s_all_distinct_strings": round(enc_s, 2),
            "n_distinct_strings": len(texts),
            "encode_ms_per_query_1_draw": 2.94,
            "encode_ms_per_query_4_draws": round(2.94 * 4, 2),
            "cost_shape": (
                "4 encodes is ~11.8 ms against 2.94 ms -- negligible. The LLM "
                "call dominates by a factor of ~10^2 and is the whole marginal "
                "cost. It also ends the property that made argmax attractive: "
                "the retriever currently has zero marginal cost per query, no "
                "network dependency and no external failure mode, and a rewriter "
                "adds all three."),
        },
        "per_row_rank": rk,
    }
    a.out.write_text(json.dumps(rep, indent=1))

    print(f"{'rule':<10}{'R@1':>7}{'R@5':>7}{'R@10':>7}{'d(R@1)':>8}"
          f"{'gain':>6}{'lost':>6}{'McN p':>8}  {'cluster 95% CI':>18}"
          f"{'task2':>7}")
    for ru in RULES:
        s = results[ru]
        f = s["paired_flips"]
        print(f"{ru:<10}{s['R@1']:>7}{s['R@5']:>7}{s['R@10']:>7}"
              f"{s['delta_R@1_vs_single']:>8}{f['gained']:>6}{f['lost']:>6}"
              f"{f['mcnemar_exact_p_two_sided']:>8}  "
              f"{str(s['cluster_bootstrap_95CI_delta_R@1']):>18}"
              f"{s['vs_task2_same_rule_fixture_phrasings']:>7}")
    print(f"\nbest: {best}   latency/req (unbatched, n={len(lat)}): "
          f"{rep['cost']['unbatched_latency_s']['mean']}s "
          f"vs 2.94 ms for the retriever alone")
    print("\nstrata (single -> rewriter fusion):")
    for name, s in sorted(strata.items(), key=lambda kv: -kv[1]["n_rows"]):
        print(f"  {name:<22} n={s['n_rows']:<4} {s['single_R@1']:>6} -> "
              f"{s[best + '_R@1']:>6}  (task2 {s['task2_fixture_fusion_R@1']})")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
