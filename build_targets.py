"""Build the 1,395 arm-E selection targets from build/dictionary.json.

Pure stdlib. No model, no network. Output feeds encode_and_score.py.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

# identifier shapes, to strip piped Qualtrics refs out of stem text
# Piped Qualtrics refs appear mid-string as well as at the tail, e.g.
# "...work days or weekdays? - Q2.4#1 - Time it takes to fall asleep".
# Match anywhere, with the " - " separators that bracket them.
ID_ANY = re.compile(
    r"\s*-\s*\d*_?Q\d+(?:\.\d+)?(?:#\d+)?(?:_\d+)*(?:_TEXT)?\b"
)
TRAIL_NUM = re.compile(r"\s*-\s*\d+\s*$")

def clean_stem(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = ID_ANY.sub("", s).strip()
        s = TRAIL_NUM.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip(" -")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("targets.json"))
    a = ap.parse_args()

    d = json.loads(a.dictionary.read_text())
    entries = d["entries"]
    version = d["version_hash"]

    seen, targets, skipped = {}, [], {"identifier": 0, "text_capture": 0}
    # text_capture stays in the report and stays at zero; see the loop below.
    for e in entries:
        # governance: never surface direct identifiers as candidates
        if e.get("is_direct_identifier"):
            skipped["identifier"] += 1
            continue
        # The free-text exclusion was REMOVED 2026-09-02. It dropped 151 rows,
        # among them four fixture gold items -- m2:Q9.96, m2:Q776,
        # m3:Q15.9_4_TEXT, m3:Q870_2 -- none of which is a direct identifier.
        # A researcher asking about commute mode should find m2:Q776. The
        # identifier exclusion below stays: it is governance and costs zero
        # fixture rows. The counter is kept, at zero, so a reader of an old
        # artifact and a new one can see which rule was in force.
        k = (e["construct_key"], e["subitem_text"], e["matrix_col"])
        if k in seen:
            seen[k]["members"].append(e["key"])
            continue
        t = {
            "target_id": len(targets) + 1,          # 1-based, index-selection
            "canonical_key": e["key"],              # withheld from any prompt
            "construct_key": e["construct_key"],
            "stem": clean_stem(e["stem_text"] or e["question_text"]),
            "option": e["subitem_text"],
            "matrix_col": e["matrix_col"],
            "roster_family_size": e.get("roster_family_size"),
            "wording": e["question_text"],          # byte-verbatim
            "members": [e["key"]],
        }
        seen[k] = t
        targets.append(t)

    sib = {}
    for t in targets:
        sib.setdefault(t["construct_key"], []).append(t["target_id"])
    for t in targets:
        t["siblings"] = [i for i in sib[t["construct_key"]] if i != t["target_id"]]

    out = {
        "schema": "arm_e_targets/1",
        "dictionary_version_hash": version,
        "n_targets": len(targets),
        "n_multi_option": sum(1 for t in targets if t["siblings"]),
        "skipped": skipped,
        "targets": targets,
    }
    a.out.write_text(json.dumps(out, indent=1))
    print(f"dictionary {version}")
    print(f"targets              {len(targets)}")
    print(f"  in multi-option    {out['n_multi_option']}")
    print(f"  skipped identifier {skipped['identifier']}")
    print(f"  skipped free text  {skipped['text_capture']}")
    print(f"largest construct    "
          f"{max((len(v) for v in sib.values()), default=0)} options")
    print(f"-> {a.out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
