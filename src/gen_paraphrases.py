"""Generate query rewrites for the fusion experiment -- the inference-time
rewriter, applied identically to positives and to negatives.

This is the one component that could not be measured from the existing fixture.
The fixture's four phrasings per item were each written FROM THE GOLD WORDING
under a "do not copy distinctive phrases" instruction; a rewriter at inference
sees only the request. So the fixture phrasings cannot stand in for a rewriter's
output, and they cannot be used for the negatives at all (no gold exists).

Both roles this serves:
  * task 3 -- the 44 held-out negatives get 3 rewrites each, so the abstention
    comparison is four-draws against four-draws rather than four against one.
  * task 4 -- the 224 positive requests get 3 rewrites each from the SAME prompt
    with no knowledge of which set a request came from, so the fused abstention
    threshold is measured in the configuration it would actually be deployed in.

Generator: claude-haiku-4-5 through the Claude Code CLI with ALL TOOLS DISABLED,
matching src/gen_training.py -- no network, no repository access, nothing but
the request text. One shard per batch so a crash resumes.

    python src/gen_paraphrases.py --fixture retrieval_queries.json \
        --out out/rewrites_positives.json --shard-dir out/rw_shards_pos
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

GENERATOR_MODEL = "claude-haiku-4-5"

# Prompt design follows the constraint recorded in the brief and corrected by
# out/fusion_task1_overlap.json: retrieval failures are NOT caused by too little
# lexical copying of the gold (overlap does not predict correctness at all), but
# short, abstract requests do lose to longer, more specific ones -- the absolute
# count of content words shared with the gold correlates with correctness at
# rho 0.186 (perm p 0.005) while the COVERAGE ratio does not (rho 0.09, p 0.17).
# So the rewriter is asked for concrete, longer restatements, not for
# gold-flavoured vocabulary it has no way to know.
PROMPT_TEMPLATE = """You rewrite a health researcher's variable-lookup request \
into alternative phrasings, which will be matched against the literal wording of \
a survey questionnaire.

For each request below, write exactly {n} alternative phrasings.

The corpus being matched against is survey question text and its response \
options, in the questionnaire's own words -- "How often did you walk while \
shopping or doing errands", "What time do you typically wake up on days off - \
AM/PM", "Have you ever taken naproxen (Naprosyn, Anaprox, Aleve) regularly". \
Requests fail when they name a construct in the abstract and the questionnaire \
names a concrete instance, a timeframe, or a specific subfield.

So each rewrite should move TOWARD the questionnaire's register:
1. Name concrete instances the construct covers -- generic and brand drug names, \
specific transport modes, specific body sites, specific relationships.
2. Make an implied timeframe, recall window, subfield or unit explicit.
3. Restate it as the plain question a survey would ask, in everyday words rather \
than analyst vocabulary.

Hard rules:
- Stay faithful to the request. Do not broaden it into a different construct, and \
do not narrow a general request down to a single instance -- name an instance as \
an EXAMPLE alongside the general term.
- Do not invent facts about what this survey contains or does not contain. If you \
do not know a concrete instance for a request, keep the general term.
- Under 15 words each. No question marks.
- The {n} rewrites must differ from each other and from the original request.

Requests:
{items}

Return ONLY a JSON object, no prose and no code fence, of the form:
{{"<id>": ["rewrite one", "rewrite two", ...], ...}}
with exactly {n} strings per id, and one key per id above."""

JSON_RE = re.compile(r"\{.*\}", re.S)


def prompt_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()[:16]


def call_generator(prompt: str, timeout: int, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            p = subprocess.run(
                ["claude", "-p", "--model", GENERATOR_MODEL, "--allowed-tools", ""],
                input=prompt, capture_output=True, text=True, timeout=timeout)
            m = JSON_RE.search(p.stdout.strip())
            if not m:
                last = f"no JSON in output: {p.stdout.strip()[:200]}"
                continue
            return json.loads(m.group(0))
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            last = repr(e)
        time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"generator failed after {retries} tries: {last}")


def run_batch(args) -> dict:
    idx, batch, n, shard_dir, timeout = args
    shard = shard_dir / f"shard_{idx:04d}.json"
    if shard.exists():
        return json.loads(shard.read_text())
    items = "\n".join(f'- id: {rid}\n  request: {q}' for rid, q in batch)
    t0 = time.time()
    raw = call_generator(PROMPT_TEMPLATE.format(n=n, items=items), timeout)
    dt = time.time() - t0
    out = {}
    for rid, q in batch:
        got = raw.get(str(rid)) or raw.get(rid) or []
        seen, keep = {q.strip().lower()}, []
        for r in got:
            if not isinstance(r, str):
                continue
            r = " ".join(r.split()).strip(" .?")
            if len(r) < 2 or r.lower() in seen:
                continue
            seen.add(r.lower())
            keep.append(r)
        out[str(rid)] = keep[:n]
    res = {"batch": idx, "n_requests": len(batch), "rewrites": out,
           "wall_s": round(dt, 2)}
    shard.write_text(json.dumps(res))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shard-dir", type=Path, required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    fx = json.loads(a.fixture.read_text())
    rows = fx["queries"] if isinstance(fx, dict) else fx
    reqs = [(i, r["query"]) for i, r in enumerate(rows)]
    a.shard_dir.mkdir(parents=True, exist_ok=True)

    batches = [(i // a.batch_size, reqs[i:i + a.batch_size], a.n, a.shard_dir,
                a.timeout) for i in range(0, len(reqs), a.batch_size)]
    t0 = time.time()
    done, wall = {}, []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for k, res in enumerate(ex.map(run_batch, batches), 1):
            done.update(res["rewrites"])
            wall.append(res["wall_s"])
            if k % 5 == 0 or k == len(batches):
                print(f"  {k}/{len(batches)} batches  {time.time()-t0:.0f}s")

    short = [i for i, _ in reqs if len(done.get(str(i), [])) < a.n]
    rep = {
        "schema": "compass_query_rewrites/1",
        "generated": time.strftime("%Y-%m-%d"),
        "generator": GENERATOR_MODEL,
        "generator_route": "claude -p --allowed-tools '' (no network, no tools)",
        "prompt_sha256_16": prompt_hash(),
        "prompt_template": PROMPT_TEMPLATE,
        "source_fixture": str(a.fixture),
        "source_fixture_schema": fx.get("schema") if isinstance(fx, dict) else None,
        "n_requests": len(reqs), "n_rewrites_requested": a.n,
        "n_requests_short_of_target": len(short),
        "rows_short_of_target": short,
        "generation_cost": {
            "n_llm_calls": len(batches), "batch_size": a.batch_size,
            "total_wall_s": round(time.time() - t0, 1),
            "mean_call_s": round(sum(wall) / len(wall), 2) if wall else None,
            "per_request_serial_s_estimate": round(
                sum(wall) / len(wall) / a.batch_size, 3) if wall else None,
        },
        "note": ("The SAME prompt is applied to positive and negative requests "
                 "with no signal about which is which -- that is the deployed "
                 "configuration, and it is what makes the task-3 abstention "
                 "comparison symmetric."),
        "rewrites": [{"row": i, "query": q, "rewrites": done.get(str(i), [])}
                     for i, q in reqs],
    }
    a.out.write_text(json.dumps(rep, indent=1))
    print(f"{len(reqs)} requests, {a.n} rewrites each, "
          f"{len(short)} short of target, "
          f"{rep['generation_cost']['total_wall_s']}s -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
