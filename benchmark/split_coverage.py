"""C29-C: does splitting a request before retrieval carry what one shared pool drops?

`serve/api.py::_pair` offers each role a pool. Without `split` both roles get
ONE pool built from the whole sentence; with it, a model names the request's
exposures and outcomes (`agent/prompt_contract.py::parse_split`) and each role
gets the union of its own phrases' pools. This measures, on the SAME requests in
the SAME run, how often each arm offers every gold item to the role that needs
it:

  shared   the whole sentence, one pool of k. What ships today.
  split    the real splitter's phrases, each at k // n, exactly as
           `_split_pools` builds them; a split the route refuses falls back to
           the shared pool, as the route does.
  oracle   the fixture's own marked phrases, each at k // n: a CEILING, the
           split a perfect splitter would make. Never reported as a result.

Every pool comes from the route's own functions (`_role_candidates`,
`_split_pools`, `_union_pools`), so the citation filter the route applies is
applied here too; `src/pool_coverage.py` could not model it.

THE FIXTURE IS NOT THE BIASED ONE. `fixtures/multi_construct_requests.json`
composes every request as `<exposures> affect <outcomes>`, so a splitter keyed
on " affect " would score the oracle there and generalise to nothing. This reads
a fixture whose questions were written by a session that never saw the
instrument, and whose gold keys a second session assigned afterwards (the
operator's two-session protocol, 2026-09-11).

WRONG-SPLIT HARM is reported beside coverage and never folded into it: the
requests the shared pool covered and the split did not. Once a split is accepted
the route has no shared pool to fall back on, so this is the cost it would pay.
Coverage is never multiplied by a split-accuracy figure; the split arm IS the
end-to-end number.

Record the live splitter once, then score as often as needed:

    python -m benchmark.split_coverage --fixture F --splits S --live
    python -m benchmark.split_coverage --fixture F --splits S
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: The two roles `_pair` offers a pool to.
ROLES: tuple[str, ...] = ("exposure", "outcome")

#: `serve/api.py::_pair`'s default pool depth, the site's "Ask the pipeline" flow.
DEFAULT_K = 20

#: `(state, text, role, k) -> pool`, the shape of `serve/api.py::_role_candidates`.
PoolFn = Callable[[Any, str, str, int], dict[str, Any]]

#: A pool that offers nothing, for a role whose phrases cited nothing.
_EMPTY: dict[str, Any] = {"cands": (), "cos": {}, "skipped": [], "rendered": ""}


class _Replay:
    """A backend that returns the splitter reply the live run recorded."""

    def __init__(self, reply: str, name: str) -> None:
        """Hold one recorded reply.

        Args:
            reply: The splitter's raw reply for this request.
            name: The model that produced it.
        """
        self._reply = reply
        self.name = name

    def transduce(self, _prompt: str) -> Any:
        """Return the recorded reply as the backend would have.

        Args:
            _prompt: Ignored; the reply was recorded against the same prompt.

        Returns:
            A `Reply` carrying the recorded text.
        """
        from agent.backends import Reply

        return Reply(content=self._reply)


def gold_by_role(request: Mapping[str, Any]) -> dict[str, list[str]] | None:
    """The gold keys each role must be offered.

    Args:
        request: One fixture row, its slots carrying `role` and `key`.

    Returns:
        Gold keys by role, or None when any slot has no key: the instrument has
        no item for that phrase, so "every construct covered" is undefined and
        the row leaves the denominator rather than counting as a miss.
    """
    out: dict[str, list[str]] = {r: [] for r in ROLES}
    for slot in request["slots"]:
        if not slot.get("key"):
            return None
        out[slot["role"]].append(slot["key"])
    return out


def offers_every_gold(pools: Mapping[str, Mapping[str, Any]],
                      golds: Mapping[str, Sequence[str]],
                      target_of: Mapping[str, int]) -> bool:
    """Whether each role's pool holds every gold item that role needs.

    Compared by retriever TARGET, not by key: a pool candidate is a target's
    representative key, and the gold may be another member of the same target.
    A gold offered only to the other role does not count, because `_pair` asks
    each role of its own pool.

    Args:
        pools: The pool offered to each role.
        golds: The gold keys each role needs.
        target_of: Every member key's target id.

    Returns:
        True when no role is missing a gold item.
    """
    for role, keys in golds.items():
        offered = {target_of.get(c.key) for c in pools[role]["cands"]}
        if any(target_of.get(k) not in offered for k in keys):
            return False
    return True


def oracle_pools(state: Any, request: Mapping[str, Any], k: int,
                 pool_fn: PoolFn) -> dict[str, Any]:
    """Each role's pool built from the fixture's own marked phrases.

    Args:
        state: Handed to `pool_fn`.
        request: One fixture row.
        k: The total pool budget, shared out over the phrases.
        pool_fn: Builds one phrase's pool.

    Returns:
        The pool each role would be offered by a perfect split.
    """
    from serve.api import _union_pools

    each = max(1, k // len(request["slots"]))
    parts: dict[str, list[dict[str, Any]]] = {r: [] for r in ROLES}
    for slot in request["slots"]:
        try:
            parts[slot["role"]].append(pool_fn(state, slot["phrase"], slot["role"], each))
        except ValueError:
            continue
    return {r: _union_pools(p) if p else _EMPTY for r, p in parts.items()}


def score_requests(fixture: Mapping[str, Any], splits: Mapping[str, Any], *,
                   state: Any, pool_fn: PoolFn, target_of: Mapping[str, int],
                   k: int = DEFAULT_K) -> dict[str, Any]:
    """Score the three arms on every request, in one pass.

    Args:
        fixture: The clean fixture, `requests` carrying labelled slots.
        splits: The live splitter's replies by request id, plus its `model`.
        state: Handed to `pool_fn` and `_split_pools`.
        pool_fn: `serve/api.py::_role_candidates`, or a stand-in in tests.
        target_of: Every member key's target id.
        k: The route's total pool budget.

    Returns:
        The report: per-request flags, coverage by arm and by shape, the harm
        and gain counts, the split statuses, and the rows left out and why.
    """
    from serve.api import _split_pools

    rows: list[dict[str, Any]] = []
    excluded: list[str] = []
    for q in fixture["requests"]:
        golds = gold_by_role(q)
        if golds is None or any(target_of.get(g) is None
                                for keys in golds.values() for g in keys):
            excluded.append(q["request_id"])
            continue
        try:
            shared = pool_fn(state, q["request"], "exposure", k)
        except ValueError:
            shared = _EMPTY
        fallback = {r: shared for r in ROLES}
        reply = str(splits["replies"].get(q["request_id"], ""))
        split, info = _split_pools(state, _Replay(reply, splits["model"]),
                                   q["request"], k, fallback)
        oracle = oracle_pools(state, q, k, pool_fn)
        flags = {arm: offers_every_gold(pools, golds, target_of)
                 for arm, pools in (("shared", fallback), ("split", split),
                                    ("oracle", oracle))}
        rows.append({"request_id": q["request_id"],
                     "shape": f"{q['shape']['exposures']}x{q['shape']['outcomes']}",
                     **flags, "split_status": info["status"],
                     "harm": flags["shared"] and not flags["split"],
                     "gain": flags["split"] and not flags["shared"]})
    n = len(rows)
    by_shape: dict[str, dict[str, Any]] = {}
    for shape in sorted({r["shape"] for r in rows}):
        these = [r for r in rows if r["shape"] == shape]
        by_shape[shape] = {"n": len(these), **{
            arm: round(sum(r[arm] for r in these) / len(these), 4)
            for arm in ("shared", "split", "oracle")}}
    return {
        "k": k,
        "n_scored": n,
        "gold_excluded": excluded,
        "covered": {arm: [sum(r[arm] for r in rows), n]
                    for arm in ("shared", "split", "oracle")},
        "by_shape": by_shape,
        "wrong_split_harm": sum(r["harm"] for r in rows),
        "split_gain": sum(r["gain"] for r in rows),
        "split_status": dict(Counter(r["split_status"] for r in rows)),
        "rows": rows,
    }


def live_splits(fixture: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    """Ask the real splitter once per request and keep its raw replies.

    Recorded rather than re-run at scoring time: the CLI has no seed, so a
    second call could split differently and the arms would stop being scored on
    the same split.

    Args:
        fixture: The clean fixture.
        model_id: The splitter model, as the route runs it.

    Returns:
        `{"model": ..., "replies": {request_id: raw reply}}`.
    """
    from agent import prompt_contract as PC
    from agent.cli_backend import ClaudeCliBackend

    backend = ClaudeCliBackend(model=model_id, mode="benchmark")
    replies = {q["request_id"]: str(backend.transduce(
        PC.split_prompt(q["request"])).content) for q in fixture["requests"]}
    return {"model": backend.name, "replies": replies}


def _main(argv: Sequence[str] | None = None) -> int:
    """Record the live splitter, or score the three arms over a recording.

    Args:
        argv: Command line, or None to read `sys.argv`.

    Returns:
        Process exit code.
    """
    from benchmark.resolver_eval import _serve_state
    from serve.api import PIPELINE_MODEL, _role_candidates

    ap = argparse.ArgumentParser(description=__doc__ or "")
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--splits", type=Path, required=True,
                    help="the recorded splitter replies; written by --live")
    ap.add_argument("--live", action="store_true",
                    help="call the splitter once per request and record it")
    ap.add_argument("--model", default=PIPELINE_MODEL)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    fixture = json.loads(args.fixture.read_text())
    if args.live:
        args.splits.write_text(json.dumps(live_splits(fixture, args.model), indent=1))
        print(f"recorded {len(fixture['requests'])} splits -> {args.splits}")
        return 0
    state = _serve_state()
    target_of = {m: t["target_id"] for t in state.retriever().targets
                 for m in t["members"]}
    report = score_requests(fixture, json.loads(args.splits.read_text()),
                            state=state, pool_fn=_role_candidates,
                            target_of=target_of, k=args.k)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
