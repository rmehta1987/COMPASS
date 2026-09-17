"""Build ``site/artifacts/roc.json`` — two ROC curves for the shipped retriever.

WHY TWO. The bundle reports one AUROC, 0.9823, and read alone it says the
retriever is nearly perfect. It is nearly perfect at ONE question: does this
request have any match in the codebook at all. The separate question a reader
actually cares about — is the top match the RIGHT item — separates at 0.6399,
barely above chance. Both curves are drawn so that contrast is the panel's
subject rather than a footnote under a single flattering number.

WHAT IT READS. ``out/char_pos_bge-small_ft.json`` and
``out/char_neg_bge-small_ft.json``, the per-row characterisation of the shipped
fine-tuned bge-small. Both are under ``out/``, which ``.gitignore`` excludes, so
this builder runs on the training machine only — the same arrangement as
``build_measurements.py`` parsing a tracked report. Nothing it emits is
instrument content: the output carries curve coordinates and counts, never a
query, a stem, an option or a key, because ``site/artifacts`` is scanned by
``site/tools/no_instrument.py`` and served publicly.

WHY THE COORDINATES ARE PERCENTAGES. ``site/tools/no_fabrication.py`` forbids a
numeric literal in the page script, so the page cannot multiply a rate by a
hundred to place a mark. Emitting percentages here means the page interpolates
the value and the stylesheet supplies the unit.

THE CROSS-CHECK IS THE POINT. Each AUROC computed here is asserted against the
figure the project already published for the same pair, so a disagreement fails
the build rather than shipping a second, quieter number.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "out"
ARTIFACTS = ROOT / "site" / "artifacts"


def auroc(pos: list[float], neg: list[float]) -> float:
    """Area under the ROC curve, by rank sum, with ties averaged.

    Args:
        pos: Scores of the positive class.
        neg: Scores of the negative class.

    Returns:
        The area, or 0.0 when either class is empty.
    """
    if not pos or not neg:
        return 0.0
    xs = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda t: t[0])
    total, i = 0.0, 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1][0] == xs[i][0]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        total += mean_rank * sum(1 for k in range(i, j + 1) if xs[k][1] == 1)
        i = j + 1
    n1, n0 = len(pos), len(neg)
    return (total - n1 * (n1 + 1) / 2) / (n1 * n0)


def curve(pos: list[float], neg: list[float]) -> list[dict[str, float]]:
    """ROC points in CSS coordinates: x is the false-positive rate, y from the top.

    Consecutive duplicates are dropped — a staircase repeats a coordinate many
    times and every repeat would be one more node in the page.

    Args:
        pos: Scores of the positive class.
        neg: Scores of the negative class.

    Returns:
        Points with `x` and `y` as percentages, `y` measured from the top edge
        so the page needs no arithmetic to place them.
    """
    taus = sorted({*pos, *neg}, reverse=True)
    pts: list[dict[str, float]] = [{"x": 0.0, "y": 100.0}]
    for t in taus:
        tpr = sum(1 for v in pos if v >= t) / len(pos)
        fpr = sum(1 for v in neg if v >= t) / len(neg)
        p = {"x": round(fpr * 100, 1), "y": round((1 - tpr) * 100, 1)}
        if p != pts[-1]:
            pts.append(p)
    last = {"x": 100.0, "y": 0.0}
    if pts[-1] != last:
        pts.append(last)
    return pts


def p50(xs: list[float]) -> float:
    """The nearest-rank 50th percentile, to four places.

    `src/char_report.py::pct` is the convention every figure in this project's
    characterisation uses, and it is NOT a median: it returns
    `sorted(xs)[int(q * len(xs))]`, so on an even-sized group it is the value
    just above the middle rather than the average of the two, and it is always
    one of the observed values.

    Re-derived here rather than trusted so the page can describe the figure
    correctly. Copying it and calling it a median is what the page did, and two
    of the four it printed were not medians: `absent` 0.5961 against a true
    median of 0.5908 over 44 rows, `answerable` 0.8795 against 0.8781 over 224.
    The other two matched only because their group sizes are odd.

    Args:
        xs: The group's scores.

    Returns:
        The value at the nearest rank for the midpoint, rounded to four places.
    """
    return round(sorted(xs)[len(xs) // 2], 4)


def main() -> int:
    """Write the artifact, or fail if a computed AUROC contradicts the published one.

    Returns:
        0 on success; non-zero is raised as an assertion instead.
    """
    posr = json.loads((OUT / "char_pos_bge-small_ft.json").read_text())["rows"]
    negr = json.loads((OUT / "char_neg_bge-small_ft.json").read_text())["rows"]
    sep = json.loads((OUT / "char_task2_negatives.json").read_text())["bge-small_ft"]
    cal = json.loads((OUT / "char_task3_calibration.json").read_text())["bge-small_ft"]
    man = json.loads((ROOT / "deploy" / "manifest.json").read_text())
    tau = man["abstention"]["default_min_cos"]

    p_all = [r["cos_top1"] for r in posr]
    n_all = [r["cos_top1"] for r in negr]
    ok = [r["cos_top1"] for r in posr if r["correct"]]
    bad = [r["cos_top1"] for r in posr if not r["correct"]]

    a_match, a_right = auroc(p_all, n_all), auroc(ok, bad)
    want_match = sep["separation_auroc"]["cos_top1_positives_all_vs_negatives"]
    want_right = cal["separation_auroc_correct_vs_incorrect"]["cos_top1"]
    assert round(a_match, 4) == want_match, f"match AUROC {a_match} != {want_match}"
    assert round(a_right, 4) == want_right, f"right AUROC {a_right} != {want_right}"

    # THE FIXTURE'S SHAPE, derived from the rows rather than parsed from prose.
    # The 224 requests are 56 codebook entries described four ways each, so a
    # count out of 224 counts requests, not distinct targets. The page quoted
    # every one of those counts at 224 and said so nowhere. Only the two counts
    # leave here -- `gold_key` is instrument content and stays in `out/`.
    per_item = sorted(set(Counter(r["gold_key"] for r in posr).values()))
    assert len(per_item) == 1, (
        f"phrasings per gold item are not uniform: {per_item}. The page says every "
        "entry was described the same number of ways; if that stops being true the "
        "sentence has to change, not this assert")
    n_items = len({r["gold_key"] for r in posr})
    assert n_items * per_item[0] == len(posr), (n_items, per_item, len(posr))

    rejected = sum(1 for v in n_all if v < tau)
    # Top-1 accuracy is the figure both areas are ABOUT, and the panel showed
    # neither it nor its denominator -- so 0.9823 read as "98% accurate". It is
    # asserted against the bundle's own headline for the same fixture.
    acc = round(len(ok) / len(posr), 3)
    assert acc == man["measured"]["recall_at1_224_row_fixture"], (
        f"top-1 accuracy {acc} != bundle {man['measured']['recall_at1_224_row_fixture']}")
    # Quoted from the published percentiles rather than recomputed: these are
    # the project's own summaries of the same rows, and a second estimator of a
    # median is a second number for one quantity.
    cos, cbc = sep["cos_top1"], cal["cos_top1_by_correctness"]
    # Every figure in `scores` re-derived from the rows and asserted against the
    # published summary, exactly as the two areas are. Quoting them unchecked is
    # how `p50` came to be printed as a median: nothing tied the label on the
    # page to the rule that produced the number.
    for label, published, derived in (
            ("absent p50", cos["negatives_all"]["p50"], p50(n_all)),
            ("answerable p50", cos["positives_all"]["p50"], p50(p_all)),
            ("right p50", cbc["correct"]["p50"], p50(ok)),
            ("wrong p50", cbc["incorrect"]["p50"], p50(bad)),
            ("wrong max", cbc["incorrect"]["max"], round(max(bad), 4)),
            ("right min", cbc["correct"]["min"], round(min(ok), 4))):
        assert published == derived, f"{label}: published {published} != {derived}"
    pts_match, pts_right = curve(p_all, n_all), curve(ok, bad)
    doc: dict[str, Any] = {
        "schema": "compass_site/roc/1",
        "provenance": {
            "source": ("computed by site/tools/build_roc.py from "
                       "out/char_pos_bge-small_ft.json and "
                       "out/char_neg_bge-small_ft.json, the per-row "
                       "characterisation of the shipped fine-tuned bge-small; "
                       "out/ is gitignored, so this runs on the training "
                       "machine only. Each area is asserted against the figure "
                       "already published for the same pair in "
                       "out/char_task2_negatives.json and "
                       "out/char_task3_calibration.json"),
            "run_id": json.loads(
                (OUT / "char_pos_bge-small_ft.json").read_text())["source"],
            "dictionary_version_hash": man["dictionary_version_hash"],
        },
        "top1_accuracy": acc,
        "scores": {
            "what": ("top match score at the nearest rank for the midpoint, and "
                     "the worst overlap. Not a median: on an even-sized group it "
                     "is the value just above the middle, and it is always one of "
                     "the observed scores. src/char_report.py::pct is the rule, "
                     "and build_roc.py re-derives every figure here from the rows"),
            "absent_p50": cos["negatives_all"]["p50"],
            "answerable_p50": cos["positives_all"]["p50"],
            "right_p50": cbc["correct"]["p50"],
            "wrong_p50": cbc["incorrect"]["p50"],
            "wrong_max": cbc["incorrect"]["max"],
            "right_min": cbc["correct"]["min"],
        },
        "fixture": {
            "n_targets": man["corpus"]["n_targets"],
            "n_questions": len(posr),
            "n_absent_requests": len(negr),
            "n_top_match_right": len(ok),
            "n_top_match_wrong": len(bad),
            "n_right_construct_wrong_item":
                sum(1 for r in posr if r["right_construct"] and not r["correct"]),
            "n_gold_is_a_folded_family": sum(1 for r in posr if r["gold_folded"]),
            # In ENTRIES as well as rows. Both counts are 56 here for different
            # reasons -- 56 entries in the fixture, and 56 rows whose gold is a
            # family -- and the page stated them four sentences apart in one
            # paragraph, where they read as the same set. They are not: the
            # family rows are 14 entries described four ways.
            "n_gold_items_folded_family": len({r["gold_key"] for r in posr
                                               if r["gold_folded"]}),
            "n_gold_items": n_items,
            "phrasings_per_item": per_item[0],
        },
        # The axes' own bounds and sense, read off the emitted points rather
        # than assumed. The page may not hold a numeric literal, so without
        # these it could print no tick at all -- and it printed none: neither
        # axis was named or scaled anywhere, which left the reader no way to
        # check the chance diagonal, or even to know which way "better" runs.
        # `y_measured_from` states the convention that `curve` applies and that
        # `parse.py::roc_reference_line_corners` holds the stylesheet to.
        "axes": {
            "unit": "percent",
            "min": min(q[k] for c in (pts_match, pts_right) for q in c for k in "xy"),
            "max": max(q[k] for c in (pts_match, pts_right) for q in c for k in "xy"),
            "y_measured_from": "top",
        },
        "curves": [
            {"id": "match",
             "what": "does this request have any match in the codebook at all",
             "positive": "a request whose construct is in the codebook",
             "negative": "a held-out request whose construct is absent",
             "auroc": a_match, "n_positive": len(p_all), "n_negative": len(n_all),
             "points": pts_match},
            {"id": "right",
             "what": "is the top match the right item",
             "positive": "the top match was the gold target",
             "negative": "the top match was some other target",
             "auroc": a_right, "n_positive": len(ok), "n_negative": len(bad),
             "points": pts_right},
        ],
        "abstention": {
            # Where the shipped threshold actually sits on the match curve, so
            # the panel can mark the operating point rather than leave the
            # reader to find it. Same CSS coordinates as a curve point.
            "operating_point": {
                "x": round(sum(1 for v in n_all if v >= tau) / len(n_all) * 100, 1),
                "y": round((1 - sum(1 for v in p_all if v >= tau) / len(p_all)) * 100, 1),
            },
            "min_cos": tau,
            "negatives_rejected": rejected,
            "n_negatives": len(n_all),
        },
    }
    (ARTIFACTS / "roc.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    pts = sum(len(c["points"]) for c in doc["curves"])
    print(f"ok    roc: match {a_match:.4f}, right {a_right:.4f}, "
          f"{rejected}/{len(n_all)} negatives rejected at {tau}, {pts} point(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
