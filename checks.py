"""checks.py — the assertions build.py makes about its own output.

SPLIT FROM `build.py` so they can run against a stored `build/dictionary.json`
without rebuilding. Asking "do the checks pass" should not require a write —
the same constraint that made `build.py::_version_hash` worth extracting.

TWO GROUPS, AND THE DIFFERENCE IS THE POINT. They were all called invariants,
and most of them are not:

    structural  true, or the build is broken. Key uniqueness, zero residual
                mojibake, the null-by-construction fields staying null, every id
                matching a known shape. A failure here is a BUG.

    snapshot    drift detectors. `distinct constructs == 1080` asserts current
                behaviour, not correctness: it passes forever while the collapse
                rule is unchanged, INCLUDING if that rule is wrong for some
                downstream purpose. It matters because 1,080 becomes S1's node
                count in `generate/funnel.py`, and grouping it with the
                structural checks made the number look validated. A failure here
                is a QUESTION.

Both groups exit 1. The labels exist so a reader knows which kind of answer the
failure needs, not to make one of them optional.

`MOJIBAKE_MARKERS` is imported from `build.py` rather than moved or copied. It
has two consumers on opposite sides of this split — `build.py::repair_mojibake`
and `residual mojibake` here — and it is a hashed input to
`build.py::_rule_fingerprint`, so a second definition would drift the hash away
from the rule it claims to describe.

Note the import runs `build.py` a second time as the module `build` when
`python build.py` is the entry point, because that process knows the file as
`__main__`. Both module objects hold the same constants and `build.py` does no
work at import, so this costs a dict and nothing else.
"""

from __future__ import annotations

from build import MOJIBAKE_MARKERS

#: The absent facts. A two-column codebook structurally cannot carry these, so
#: they are null by construction rather than because nobody looked. This group
#: failing is the notification that a richer codebook arrived.
NULL_BY_CONSTRUCTION = ("value_labels", "response_options", "value_type",
                        "missing_codes", "measurement_level",
                        "branch_dependency")


def _expect(failures: list[str], label: str, got: object, want: object) -> None:
    """Record a failure when `got` is not `want`.

    Args:
        failures: The list to append to.
        label: What was checked, as a reader should see it.
        got: The observed value.
        want: The expected value.
    """
    if got != want:
        failures.append(f"{label}: got {got}, expected {want}")


def structural(d: dict) -> list[str]:
    """Checks that are true, or the build is broken.

    Args:
        d: A loaded dictionary artefact.

    Returns:
        One string per failure, empty when the build is sound.
    """
    f: list[str] = []
    entries = d["entries"]

    # Keys must be unique, which is the whole point of the occurrence ordinal.
    keys = [e["key"] for e in entries]
    _expect(f, "duplicate keys", len(keys) - len(set(keys)), 0)

    # No residual mojibake anywhere.
    _expect(f, "residual mojibake",
            sum(1 for e in entries
                if any(m in e["question_text"] for m in MOJIBAKE_MARKERS)), 0)

    # Absent facts must be absent, and stay that way.
    for fname in NULL_BY_CONSTRUCTION:
        _expect(f, f"{fname} non-null rows",
                sum(1 for e in entries if e[fname] is not None), 0)

    # Every id matched a known shape. `parse_shape` raises rather than falling
    # back, so a row carrying an unknown shape name could only arrive by hand.
    known = set(d["counts"]["shapes"])
    _expect(f, "entries whose shape is not a known shape",
            sum(1 for e in entries if e["shape"] not in known), 0)

    # The identifier tiers, named rather than counted. A count alone stays green
    # if the pattern starts matching 43 other things.
    # `.get` rather than `[]`: a checker that raises on a missing key reports
    # nothing at all, and the first thing to go wrong in a broken build is
    # often the key space. A vanished row is recorded as a failure like any
    # other, and the remaining checks still run.
    by_key = {e["key"]: e for e in entries}
    for k in ("m1:Q2.2_1", "m1:Q2.2_2", "m1:Q2.3", "m1:Q2.4"):
        row = by_key.get(k)
        _expect(f, f"{k} is a direct identifier",
                row["is_direct_identifier"] if row else "the row is absent", True)
    battery = [e for e in entries
               if e["module"] == "2" and e["base_id"].startswith("Q16.")]
    _expect(f, "cancer-battery rows examined", len(battery), 1040)
    _expect(f, "cancer-battery rows tagged as direct identifiers",
            sum(1 for e in battery if e["is_direct_identifier"]), 0)

    # `roster_family_size` is null exactly where the row is not a roster repeat.
    # Structural, not a snapshot: a question asked once has no family size, and
    # the two conditions are the same condition stated twice.
    _expect(f, "rows where roster_family_size and is_roster_repeat disagree",
            sum(1 for e in entries
                if (e["roster_family_size"] is None) == e["is_roster_repeat"]), 0)

    # The count is DISTINCT roster rows, and it must equal the maximum for every
    # family — a roster numbered 1, 2, 5 would separate them, and the field is a
    # count of members rather than the largest label.
    biggest: dict[tuple[str, str], int] = {}
    for e in entries:
        if e["roster_row"] is not None:
            g = (e["module"], e["base_id"])
            biggest[g] = max(biggest.get(g, 0), e["roster_row"])
    _expect(f, "roster families where the member count is not the highest row",
            sum(1 for e in entries if e["is_roster_repeat"]
                and e["roster_family_size"] != biggest[(e["module"],
                                                        e["base_id"])]), 0)
    return f


def snapshot(d: dict) -> list[str]:
    """Drift detectors. A failure here is a question, not a bug.

    Every number is current behaviour measured once and pinned. None of them
    validates a design choice.

    Args:
        d: A loaded dictionary artefact.

    Returns:
        One string per drifted count, empty when nothing moved.
    """
    f: list[str] = []
    c = d["counts"]
    _expect(f, "total records", c["total"], 2804)
    _expect(f, "module 1 records", c["by_module"]["1"], 142)
    _expect(f, "module 2 records", c["by_module"]["2"], 2326)
    _expect(f, "module 3 records", c["by_module"]["3"], 336)
    _expect(f, "non-unique qids", c["non_unique_qids"], 121)
    _expect(f, "ids containing '#'", c["ids_with_hash"], 754)
    _expect(f, "roster-prefixed repeats", c["roster_repeats"], 1520)
    _expect(f, "distinct constructs", c["distinct_constructs"], 1080)
    _expect(f, "mojibake rows repaired", c["text_repaired"], 98)
    _expect(f, "identifier shapes", len(c["shapes"]), 9)
    _expect(f, "free-text items", c["free_text"], 151)
    _expect(f, "direct identifiers", c["direct_identifiers"], 43)
    _expect(f, "quasi identifiers", c["quasi_identifiers"], 171)
    _expect(f, "roster families", c["roster_families"], 74)
    return f


def run(d: dict) -> dict[str, list[str]]:
    """Run both groups against a loaded dictionary.

    Args:
        d: A loaded dictionary artefact — from a fresh build or read off disk.

    Returns:
        `{"structural": [...], "snapshot": [...]}`, each a list of failures.
    """
    return {"structural": structural(d), "snapshot": snapshot(d)}


def report(groups: dict[str, list[str]]) -> str:
    """Render both groups so a failure's meaning is unambiguous from the output.

    Args:
        groups: The return value of `run`.

    Returns:
        The text to print. Empty when nothing failed.
    """
    meaning = {"structural": "the build is broken",
               "snapshot": "a count moved; decide whether that was intended"}
    out: list[str] = []
    for name, failures in groups.items():
        if failures:
            out.append(f"\n{name.upper()} FAILURES — {meaning[name]}:")
            out.extend(f"  {line}" for line in failures)
    return "\n".join(out)
