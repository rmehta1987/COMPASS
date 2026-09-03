"""Task 4: R@1 / R@10 for the shipped model, stratified.

Aggregate recall hides structural imbalance. The instrument is cancer-heavy and
SES-thin, and SES variables are exactly what a disparities hypothesis needs as
mediators -- so a lopsided recall profile is a documented limitation of the tool
even when it is not a number worth trying to improve.

`dictionary.json` carries NO domain or topic tag (its only grouping fields are
`module`, `construct_key`, `group_key` and the qid grammar). Domains here are
therefore assigned by keyword match against the target's cleaned STEM text, in
the fixed priority order of DOMAIN_KEYWORDS below -- first pattern to match
wins, so e.g. "Was this sibling ever diagnosed with ... cancer" is
`cancer_history`, not `family_roster`. The classifier is committed here so the
grouping is reproducible and auditable rather than described in prose.

    python src/char_strata.py --pos out/char_pos_bge-small_ft.json \
        --targets out/targets_full.json --out out/char_task4_strata.json
"""
from __future__ import annotations

import argparse, json, math, re
from collections import Counter, defaultdict
from pathlib import Path

# Priority-ordered. First match wins. Patterns are matched case-insensitively
# against the target's cleaned stem only (not the option), so every option under
# one question lands in the same domain.
#
# The pattern list was extended once, on CORPUS-COVERAGE grounds only: the first
# version left 340/1353 targets (25%) unclassified, dominated by two families --
# the m2:Q5.x "How old were you when you were first told that you had <named
# condition>" block and the m2:Q19-23.x named-drug block. Patterns for those two
# families and for medical-care access/cost were added. Recall numbers were not
# consulted in choosing them; what remains unclassified is survey admin
# (contact-preference, "List of Countries", untitled Qualtrics placeholders).
DOMAIN_KEYWORDS = [
    ("cancer_screening", r"colonoscopy|sigmoidoscopy|barium enema|mammogram|"
                         r"pap smear|\bpsa\b|digital rectal exam|screening"),
    ("cancer_history",   r"cancer|tumor|tumour|melanoma|lymphoma|leukemia|leukaemia|"
                         r"myeloma|carcinoma|chemotherapy|radiation therapy|oncolog"),
    # "first told that you had X" is the m2:Q5.x block's own stem shape and
    # covers ~130 named conditions the explicit list below does not enumerate.
    ("chronic_condition", r"first told that you had|diabet|hypertension|blood pressure|"
                          r"cholesterol|asthma|\bcopd\b|emphysema|heart attack|"
                          r"\bstroke\b|arthritis|kidney|liver|depress|anxiet|thyroid|"
                          r"blood clot|anemia|osteoporosis|\bulcer\b|\bgout\b|"
                          r"health condition|serious illness|medical condition"),
    ("tobacco",          r"cigarette|smok|tobacco|\bvap\b|vaping|nicotine|\bcigar\b|"
                         r"hookah|electronic delivery|snuff|chewing tobacco"),
    ("alcohol",          r"alcohol|\bdrink\b|drinks|drinking|\bbeer\b|\bwine\b|liquor"),
    ("sleep",            r"\bsleep|wake up|go to bed|\bnap\b|snor|insomnia"),
    ("physical_activity", r"exercis|walking|\bwalk\b|physical activ|\bsport|bicycl|"
                          r"recreational activit|in what seasons|during these seasons|"
                          r"seasons that you|\bchores\b|\byoga\b|pilates|tai chi|"
                          r"\bgolf\b|home repair|garden|mow|\bswim|\bdanc|"
                          r"time per day did you spend"),
    ("ses_employment",   r"employ|occupation|\bjob\b|income|wage|salary|work status|"
                         r"currently a student|highest.*(?:grade|degree|education)|"
                         r"stress.*at work|work for pay|personal finances"),
    ("insurance_access", r"insurance|medicaid|medicare|health plan|coverage|"
                         r"usual source of care|delay.*care|afford|out of pocket|"
                         r"cost of your medical care|medical care costs|"
                         r"not able to get medical care|needed medical care"),
    # named-drug block (m2:Q19-Q23): "have you ever taken <drug> regularly", and
    # the follow-ups about years, reasons and interference.
    ("medication",       r"\bmetformin\b|\binsulin\b|naproxen|ibuprofen|acetaminophen|"
                         r"\baspirin\b|antihistamine|\bstatin|celecoxib|\bnsaid|"
                         r"prescription hormone|\bopioid|proton pump|"
                         r"ever taken .* regularly|taking .* regularly|"
                         r"did pain interfere"),
    ("healthcare_util",  r"emergency room|\bdoctor|\bnurse|hospital|health care|"
                         r"healthcare|\bclinic|prescription|medicine|medication|pharmac|"
                         r"seen a doctor|overnight|medical care|quality of medical care|"
                         r"where do you usually go"),
    ("residence_commute", r"commute|\baddress\b|live in|residence|transportation|"
                          r"neighborhood|neighbourhood|zip code|what state|what city|"
                          r"moved into|source of water|tap water|baths or showers"),
    ("reproductive_hormonal", r"hormone|pregnan|menstrua|menopaus|contracept|birth control|"
                              r"breastfe|hysterectomy|ovar|estrogen|progestin"),
    ("demographics",     r"sex was classified|gender identity|marital status|"
                         r"hispanic|\brace\b|religio|birthday|how old are you|"
                         r"height|weight|country|years have you lived|"
                         r"how you think of yourself|closer description to your gender"),
    ("family_roster",    r"sibling|this child|your child|parent|mother|father|brother|"
                         r"sister|household|relative|other people live with you|"
                         r"additional contact"),
]
COMPILED = [(n, re.compile(p, re.I)) for n, p in DOMAIN_KEYWORDS]


def domain_of(stem: str) -> str:
    s = stem or ""
    for name, rx in COMPILED:
        if rx.search(s):
            return name
    return "unclassified"


def wilson(k, n, z=1.96):
    """95% Wilson interval. Reported because these strata are small enough that
    a single row flip moves R@1 by several points."""
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 3), round((c + h) / d, 3)]


def stats(rows):
    n = len(rows)
    if not n:
        return {"n_rows": 0}
    k1 = sum(1 for r in rows if r["rank"] == 1)
    k10 = sum(1 for r in rows if r["rank"] <= 10)
    ranks = sorted(r["rank"] for r in rows)
    return {
        "n_rows": n,
        "n_items": len({r["gold_key"] for r in rows}),
        "R@1": round(k1 / n, 3), "R@1_ci95": wilson(k1, n),
        "R@10": round(k10 / n, 3), "R@10_ci95": wilson(k10, n),
        "rank_p50": ranks[len(ranks) // 2], "rank_max": ranks[-1],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", type=Path, default=Path("out/char_pos_bge-small_ft.json"))
    ap.add_argument("--pos-frozen", type=Path,
                    default=Path("out/char_pos_bge-small_frozen.json"))
    ap.add_argument("--targets", type=Path, default=Path("out/targets_full.json"))
    ap.add_argument("--out", type=Path, default=Path("out/char_task4_strata.json"))
    a = ap.parse_args()

    T = json.loads(a.targets.read_text())["targets"]
    by_id = {t["target_id"]: t for t in T}

    # corpus-side imbalance: how many targets / constructs each stratum holds
    corpus_dom = Counter(domain_of(t["stem"]) for t in T)
    seen, corpus_dom_con = set(), Counter()
    for t in T:
        if t["construct_key"] in seen:
            continue
        seen.add(t["construct_key"])
        corpus_dom_con[domain_of(t["stem"])] += 1
    corpus_mod = Counter(t["module"] for t in T)

    out = {
        "schema": "char_strata/1",
        "grouping_method": (
            "dictionary.json carries no domain tag; domains are assigned by "
            "priority-ordered keyword regex against the target's cleaned stem "
            "(src/char_strata.py::DOMAIN_KEYWORDS, first match wins). Module is "
            "the instrument's own field. Fold class and sibling status come from "
            "src/compass_build.py."),
        "domain_keyword_patterns": {n: p for n, p in DOMAIN_KEYWORDS},
        "corpus_composition": {
            "n_targets": len(T),
            "by_module_targets": dict(sorted(corpus_mod.items())),
            "by_domain_targets": dict(corpus_dom.most_common()),
            "by_domain_constructs": dict(corpus_dom_con.most_common()),
        },
        "models": {},
    }

    for label, path in (("bge-small_ft", a.pos), ("bge-small_frozen", a.pos_frozen)):
        rows = [r for r in json.loads(path.read_text())["rows"] if not r["unreachable"]]
        for r in rows:
            r["_domain"] = domain_of(by_id[r["gold_target"]]["stem"])
            r["_block"] = f"m{r['gold_module']}:" + \
                re.match(r"m\d+:(Q\d+)", r["gold_construct"]).group(1)
        m = {"overall": stats(rows)}
        m["by_module"] = {f"module_{k}": stats([r for r in rows if r["gold_module"] == k])
                          for k in sorted({r["gold_module"] for r in rows})}
        m["by_domain"] = {k: stats([r for r in rows if r["_domain"] == k])
                          for k in sorted({r["_domain"] for r in rows},
                                          key=lambda k: -corpus_dom[k])}
        m["by_fold_class"] = {
            "singleton": stats([r for r in rows if not r["gold_folded"]]),
            "folded_family": stats([r for r in rows if r["gold_folded"]]),
        }
        m["by_sibling_status"] = {
            "no_siblings": stats([r for r in rows if not r["gold_multi_option"]]),
            "has_siblings_near_duplicate": stats([r for r in rows if r["gold_multi_option"]]),
        }
        m["by_questionnaire_block"] = {
            k: stats([r for r in rows if r["_block"] == k])
            for k in sorted({r["_block"] for r in rows})}
        out["models"][label] = m

    a.out.write_text(json.dumps(out, indent=1))

    ft = out["models"]["bge-small_ft"]
    fz = out["models"]["bge-small_frozen"]
    print(f"corpus: {len(T)} targets   by module "
          f"{out['corpus_composition']['by_module_targets']}")
    print(f"\n{'stratum':28s} {'corpus':>7s} {'rows':>5s} "
          f"{'ft R@1':>8s} {'ft R@10':>8s} {'fz R@1':>8s}")
    def line(name, corpus, s, sz):
        if not s.get("n_rows"):
            return
        print(f"{name:28s} {corpus:>7} {s['n_rows']:5d} {s['R@1']:8.3f} "
              f"{s['R@10']:8.3f} {sz['R@1']:8.3f}")
    print("-- by module")
    for k, s in ft["by_module"].items():
        line(k, corpus_mod[k[-1]], s, fz["by_module"][k])
    print("-- by domain (keyword on stem; corpus col = targets in that domain)")
    for k, s in ft["by_domain"].items():
        line(k, corpus_dom[k], s, fz["by_domain"][k])
    print("-- by fold class / sibling status")
    for grp in ("by_fold_class", "by_sibling_status"):
        for k, s in ft[grp].items():
            line(k, "-", s, fz[grp][k])
    print(f"\noverall ft R@1 {ft['overall']['R@1']}  R@10 {ft['overall']['R@10']}"
          f"   frozen R@1 {fz['overall']['R@1']}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
