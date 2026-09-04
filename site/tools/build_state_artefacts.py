"""Turn the private captures under run/site/ into public artefacts.

Reads ``run/site/pipeline_state.json`` (capture_pipeline_state.py) and
``run/site/negatives_absence_check.json`` (src/verify_negatives.py) and writes
``funnel.json``, ``score.json`` and ``absence.json`` under ``site/artefacts``.
Only counts, flags, names of exports and domains, and provenance cross the
line; the captures' construct keys, stems and search patterns stay private.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "run" / "site"
OUT = REPO / "site" / "artefacts"
KEY_RE = re.compile(r"\bm\d+:Q\d+")


def write(name: str, doc: dict) -> None:
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if KEY_RE.search(text):
        raise SystemExit(f"refusing to write {name}: a variable key reached it")
    (OUT / name).write_text(text, encoding="utf-8")
    print("wrote", name)


def main() -> int:
    st = json.loads((RUN / "pipeline_state.json").read_text())
    ab = json.loads((RUN / "negatives_absence_check.json").read_text())
    ex = st["worked_frame_extra"]
    g = st["gate"]
    verdict_marks = sorted({v["estimability"] for v in g["verdicts"]})
    n_sources = sorted({v["n_source"] for v in g["verdicts"]})
    blocked_on = sorted({b for v in g["verdicts"] for b in v["blocked_on"]})
    prov_common = {
        "run_id": st["captured"],
        "commit": f"generation clone ralph-loop {st['generation_clone_head']}",
        "dictionary_version_hash": ab["dictionary_version_hash"],
    }
    write("funnel.json", {
        "schema": "compass_site/funnel/1",
        "provenance": {"source": "site/tools/capture_pipeline_state.py calling pipeline.auto_intake.worked_frame() and pipeline.gate.gate(allow_unestimable=False) in the generation clone; the same calls its `python -m pipeline.gate` makes", **prov_common},
        "stages": {
            "S1_enumerated": ex["enumerated"],
            "S2_pruned": ex["pruned_S2"],
            "S3_parked": ex["parked_S3"],
            "live": ex["live"],
            "S3_estimable": ex["estimable"],
            "S3_unknown": ex["unknown"],
            "S3_requires_derivation": ex["requires_derivation"],
        },
        "gate": {
            "allow_unestimable": g["allow_unestimable"],
            "live": len(g["verdicts"]),
            "passed": sum(1 for v in g["verdicts"] if v["passed"]),
            "blocked": sum(1 for v in g["verdicts"] if not v["passed"]),
            "estimability_marks": verdict_marks,
            "n_sources": n_sources,
            "missing_exports": list(g["missing_exports"]),
            "blocked_on": blocked_on,
        },
        "pairs_emitted": sum(1 for v in g["verdicts"] if v["passed"]),
    })
    env = st["generation_env"]
    write("score.json", {
        "schema": "compass_site/score/1",
        "provenance": {"source": "site/tools/capture_pipeline_state.py calling pipeline.generation_env.stamp() on the generation clone", **prov_common},
        "generation_env": {
            "key_present": env["key_present"],
            "key_fetchable": env["key_fetchable"],
            "tree_sha": env["tree_sha"],
            "tree_clean": env["tree_clean"],
            "branch": env["branch"],
            "clean_for_scoring": st["clean_for_scoring"],
        },
        "status": "gated",
        "scoring_has_run": False,
        "why_not": [
            "the estimability gate passes zero pairs without the two survey metadata exports, so there is no estimable denominator",
            "the baseline score runs once, on a tag, in a separate clone that holds the key; that item is still open in the pipeline loop",
        ],
        "estimable_denominator": ex["estimable"],
    })
    write("absence.json", {
        "schema": "compass_site/absence/1",
        "provenance": {"source": "src/verify_negatives.py re-run against the dictionary, the deploy targets and the negative-request fixture; patterns and adjacent keys stay private",
                       "run_id": prov_common["run_id"], "commit": "COMPASS main 265241d",
                       "dictionary_version_hash": ab["dictionary_version_hash"]},
        "n_dictionary_entries": ab["n_dictionary_entries"],
        "n_targets": ab["n_targets"],
        "n_negative_queries": ab["n_negative_queries"],
        "fields_searched": ab["fields_searched"],
        "all_domains_absent": ab["all_domains_absent"],
        "domains": [
            {"domain": k,
             "dictionary_entries_matching": v["dictionary_entries_matching_absent_pattern"],
             "targets_matching": v["target_corpus_matching_absent_pattern"],
             "adjacent_constructs_present": v["adjacent_constructs_present"]}
            for k, v in ab["domains"].items()
        ],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
