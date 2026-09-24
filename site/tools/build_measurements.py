"""Item 11 — extract the measurement figures from their committed sources.

Nothing is retyped. The encoder sweep rows are parsed out of the table in
``arm_hybrid_e_D.md`` §2 (the per-config JSONs are withheld and the document
is the committed record; the artifact says so). The shipped model's figures
are read from ``out/smoke_report_x86_64_Wright.json`` (tracked) and
``deploy/manifest.json``. Output: ``site/artifacts/measurements.json``.
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


def by_topic() -> list[dict]:
    """Every topic the characterisation measured, not the three the prose names.

    ``deploy/manifest.json::known_limitations[1]`` names three topics as
    examples -- the two worst and the biggest -- and this builder used to regex
    exactly those three out of that sentence, after which the page said "the
    rest are not grouped by topic".

    MEASURED 2026-09-16: that sentence was false. ``out/char_task4_strata.json``
    already groups every one of the fixture's rows into eleven topics whose
    ``n_rows`` sum to the fixture exactly, so eight were being suppressed --
    including every topic scoring better than the best one shown, and the single
    topic at 1.000. A reader saw the two worst and the biggest and concluded
    recall was uniformly poor by topic.

    The upstream file is withheld from the public tree, so this builder now runs
    on the training machine only and ``measurements.json`` ships the rows with
    that note. The manifest sentence stays the tracked public record and
    ``limitations`` cross-checks it against these rows.

    Returns:
        One row per topic, worst first: the topic, its R@1, the number of test
        questions, and the number of codebook entries those questions came from.

    Raises:
        SystemExit: When the withheld characterisation file is absent.
    """
    path = REPO / "out" / "char_task4_strata.json"
    if not path.exists():
        raise SystemExit(
            f"{path.relative_to(REPO)} is withheld from the public tree, so this builder "
            "runs on the training machine only. site/artifacts/measurements.json is the "
            "committed record of these figures; do not rebuild it here.")
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc["models"]["bge-small_ft"]["by_domain"]
    return sorted(({"topic": k, "recall_at_1": v["R@1"],
                    "n": v["n_rows"], "n_items": v["n_items"]}
                   for k, v in rows.items()),
                  key=lambda r: (r["recall_at_1"], r["topic"]))


def limitations(man: dict) -> dict:
    """Parse every figure out of the manifest's ``known_limitations`` prose.

    The manifest is the source the fixture note already cites, and until
    2026-09-09 the page kept only its first clause -- "recall is an upper
    bound" -- and dropped the shared generator family, the unknown
    register-alignment share, and the two strata at or near zero, while
    rendering the frozen-versus-fine-tuned comparison those sentences qualify.
    Parsed, never retyped: every regex must match or the build fails.

    Args:
        man: ``deploy/manifest.json`` as loaded.

    Returns:
        The structured limitations block for ``measurements.json``.
    """
    kl = man["known_limitations"]
    def grab(rx: str, text: str) -> tuple[str, ...]:
        m = re.search(rx, text)
        assert m, (rx, text)
        return m.groups()
    (pairs,) = grab(r"same generator family as the ([\d,]+) training pairs", kl[0])
    (gain,) = grab(r"An unknown share of the \+([\d.]+) over frozen bge-small is register alignment", kl[0])
    rho, pval = grab(r"Spearman (-?[\d.]+) \(permutation p ([\d.]+)\)", kl[0])
    quart = grab(r"quartile ([\d.]+) / ([\d.]+) / ([\d.]+) / ([\d.]+), non-monotonic", kl[0])
    named = re.findall(r"([\w/]+)(?: R@1)? ([\d.]+) \(n=(\d+)\)", kl[1])
    assert len(named) == 3, named
    topics = by_topic()
    index = {t["topic"]: t for t in topics}
    # The manifest sentence remains the TRACKED public record of these figures
    # while the rows come from a withheld file, so the two must agree or the
    # build stops: a silent disagreement would publish eleven rows that the one
    # sentence a public reader can check does not support. Names differ by
    # separator only -- the prose writes `residence/commute`, the artifact keys
    # it `residence_commute`.
    for name, r1, n_rows in named:
        t = index.get(name.replace("/", "_"))
        assert t, (name, sorted(index))
        assert t["recall_at_1"] == float(r1) and t["n"] == int(n_rows), (name, t, r1, n_rows)
    (missing,) = grab(r"contains no (.+?) row", kl[2])
    unmeasured = [x.strip() for x in re.split(r", | or ", missing)]
    never, gold, phr, once = grab(r"(\d+) of (\d+) gold items are retrieved on 0 of their (\d+) phrasings and (\d+) on 1 of", kl[3])
    return {
        "source": ("deploy/manifest.json known_limitations, parsed by "
                   "site/tools/build_measurements.py. The by-topic rows come from "
                   "out/char_task4_strata.json and are cross-checked against the three"
                   " topics that sentence names. The per-topic and phrasing files are "
                   "not in the public tree, so the manifest sentence is the tracked "
                   "record and this artifact ships the rows"),
        "generator_family_shared_with_training": True,
        "training_pairs": int(pairs.replace(",", "")),
        "gain_r1_over_frozen_bge_small": float(gain),
        "register_alignment_share": "unknown",
        "lexical_leakage": {
            "measured": True,
            "survives": False,
            "item_level_spearman": float(rho),
            "permutation_p": float(pval),
            "r1_by_query_gold_overlap_quartile": [float(q) for q in quart],
            "monotonic": False,
            "flat_within_query_length_groups": True,
        },
        "topics": topics,
        "unmeasured_topics": unmeasured,
        "phrasing": {"gold_items": int(gold), "phrasings_per_item": int(phr),
                     "items_retrieved_on_no_phrasing": int(never), "items_retrieved_on_one_phrasing": int(once)},
    }


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
            "sweep_artifacts_note": ("The per-configuration JSON files behind the "
                                     "sweep table are withheld from the public tree; "
                                     "the document is the committed record"),
        },
        "fixture": {"n_positive_rows": acc["I"]["ranks"].__len__(), "n_negative_rows": acc["I"]["n_negatives"],
                    "note": "queries were written by a model that saw the gold wording, by the same generator family as the training pairs, so recall is an upper bound and an unknown share of the fine-tuned model's gain over the frozen one is register alignment (manifest known_limitations, parsed below)"},
        "limitations": limitations(man),
        "sweep": {
            "what": ("frozen encoders (no fine-tuning), untemplated fixture queries, "
                     "full target set"),
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
                          "f1": thr["at_shipped_tau"]["f1"], "candidate_taus": thr["candidate_taus_exhaustive"],
                          # src/char_report.py::sweep, the code that computed them
                          "definitions": {"coverage": "positives answered (top cosine at or above min_cos) over all positives",
                                          "precision": "correct over answered",
                                          "recall": "correct over all positives, so abstaining costs recall"},
                          "selection_note": ("min_cos is the value that maximises F1 "
                                             "on the positives, and its precision, "
                                             "recall, coverage and F1 are reported on "
                                             "those same positives, so none of them "
                                             "has a held-out estimate. Only the "
                                             "negatives are held out")},
            "latency": {"query_ms_isolated_single": rep["latency"]["query_ms_isolated_single"],
                        "threads": rep["latency"]["threads"], "machine": rep["machine"]["machine"],
                        "note": ("measured on the serving machine, one query per "
                                 "forward pass, fp32, after warm-up; other machines "
                                 "differ, and the run artifacts on this page report "
                                 "their own")},
            "wrong_pick_detection": {"available": False,
                                     "note": ("How well the retriever detects its own "
                                              "wrong picks was measured, but the "
                                              "artifact was withdrawn from git and "
                                              "nothing on this page can reproduce the "
                                              "figure. It is measured, not missing, and"
                                              " it is not shown")},
        },
    }
    # The by-topic rows must account for every positive row in the fixture. The
    # three-topic version did not -- it carried 100 of them and told the reader
    # the rest were not grouped by topic -- so the completeness of that chart is
    # asserted here rather than left to the prose that describes it.
    covered = sum(t["n"] for t in out["limitations"]["topics"])
    assert covered == out["fixture"]["n_positive_rows"], (
        f"the by-topic rows cover {covered} of the fixture's "
        f"{out['fixture']['n_positive_rows']} positive rows; a bar chart that drops rows "
        "must say which, and how many")
    (REPO / "site" / "artifacts" / "measurements.json").write_text(json.dumps(out, indent=1) + "\n")
    print("wrote site/artifacts/measurements.json;", [r["model"] for r in out["sweep"]["rows"]], out["provenance"]["commit"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
