"""Re-verify that the negative fixture's five domains are absent from the corpus.

The negative set is only a true-negative set if the constructs really are not in
the instrument. This re-runs the absence check as a committed artifact rather
than leaving it as a claim in a brief, and records what it found -- including the
adjacent constructs that DO exist, which the domain patterns must not be read as
denying.

    python src/verify_negatives.py --dictionary dictionary.json \
        --targets out/targets_full.json --fixture fixtures/negative_requests.json \
        --out out/negatives_absence_check.json
"""
from __future__ import annotations

import argparse, json, re, sys
from pathlib import Path

EXPECTED_HASH = "3dc8415eccfe"

# Per-domain patterns. `absent` must match nothing: it is the construct the
# negative requests actually ask for. `adjacent` is allowed to match and is
# reported: it names the topically-related-but-categorically-different items
# that make some of these negatives hard rather than trivial.
DOMAINS = {
    "ambient_air_pollution": {
        "absent": r"pm2\.?5|air quality|particulate|\bozone\b|\bno2\b|air pollut\w* (?:level|concentration|exposure|index)|smog",
        "adjacent": r"pollut|environment",
    },
    "area_deprivation": {
        "absent": r"deprivation index|\badi\b|social vulnerability|\bsvi\b|census block group|poverty rate|rural-urban commuting|\bruca\b|area-level",
        "adjacent": r"income|neighborhood|neighbourhood",
    },
    "geocode_spatial": {
        "absent": r"census tract|geocod|latitude|longitude|block group|fips|coordinate|green space",
        "adjacent": r"zip code|street address|what state do you live|what city do you live",
    },
    "biospecimen_assay": {
        "absent": r"biospecimen|blood draw|\bserum\b|\bplasma\b|\bassay\b|biomarker|genotyp|cotinine|saliva|swab|hba1c|\ba1c\b|blood lead",
        "adjacent": r"blood cholesterol|blood test|diabet",
    },
    "genomics_ancestry": {
        "absent": r"ancestry inform|\bsnp\b|polygenic|genom|\bdna\b|\bbrca\b|genetic|sequencing|inherited",
        "adjacent": r"ancestry|\brace\b|family history",
    },
}

FIELDS = ("question_text", "stem_text", "subitem_text", "searchable_text")


def blob(e) -> str:
    return " ".join(str(e.get(f) or "") for f in FIELDS)


def target_blob(t) -> str:
    return " ".join(str(t.get(f) or "") for f in ("stem", "option", "wording"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    d = json.loads(a.dictionary.read_text())
    if d["version_hash"] != EXPECTED_HASH:
        raise SystemExit(f"dictionary {d['version_hash']}, expected {EXPECTED_HASH}")
    T = json.loads(a.targets.read_text())
    if T["dictionary_version_hash"] != EXPECTED_HASH:
        raise SystemExit("targets built from a different dictionary")
    fx = json.loads(a.fixture.read_text())

    entries, targets = d["entries"], T["targets"]
    report, failures = {}, []
    for dom, pats in DOMAINS.items():
        rx_a = re.compile(pats["absent"], re.I)
        rx_j = re.compile(pats["adjacent"], re.I)
        e_hits = [e["key"] for e in entries if rx_a.search(blob(e))]
        t_hits = [t["canonical_key"] for t in targets if rx_a.search(target_blob(t))]
        adj = sorted({t["construct_key"] for t in targets if rx_j.search(target_blob(t))})
        report[dom] = {
            "absent_pattern": pats["absent"],
            "dictionary_entries_matching_absent_pattern": len(e_hits),
            "target_corpus_matching_absent_pattern": len(t_hits),
            "example_absent_matches": e_hits[:10],
            "adjacent_pattern": pats["adjacent"],
            "adjacent_constructs_present": len(adj),
            "adjacent_construct_keys": adj[:40],
        }
        if e_hits or t_hits:
            failures.append(dom)

    # every fixture row's domain must be one we checked
    doms = {r["domain"] for r in fx["queries"]}
    unchecked = sorted(doms - set(DOMAINS))
    if unchecked:
        failures.append(f"fixture domains not checked: {unchecked}")

    out = {
        "schema": "negatives_absence_check/1",
        "dictionary_version_hash": d["version_hash"],
        "n_dictionary_entries": len(entries),
        "n_targets": len(targets),
        "fixture": str(a.fixture),
        "n_negative_queries": len(fx["queries"]),
        "fields_searched": list(FIELDS),
        "all_domains_absent": not failures,
        "failures": failures,
        "domains": report,
    }
    a.out.write_text(json.dumps(out, indent=1))
    for dom, r in report.items():
        print(f"{dom:24s} absent-pattern hits: dict {r['dictionary_entries_matching_absent_pattern']:3d}"
              f"  targets {r['target_corpus_matching_absent_pattern']:3d}"
              f"   adjacent constructs present: {r['adjacent_constructs_present']:3d}")
    print(f"\nall_domains_absent = {out['all_domains_absent']}  -> {a.out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
