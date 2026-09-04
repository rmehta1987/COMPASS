"""Item 4 — run the real retriever and emit tier-A artefacts.

Runs only where the deploy bundle is complete (``deploy/model/`` and
``deploy/targets.json`` are withheld from the public tree). For each request
in ``requests.json`` it renders the shipped template, calls ``search`` and
``select`` on ``deploy/retriever.py`` exactly as a caller would, and records
what came back. Two files are written:

* ``site/artefacts/runs.json`` — public. Cosine, rank, margin, threshold,
  abstention, fold size and option position verbatim; every target renamed
  ``TARGET-NN`` by first appearance; domain from ``src/char_strata.py``; no
  key, stem, option label or module anywhere. The writer refuses to save a
  file that matches a key pattern.
* ``run/site/<run_id>/`` — private, gitignored. The pseudonym map and the raw
  hits with keys, so a reader with the bundle can verify every public row.

Usage (training machine)::

    /path/to/venv/python site/tools/run_examples.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEPLOY = REPO / "deploy"
KEY_RE = re.compile(r"\bm\d+:Q\d+")


def load(path: Path, name: str):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()


def main() -> int:
    import torch
    import transformers

    R = load(DEPLOY / "retriever.py", "compass_deploy_retriever")
    strata = load(REPO / "src" / "char_strata.py", "compass_char_strata")
    r = R.CompassRetriever(DEPLOY)
    reqs = json.loads((HERE / "requests.json").read_text())
    by_construct: dict[str, list[dict]] = {}
    for t in r.targets:
        by_construct.setdefault(t["construct_key"], []).append(t)
    for v in by_construct.values():
        v.sort(key=lambda t: t["target_id"])

    run_id = datetime.now(timezone.utc).strftime("site-%Y%m%dT%H%M%SZ")
    pseud: dict[str, str] = {}

    def name(key: str) -> str:
        if key not in pseud:
            pseud[key] = f"TARGET-{len(pseud) + 1:02d}"
        return pseud[key]

    def describe(hit: dict) -> dict:
        t = r.targets[hit["target_id"] - 1]
        sibs = by_construct[t["construct_key"]]
        pos = next(i for i, s in enumerate(sibs, 1) if s["target_id"] == t["target_id"])
        return {
            "pseudonym": name(hit["key"]),
            "domain": strata.domain_of(t["stem"]),
            "level": "individual",
            "option_position": pos if t["option"] else None,
            "option_count": len(sibs) if t["option"] else None,
            "fold_size": hit["fold_size"],
            "n_siblings": hit["n_siblings"],
        }

    public = []
    private = []
    warm = r.search("warm-up", k=1)  # first call pays model warm-up; not timed
    for ex in reqs["examples"]:
        req = R.RetrievalRequest(construct=ex["request"], role=R.VariableRole(ex["role"]),
                                 instances=tuple(ex["instances"]))
        q = req.to_query()
        dropped = [i for i in ex["instances"] if i not in q]
        k = 10
        hits = r.search(q, k=k)
        chosen = r.select(q)
        times = []
        for _ in range(7):
            t0 = time.perf_counter(); r.search(q, k=1); times.append((time.perf_counter() - t0) * 1000)
        top = hits[0]
        rec = {
            "abstained": chosen is None,
            "top_cos": top["cos"],
            "rank": None if chosen is None else 1,
            "margin_12": round(hits[0]["cos"] - hits[1]["cos"], 6),
            "gap_above_threshold": round(top["cos"] - r.min_cos, 6),
            "target": None if chosen is None else describe(chosen),
            "nearest_if_abstained": describe(top) if chosen is None else None,
            "query_ms_median": round(statistics.median(times), 2),
        }
        tool_log = [
            {"tool": "search", "args": {"query": q, "k": k},
             "returned": {"n_hits": len(hits), "top_cos": top["cos"], "top": name(top["key"]),
                          "top_domain": strata.domain_of(r.targets[top["target_id"] - 1]["stem"])}},
            {"tool": "select", "args": {"query": q, "min_cos": r.min_cos},
             "returned": None if chosen is None else
             {"target": name(chosen["key"]), "cos": chosen["cos"], "margin_12": chosen["margin_12"]}},
        ]
        public.append({
            "id": ex["id"], "label": ex["label"], "origin": ex["origin"],
            "request": {"text": ex["request"], "construct": ex["request"], "role": ex["role"],
                        "instances": ex["instances"], "population": None},
            "rendered_query": q, "instances_dropped_as_covered": dropped,
            "tool_log": tool_log, "record": rec,
            "candidates": [{"rank": i, **describe(h), "cos": h["cos"]} for i, h in enumerate(hits, 1)],
        })
        private.append({"id": ex["id"], "query": q, "select": chosen,
                        "hits": [{**h, "stem": h["stem"], "option": h["option"]} for h in hits]})

    m = r.manifest
    out = {
        "schema": "compass_site/runs/1",
        "provenance": {
            "source": "site/tools/run_examples.py calling deploy/retriever.py search() and select() on the frozen bundle; requests from site/tools/requests.json",
            "run_id": run_id,
            "git_head": git("rev-parse", "--short", "HEAD"),
            "machine": {"node": platform.node(), "machine": platform.machine(), "platform": platform.platform(),
                        "python": platform.python_version(), "torch": torch.__version__,
                        "transformers": transformers.__version__, "threads": r.threads},
            "bundle": {"manifest_sha256": sha(DEPLOY / "manifest.json"),
                       "retriever_py_sha256": sha(DEPLOY / "retriever.py"),
                       "template_py_sha256": sha(DEPLOY / "template.py"),
                       "dictionary_version_hash": m["dictionary_version_hash"],
                       "frozen": m["frozen"]},
            "pseudonyms": "TARGET-NN by first appearance in this file; the map is in run/site/<run_id>/ on the private side and is not published",
            "tier": "A",
        },
        "threshold": {"min_cos": r.min_cos, "source": "deploy/manifest.json abstention.default_min_cos",
                      "how_chosen": "F1-maximising value over the positive fixture rows only; the held-out negative set reported the rejection rate and did not choose the value (deploy/manifest.json abstention.how_chosen)"},
        "corpus": {"n_targets": m["corpus"]["n_targets"], "n_constructs": m["corpus"]["n_constructs"],
                   "n_folded_family": m["corpus"]["n_folded_family"], "embed_dim": m["encoder"]["embed_dim"],
                   "params_m": m["encoder"]["params_m"]},
        "level_rule": "every target is individual-level: the instrument carries no area-level construct (see absence.json)",
        "domain_rule": "src/char_strata.py::domain_of over the target's stem, priority-ordered keyword regex, first match wins; 'unclassified' when none matches",
        "latency_note": "query_ms_median is seven isolated single-query search calls on this machine after warm-up, at the manifest's pinned thread count; it is not the serving-machine figure",
        "examples": public,
    }
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if KEY_RE.search(text):
        raise SystemExit("refusing to write: a variable key reached the public artefact")
    (REPO / "site" / "artefacts" / "runs.json").write_text(text, encoding="utf-8")
    priv = REPO / "run" / "site" / run_id
    priv.mkdir(parents=True, exist_ok=True)
    (priv / "pseudonym_map.json").write_text(json.dumps(pseud, indent=1) + "\n")
    (priv / "raw_runs.json").write_text(json.dumps(private, indent=1, ensure_ascii=False) + "\n")
    print(f"run_id {run_id}  examples {len(public)}  pseudonyms {len(pseud)}  private -> {priv.relative_to(REPO)}")
    for ex in public:
        rec = ex["record"]
        print(f"  {ex['id']:14s} cos {rec['top_cos']:.4f} gap {rec['gap_above_threshold']:+.4f} "
              f"abstained {rec['abstained']} margin {rec['margin_12']:.4f} ms {rec['query_ms_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
