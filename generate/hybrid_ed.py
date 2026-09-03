"""Hybrid E→D: arm E builds the pool, arm D's selector picks inside it.

THE HYPOTHESIS, AND THE ONE NUMBER THAT SETTLES IT. End-to-end accuracy is
coverage x conversion, and conversion is commit rate x precision. Arm D over its
whole 1,400-item catalogue: coverage 1.00, commit rate 59.8% (134/224),
precision 67.2% (90/134), conversion 40.2%. Beating that from a pool whose
coverage is below 1.00 requires a HIGHER conversion, and at measured precision
that can only come from committing more often. So `commit_rate` is the leading
indicator: if it stays near 60% the hybrid cannot clear 0.402 and no precision
figure changes the answer.

WHAT IS HELD FIXED. The selector is arm D's — the same `RETRIEVAL_GUIDANCE`, the
same `VariableSelection` with all five verdicts, the same one call per row (k=1),
the same `claude-haiku-4-5`. Only the candidate list changes.

WHAT NECESSARILY CHANGES, AND IS THEREFORE A CONFOUND. Arm D read 1,400
candidates in instrument order from a cached static system prompt. This reads N
candidates in cosine order in a per-row user prompt, so pool SIZE, pool
RELEVANCE and prompt CACHING all move together. A rise in conversion cannot be
attributed to size alone. The control that would isolate it — the same selector
over a random N containing gold — is worth running only if the hybrid wins.

WHAT IT REUSES. Pools come from `encode_and_score.py`, imported rather than
reimplemented, so the vectors here are the vectors that produced the arm E
figures. Wording comes from `env/labels.py::cite` through
`catalogue_display`, the same path arm D rendered under. Scoring is at
folded-target level, matching what the selector is offered.

Run it:
    python -m generate.hybrid_ed pools --config bge-small
    python -m generate.hybrid_ed produce --config bge-small --depth 10
    python -m generate.hybrid_ed measure --config bge-small
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from agent.prompt_contract import (
    Candidate,
    SelectionContract,
    catalogue_contract,
)
from benchmark import retrieval_eval as R
from env import labels
from generate.arm_d import parse_selection, user_turn
from generate.c16_rewrites import PerThreadSeal

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"

#: The in-pipeline pin, unchanged from arm D.
MODEL = "claude-haiku-4-5"

#: Pool depths measured. Coverage rises with depth and conversion may fall, so
#: the optimum can be interior; a single depth would not show that.
DEPTHS = (10, 25, 50)

#: Concurrent calls. Higher than arm D's four because these prompts are two
#: orders of magnitude smaller.
WORKERS = 6


def targets_path() -> Path:
    """Where the arm E target set lives.

    Returns:
        The path.
    """
    return ROOT / "targets.json"


def load_targets() -> tuple[list[dict], dict[str, int]]:
    """Read the target set and index its members.

    Returns:
        `(targets, key -> target_id)`.

    Raises:
        FileNotFoundError: If the target set has not been built.
    """
    p = targets_path()
    if not p.exists():
        raise FileNotFoundError(
            f"{p} is missing. Run `python build_targets.py --dictionary "
            f"build/dictionary.json --out targets.json`.")
    doc = json.loads(p.read_text())
    if doc["dictionary_version_hash"] != R.tools.dictionary_version():
        raise ValueError(
            f"targets were built from {doc['dictionary_version_hash']}, the "
            f"dictionary is {R.tools.dictionary_version()}. A stale vector set "
            f"answers confidently and wrongly.")
    targets = doc["targets"]
    return targets, {m: t["target_id"] for t in targets for m in t["members"]}


def pools_path(config: str) -> Path:
    """Where a config's per-request pools are cached.

    Args:
        config: The `encode_and_score.py` model config.

    Returns:
        The path.
    """
    return RUN / f"hybrid_pools.{config}.json"


def build_pools(config: str, depth: int = max(DEPTHS)) -> Path:
    """Encode targets and requests once and cache the top-`depth` per request.

    Imported from `encode_and_score.py` rather than reimplemented: a second
    encoder here would silently diverge from the one that produced the arm E
    figures, and the pools would then describe a ranking nobody measured.

    Args:
        config: The model config.
        depth: How many candidates to keep per request.

    Returns:
        The cache path.
    """
    sys.path.insert(0, str(ROOT))
    import encode_and_score as E

    targets, _ = load_targets()
    cfg: dict[str, Any] = dict(E.MODELS[config])
    tok_q = E.AutoTokenizer.from_pretrained(cfg["q"])
    mod_q = E.AutoModel.from_pretrained(cfg["q"]).eval()
    if cfg["d"] == cfg["q"]:
        tok_d, mod_d = tok_q, mod_q
    else:
        tok_d = E.AutoTokenizer.from_pretrained(cfg["d"])
        mod_d = E.AutoModel.from_pretrained(cfg["d"]).eval()

    pairs = [E.target_text(t, cfg["order"]) for t in targets]
    started = time.time()
    if cfg["d"] == cfg["q"]:
        D = E.encode([f"{x[0]} {x[1]}".strip() for x in pairs],
                     tok_d, mod_d, cfg["pool"], 256, "cpu")
    else:
        D = E.encode(pairs, tok_d, mod_d, cfg["pool"], 256, "cpu", pair=True)

    requests = _requests()
    Q = E.encode([cfg["q_prefix"] + q for q in requests],
                 tok_q, mod_q, cfg["pool"], 64, "cpu")
    sims = Q @ D.T
    order = sims.argsort(dim=-1, descending=True)[:, :depth]

    path = pools_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "hybrid_pools/1",
        "config": config,
        "order": cfg["order"],
        "dictionary_version_hash": R.tools.dictionary_version(),
        "n_targets": len(targets),
        "depth": depth,
        "encode_seconds": round(time.time() - started, 1),
        "pools": {q: [int(order[i, j]) + 1 for j in range(depth)]
                  for i, q in enumerate(requests)},
    }, indent=1))
    return path


def _requests() -> list[str]:
    """Every distinct fixture request, in fixture order.

    Returns:
        The requests.
    """
    seen: set[str] = set()
    out: list[str] = []
    for row in R.load_fixture().queries:
        if row.query not in seen:
            seen.add(row.query)
            out.append(row.query)
    return out


def render_pool(targets: Sequence[dict]) -> str:
    """Render a pool the way arm D rendered its catalogue.

    Same normalisation (`catalogue_display` over `question_text`), same
    `i<N>` index token — the prefix exists because a bare number collides with
    the numeric markers `benchmark/contamination_check.py` scans for. NOT
    grouped under a shared stem: the pool is ordered by cosine and grouping
    would reorder it, which is a second change on top of the one being measured.

    Args:
        targets: The pooled targets, best first.

    Returns:
        The candidate block.
    """
    lines = []
    for i, t in enumerate(targets, start=1):
        text = labels.catalogue_display(t["wording"])
        fam = t.get("roster_family_size")
        tag = f"  [roster_family_size: {fam}]" if fam else ""
        lines.append(f"i{i} {text}{tag}")
    return "\n".join(lines)


def pool_contract(pool: Sequence[dict]) -> SelectionContract:
    """Arm D's selection surface over a pool instead of the whole instrument.

    Args:
        pool: The pooled targets, best first.

    Returns:
        The contract, indexing 1..n over the pool.
    """
    candidates = tuple(
        Candidate(index=i, key=t["canonical_key"],
                  wording=labels.cite(t["canonical_key"]).wording,
                  facts={"roster_family_size": t.get("roster_family_size")})
        for i, t in enumerate(pool, start=1))
    return catalogue_contract(candidates)


def prompt_for(pool: Sequence[dict], request: str) -> str:
    """The whole prompt for one row.

    Args:
        pool: The pooled targets, best first.
        request: The researcher's words.

    Returns:
        The prompt.
    """
    return (pool_contract(pool).render(catalogue=render_pool(pool))
            + "\n\n" + user_turn(request))


def artifact_path(config: str, depth: int) -> Path:
    """Where one depth's selections live.

    Args:
        config: The pool's model config.
        depth: The pool depth.

    Returns:
        The path.
    """
    return RUN / f"hybrid_ed.{config}.d{depth}.json"


def _ask(call: PerThreadSeal, prompt: str, request: str,
         attempts: int = 2) -> dict:
    """One row's selection, with a retry that cannot take the pass down.

    Args:
        call: The sealed model.
        prompt: The rendered prompt.
        request: The researcher's words, carried for the record.
        attempts: How many tries before recording the failure.

    Returns:
        The row's record.
    """
    last = ""
    for _ in range(attempts):
        try:
            started = time.time()
            out = call.call_json(prompt)
            raw = str(out.get("result", ""))
            sel = parse_selection(raw)
            return {"request": request,
                    "verdict": sel.verdict if sel else "",
                    "indices": list(sel.indices) if sel else [],
                    "reason": sel.reason if sel else "",
                    "malformed": sel is None, "raw": raw,
                    "usage": out.get("usage", {}),
                    "cost_usd": out.get("total_cost_usd"),
                    "seconds": round(time.time() - started, 1)}
        except Exception as exc:
            last = f"ERROR {type(exc).__name__}: {str(exc)[:300]}"
    return {"request": request, "verdict": "", "indices": [], "reason": "",
            "malformed": True, "raw": last, "usage": {}, "cost_usd": None,
            "seconds": 0.0}


def produce(config: str, depth: int) -> Path:
    """Run the selector over every request at one pool depth.

    Args:
        config: The pool's model config.
        depth: How many candidates to offer.

    Returns:
        The artifact path.

    Raises:
        FileNotFoundError: If the pools have not been built.
    """
    p = pools_path(config)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} is missing. Run `python -m generate.hybrid_ed pools "
            f"--config {config}`.")
    pools = json.loads(p.read_text())["pools"]
    targets, _ = load_targets()
    by_id = {t["target_id"]: t for t in targets}

    path = artifact_path(config, depth)
    done: dict[str, dict] = {}
    if path.exists():
        done = {q: v for q, v in json.loads(path.read_text())["rows"].items()
                if not v["malformed"]}
    todo = [q for q in _requests() if q not in done]
    started = time.time()
    call = PerThreadSeal(MODEL)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool_exec:
            futures = {}
            for q in todo:
                pool = [by_id[i] for i in pools[q][:depth]]
                futures[pool_exec.submit(
                    _ask, call, prompt_for(pool, q), q)] = q
            for i, fut in enumerate(as_completed(futures), start=1):
                row = fut.result()
                done[row["request"]] = row
                if i % 20 == 0 or i == len(todo):
                    _write(path, config, depth, started, done, len(todo))
                    print(f"  d{depth} {i}/{len(todo)}", flush=True)
    finally:
        call.close()
    return _write(path, config, depth, started, done, len(todo))


def _write(path: Path, config: str, depth: int, started: float,
           done: dict[str, dict], asked: int) -> Path:
    """Write an artifact from whatever has finished.

    Args:
        path: Where to write.
        config: The pool's model config.
        depth: The pool depth.
        started: When the pass began.
        done: Rows finished so far.
        asked: How many rows this pass called for.

    Returns:
        The artifact path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "hybrid_ed/1", "generated": time.strftime("%Y-%m-%d"),
        "model": MODEL, "pool_config": config, "depth": depth,
        "dictionary_version_hash": R.tools.dictionary_version(),
        "seconds": round(time.time() - started, 1),
        "finished": len(done), "asked_this_pass": asked, "rows": done,
    }, indent=1))
    return path


def score(config: str, depth: int) -> tuple[list[dict], dict]:
    """Score one depth against the fixture.

    Args:
        config: The pool's model config.
        depth: The pool depth.

    Returns:
        `(rows, artifact)`.

    Raises:
        FileNotFoundError: If that depth has not been produced.
    """
    path = artifact_path(config, depth)
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; produce it first.")
    doc = json.loads(path.read_text())
    pools = json.loads(pools_path(config).read_text())["pools"]
    targets, by_key = load_targets()

    out = []
    for row in R.load_fixture().queries:
        sel = doc["rows"].get(row.query, {})
        pool = pools[row.query][:depth]
        gold = by_key.get(row.key)
        idx = [i for i in sel.get("indices", []) if 1 <= i <= len(pool)]
        chosen = pool[idx[0] - 1] if idx else None
        committed = sel.get("verdict") in ("resolved", "family")
        out.append({
            "key": row.key, "request": row.query,
            "verdict": str(sel.get("verdict", "")) or "malformed",
            "pool_has_gold": gold in pool,
            "committed": committed,
            "match": bool(committed and chosen == gold),
            "any_index": any(pool[i - 1] == gold for i in idx),
            "singleton": len(targets[gold - 1]["members"]) == 1 if gold else False,
        })
    return out, doc


def _rate(hits: int, n: int) -> str:
    """Render `hits/n  pp.p%`.

    Args:
        hits: Numerator.
        n: Denominator.

    Returns:
        The rendered rate.
    """
    return f"{hits:>3}/{n:<3} {100 * hits / n:5.1f}%" if n else "  n/a"


def measure(config: str) -> int:
    """Report every produced depth for one pool config.

    Args:
        config: The pool's model config.

    Returns:
        A process exit code; always 0. This is a measurement, not a gate.
    """
    print(f"Hybrid E→D — pool {config}, selector arm D's, k=1\n")
    print(f"dictionary   {R.tools.dictionary_version()}")
    print(f"pools        {pools_path(config)}")
    print(f"selector     {MODEL}, one call per row, "
          f"VariableSelection unchanged\n")
    print(R.BIAS_BANNER)
    print("    Coverage comes from arm E, the most bias-inflated input in the "
          "chain.\n    Treat anything under ~0.45 end-to-end as unresolved.\n")
    print("ARM D BASELINE (depth 1400, catalogue order): coverage 1.000, "
          "commit 59.8%,\n              precision 67.2%, conversion 40.2%, "
          "END-TO-END 0.402\n")

    for depth in DEPTHS:
        try:
            rows, doc = score(config, depth)
        except FileNotFoundError:
            print(f"depth {depth}: not produced")
            continue
        n = len(rows)
        cov = sum(1 for r in rows if r["pool_has_gold"])
        com = sum(1 for r in rows if r["committed"])
        match = sum(1 for r in rows if r["match"])
        print(f"── depth {depth} " + "─" * 52)
        print(f"    coverage            {_rate(cov, n)}")
        print(f"    1. COMMIT RATE      {_rate(com, n)}"
              f"   (arm D 59.8%)")
        print(f"    2. precision        {_rate(match, com)}"
              f"   (arm D 67.2%)")
        print(f"    3. conversion       {_rate(match, n)}"
              f"   NOT comparable across depths")
        print(f"    4. END-TO-END       {_rate(match, n)}"
              f"   (arm D 0.402)")
        singles = [r for r in rows if r["singleton"]]
        hit = sum(1 for r in singles if r["match"])
        print(f"       singleton subset {_rate(hit, len(singles))}")

        tally = collections.Counter(r["verdict"] for r in rows)
        print("    5. verdicts         " + "  ".join(
            f"{v} {tally.get(v, 0)}" for v in
            ("resolved", "family", "derive", "ambiguous", "absent", "malformed")
            if tally.get(v)))

        missed = [r for r in rows if not r["match"] and not r["pool_has_gold"]]
        could = [r for r in rows if not r["match"] and r["pool_has_gold"]]
        print(f"    6. misses           pool-missed {len(missed)}  "
              f"could-not-choose {len(could)}")
        cnc = collections.Counter(r["verdict"] for r in could)
        print(f"       could-not-choose by verdict: {dict(cnc.most_common())}")

        use = [r["usage"] for r in doc["rows"].values() if r.get("usage")]
        costs = [r["cost_usd"] for r in doc["rows"].values() if r.get("cost_usd")]
        if use:
            inp = [u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                   for u in use]
            outp = [u.get("output_tokens", 0) for u in use]
            print(f"    7. cost/row         input median "
                  f"{int(statistics.median(inp)):,} tok   output median "
                  f"{int(statistics.median(outp)):,} tok   "
                  f"${statistics.median(costs):.4f}   total ${sum(costs):.2f}")
        print()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a subcommand.

    Args:
        argv: Command-line arguments.

    Returns:
        A process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("pools", "produce", "measure"))
    ap.add_argument("--config", default="bge-small")
    ap.add_argument("--depth", type=int, default=10)
    a = ap.parse_args(argv)
    if a.command == "pools":
        print(build_pools(a.config))
        return 0
    if a.command == "produce":
        print(produce(a.config, a.depth))
        return 0
    return measure(a.config)


if __name__ == "__main__":
    sys.exit(main())
