"""Build site/artifacts/metrics.json — the scored baseline, instrument-free.

The Metrics tab answers one question honestly: what has actually been measured,
and what does the number mean. Two sources feed it, both read here and never
transcribed by hand:

  * the scored baseline in the scoring clone (`artefacts/<run>/`), which is the
    only place the prevalence key exists and the only place scoring may run;
  * the cohort bibliography `benchmark/cohort_papers.py`, which is tracked and
    public, and is held out from the TOOL layer, not from people.

WHAT IS DELIBERATELY NOT IN THIS FILE. No variable key, no instrument wording,
no `pair_id`, no `protocol_id`. Those two read as a module and question id
joined by `_to_` and by an arrow respectively, so both are variable keys in
disguise and both fail site-check step 2 on purpose — which is why this
docstring describes their shape instead of showing one. Each artifact is
identified here by its
`record_hash` alone. A reviewer who holds the dictionary sees the real pair over
the endpoint's `/api/metrics`, which is where the instrument is allowed to be.

WHAT THE BIBLIOGRAPHY DOES NOT CARRY. Per paper there is a prose `design`
("exposure to outcome, plus the method where it is distinctive") but no exposure
or outcome resolved against the instrument. Resolving those is task C12 and is
not built. Matching itself IS automatic -- `benchmark/baseline_score.py` scores
every emitted artifact against the whole bibliography -- but it can only reach
the papers whose outcome keys the held-out key records. That is what caps the
ceiling, and it is stated in the artifact rather than papered over.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCORE = Path("/home/mehta5/compass-score")
COMPASS = Path("/home/mehta5/COMPASS")
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "metrics.json"
RUN = "b3-20260904"


def one(pattern: str, text: str) -> str | None:
    """Return the first capture of `pattern` in `text`, or None.

    Args:
        pattern: A regular expression with one group.
        text: The text to search.

    Returns:
        The captured string, or None when the pattern does not match.
    """
    m = re.search(pattern, text)
    return m.group(1) if m else None


def main() -> int:
    """Write metrics.json from the scored run and the bibliography.

    Returns:
        0 on success, 1 when a source is missing.
    """
    run_dir = SCORE / "artefacts" / RUN
    md = run_dir / "BASELINE.md"
    if not md.is_file():
        print(f"FAIL  no scored run at {md}")
        return 1
    text = md.read_text(encoding="utf-8")
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    sys.path.insert(0, str(COMPASS))
    from benchmark.cohort_papers import COHORT_PAPERS

    abstained = {p: int(n) for p, n in
                 re.findall(r"^- (\d+): (\d+) of the line", text, re.M)}

    # The SCORED set is the ledger's `emitted` rows, not the directory listing.
    # Thirty-nine files sit in the run directory and only twenty-eight were
    # scored: a discarded pair can still have written its artifact, so globbing
    # the directory would silently inflate the denominator by eleven.
    ledger = [json.loads(x) for x in
              (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if x]
    emitted = {r["record_hash"]: r for r in ledger if r["outcome"] == "emitted"}

    artifacts = []
    for f in sorted(run_dir.glob("m2q*.json")):
        # `artefact`, en-GB: the key belongs to compass-score's schema, not to
        # this site. Everything the SITE spells is `artifact`; the four places
        # that reach into the scoring clone keep its spelling, and a blanket
        # rename that catches them fails loudly here rather than quietly.
        a = json.loads(f.read_text(encoding="utf-8"))["artefact"]
        if a["record_hash"] not in emitted:
            continue
        pr = a["protocol"]
        row = emitted[a["record_hash"]]
        artifacts.append({
            "record_hash": a["record_hash"],
            "estimability": a["estimability"],
            "exposure_stratum": row["exposure_stratum"],
            "outcome_stratum": row["outcome_stratum"],
            "n_adjusted": len(pr["adjusted_covariates"]),
            "n_excluded": len(pr["excluded_variables"]),
            "n_sought_not_found": len(pr["sought_covariates"]),
            "n_undetermined": len(pr["undetermined_covariates"]),
            "n_source": pr["estimability"]["n_source"],
            "modules_required": pr["estimability"]["modules_required"],
        })

    doc = {
        "schema": "compass_site/metrics/1",
        "provenance": {
            "run_id": RUN,
            "source": ("scored in the clone that holds the prevalence key, on a "
                       "tag, before any tuning; this page reads the result and "
                       "never the key"),
            "baseline_md": f"artefacts/{RUN}/BASELINE.md",
            "bibliography": "benchmark/cohort_papers.py",
            "dictionary_version_hash": one(r"dictionary: (\w+)", text),
            "tree_sha": one(r"tree: (\w+)", text),
        },
        "headline": one(r"\*\*(Ceiling:.*?)\*\*", text),
        "question_answered": one(r"Question answered: (.+)", text),
        "ceiling": {
            "max_matched": int(one(r"ceiling: max matched / max rate \| (\d+)", text)),
            "matchable_papers": int(one(r"\((\d+) matchable papers\)", text)),
            "papers_in_table": int(one(r"papers in the table: (\d+)", text)),
            "with_outcome_key": int(one(r"with an outcome key on record: (\d+)", text)),
            "with_exposure_resolved": int(
                one(r"with an exposure the retriever resolved: (\d+)", text)),
        },
        "observed": {
            "matched": int(one(r"\| matched \(N\) \| (\d+)", text)),
            "scored": summary["by_outcome"]["emitted"],
            "ledger_denominator": summary["total_generated_this_run"],
            "by_outcome": summary["by_outcome"],
            "strata": summary["strata"],
            "artifact_files_on_disk": len(list(run_dir.glob("m2q*.json"))),
            "denominator_note": ("the scored set is the ledger's `emitted` rows. "
                                 "More artifact files than that sit in the run "
                                 "directory, because a discarded pair can still "
                                 "have written one; the extras are not scored and "
                                 "are not listed here"),
        },
        "verdicts": dict(re.findall(r"^- (\w+): (\w+)$", text, re.M)),
        "artifacts": artifacts,
        "papers": [
            {"pmid": int(r.pmid), "year": r.year, "venue": r.venue,
             "design": r.design, "n": r.n,
             "inventoried_before_2026_08_27": r.inventoried_before_2026_08_27,
             "exposure_terms_abstained": abstained.get(r.pmid, 0)}
            for r in COHORT_PAPERS],
        "reads": {
            "establishes": ("that the harness runs end to end, refuses unstamped "
                            "artifacts and emits clean verdicts"),
            "is_not": ("a measurement of hypothesis quality. The observed rate IS "
                       "the ceiling, so a pipeline that reasoned perfectly would "
                       "score exactly the same"),
            "why_the_ceiling_is_low": ("a paper is matchable only when its outcome "
                                       "key is on record and its exposure resolves "
                                       "against the instrument; one paper of "
                                       "sixteen clears both"),
            # The recurring question from readers, asked twice now: why are there
            # more artifacts than papers, and which paper is each artifact from?
            # The premise is the confusion -- the two are not two counts of one
            # population, and an artifact is not FROM a paper at all.
            # Rewritten 2026-09-09 after the operator read the first version and
            # asked what it meant. Plain nouns, one idea per clause, and the
            # consequence (no PMID) stated as a result rather than an aside.
            "how_the_two_populations_relate": (
                "an artifact is a pair of questionnaire items that the pipeline "
                "proposed by itself, by working through the instrument; a paper "
                "is a published study about the same cohort. Neither list was "
                "built from the other, so there is no reason for the two counts "
                "to match. Scoring compares them: every artifact below was "
                "checked against all sixteen papers, and none matched one"),
            # An earlier version of the page said the artifacts were "not
            # joined" to the papers. That was wrong, and the operator caught it:
            # `benchmark/baseline_score.py` scores every emitted artifact
            # against the whole bibliography. What C12 has not built is the FULL
            # per-paper key -- covariates, model form, tier -- not the join.
            "what_the_paper_column_means": (
                "every artifact here was scored against the bibliography. An "
                "artifact matches a paper when the paper's outcome key is one "
                "the artifact used, and the paper's exposure terms resolve "
                "through the deployed retriever to the artifact's exposure. "
                "None matched, so the column reads none: a scored result, not a "
                "missing feature. It can only reach the papers that have an "
                "outcome key on record, which is what caps the ceiling"),
            # Sourced from the run's own log line for item 15d, which records
            # why a matchable paper still yields a zero ceiling.
            "why_no_match_was_available": (
                "That paper is outside the frame this run drew from, so no "
                "match was available to find: none were possible, and none "
                "were found. A pipeline that reasoned perfectly would have "
                "scored the same"),
        },
        "not_built": [
            # Rewritten 2026-09-09. The previous text said "no scored artifact
            # can be matched to a paper automatically", which is wrong: that is
            # exactly what `benchmark/baseline_score.py` does. What C12 has not
            # built is the REST of the per-paper key.
            {"what": "the full per-paper key",
             "why": ("matching is already automatic -- every emitted artifact "
                     "is scored against the whole bibliography, taking each "
                     "paper's outcome keys from the held-out key and resolving "
                     "its exposure terms through the deployed retriever. What "
                     "is missing is the rest of that key: the covariate set, "
                     "the model form and the tier, which is task C12. Until it "
                     "exists the comparison reaches only the papers whose "
                     "outcome keys are on record, and that is what caps the "
                     "ceiling")},
            {"what": "scoring from this page",
             "why": ("scoring needs benchmark/prevalence_key.py and runs exactly "
                     "once, on a tag, before any tuning, so that it cannot become "
                     "a feedback signal. A button that re-scored on demand would "
                     "break that, not complete it")},
        ],
        "pubmed_base": "https://pubmed.ncbi.nlm.nih.gov/",
        "instrument_withheld_here": ("Each scored artifact is identified by its "
                                     "record hash. The exposure and outcome keys "
                                     "and their wording are instrument content and "
                                     "are served only by the endpoint, to a "
                                     "reviewer who already holds the dictionary."),
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT} · {len(artifacts)} artifacts · {len(doc['papers'])} papers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
