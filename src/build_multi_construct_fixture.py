"""Compose multi-construct requests from the single-construct fixture.

`serve/api.py::_pair` sends the researcher's WHOLE sentence to the retriever as
one construct and offers the single resulting pool to every role. The 224-row
fixture is single-construct lookup labels, so nothing in it measures whether one
ranking covers two or three constructs at once. This builds the fixture that
does.

Each request joins N constituent constructs, each drawn from a distinct gold
TARGET (distinctness is at target grain, not key grain -- two keys that fold to
one target would make "both golds in the pool" vacuous). Shapes cover more than
one exposure and more than one outcome, because `serve/api.py` and
`agent/schema.py` both assume exactly one of each and the question is what the
retriever does when that assumption is dropped.

WHAT THIS CARRIES, AND WHAT IT MUST NOT. Only `key` and the fixture's own
`query` phrasing. The gold `text` -- the instrument's question wording -- is
NEVER copied here: this repository is public and that wording is withheld
(`README.md` §What is withheld). The composed sentence is therefore built from
request phrasings, not from questionnaire text.

INHERITED BIAS. The constituent phrasings come from `retrieval_queries.json`,
whose `KNOWN_BIAS` records that a model wrote them having seen the gold wording.
Coverage measured on this fixture is an UPPER BOUND for the same reason recall
on the 224 rows is, and the composition adds a second optimism: a real
researcher's sentence is not a conjunction of two lookup labels.

    python src/build_multi_construct_fixture.py \
        --out fixtures/multi_construct_requests.json
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

#: Request shapes as (n_exposures, n_outcomes), with how many to draw of each.
#: 1x1 is today's assumed shape; the rest are the ones the operator asked for
#: and that no layer can currently express (`agent/schema.py::ProtocolSpecification`
#: declares `exposure: Ref` and `outcome: Ref`, singular, under extra="forbid").
SHAPES: tuple[tuple[int, int, int], ...] = (
    (1, 1, 40),
    (1, 2, 30),
    (2, 1, 20),
    (2, 2, 10),
)

#: Fixed connectives, one per shape arity. Deliberately plain and deliberately
#: FEW: a template is a variable, and this fixture exists to vary the number of
#: constructs, not the prose. `AGENTS.md` §Verification Discipline -- an eval
#: whose result moves with its wording is not a measurement -- so the sentence
#: form is held constant and any future wording arm is a separate run.
CONNECTIVE = {
    (1, 1): "does {e} affect {o}",
    (1, 2): "does {e} affect {o}",
    (2, 1): "do {e} affect {o}",
    (2, 2): "do {e} affect {o}",
}


def join(parts: list[str]) -> str:
    """Join constituent phrases with `and`, Oxford-comma free.

    Args:
        parts: The constituent request phrasings.

    Returns:
        One noun phrase.
    """
    if len(parts) == 1:
        return parts[0]
    return " and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 2 \
        else f"{parts[0]} and {parts[1]}"


def main() -> int:
    """Write the composed fixture.

    Returns:
        0 on success.

    Raises:
        SystemExit: When the source fixture cannot supply distinct targets.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    ap.add_argument("--deploy", type=Path,
                    default=Path("/home/mehta5/compass-gen/deploy"),
                    help="bundle supplying targets.json, for key->target folding")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    rows = json.loads(a.fixture.read_text())["queries"]
    by_key: dict[str, list[str]] = defaultdict(list)
    for x in rows:
        by_key[x["key"]].append(x["query"])          # `text` is NEVER read here

    # Fold keys to targets: distinctness has to hold at the grain the gold rule
    # scores on, or a "both golds present" hit can be one target counted twice.
    targets = json.loads((a.deploy / "targets.json").read_text())
    tid_of: dict[str, int] = {}
    for t in targets["targets"] if isinstance(targets, dict) else targets:
        for m in t["members"]:
            tid_of[m] = t["target_id"]
    keys = sorted(k for k in by_key if k in tid_of)
    if len(keys) < 4:
        raise SystemExit(f"only {len(keys)} gold keys fold to a target; need 4+")

    rng = random.Random(a.seed)
    out, seen = [], set()
    for n_e, n_o, want in SHAPES:
        made = 0
        for _ in range(want * 200):
            if made >= want:
                break
            pick = rng.sample(keys, n_e + n_o)
            tids = [tid_of[k] for k in pick]
            if len(set(tids)) != len(tids):          # distinct TARGETS, not keys
                continue
            sig = (n_e, n_o, tuple(sorted(pick)))
            if sig in seen:
                continue
            seen.add(sig)
            slots = [{"role": "exposure" if i < n_e else "outcome",
                      "key": k, "target_id": tid_of[k],
                      "phrase": rng.choice(by_key[k])}
                     for i, k in enumerate(pick)]
            sentence = CONNECTIVE[(n_e, n_o)].format(
                e=join([s["phrase"] for s in slots if s["role"] == "exposure"]),
                o=join([s["phrase"] for s in slots if s["role"] == "outcome"]))
            out.append({"request_id": f"{n_e}x{n_o}-{made:03d}",
                        "shape": {"exposures": n_e, "outcomes": n_o},
                        "request": sentence, "slots": slots})
            made += 1
        if made < want:
            raise SystemExit(f"shape {n_e}x{n_o}: only {made} of {want} composed")

    rep = {
        "schema": "compass_multi_construct_requests/1",
        "what": ("Requests carrying more than one construct, for measuring "
                 "whether ONE ranking covers all of them. Built from "
                 "retrieval_queries.json's request phrasings; the gold question "
                 "wording is never copied here."),
        "built_by": "src/build_multi_construct_fixture.py",
        "source_fixture": str(a.fixture),
        "seed": a.seed,
        "KNOWN_BIAS": (
            "INHERITED, and compounded. The constituent phrasings come from "
            "retrieval_queries.json, whose own KNOWN_BIAS records that a model "
            "wrote them having seen the gold wording. Coverage measured here is "
            "an UPPER BOUND. Second, a composed conjunction of two lookup labels "
            "is not a researcher's sentence: it names both constructs explicitly "
            "and at equal length, which is the most favourable case for a single "
            "ranking. A real request that leans on one construct is worse."),
        "distinctness": "slots hold distinct target_ids, not merely distinct keys",
        "n_requests": len(out),
        "shapes": {f"{e}x{o}": n for e, o, n in SHAPES},
        "requests": out,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=1))
    print(f"{len(out)} requests -> {a.out}")
    for e, o, _ in SHAPES:
        ex = next(r for r in out if r["shape"] == {"exposures": e, "outcomes": o})
        print(f"  {e}x{o}: {ex['request']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
