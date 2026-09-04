"""Count instrument wording surviving in the tracked tree.

The repository is public and the survey instrument is withheld, so this script
measures the residual: every distinct 8-word run (shingle) from any string in
dictionary.json that also occurs in a tracked text file. Distinct shingles, not
occurrences; a 9-word run counts as two. Runs on the training machine only
(dictionary.json is withheld).

    python src/wording_scan.py [--dictionary dictionary.json] [--out out/wording_scan.json]

README.md quotes this script's totals with the date they were measured.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date
from pathlib import Path

TOK = re.compile(r"[a-z0-9]+")
TEXT_SUFFIXES = (".md", ".py", ".json", ".txt", ".jsx", ".toml", ".cfg", ".yaml", ".yml")


def words(s: str) -> list[str]:
    return TOK.findall(s.lower())


def strings_of(o) -> list[str]:
    out: list[str] = []
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            out.extend(strings_of(v))
    elif isinstance(o, list):
        for v in o:
            out.extend(strings_of(v))
    return out


def shingles(ws: list[str], k: int = 8) -> set[str]:
    return {" ".join(ws[i:i + k]) for i in range(len(ws) - k + 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", type=Path, default=Path("dictionary.json"))
    ap.add_argument("--out", type=Path, default=Path("out/wording_scan.json"))
    a = ap.parse_args()
    instrument = set()
    for s in strings_of(json.loads(a.dictionary.read_text())):
        instrument |= shingles(words(s))
    files = subprocess.run(["git", "ls-files", "--cached"], capture_output=True,
                           text=True, check=True).stdout.split()
    rows = []
    for f in files:
        if not f.endswith(TEXT_SUFFIXES):
            continue
        text = subprocess.run(["git", "show", f":{f}"], capture_output=True,
                              text=True).stdout
        hits = shingles(words(text)) & instrument
        if hits:
            rows.append({"file": f, "distinct_8_word_runs": len(hits)})
    rows.sort(key=lambda r: -r["distinct_8_word_runs"])
    rep = {"schema": "compass_wording_scan/1", "run": str(date.today()),
           "dictionary_shingles": len(instrument), "files_scanned": sum(1 for f in files if f.endswith(TEXT_SUFFIXES)),
           "files_with_hits": len(rows), "total_distinct_runs": sum(r["distinct_8_word_runs"] for r in rows),
           "rows": rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rep, indent=1))
    for r in rows:
        print(f"{r['distinct_8_word_runs']:6d}  {r['file']}")
    print(f"TOTAL {rep['total_distinct_runs']} distinct runs across {rep['files_with_hits']} of "
          f"{rep['files_scanned']} tracked text files ({rep['dictionary_shingles']} instrument shingles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
