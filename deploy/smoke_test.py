"""Prove the ported bundle is the fine-tuned model, on CPU, at the right point.

A wrong port does not raise. It answers. Base weights instead of fine-tuned,
a dropped query prefix, mean instead of CLS pooling, bf16 instead of fp32, a
stale target order: every one of these yields a working retriever with wrong
output. So the acceptance criterion is a NUMBER REPRODUCED EXACTLY, not a
successful import. Every figure asserted below was reproduced to the last
digit across two independent harnesses on the training machine; drift here
means something is wrong, not that CPU arithmetic differs.

    python deploy/smoke_test.py                      # from the repo root
    python deploy/smoke_test.py --adopt-local-vectors

Steps, in order; the first failure stops the run:

  0. integrity   sha256 of every shipped file against manifest["files"],
                 BEFORE torch is imported. Prints model.safetensors' sha256.
  1. load        retriever.py from the bundle, threads pinned by the manifest
  2. template    re-render all 268 pre-registered strings (224 positives, 44
                 negatives, arms F and P) through deploy/template.py
  3. re-encode   all 1,353 targets on THIS machine; max |delta| against the
                 transferred vectors (expect ~1e-7; >= 1e-3 means a different
                 checkpoint or dtype). --adopt-local-vectors then rewrites the
                 vector file and its manifest checksum and re-verifies.
  4. acceptance  224-row fixture, single query, fp32; R@1/5/10, rank p50/p90/
                 max per arm; 44 negatives: rejected at min_cos, AUROC
  5. threshold   F-optimal tau re-derived on positives only over an exhaustive
                 candidate set AND a 20,001-point dense grid; plateau reported
  6. latency     isolated single-query ms at the pinned thread count
  7. smoke       the four canonical queries from retriever.__main__

Exit 0 only if every assertion holds. 2 = integrity, 1 = anything else.

Fixture: out/qx_preregistration.json (tracked in git). It carries the 224
queries with gold keys, the 44 negative requests, and the template fields for
both, frozen before any scoring. It is the only fixture this test needs, and it
travels with the repository. The raw retrieval_queries.json and
fixtures/negative_requests.json stay gitignored and are not required here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import socket
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- expectations
# From out/qx_task2_paired.json (arms S and F, rounded to 3 dp as the brief
# states them; ranks exact) and out/qx_task3_abstention.json (negatives).
# Arm I ("instances only") is the SHIPPED contract: population left None. It is
# a post-hoc revision of pre-registered arm F and was measured on the training
# machine's CPU through this script.
EXPECTED = {
    "S": {"R@1": 0.567, "R@5": 0.862, "R@10": 0.920,
          "rank_p50": 1, "rank_p90": 9, "rank_max": 82,
          "negatives_rejected": 43, "auroc": 0.9823},
    "F": {"R@1": 0.643, "R@5": 0.888, "R@10": 0.942,
          "rank_p50": 1, "rank_p90": 6, "rank_max": 61,
          "negatives_rejected": 43, "auroc": 0.9867},
    # measured 2026-09-03 on the training machine's CPU (spark-2500, aarch64),
    # single query, fp32, transferred vectors; 4 dp: R@1 0.6429, R@5 0.8884,
    # R@10 0.9375. Against arm F: 13 rows re-rank, 4 gained, 4 lost at rank 1.
    "I": {"R@1": 0.643, "R@5": 0.888, "R@10": 0.938,
          "rank_p50": 1, "rank_p90": 7, "rank_max": 61,
          "negatives_rejected": 43, "auroc": 0.9874},
}
# out/qx_task3_abstention.json: recall at the shipped tau, arms S and F
EXPECTED_RECALL_AT_SHIPPED = {"S": 0.558, "F": 0.6339}
# The F1 optimum by the artifacts' rule lands on one of two adjacent candidates
# depending on which side of the shipped threshold fixture row 68 falls, and
# that is decided by ~6e-8 of encoding noise: on the training machine (Arm,
# single query) it fell above -> tau* 0.731902; on the x86 serving machine it
# fell below -> tau* 0.729476, the shipped value. Either is the correct answer
# for the machine that produced it. Anything else is a real change.
KNIFE_EDGE_TAUS = (0.729476, 0.731902)
ARM_LABEL = {"S": "no template (row's own query)",
             "F": "pre-registered arm F: population + instances",
             "I": "shipped contract: instances only, population None"}
MAX_VECTOR_DELTA = 1e-3
CANONICAL = [  # retriever.__main__'s four queries; CHARACTERISATION.md section 5
    ("exogenous hormone medication", "m2:Q9.95"),
    ("primary method used to get to work", None),
    ("ambient PM2.5 exposure at the residential address", None),
    ("polygenic risk score for breast cancer", None),
]


class Failed(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------- statistics (verbatim)
# rank_stats: src/qx_paired.py. auroc, pct: src/fusion_abstain.py. Copied so the
# numbers here are computed by the same arithmetic that produced the artifacts.

def rank_stats(ranks):
    s = sorted(ranks)
    n = len(s)
    return {"n": n,
            "R@1": round(sum(r == 1 for r in s) / n, 4),
            "R@5": round(sum(r <= 5 for r in s) / n, 4),
            "R@10": round(sum(r <= 10 for r in s) / n, 4),
            "rank_p50": s[int(0.5 * (n - 1))], "rank_p90": s[min(n - 1, int(0.9 * n))],
            "rank_max": s[-1]}


def auroc(pos, neg):
    """Mann-Whitney U with ties counted as half."""
    allv = sorted([(v, 0) for v in pos] + [(v, 1) for v in neg])
    vals = [v for v, _ in allv]
    r = [0.0] * len(vals)
    i = 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[i]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[k] = avg
        i = j + 1
    rsum = sum(r[k] for k in range(len(allv)) if allv[k][1] == 0)
    n1, n2 = len(pos), len(neg)
    return round((rsum - n1 * (n1 + 1) / 2) / (n1 * n2), 4)


def f1_at(tau, ps, pc):
    ansi = [i for i, s in enumerate(ps) if s >= tau]
    cor = sum(pc[i] for i in ansi)
    prec = cor / len(ansi) if ansi else None
    rec = cor / len(ps)
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
    return f1, prec, rec, len(ansi)


def threshold_report(ps, pc, ns, shipped, grid_points=20001):
    """Positives select, negatives report. Exhaustive candidates (every distinct
    positive score) give the true F1 optimum: F1 is piecewise constant between
    positive scores, so no finer grid can find a different one. The dense grid
    is run anyway to show the plateau the optimum sits on."""
    cands = sorted({round(s, 6) for s in ps})
    # The artifacts' rule (src/fusion_abstain.py::sweep): F1 rounded to 4 dp,
    # first maximum wins, i.e. the LOWEST tau among 4-dp ties. Reproduced here
    # so the shipped value can be asserted against the rule that produced it.
    best_rule = max(cands, key=lambda t: round(f1_at(t, ps, pc)[0], 4))
    best = max(cands, key=lambda t: f1_at(t, ps, pc)[0])   # unrounded F1
    f1b = f1_at(best, ps, pc)[0]
    # rows within 0.003 of the shipped threshold: a 1e-7 encoding difference
    # (batch vs single query, Arm vs x86) can move these across it
    knife = [{"i": i, "score": round(s, 6), "correct": bool(pc[i])}
             for i, s in enumerate(ps) if abs(s - shipped) < 0.003]
    knife_neg = [{"i": i, "score": round(s, 6)} for i, s in enumerate(ns) if abs(s - shipped) < 0.003]
    lo, hi = min(ps), max(ps)
    plateau = []
    for k in range(grid_points):
        t = lo + (hi - lo) * k / (grid_points - 1)
        if abs(f1_at(t, ps, pc)[0] - f1b) < 1e-12:
            plateau.append(t)
    f1s, prec, rec, n_ans = f1_at(shipped, ps, pc)
    return {
        "candidate_taus_exhaustive": len(cands),
        "tau_star_artifact_rule_4dp_f1_lowest_tie": best_rule,
        "tau_star_unrounded_f1": best,
        "f1_at_tau_star": round(f1b, 4),
        "f1_at_shipped_minus_max_f1": round(f1_at(shipped, ps, pc)[0] - f1b, 6),
        "knife_edge_positives_within_0.003": knife,
        "knife_edge_negatives_within_0.003": knife_neg,
        "dense_grid_points": grid_points,
        "dense_grid_plateau_of_max_f1": [round(plateau[0], 6), round(plateau[-1], 6)]
        if plateau else None,
        "shipped_tau": shipped,
        "shipped_tau_on_plateau": bool(plateau) and plateau[0] - 1e-9 <= shipped <= plateau[-1] + 1e-9,
        "shipped_tau_is_tau_star": round(shipped, 6) == best,
        "at_tau_star": {"negatives_rejected": sum(1 for s in ns if s < best),
                        "precision": round(f1_at(best, ps, pc)[1] or 0, 4),
                        "recall": round(f1_at(best, ps, pc)[2], 4)},
        "at_shipped_tau": {"negatives_rejected": sum(1 for s in ns if s < shipped),
                           "precision": round(prec or 0, 4), "recall": round(rec, 4),
                           "coverage": round(n_ans / len(ps), 4), "f1": round(f1s, 4)},
    }


# ---------------------------------------------------------------------- steps

def step0_integrity(bundle: Path, rep: dict):
    print("0. integrity (before loading anything)")
    mpath = bundle / "manifest.json"
    if not mpath.exists():
        raise Failed(f"{mpath} missing. The bundle's json/safetensors are not on "
                     f"the remote; copy deploy/ from the training machine.", 2)
    m = json.loads(mpath.read_text())
    bad = []
    for rel, meta in m["files"].items():
        p = bundle / rel
        if not p.exists():
            bad.append(f"MISSING  {rel}")
            continue
        h = sha256(p)
        ok = h == meta["sha256"] and p.stat().st_size == meta["bytes"]
        print(f"  {'ok  ' if ok else 'BAD '} {h[:16]}  {p.stat().st_size:>11,d}  {rel}")
        if not ok:
            bad.append(f"MISMATCH {rel}: {h[:12]} != manifest {meta['sha256'][:12]}")
    rep["integrity"] = {"files": len(m["files"]), "failures": bad,
                        "model_safetensors_sha256": m["files"]["model/model.safetensors"]["sha256"]}
    print(f"  model/model.safetensors sha256 (manifest, matches on disk): "
          f"{rep['integrity']['model_safetensors_sha256']}")
    if bad:
        if any(b.startswith("MISSING  model/") for b in bad):
            print("  deploy/model/ is gitignored (133 MB, over GitHub's file limit). "
                  "Copy it from the training machine, e.g.\n"
                  "    rsync -av <spark>:COMPASS/deploy/model/ deploy/model/")
        raise Failed("integrity: " + "; ".join(bad), 2)
    return m


def machine_info(torch, transformers, threads):
    return {"hostname": socket.gethostname(), "machine": platform.machine(),
            "platform": platform.platform(), "python": platform.python_version(),
            "torch": torch.__version__, "transformers": transformers.__version__,
            "cpu_count": os.cpu_count(), "torch_threads": threads,
            "cuda_visible": bool(torch.cuda.is_available())}


def target_text(t: dict, mode: str) -> str:
    stem = t["stem"] or ""
    opt = t["option"] or ""
    if mode == "stem_option_dup":
        return f"{stem} {opt}".strip() if opt else f"{stem} {stem}".strip()
    raise Failed(f"manifest rendering {mode!r} is not the shipped 'stem_option_dup'")


def encode_docs(r, texts, max_len, batch=64):
    import torch
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), batch):
            enc = r.tok(texts[i:i + batch], truncation=True, padding=True,
                        max_length=max_len, return_tensors="pt")
            h = r.model(**enc).last_hidden_state
            if r.pool == "cls":
                v = h[:, 0, :]
            else:
                mk = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
                v = (h * mk).sum(1) / mk.sum(1).clamp(min=1e-9)
            out.append(torch.nn.functional.normalize(v, dim=-1))
    return torch.cat(out)


def encode_single(r, texts):
    """One query per forward pass: the deployed access pattern."""
    import torch
    return torch.cat([r.encode_queries([t]) for t in texts])


def check(name, got, want, fails):
    ok = got == want
    print(f"    {'PASS' if ok else 'FAIL'}  {name}: {got}" + ("" if ok else f"  (expected {want})"))
    if not ok:
        fails.append(f"{name}: got {got}, expected {want}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=HERE)
    ap.add_argument("--prereg", type=Path, default=HERE.parent / "out" / "qx_preregistration.json")
    ap.add_argument("--report", type=Path,
                    default=HERE.parent / "out" / f"smoke_report_{platform.machine()}_{socket.gethostname()}.json",
                    help="per-machine by default so runs on different machines do not overwrite each other")
    ap.add_argument("--adopt-local-vectors", action="store_true",
                    help="after re-encoding, replace target_vectors.safetensors with the "
                         "locally computed vectors, rewrite its manifest checksum, re-verify")
    ap.add_argument("--threads", type=int, default=None,
                    help="override the manifest's pinned thread count (reported, not hidden)")
    a = ap.parse_args()
    bundle = a.bundle.resolve()
    rep = {"schema": "compass_cpu_smoke/1", "run": str(date.today()), "bundle": str(bundle)}
    fails: list[str] = []

    try:
        m = step0_integrity(bundle, rep)

        import torch, transformers                       # noqa: E401  (after step 0)
        from safetensors.torch import save_file
        torch.manual_seed(0)

        print("1. load")
        R = load_by_path(bundle / "retriever.py", "compass_deploy_retriever")
        t0 = time.perf_counter()
        r = R.CompassRetriever(bundle, threads=a.threads)   # verifies checksums again
        rep["machine"] = machine_info(torch, transformers, r.threads)
        rep["load_s"] = round(time.perf_counter() - t0, 2)
        mi = rep["machine"]
        print(f"  {mi['hostname']}  {mi['machine']}  {mi['platform']}")
        print(f"  python {mi['python']}  torch {mi['torch']}  transformers {mi['transformers']}"
              f"  cpu_count {mi['cpu_count']}  torch threads {mi['torch_threads']}"
              f"  (manifest pins {m.get('device', {}).get('threads')})")
        if next(r.model.parameters()).dtype != torch.float32:
            raise Failed(f"model dtype {next(r.model.parameters()).dtype}, not fp32")
        if next(r.model.parameters()).device.type != "cpu":
            raise Failed("model is not on cpu")
        print(f"  dtype float32, device cpu, min_cos {r.min_cos}, "
              f"query prefix {r.q_prefix!r}, pooling {r.pool}")

        print("2. template parity against the pre-registration")
        if not a.prereg.exists():
            raise Failed(f"{a.prereg} missing; it is tracked in git under out/")
        PR = json.loads(a.prereg.read_text())
        Req, Role = R.RetrievalRequest, R.VariableRole
        n_bad = 0
        for row in PR["positives"] + PR["negatives"]:
            rq = Req(construct=row["query"], role=Role.EXPOSURE,
                     population=row["population"], instances=tuple(row["instances"]))
            if rq.to_query() != row["expanded_F"] or rq.to_query(with_instances=False) != row["expanded_P"]:
                n_bad += 1
        rep["template"] = {"rows_rendered": len(PR["positives"]) + len(PR["negatives"]),
                           "rows_differing": n_bad,
                           "template_sha256": sha256(bundle / "template.py")}
        check("pre-registered strings re-rendered identically",
              f"{rep['template']['rows_rendered'] - n_bad}/{rep['template']['rows_rendered']}",
              f"{rep['template']['rows_rendered']}/{rep['template']['rows_rendered']}", fails)
        if n_bad:
            raise Failed("template.py does not reproduce the registered strings")

        print("3. re-encode all targets on this machine")
        c = m["conventions"]
        docs = [c["document_prefix"] + target_text(t, c["target_text_rendering"]) for t in r.targets]
        t0 = time.perf_counter()
        D_local = encode_docs(r, docs, c["max_len_document"])
        enc_s = time.perf_counter() - t0
        delta = float((D_local - r.D).abs().max())
        S_q = [row["query"] for row in PR["positives"]]
        Qs = encode_single(r, S_q).double()
        agree = int(((Qs @ D_local.double().T).argmax(-1) == (Qs @ r.D.double().T).argmax(-1)).sum())
        rep["reencode"] = {"n_targets": len(docs), "wall_s": round(enc_s, 1),
                           "threads": r.threads,
                           "max_abs_delta_local_vs_transferred": delta,
                           "top1_agreement_224_rows_local_vs_transferred": f"{agree}/{len(S_q)}",
                           "transferred_vectors_sha256": m["files"][m["corpus"]["vectors_file"]]["sha256"]}
        print(f"  {len(docs)} targets in {enc_s:.1f}s at {r.threads} threads")
        print(f"  max |delta| local vs transferred: {delta:.3e}   "
              f"top-1 agreement on 224 rows: {agree}/{len(S_q)}")
        if delta >= MAX_VECTOR_DELTA:
            raise Failed(f"max |delta| {delta:.3e} >= {MAX_VECTOR_DELTA}: different checkpoint or dtype")
        if a.adopt_local_vectors:
            vf = bundle / m["corpus"]["vectors_file"]
            save_file({"target_vectors": D_local.contiguous()}, str(vf))
            m["files"][m["corpus"]["vectors_file"]] = {"sha256": sha256(vf), "bytes": vf.stat().st_size}
            m["device"]["vectors_computed_on"] = f"cpu ({mi['hostname']}, {mi['machine']})"
            m["device"]["vectors_adopted"] = {
                "by": "deploy/smoke_test.py --adopt-local-vectors", "on": str(date.today()),
                "replaced_sha256": rep["reencode"]["transferred_vectors_sha256"],
                "max_abs_delta_vs_replaced": delta}
            (bundle / "manifest.json").write_text(json.dumps(m, indent=1))
            print(f"  adopted local vectors -> {vf.name} sha256 {m['files'][m['corpus']['vectors_file']]['sha256'][:16]}; re-verifying")
            step0_integrity(bundle, rep)
            r = R.CompassRetriever(bundle, threads=a.threads)
            rep["reencode"]["adopted"] = True
        rep["reencode"]["served_vectors"] = "local" if a.adopt_local_vectors else "transferred"

        print(f"4. acceptance: 224 rows x 3 arms, 44 negatives, single query, fp32, "
              f"served vectors = {rep['reencode']['served_vectors']}")
        by_key = {mem: t["target_id"] - 1 for t in r.targets for mem in t["members"]}
        gold = [by_key[row["gold_key"]] for row in PR["positives"]]
        queries = {"S": [], "F": [], "I": []}
        negq = {"S": [], "F": [], "I": []}
        for row in PR["positives"]:
            queries["S"].append(row["query"]); queries["F"].append(row["expanded_F"])
            queries["I"].append(Req(construct=row["query"], role=Role.EXPOSURE,
                                    instances=tuple(row["instances"])).to_query())
        for row in PR["negatives"]:
            negq["S"].append(row["query"]); negq["F"].append(row["expanded_F"])
            negq["I"].append(Req(construct=row["query"], role=Role.EXPOSURE,
                                 instances=tuple(row["instances"])).to_query())
        D = r.D.double()
        rep["acceptance"] = {}
        rep["threshold"] = {}
        for arm in ("S", "F", "I"):
            Sp = encode_single(r, queries[arm]).double() @ D.T
            Sn = encode_single(r, negq[arm]).double() @ D.T
            order = Sp.argsort(dim=-1, descending=True)
            rk = order.argsort(dim=-1)
            ranks = [int(rk[i, gold[i]]) + 1 for i in range(len(gold))]
            ps = [float(Sp[i].max()) for i in range(len(gold))]
            pc = [1 if ranks[i] == 1 else 0 for i in range(len(gold))]
            ns = [float(Sn[i].max()) for i in range(len(negq[arm]))]
            st = rank_stats(ranks)
            got = {"R@1": round(st["R@1"], 3), "R@5": round(st["R@5"], 3), "R@10": round(st["R@10"], 3),
                   "rank_p50": st["rank_p50"], "rank_p90": st["rank_p90"], "rank_max": st["rank_max"],
                   "negatives_rejected": sum(1 for s in ns if s < r.min_cos),
                   "auroc": auroc(ps, ns)}
            rep["acceptance"][arm] = {"label": ARM_LABEL[arm], **got,
                                      "R@1_4dp": st["R@1"], "R@5_4dp": st["R@5"], "R@10_4dp": st["R@10"],
                                      "n_negatives": len(ns), "ranks": ranks}
            print(f"  arm {arm}: {ARM_LABEL[arm]}")
            exp = EXPECTED[arm]
            if exp is None:
                print(f"    (report only; no expectation pinned yet) {got}")
            else:
                for k in ("R@1", "R@5", "R@10", "rank_p50", "rank_p90", "rank_max",
                          "negatives_rejected", "auroc"):
                    check(f"arm {arm} {k}", got[k], exp[k], fails)
            rep["threshold"][arm] = threshold_report(ps, pc, ns, r.min_cos)
        if EXPECTED["S"] and rep["acceptance"]["S"]["R@1"] == 0.375:
            print("  >>> R@1 0.375 is the FROZEN base model's number: the base weights loaded.")

        print("5. threshold re-derivation (positives select, negatives report)")
        for arm in ("S", "F", "I"):
            th = rep["threshold"][arm]
            print(f"  arm {arm}: {th['candidate_taus_exhaustive']} exhaustive candidates; "
                  f"tau* by the artifacts' rule (4-dp F1, lowest tie) {th['tau_star_artifact_rule_4dp_f1_lowest_tie']}; "
                  f"by unrounded F1 {th['tau_star_unrounded_f1']}; "
                  f"F1(shipped) - max F1 = {th['f1_at_shipped_minus_max_f1']}; "
                  f"dense-grid plateau {th['dense_grid_plateau_of_max_f1']}")
            print(f"    at unrounded tau* rejects {th['at_tau_star']['negatives_rejected']}/44, "
                  f"precision {th['at_tau_star']['precision']}, recall {th['at_tau_star']['recall']}; "
                  f"at shipped rejects {th['at_shipped_tau']['negatives_rejected']}/44, "
                  f"precision {th['at_shipped_tau']['precision']}, recall {th['at_shipped_tau']['recall']}")
            print(f"    knife-edge rows within 0.003 of shipped tau: "
                  f"{len(th['knife_edge_positives_within_0.003'])} positives "
                  f"{[(k['score'], k['correct']) for k in th['knife_edge_positives_within_0.003']]}, "
                  f"{len(th['knife_edge_negatives_within_0.003'])} negatives "
                  f"{[k['score'] for k in th['knife_edge_negatives_within_0.003']]}")
            if arm in ("S", "F"):
                # The shipped tau is the 6-dp rounding of an INCORRECT positive's
                # score (row 68, 'electronic nicotine delivery frequency'). On the
                # training machine batch encoding put it 1.9e-8 below the threshold
                # and single-query encoding 4.5e-8 above; on the x86 serving machine
                # single-query encoding put it below again. tau* therefore flips
                # between 0.729476 and 0.731902 by machine, and F1(shipped) is at
                # most one row short of the optimum. Recall and the negatives are
                # unaffected. Assert the facts that hold everywhere; report the rest.
                check(f"arm {arm} recall at shipped min_cos",
                      th["at_shipped_tau"]["recall"], EXPECTED_RECALL_AT_SHIPPED[arm], fails)
                check(f"arm {arm} shipped min_cos within one row of max F1",
                      -0.002 < th["f1_at_shipped_minus_max_f1"] <= 0.0, True, fails)
                check(f"arm {arm} tau* is one of the two knife-edge candidates {KNIFE_EDGE_TAUS}",
                      th["tau_star_artifact_rule_4dp_f1_lowest_tie"] in KNIFE_EDGE_TAUS, True, fails)

        print("6. isolated single-query latency at the pinned thread count")
        for q in queries["S"][:8]:
            r.encode_queries([q])
        t0 = time.perf_counter()
        for q in queries["S"]:
            r.encode_queries([q])
        ms = (time.perf_counter() - t0) / len(queries["S"]) * 1000
        rep["latency"] = {"query_ms_isolated_single": round(ms, 2), "threads": r.threads,
                          "n_queries": len(queries["S"])}
        print(f"  {ms:.2f} ms/query at {r.threads} threads "
              f"(manifest records {m.get('device', {}).get('query_ms_isolated_single_at_pinned_threads')} "
              f"on {m.get('device', {}).get('latency_measured_on')})")

        print("7. canonical smoke queries")
        rep["smoke"] = []
        for q, want in CANONICAL:
            hit = r.select(q)
            got = hit["key"] if hit else None
            best = hit["cos"] if hit else r.search(q, k=1)[0]["cos"]
            rep["smoke"].append({"query": q, "selected": got, "cos": best})
            check(f"{q!r}", got, want, fails)

    except Failed as e:
        rep["result"] = {"ok": False, "error": str(e), "failures": fails}
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(rep, indent=1))
        print(f"\nSTOP: {e}\nreport -> {a.report}")
        return e.code

    rep["result"] = {"ok": not fails, "failures": fails}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(rep, indent=1))
    print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAILURE(S)'}  report -> {a.report}")
    for f in fails:
        print(f"  - {f}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
