"""Recall at the POOL DEPTHS the interactive endpoint actually uses.

FUSION.md sec 4 reports R@1, R@5 and R@10 for the five fusion rules, and sec 6
recommends `mean_cos` on the strength of its R@1. Neither interactive route in
`serve/api.py` consumes rank 1. `_resolve` offers a pool of k=8 to a model and
then to a human; `_pair` offers k=20. So the quantity those routes are graded
on is R@8 and R@20, not R@1, and sec 4's table stops short of both.

Nothing is re-encoded and no model is called. `out/fusion_task4_rewriter.json`
already carries `per_row_rank` -- the gold item's rank under every rule, per row
-- and the gold item for row i is `retrieval_queries.json::queries[i]["key"]`,
which is what clusters the bootstrap. This script only re-reads those two files
at the depths sec 4 did not report.

The estimator is `src/fusion_rewriter.py::cluster_bootstrap`, imported rather
than reimplemented, at its own default seed, so a Delta at k=8 is computed the
same way as the Delta at k=1 it is being compared against.

    python src/fusion_pool_depth.py --out out/fusion_pool_depth.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fusion_rewriter import cluster_bootstrap, mcnemar_exact

#: The two pool depths `serve/api.py` actually offers, beside sec 4's own three.
#: `_resolve` defaults to k=8 and `_pair` to k=20 (both clamped to <= 20 and
#: <= 40 respectively); 1, 5 and 10 are carried so the new rows can be checked
#: against the published table rather than replacing it.
DEPTHS = (1, 5, 8, 10, 20)

#: Which handler runs at which depth, and the caveat that MUST travel with the
#: number. These rows are a MARGINAL -- one gold per single-construct query.
#: `_pair` builds ONE pool that has to carry EVERY construct the sentence names,
#: which is a joint event and is strictly smaller: out/pool_coverage.json
#: measures it at 0.32 against this file's 0.942 marginal. An earlier version of
#: this constant named the handlers without that sentence, so the artifact
#: asserted an attribution FUSION.md had already disowned in prose -- a
#: disclaimer that lives only in the document does not travel with the JSON.
_JOINT = (" -- MARGINAL, one gold per single-construct query. This route needs "
          "EVERY construct of the request in one pool; see out/pool_coverage.json")
CONSUMED_BY = {8: "serve/api.py::_resolve (k default 8)" + _JOINT,
               20: "serve/api.py::_pair (k default 20)" + _JOINT}


def main() -> int:
    """Write recall at every depth in `DEPTHS`, with item-clustered CIs.

    Returns:
        0 on success.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--task4", type=Path,
                    default=Path("out/fusion_task4_rewriter.json"))
    ap.add_argument("--fixture", type=Path,
                    default=Path("retrieval_queries.json"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    t4 = json.loads(a.task4.read_text())
    rk = t4["per_row_rank"]
    rows = json.loads(a.fixture.read_text())["queries"]
    if len(rows) != t4["n_rows"]:
        raise SystemExit(f"fixture has {len(rows)} rows, artifact says "
                         f"{t4['n_rows']}: not the fixture that produced it")

    item_of: dict[str, list[int]] = defaultdict(list)
    for i, x in enumerate(rows):
        item_of[x["key"]].append(i)
    if len(item_of) != t4["n_items"]:
        raise SystemExit(f"{len(item_of)} items against {t4['n_items']}")

    rules = list(rk)
    base = rk["single"]
    n = len(base)
    out: dict[str, dict] = {}
    for d in DEPTHS:
        b_hit = [1 if v <= d else 0 for v in base]
        per_rule = {}
        for ru in rules:
            v = rk[ru]
            hit = [1 if x <= d else 0 for x in v]
            gained = sum(1 for i in range(n) if hit[i] and not b_hit[i])
            lost = sum(1 for i in range(n) if b_hit[i] and not hit[i])
            pairs = {k: [(b_hit[i], hit[i]) for i in idxs]
                     for k, idxs in item_of.items()}
            per_rule[ru] = {
                f"R@{d}": round(sum(hit) / n, 4),
                f"delta_R@{d}_vs_single": round((sum(hit) - sum(b_hit)) / n, 4),
                "gained": gained, "lost": lost,
                "mcnemar_exact_p_two_sided": round(mcnemar_exact(gained, lost), 5),
                f"cluster_bootstrap_95CI_delta_R@{d}": cluster_bootstrap(pairs),
            }
        out[f"depth_{d}"] = {"consumed_by": CONSUMED_BY.get(d), "rules": per_rule}

    rep = {
        "schema": "compass_pool_depth/1",
        "what": ("Recall at the pool depths serve/api.py offers, re-read from "
                 "out/fusion_task4_rewriter.json::per_row_rank. No encoding, no "
                 "model call, no new generation: the ranks are the committed "
                 "ones and only the depth threshold changes."),
        "why": ("FUSION.md sec 6 recommends mean_cos on its R@1. The two "
                "interactive handlers never read rank 1 alone -- they offer a "
                "pool of 8 or 20 to a model and then to a human -- so R@1 is "
                "not the quantity those routes are graded on."),
        "sources": {
            "ranks": str(a.task4),
            "item_clustering": f"{a.fixture}::queries[i]['key']",
            "estimator": ("src/fusion_rewriter.py::cluster_bootstrap, imported, "
                          "20000 iterations, seed 20260903"),
        },
        "n_rows": n, "n_items": len(item_of),
        "depths": out,
    }
    a.out.write_text(json.dumps(rep, indent=1))

    hdr = "".join(f"{'R@'+str(d):>9}{'d':>8}{'95% CI':>18}" for d in DEPTHS)
    print(f"{'rule':<10}{hdr}")
    for ru in rules:
        cells = ""
        for d in DEPTHS:
            s = out[f"depth_{d}"]["rules"][ru]
            cells += (f"{s[f'R@{d}']:>9}{s[f'delta_R@{d}_vs_single']:>8}"
                      f"{s[f'cluster_bootstrap_95CI_delta_R@{d}']!s:>18}")
        print(f"{ru:<10}{cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
