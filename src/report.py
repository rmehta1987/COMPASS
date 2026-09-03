"""Assemble the frozen-vs-fine-tuned deliverable table from out/*.json."""
from __future__ import annotations
import json, sys
from pathlib import Path

OUT = Path("out")

def rows():
    for f in sorted(OUT.glob("frozen_*.json")) + sorted(OUT.glob("ft_*.json")) \
             + sorted(OUT.glob("mrl_*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if "overall" not in d:
            continue
        o, s, fo, nd = d["overall"], d["singleton"], d["folded_family"], d["near_duplicate"]
        e = d["errors"]; wc = d["within_construct_cosine"]
        yield {
            "kind": "frozen" if f.name.startswith("frozen") else
                    ("mrl" if f.name.startswith("mrl") else "fine-tuned"),
            "label": d["label"], "params": d.get("params_m"),
            "mrl": d.get("mrl_dim"),
            "at1": o["@1"], "at5": o["@5"], "at10": o["@10"],
            "at25": o["@25"], "at50": o["@50"],
            "p50": o["rank_p50"], "p90": o["rank_p90"], "max": o["rank_max"],
            "sing": s.get("@1"), "sing_n": s["n"],
            "fold": fo.get("@1"), "fold_n": fo["n"],
            "nd": nd.get("@1"), "nd_n": nd["n"],
            "nd_ratio": d.get("near_duplicate_ratio_to_own_at1"),
            "err": e["n_top1_errors"], "wrong_construct": e["wrong_construct"],
            "rc_wo": e["right_construct_wrong_option"],
            "wc50": wc["p50"], "wc90": wc["p90"],
            "ms": d["cost"]["query_ms_per_row"],
            "enc_s": d["cost"]["target_encode_s"],
            "n_targets": d["n_targets"], "n_rows": d["n_rows_scored"],
        }

def main():
    R = sorted(rows(), key=lambda r: (-r["at1"]))
    hdr = ("| model | kind | par | @1 | @5 | @10 | @25 | @50 | p50/p90/max | "
           "singleton@1 | folded@1 | near-dup@1 | nd÷own@1 | wrong-constr | rc-wrong-opt | wc-cos p50 | ms/q |")
    print(hdr); print("|" + "---|" * 17)
    for r in R:
        lbl = r["label"]
        if r["mrl"] and f"d={r['mrl']}" not in lbl:
            lbl += f" d={r['mrl']}"
        print(f"| {lbl} | {r['kind']} | {r['params'] or '-'} | {r['at1']:.3f} | {r['at5']:.3f} | "
              f"{r['at10']:.3f} | {r['at25']:.3f} | {r['at50']:.3f} | "
              f"{r['p50']}/{r['p90']}/{r['max']} | {r['sing']:.3f} | {r['fold']:.3f} | "
              f"{r['nd']:.3f} | {r['nd_ratio']} | {r['wrong_construct']}/{r['err']} | "
              f"{r['rc_wo']} | {r['wc50']} | {r['ms']:.1f} |")
    print(f"\n{len(R)} configurations. Targets/rows: "
          f"{R[0]['n_targets']}/{R[0]['n_rows']}" if R else "none")
    json.dump(R, open(OUT / "report_table.json", "w"), indent=1)

if __name__ == "__main__":
    sys.exit(main())
