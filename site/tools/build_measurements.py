"""Item 11 — extract the measurement figures from their committed sources.

Nothing is retyped. The encoder sweep rows are parsed out of the table in
``arm_hybrid_e_D.md`` §2 (the per-config JSONs are withheld and the document
is the committed record; the artefact says so). The shipped model's figures
are read from ``out/smoke_report_x86_64_Wright.json`` (tracked) and
``deploy/manifest.json``. Output: ``site/artefacts/measurements.json``.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SWEEP = ["bge-small", "bge-base", "embeddinggemma", "bge-large", "qwen3-0.6b"]


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()


def num(s: str) -> float | int:
    s = s.replace("*", "").replace(",", "").strip()
    return float(s) if "." in s else int(s)


def sweep_rows() -> list[dict]:
    doc = (REPO / "arm_hybrid_e_D.md").read_text(encoding="utf-8")
    sec = doc.split("## 2. Task 1")[1].split("### 2a")[0]
    rows = []
    for line in sec.splitlines():
        if not line.startswith("|") or "config" in line or "---" in line:
            continue
        cells = [c.strip().replace("**", "") for c in line.strip("|").split("|")]
        if cells[0] not in SWEEP:
            continue
        rows.append({"model": cells[0], "params_m": num(cells[1].rstrip("M")),
                     "recall_at_1": num(cells[2]), "recall_at_5": num(cells[3]),
                     "recall_at_10": num(cells[4]), "recall_at_25": num(cells[5]),
                     "recall_at_50": num(cells[6]), "rank_p50": num(cells[7]),
                     "rank_p90": num(cells[8]), "rank_max": num(cells[9]),
                     "encode_s": num(cells[10].rstrip(" s")), "ms_per_query": num(cells[11])})
    assert [r["model"] for r in rows] == sorted(SWEEP, key=[r["model"] for r in rows].index), rows
    assert len(rows) == len(SWEEP), [r["model"] for r in rows]
    return sorted(rows, key=lambda r: r["params_m"])


def main() -> int:
    rep = json.loads((REPO / "out" / "smoke_report_x86_64_Wright.json").read_text())
    man = json.loads((REPO / "deploy" / "manifest.json").read_text())
    acc = rep["acceptance"]
    thr = rep["threshold"]["I"]
    sweep_commit = git("log", "-1", "--format=%h", "--", "arm_hybrid_e_D.md")
    report_commit = git("log", "-1", "--format=%h", "--", "out/smoke_report_x86_64_Wright.json")
    out = {
        "schema": "compass_site/measurements/1",
        "provenance": {
            "source": "site/tools/build_measurements.py parsing arm_hybrid_e_D.md §2 (encoder sweep) and reading out/smoke_report_x86_64_Wright.json + deploy/manifest.json (shipped model)",
            "commit": f"arm_hybrid_e_D.md {sweep_commit}; smoke report {report_commit}; main 265241d",
            "run_id": f"sweep measured 2026-09-02/03 (x86, frozen encoders); smoke report run {rep['run']} on {rep['machine']['hostname']}",
            "sweep_artefacts_note": "the per-config JSONs the sweep table was written from are withheld from the public tree; the document is the committed record",
        },
        "fixture": {"n_positive_rows": acc["I"]["ranks"].__len__(), "n_negative_rows": acc["I"]["n_negatives"],
                    "note": "queries were written by a model that saw the gold wording; recall is an upper bound (manifest known_limitations)"},
        "sweep": {
            "what": "frozen encoders, no fine-tuning, untemplated fixture queries, full target corpus",
            "dictionary_version_hash": "3dc8415eccfe",
            "machine": "x86, CPU only",
            "columns": [["model", "model"], ["params_m", "params"], ["recall_at_1", "R@1"], ["recall_at_5", "R@5"],
                        ["recall_at_10", "R@10"], ["recall_at_25", "R@25"], ["recall_at_50", "R@50"],
                        ["rank_p50", "rank p50"], ["rank_p90", "p90"], ["rank_max", "max"], ["ms_per_query", "ms / query"]],
            "rows": sweep_rows(),
        },
        "shipped": {
            "model": "bge-small, fine-tuned",
            "params_m": man["encoder"]["params_m"],
            "embed_dim": man["encoder"]["embed_dim"],
            "training": {"negatives": "in-batch negatives only",
                         "temperature": float(re.search(r"t=([\d.]+)", man["encoder"]["training_config"]).group(1))},
            "dictionary_version_hash": man["dictionary_version_hash"],
            "n_targets": man["corpus"]["n_targets"],
            "arm_columns": [["recall_at_1", "R@1"], ["recall_at_5", "R@5"], ["recall_at_10", "R@10"],
                            ["rank_p50", "rank p50"], ["rank_p90", "p90"], ["rank_max", "max"]],
            "arms": {
                k: {"label": acc[k]["label"], "recall_at_1": acc[k]["R@1"], "recall_at_5": acc[k]["R@5"],
                    "recall_at_10": acc[k]["R@10"], "rank_p50": acc[k]["rank_p50"], "rank_p90": acc[k]["rank_p90"],
                    "rank_max": acc[k]["rank_max"], "negatives_rejected": acc[k]["negatives_rejected"],
                    "n_negatives": acc[k]["n_negatives"], "auroc_absent_vs_present": acc[k]["auroc"]}
                for k in ("S", "I")
            },
            "threshold": {"min_cos": thr["shipped_tau"], "coverage": thr["at_shipped_tau"]["coverage"],
                          "precision": thr["at_shipped_tau"]["precision"], "recall": thr["at_shipped_tau"]["recall"],
                          "f1": thr["at_shipped_tau"]["f1"], "candidate_taus": thr["candidate_taus_exhaustive"]},
            "latency": {"query_ms_isolated_single": rep["latency"]["query_ms_isolated_single"],
                        "threads": rep["latency"]["threads"], "machine": rep["machine"]["machine"],
                        "note": "serving machine, one query per forward pass, fp32, warm; other machines differ (the run artefacts on this page report their own)"},
            "wrong_pick_detection": {"available": False,
                                     "note": "the AUROC for correct-vs-incorrect picks under the shipped arm lives only in an artefact withdrawn from git and is not shown"},
        },
    }
    (REPO / "site" / "artefacts" / "measurements.json").write_text(json.dumps(out, indent=1) + "\n")
    print("wrote site/artefacts/measurements.json;", [r["model"] for r in out["sweep"]["rows"]], out["provenance"]["commit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
