"""Generate synthetic (request, target) training pairs from dictionary wording.

Generator: claude-haiku-4-5, driven through the Claude Code CLI with ALL TOOLS
DISABLED, so the generator has no network access and sees nothing but the
target wording we hand it. Sixteen papers exist from this cohort; none of their
findings can reach the training data by this route.

The model choice is deliberate and is a real cost, declared rather than hidden:
the fixture's queries were written by claude-haiku-4-5, so matching it keeps the
training and evaluation registers aligned -- which also means the fixture
flatters this training set.

Writes one shard per batch so a crash resumes instead of restarting.
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

PROMPT_TEMPLATE = """You write short search requests that a health researcher \
would type to find a variable in a survey codebook.

For each survey item below, write exactly {n} DISTINCT requests.

Registers to spread across (roughly evenly):
1. ABBREVIATION / ACRONYM the field actually uses (HNC, NSAID, ED, COPD, BMI, PA, SES).
2. CLINICAL term where the survey uses a lay one (analgesic, metastatic, circadian,
   dyspnea, adiposity, parity, comorbidity).
3. ABSTRACT NOUN PHRASE naming the construct (household occupancy, domestic activity,
   care access, symptom burden, residential tenure).
4. VARIABLE-NAME style, as a column would be named (sleep_latency, commute_mode_other,
   sib_breast_ca).
5. BARE TOPIC KEYWORDS, two to four words (stretching frequency, HNC family).

Hard rules:
- DO NOT paraphrase or restate the item's sentence. A request is a LOOKUP LABEL,
  not a rewording of the question. If your request reads like the question with
  synonyms swapped in, replace it.
- Keep each request under 8 words. Most should be 2-5 words.
- No question marks. No "what is", no "how many", no "did you".
- When the item has an OPTION, the option is the thing being asked for: it MUST be
  identifiable from the request. Sibling breast cancer and sibling lung cancer are
  different variables and must get different requests.
- When the item is asked once per household member or sibling, name the RELATIONSHIP
  or the option, never a member number ("sibling", "household member", not "sibling 7").
- Never invent facts, prevalences, or findings. Use only the wording given.

Items:
{items}

Return ONLY a JSON object, no prose and no code fence, of the form:
{{"<id>": ["request one", "request two", ...], ...}}
with exactly {n} strings per id, and one key per item id above."""


def prompt_hash() -> str:
    return hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()[:16]


def render_item(t: dict) -> str:
    parts = [f'- id: {t["target_id"]}', f'  question: {t["stem"]}']
    if t.get("option"):
        parts.append(f'  option (this is the variable): {t["option"]}')
    if t.get("fold_size", 1) > 1:
        parts.append(f'  asked once per person, {t["fold_size"]} times')
    n_sib = len(t.get("siblings", []))
    if n_sib:
        parts.append(f'  one of {n_sib + 1} options under the same question')
    return "\n".join(parts)


JSON_RE = re.compile(r"\{.*\}", re.S)


def call_generator(prompt: str, timeout: int, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            p = subprocess.run(
                ["claude", "-p", "--model", GENERATOR_MODEL, "--allowed-tools", ""],
                input=prompt, capture_output=True, text=True, timeout=timeout)
            out = p.stdout.strip()
            m = JSON_RE.search(out)
            if not m:
                last = f"no JSON in output: {out[:200]}"
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
    items = "\n".join(render_item(t) for t in batch)
    prompt = PROMPT_TEMPLATE.format(n=n, items=items)
    raw = call_generator(prompt, timeout)
    pairs = []
    for t in batch:
        got = raw.get(str(t["target_id"])) or raw.get(t["target_id"]) or []
        seen = set()
        for q in got:
            if not isinstance(q, str):
                continue
            q = " ".join(q.split()).strip(" .?")
            kq = q.lower()
            if len(q) < 2 or kq in seen:
                continue
            seen.add(kq)
            pairs.append({"query": q, "target_id": t["target_id"],
                          "canonical_key": t["canonical_key"],
                          "construct_key": t["construct_key"]})
    res = {"batch": idx, "n_targets": len(batch), "pairs": pairs}
    shard.write_text(json.dumps(res))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--shard-dir", type=Path, required=True)
    ap.add_argument("--per-target", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=12)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    T = json.loads(a.targets.read_text())
    targets = T["targets"][: a.limit] if a.limit else T["targets"]
    a.shard_dir.mkdir(parents=True, exist_ok=True)

    batches = [targets[i:i + a.batch_size]
               for i in range(0, len(targets), a.batch_size)]
    jobs = [(i, b, a.per_target, a.shard_dir, a.timeout)
            for i, b in enumerate(batches)]

    t0 = time.time()
    results, failures = [], []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_batch, j): j[0] for j in jobs}
        done = 0
        for f in cf.as_completed(futs):
            done += 1
            try:
                results.append(f.result())
            except Exception as e:
                failures.append({"batch": futs[f], "error": str(e)})
            if done % 10 == 0 or done == len(jobs):
                el = time.time() - t0
                print(f"  {done}/{len(jobs)} batches  {el:.0f}s  "
                      f"failures {len(failures)}", flush=True)

    pairs = [p for r in sorted(results, key=lambda r: r["batch"]) for p in r["pairs"]]
    covered = {p["target_id"] for p in pairs}
    body = json.dumps(pairs, sort_keys=True).encode()
    artifact = {
        "schema": "compass_training_pairs/1",
        "provenance": {
            "generator_model": GENERATOR_MODEL,
            "generator_driver": "claude-code-cli --allowed-tools '' (no network, no tools)",
            "prompt_sha256_16": prompt_hash(),
            "prompt_template": PROMPT_TEMPLATE,
            "requests_per_target": a.per_target,
            "batch_size": a.batch_size,
            "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "wall_clock_s": round(time.time() - t0, 1),
            "source_targets": str(a.targets),
            "dictionary_version_hash": T["dictionary_version_hash"],
            "n_targets_in_source": len(T["targets"]),
        },
        "n_pairs": len(pairs),
        "n_targets_covered": len(covered),
        "n_targets_missing": len(targets) - len(covered),
        "missing_target_ids": sorted({t["target_id"] for t in targets} - covered),
        "failures": failures,
        "training_set_sha256": hashlib.sha256(body).hexdigest(),
        "pairs": pairs,
    }
    a.out.write_text(json.dumps(artifact, indent=1))
    print(f"pairs {len(pairs)}   targets covered {len(covered)}/{len(targets)}   "
          f"failed batches {len(failures)}")
    print(f"training_set_sha256 {artifact['training_set_sha256']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
