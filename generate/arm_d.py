"""Arm D: the whole instrument in the prompt, selection by index, no retrieval.

WHAT THIS ARM IS. No search, no ranking, no filtering. Every one of the
instrument's 1,400 selectable items is rendered into a static prompt and the
model returns an index. Reachability is 100% by construction rather than by
measurement, and the idf, floor and vocabulary-gap failure class the lexical
arms live inside does not exist here — there is nothing to match against.

WHAT A CANDIDATE IS, and this is the load-bearing decision. One candidate per
(construct, option) after `env/labels.py::catalogue_display` folds roster
members together: 1,400 options under 1,080 stems, from 2,804 dictionary rows.
`m2:Q16.8` is 440 rows — 22 cancer types asked of 20 siblings — and is 22
candidates here.

THE FOLD IS NOT FREE AND THE REPORT SAYS SO. What separates those 20 siblings
in `question_text` is a leaked piped Qualtrics reference, `- 1_Q16.9#1 - 1 -`,
which `TASKS.md` R9 names as the ONLY discriminator for 44 of the fixture's 224
rows. The catalogue strips it, so those 20 rows are one candidate and the
retrieval gold rule — roster-normalised wording equality, which does NOT strip
it — can no longer be applied row for row. Two match rules are therefore
reported, never one:

  * FOLDED, the primary: a row is matched when the gold key is one of the keys
    the selected candidate stands for. This is what the arm can actually be
    asked to do.
  * SINGLETON, the comparable one: the same rule restricted to rows whose gold
    candidate stands for exactly ONE key. On that subset the fold gives the arm
    nothing the lexical arms were not also asked for.

Reporting only the first would credit arm D for a distinction it was never made
to draw; reporting only the second would throw away 14 of 56 gold items.

Run it:
    python -m generate.arm_d produce
    python -m generate.arm_d measure
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import statistics
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from agent.prompt_contract import (
    VariableSelection,
    candidates_from_keys,
    catalogue_contract,
)
from benchmark import retrieval_eval as R
from env import labels
from generate.c16_rewrites import PerThreadSeal

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run"

#: The in-pipeline pin (`AGENTS.md` §Hard Constraints). Arm D asks more of a
#: model than the lexical arms do — 38k tokens of context instead of a ranked
#: page — which is exactly why it runs at the pin and not above it.
MODEL = "claude-haiku-4-5"

#: Concurrent calls. Lower than C16's six: these replies run to thousands of
#: output tokens and one row took 66 seconds.
WORKERS = 4

#: The five verdicts, in report order. All of them stay reachable: an arm that
#: reaches a high match rate by never abstaining is worse than the control, and
#: `docs/adr/003-index-selection.md` records the measured direction of this
#: system's error — five false positives in 21 rows.
VERDICTS = ("resolved", "family", "derive", "ambiguous", "absent")


@dataclass
class Surface:
    """The static half of arm D's prompt, built once.

    Attributes:
        catalogue: The folded instrument.
        prompt: The rendered system prompt every row shares.
        contract: The selection contract, for index resolution.
    """

    catalogue: labels.Catalogue
    prompt: str
    contract: object = field(default=None, repr=False)


def build_surface() -> Surface:
    """Render the catalogue and the contract into one static prompt.

    Returns:
        The surface. Its `prompt` names no request: the request is the user
        turn, so the instrument stays a byte-identical prefix across rows and
        is read from cache rather than re-sent.
    """
    cat = labels.build_catalogue()
    cands = candidates_from_keys(
        [o.representative for o in cat.options],
        {o.representative: {"module": o.module,
                            "roster_family_size": o.roster_family_size}
         for o in cat.options})
    contract = catalogue_contract(cands)
    return Surface(catalogue=cat, contract=contract,
                   prompt=contract.render(catalogue=labels.render_catalogue(cat)))


def prompt_hash(surface: Surface | None = None) -> str:
    """A digest of the static prompt an artifact was produced under.

    Args:
        surface: The surface; built fresh by default.

    Returns:
        Twelve hex characters of its SHA-256.
    """
    s = surface or build_surface()
    return hashlib.sha256(s.prompt.encode()).hexdigest()[:12]


def artifact_path(digest: str, model: str = MODEL) -> Path:
    """Where a produced artifact lives.

    Args:
        digest: The prompt digest.
        model: The model the selections were produced at.

    Returns:
        The path.
    """
    return RUN / f"arm_d.{model}.{digest}.json"


def user_turn(request: str) -> str:
    """The only part of the prompt that changes between rows.

    Args:
        request: The researcher's words.

    Returns:
        The user turn.
    """
    return f'The researcher asked for: "{request}"'


def parse_selection(raw: str) -> VariableSelection | None:
    """Recover a selection from the model's reply.

    Args:
        raw: The model's text.

    Returns:
        The selection, or None when the text carries no valid one.
    """
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return VariableSelection.model_validate_json(text[start:end + 1])
    except ValueError:
        return None


def _ask(call: PerThreadSeal, request: str, attempts: int = 2) -> dict:
    """One row's selection, with a retry, that cannot take the pass down.

    Args:
        call: The sealed model.
        request: The researcher's words.
        attempts: How many times to try before recording the failure.

    Returns:
        The row's record: verdict, indices and the usage block behind them.
    """
    last = ""
    for _ in range(attempts):
        try:
            started = time.time()
            out = call.call_json(user_turn(request))
            raw = str(out.get("result", ""))
            sel = parse_selection(raw)
            return {
                "request": request,
                "verdict": sel.verdict if sel else "",
                "indices": list(sel.indices) if sel else [],
                "recipe": sel.recipe if sel else "",
                "missing_dimension": sel.missing_dimension if sel else "",
                "reason": sel.reason if sel else "",
                "malformed": sel is None,
                "raw": raw,
                "usage": out.get("usage", {}),
                "cost_usd": out.get("total_cost_usd"),
                "seconds": round(time.time() - started, 1),
            }
        except Exception as exc:
            last = f"ERROR {type(exc).__name__}: {str(exc)[:300]}"
    return {"request": request, "verdict": "", "indices": [], "recipe": "",
            "missing_dimension": "", "reason": "", "malformed": True,
            "raw": last, "usage": {}, "cost_usd": None, "seconds": 0.0}


def requests_from_fixture() -> tuple[str, ...]:
    """Every distinct request in the committed retrieval fixture.

    Returns:
        The requests, in fixture order, deduplicated.
    """
    seen: set[str] = set()
    out: list[str] = []
    for row in R.load_fixture().queries:
        if row.query not in seen:
            seen.add(row.query)
            out.append(row.query)
    return tuple(out)


def _write(path: Path, surface: Surface, digest: str, started: float,
           done: dict[str, dict], asked: int) -> Path:
    """Write the artifact from whatever has finished so far.

    Args:
        path: Where to write.
        surface: The surface the selections were produced under.
        digest: Its prompt digest.
        started: When the pass began.
        done: The rows finished so far.
        asked: How many rows this pass called the model for.

    Returns:
        The artifact path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "arm_d_selections/1",
        "generated": time.strftime("%Y-%m-%d"),
        "model": MODEL,
        "prompt_hash": digest,
        "prompt_chars": len(surface.prompt),
        "candidates": len(surface.catalogue.options),
        "constructs": len(surface.catalogue.order),
        "seconds": round(time.time() - started, 1),
        "finished": len(done),
        "asked_this_pass": asked,
        "selections": done,
    }, indent=1))
    return path


def produce() -> Path:
    """Ask the model to select for every distinct fixture request.

    Resumable and checkpointed: a row already carrying a parsed verdict is not
    re-asked, and the artifact is written as the pass runs rather than at the
    end.

    Returns:
        The artifact path.
    """
    surface = build_surface()
    digest = prompt_hash(surface)
    path = artifact_path(digest)
    done: dict[str, dict] = {}
    if path.exists():
        done = {q: v for q, v in json.loads(path.read_text())["selections"].items()
                if not v["malformed"]}
    todo = [q for q in requests_from_fixture() if q not in done]
    started = time.time()
    call = PerThreadSeal(MODEL, system=surface.prompt)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_ask, call, q) for q in todo]
            for i, fut in enumerate(as_completed(futures), start=1):
                row = fut.result()
                done[row["request"]] = row
                if i % 10 == 0 or i == len(todo):
                    _write(path, surface, digest, started, done, len(todo))
                    print(f"  {i}/{len(todo)}", flush=True)
    finally:
        call.close()
    return _write(path, surface, digest, started, done, len(todo))


@dataclass
class RowScore:
    """One fixture row, scored.

    Attributes:
        key: The gold key.
        request: The request that was asked.
        verdict: What the model returned.
        folded: Gold key among the keys the FIRST selected candidate stands for.
        any_index: Gold key among the keys ANY selected candidate stands for.
        singleton: Whether the gold candidate stands for exactly one key.
        near_duplicate: Whether the gold candidate's construct has more than one
            option — the long-context regime where attention degrades.
    """

    key: str
    request: str
    verdict: str
    folded: bool
    any_index: bool
    singleton: bool
    near_duplicate: bool


def score(path: Path | None = None) -> tuple[list[RowScore], dict]:
    """Score a produced artifact against the committed fixture.

    Args:
        path: The artifact; the current prompt's by default.

    Returns:
        `(rows, doc)` — one score per fixture row, and the artifact.

    Raises:
        FileNotFoundError: If no artifact exists for this prompt.
    """
    surface = build_surface()
    digest = prompt_hash(surface)
    p = path or artifact_path(digest)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} is missing. Run `python -m generate.arm_d produce`. An "
            f"artifact for a different prompt hash does not substitute: the "
            f"indices mean what THAT rendering said they meant.")
    doc = json.loads(p.read_text())
    cat = surface.catalogue
    per_construct = collections.Counter(o.construct_key for o in cat.options)

    rows: list[RowScore] = []
    for row in R.load_fixture().queries:
        sel = doc["selections"].get(row.query, {})
        idx = cat.index_of_key(row.key)
        gold = cat.by_index(idx) if idx else None
        chosen = [i for i in sel.get("indices", [])
                  if 1 <= i <= len(cat.options)]
        first = cat.by_index(chosen[0]) if chosen else None
        rows.append(RowScore(
            key=row.key,
            request=row.query,
            verdict=str(sel.get("verdict", "")) or "malformed",
            folded=bool(first and row.key in first.keys),
            any_index=any(row.key in cat.by_index(i).keys for i in chosen),
            singleton=bool(gold and len(gold.keys) == 1),
            near_duplicate=bool(gold and per_construct[gold.construct_key] > 1),
        ))
    return rows, doc


def _rate(hits: int, n: int) -> str:
    """Render a count as `hits/n  pp.p%`.

    Args:
        hits: The numerator.
        n: The denominator.

    Returns:
        The rendered rate, or `n/a` when the denominator is zero.
    """
    return f"{hits:>3}/{n:<3} {100 * hits / n:5.1f}%" if n else "  n/a"


def measure(path: Path | None = None) -> int:
    """Score arm D and print it beside the three lexical arms.

    Args:
        path: The artifact to score.

    Returns:
        A process exit code; 0 always — this arm is a measurement, not a gate.
    """
    rows, doc = score(path)
    decisive = [r for r in rows if r.verdict in ("resolved", "family")]
    matched = [r for r in decisive if r.folded]
    singles = [r for r in rows if r.singleton]
    single_hit = [r for r in singles if r.folded and
                  r.verdict in ("resolved", "family")]
    near = [r for r in rows if r.near_duplicate]
    near_hit = [r for r in near if r.folded and
                r.verdict in ("resolved", "family")]

    print("Arm D — whole-dictionary in-context selection\n")
    print(f"model            {doc['model']}")
    print(f"prompt           {doc['prompt_hash']}  "
          f"({doc['prompt_chars']:,} chars, {doc['candidates']:,} candidates "
          f"under {doc['constructs']:,} stems)")
    print(f"fixture          benchmark/fixtures/retrieval_queries.json, "
          f"{len(rows)} rows")
    print(f"dictionary       {R.tools.dictionary_version()}\n")
    print(R.BIAS_BANNER)
    print("    The fixture's queries were written by a model that had seen "
          "each gold item's\n    wording. That bias plausibly favours arm D "
          "MORE than the lexical arms: a\n    model reading every candidate is "
          "helped most by a request already phrased in\n    the instrument's "
          "own words. Arm D winning here does not establish it scales.\n")

    print("MATCH RULE. Folded: the gold key is one of the keys the selected "
          "candidate stands\nfor. Singleton: the same rule on rows whose gold "
          "candidate stands for exactly one\nkey — the subset where arm D is "
          "asked no less than the lexical arms were.\n")
    print(f"{'arm':<12} {'gold_excluded':>14} {'@1':>7} {'@5':>7} {'@10':>7}")
    print(f"{'control':<12} {'18/224':>14} {0.152:>7.3f} {0.415:>7.3f} "
          f"{0.536:>7.3f}")
    print(f"{'min_rank':<12} {'0/224':>14} {0.152:>7.3f} {0.438:>7.3f} "
          f"{0.549:>7.3f}")
    print(f"{'rrf':<12} {'0/224':>14} {0.192:>7.3f} {0.469:>7.3f} "
          f"{0.567:>7.3f}")
    print(f"{'arm D':<12} {'0/224 (by':>14} construction — no filter, every "
          f"item is offered)")
    print("\narm D is a selection, not a ranking, so it has no @k. Its figure "
          "is:")
    print(f"    exact match, folded      {_rate(len(matched), len(rows))}")
    print(f"    exact match, singleton   {_rate(len(single_hit), len(singles))}")
    print(f"    gold among ANY index     "
          f"{_rate(sum(1 for r in rows if r.any_index), len(rows))}")

    print("\nVERDICTS — an arm that never abstains is worse than the control")
    tally = collections.Counter(r.verdict for r in rows)
    for v in (*VERDICTS, "malformed"):
        n = tally.get(v, 0)
        if not n:
            continue
        hit = sum(1 for r in rows if r.verdict == v and r.any_index)
        note = {
            "absent": "  FALSE — every fixture row has a gold item",
            "ambiguous": f"  gold was among the offered indices in {hit}",
            "derive": f"  gold was among the named inputs in {hit}",
        }.get(v, "")
        print(f"    {v:<11} {n:>3}/{len(rows)} {100 * n / len(rows):5.1f}%{note}")

    print("\nNEAR-DUPLICATES — gold in a construct with more than one option")
    print(f"    rows                     {len(near)}/{len(rows)}")
    print(f"    exact match, folded      {_rate(len(near_hit), len(near))}")
    far = [r for r in rows if not r.near_duplicate]
    far_hit = [r for r in far if r.folded and
               r.verdict in ("resolved", "family")]
    print(f"    single-option constructs {_rate(len(far_hit), len(far))}")

    use = [s["usage"] for s in doc["selections"].values() if s.get("usage")]
    costs = [s["cost_usd"] for s in doc["selections"].values() if s.get("cost_usd")]
    read = [u.get("cache_read_input_tokens", 0) for u in use]
    made = [u.get("cache_creation_input_tokens", 0) for u in use]
    outs = [u.get("output_tokens", 0) for u in use]
    print("\nTOKEN COST")
    print(f"    rows called              {len(use)}")
    print(f"    cache READ per row       median {int(statistics.median(read)):,}")
    print(f"    cache CREATED per row    median {int(statistics.median(made)):,}"
          f"  (rows creating >30k: "
          f"{sum(1 for m in made if m > 30_000)})")
    print(f"    output tokens per row    median {int(statistics.median(outs)):,}"
          f"  max {max(outs):,}")
    if costs:
        print(f"    cost per row             median ${statistics.median(costs):.4f}"
              f"  total ${sum(costs):.2f}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a subcommand.

    Args:
        argv: Command-line arguments; `sys.argv[1:]` by default.

    Returns:
        A process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("produce", "measure"))
    args = ap.parse_args(argv)
    if args.command == "produce":
        print(produce())
        return 0
    return measure()


if __name__ == "__main__":
    sys.exit(main())
