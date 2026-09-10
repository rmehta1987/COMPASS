"""Does ONE ranking cover every construct a request carries?

`serve/api.py::_pair` builds one pool from the whole sentence and offers it to
every role. `FUSION.md` §4 and its 2026-09-10 addendum measure recall for ONE
gold per single-construct query -- a MARGINAL. What `_pair` needs is the JOINT
event: every construct's gold inside the same top-k. Those differ, and nothing
had measured the joint.

Three arms, all over the same fixture and the same frozen bundle:

  shared              one query = the whole sentence, one pool of k. What ships.
  split_role          ONE QUERY PER ROLE -- exposure phrases joined, outcome phrases
                      joined -- at k // 2 each. This is the design TASKS.md C29 names
                      and the operator described: "separates the query into the schema
                      -- exposure, outcome". On a 1x2 request its outcome query still
                      carries two blended constructs, so it is NOT the construct arm.
  split_construct     each construct queried alone at k // n, pools unioned. A FINER
                      split than C29 names; on the 40 1x1 requests the two are the same
                      operation, on the other 60 they are different designs.
  split_construct_k   each construct queried alone at k. n x the budget.

The role arm exists because reporting the construct arm as C29's ceiling was an error:
a role splitter with perfect role accuracy cannot reach it on any shape but 1x1.

THE SPLIT ARMS ARE AN ORACLE AND ARE NOT A DESIGN MEASUREMENT. They split on
the fixture's own constituent phrases, i.e. on a perfect decomposition. They
bound what splitting could buy IF the splitter never erred; they say nothing
about a real splitter, which is unbuilt and unmeasured. Read them exactly as
`FUSION.md` §2 reads its 0.821 oracle row. `AGENTS.md` §Testing Patterns bans an
oracle inside a reported result, not a ceiling reported as a ceiling.

No model is called anywhere in this script.

    python src/pool_coverage.py --out out/pool_coverage.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from build_multi_construct_fixture import join
from fusion_eval import encode_queries, load_deploy

#: The two roles `serve/api.py::_pair` asks about. A role splitter emits one query
#: per role no matter how many constructs that role carries -- that is what makes it
#: a different design from a per-construct split.
ROLES: tuple[str, ...] = ("exposure", "outcome")

#: Pool depths to report. 8 and 20 are `_resolve`'s and `_pair`'s defaults
#: (`serve/api.py`); 10 and 40 bracket them, 40 being `_pair`'s clamp ceiling.
DEPTHS: tuple[int, ...] = (8, 10, 20, 40)

#: Single-construct R@20 over the 224-row fixture, from
#: out/fusion_pool_depth.json::depths.depth_20.rules.single. The bundle and this
#: script's retrieval path must reproduce it or the coverage numbers below are
#: measuring something else. Not a preference -- the run raises.
PARITY_R_AT_20 = 0.942
PARITY_TOL = 0.0005


def render(r_mod: object, text: str) -> str:
    """Render a request the way `serve/api.py::_role_candidates` does.

    Args:
        r_mod: The bundle's `retriever` module namespace.
        text: The construct text.

    Returns:
        The string that reaches the encoder.
    """
    req = r_mod.RetrievalRequest(construct=text, role=r_mod.VariableRole.EXPOSURE)
    return req.to_query()


def topk_targets(sims: torch.Tensor, k: int) -> list[int]:
    """The k best target_ids for one query row, best first.

    Args:
        sims: 1-D similarities over the corpus, index i = target_id i+1.
        k: How many to take.

    Returns:
        `target_id` values, best first.
    """
    return [int(i) + 1 for i in sims.argsort(descending=True)[:k].tolist()]


def main() -> int:
    """Measure joint pool coverage and write the artifact.

    Returns:
        0 on success.

    Raises:
        SystemExit: When the parity check fails or a gold target is unknown.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", type=Path,
                    default=Path("/home/mehta5/compass-gen/deploy"))
    ap.add_argument("--fixture", type=Path,
                    default=Path("fixtures/multi_construct_requests.json"))
    ap.add_argument("--single", type=Path, default=Path("retrieval_queries.json"),
                    help="224-row single-construct fixture, for the parity gate")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    r = load_deploy(a.deploy.resolve())
    import retriever as r_mod
    D = r.D.double()
    by_key = {m: t["target_id"] for t in r.targets for m in t["members"]}

    # --- parity gate ------------------------------------------------------ #
    single = json.loads(a.single.read_text())["queries"]
    sv = encode_queries(r, [render(r_mod, x["query"]) for x in single]).double()
    ss = sv @ D.T
    gold1 = [by_key[x["key"]] for x in single]
    hit20 = sum(g in topk_targets(ss[i], 20) for i, g in enumerate(gold1))
    r20 = round(hit20 / len(single), 4)
    if abs(r20 - PARITY_R_AT_20) > PARITY_TOL:
        raise SystemExit(
            f"PARITY FAILED: single-construct R@20 is {r20}, expected "
            f"{PARITY_R_AT_20}. The bundle or the retrieval path is not the one "
            f"that produced out/fusion_pool_depth.json; coverage below would "
            f"measure something else.")

    # --- the multi-construct fixture -------------------------------------- #
    fx = json.loads(a.fixture.read_text())
    reqs = fx["requests"]
    for q in reqs:
        for s in q["slots"]:
            if by_key.get(s["key"]) != s["target_id"]:
                raise SystemExit(f"{q['request_id']}: {s['key']} folds to "
                                 f"{by_key.get(s['key'])}, fixture says "
                                 f"{s['target_id']}")

    whole = encode_queries(r, [render(r_mod, q["request"]) for q in reqs]).double()
    flat = [(qi, si) for qi, q in enumerate(reqs) for si in range(len(q["slots"]))]
    parts = encode_queries(
        r, [render(r_mod, reqs[qi]["slots"][si]["phrase"]) for qi, si in flat]
    ).double()
    # One query per role: that role's phrases joined by the same `join` the
    # fixture builder used, so the role query is the sentence's own words for
    # that half and nothing is re-authored here.
    rflat = [(qi, role) for qi in range(len(reqs)) for role in ROLES
             if any(sl["role"] == role for sl in reqs[qi]["slots"])]
    roleq = encode_queries(r, [
        render(r_mod, join([sl["phrase"] for sl in reqs[qi]["slots"]
                            if sl["role"] == role]))
        for qi, role in rflat]).double()

    ws, ps = whole @ D.T, parts @ D.T
    rsim = roleq @ D.T
    rs = {qr: rsim[i] for i, qr in enumerate(rflat)}
    prow = {qs: i for i, qs in enumerate(flat)}

    # How alike are the constructs a request carries? Slot competition is worst
    # when they crowd the same neighbourhood, so coverage is reported against it.
    def pair_cos(qi: int) -> float:
        idx = [prow[(qi, si)] for si in range(len(reqs[qi]["slots"]))]
        v = parts[idx]
        v = v / v.norm(dim=-1, keepdim=True)
        m = v @ v.T
        n = len(idx)
        return float((m.sum() - n) / (n * (n - 1))) if n > 1 else 1.0

    cosines = [pair_cos(qi) for qi in range(len(reqs))]

    by_depth: dict[str, dict] = {}
    per_request: list[dict] = []
    for k in DEPTHS:
        arms = {"shared": [], "split_role": [],
                "split_construct": [], "split_construct_k": []}
        role_hit: dict[str, list[int]] = defaultdict(list)
        worst_rank: list[int | None] = []
        for qi, q in enumerate(reqs):
            slots = q["slots"]
            n = len(slots)
            golds = [s["target_id"] for s in slots]

            pool = topk_targets(ws[qi], k)
            arms["shared"].append(int(all(g in pool for g in golds)))
            ranks = [pool.index(g) + 1 if g in pool else None for g in golds]
            worst_rank.append(None if any(x is None for x in ranks) else max(ranks))
            for s, g in zip(slots, golds, strict=True):
                role_hit[f"shared_{s['role']}"].append(int(g in pool))

            for arm, budget in (("split_construct", max(1, k // n)),
                                ("split_construct_k", k)):
                ok = all(
                    golds[si] in topk_targets(ps[prow[(qi, si)]], budget)
                    for si in range(n))
                arms[arm].append(int(ok))
                if arm == "split_construct":
                    for si, s in enumerate(slots):
                        role_hit[f"splitconstruct_{s['role']}"].append(int(
                            golds[si] in topk_targets(ps[prow[(qi, si)]], budget)))

            # One query per ROLE, which is what C29 names. Two queries always,
            # so a role carrying two constructs sends them blended -- the very
            # defect the shared arm has, surviving inside the split.
            rb = max(1, k // len(ROLES))
            ok_role = True
            for role in ROLES:
                idx = [si for si in range(n) if slots[si]["role"] == role]
                if not idx:
                    continue
                pool_r = topk_targets(rs[(qi, role)], rb)
                for si in idx:
                    got = golds[si] in pool_r
                    ok_role &= got
                    role_hit[f"splitrole_{role}"].append(int(got))
            arms["split_role"].append(int(ok_role))

            if k == 20:
                per_request.append({
                    "request_id": q["request_id"],
                    "n_constructs": n,
                    "mean_pairwise_cos": round(cosines[qi], 4),
                    "shared_ranks_of_golds": ranks,
                    "shared_all_covered": arms["shared"][-1],
                    "split_role_all_covered": arms["split_role"][-1],
                    "split_construct_all_covered": arms["split_construct"][-1],
                })

        n_req = len(reqs)
        shp: dict[str, dict] = {}
        for name in ("shared", "split_role", "split_construct", "split_construct_k"):
            for q, v in zip(reqs, arms[name], strict=True):
                s = f"{q['shape']['exposures']}x{q['shape']['outcomes']}"
                shp.setdefault(s, {}).setdefault(name, []).append(v)
        by_depth[f"depth_{k}"] = {
            "consumed_by": {8: "serve/api.py::_resolve (k default 8)",
                            20: "serve/api.py::_pair (k default 20)"}.get(k),
            "all_constructs_covered": {
                name: round(sum(v) / n_req, 4) for name, v in arms.items()},
            "covered_n_of": {name: [sum(v), n_req] for name, v in arms.items()},
            "per_role_marginal": {
                name: round(sum(v) / len(v), 4) for name, v in sorted(role_hit.items())},
            "by_shape": {s: {nm: round(sum(v) / len(v), 4) for nm, v in d.items()}
                         for s, d in sorted(shp.items())},
            "shared_worst_gold_rank_when_all_covered": sorted(
                x for x in worst_rank if x is not None),
        }

    rep = {
        "schema": "compass_pool_coverage/1",
        "what": ("Joint pool coverage: does ONE ranking built from the whole "
                 "sentence carry EVERY construct the sentence names? Measured "
                 "against an oracle split that queries each construct alone."),
        "oracle_warning": (
            "split_equal_total and split_per_role split on the fixture's own "
            "constituent phrases -- a PERFECT decomposition. They are a CEILING "
            "on what splitting could buy, not a measurement of any splitter. No "
            "splitter exists and none is measured here."),
        "no_model_called": True,
        "bundle": str(a.deploy),
        "parity": {"single_construct_R@20": r20, "expected": PARITY_R_AT_20,
                   "source": "out/fusion_pool_depth.json::depths.depth_20"
                             ".rules.single.R@20",
                   "n_rows": len(single)},
        "fixture": {"path": str(a.fixture), "n_requests": len(reqs),
                    "KNOWN_BIAS": fx["KNOWN_BIAS"]},
        "gold_excluded": 0,
        "gold_excluded_note": ("every slot's target_id was found in the bundle's "
                               "corpus and re-checked against the fixture; a "
                               "mismatch raises rather than reporting"),
        "not_modelled": (
            "serve/api.py drops a hit whose key fails env/labels.py::cite "
            "(`skipped_uncitable`). build/dictionary.json is absent from this "
            "checkout, so that filter is NOT applied here and every coverage "
            "figure is an upper bound on the offered pool by that much too."),
        "depths": by_depth,
        "per_request_at_k20": per_request,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=1))

    print(f"parity: single-construct R@20 = {r20} (expected {PARITY_R_AT_20})  OK\n")
    names = ("shared", "split_role", "split_construct", "split_construct_k")
    print(f"{'depth':>5}  " + "".join(f"{n:>21}" for n in names))
    for k in DEPTHS:
        d = by_depth[f"depth_{k}"]["all_constructs_covered"]
        c = by_depth[f"depth_{k}"]["covered_n_of"]
        cells = "".join(f"{d[n]:>12} {c[n][0]:>3}/{c[n][1]:<4}" for n in names)
        print(f"{k:>5}  {cells}")
    print("\nby shape at k=20 (exposures x outcomes):")
    print(f"{'shape':>7}  " + "".join(f"{n:>19}" for n in names))
    for sh, d in by_depth["depth_20"]["by_shape"].items():
        print(f"{sh:>7}  " + "".join(f"{d[n]:>19}" for n in names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
