"""Encode requests and selection targets with a frozen (or fine-tuned) encoder,
select by argmax cosine, and report the gold target's rank per fixture row.

A row is correct when the gold KEY's TARGET is at rank k. Targets fold roster
members, so this is more permissive than row-level wording equality.

Asserts the dictionary build hash at load: a stale vector file gives wrong
answers silently.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

EXPECTED_HASH = "3dc8415eccfe"

# Per-model prompting conventions. Running a model under the wrong convention
# underperforms for reasons unrelated to its quality.
MODELS = {
    # Conventions taken from each repo's 1_Pooling/config.json and
    # config_sentence_transformers.json, not from secondary sources.
    "bge-small": dict(repo="BAAI/bge-small-en-v1.5", rev="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
                      pool="cls", params=33,
                      q_prefix="Represent this sentence for searching relevant passages: ",
                      d_prefix="", pad="right", trc=False),
    "bge-base":  dict(repo="BAAI/bge-base-en-v1.5", rev="a5beb1e3e68b9ab74eb54cfd186867f64f240e1a",
                      pool="cls", params=109,
                      q_prefix="Represent this sentence for searching relevant passages: ",
                      d_prefix="", pad="right", trc=False),
    "e5-base":   dict(repo="intfloat/e5-base-v2", rev="f52bf8ec8c7124536f0efb74aca902b2995e5bcd",
                      pool="mean", params=109,
                      q_prefix="query: ", d_prefix="passage: ", pad="right", trc=False),
    "gte-mbert": dict(repo="Alibaba-NLP/gte-modernbert-base", rev="e7f32e3c00f91d699e8c43b53106206bcc72bb22",
                      pool="cls", params=149,
                      q_prefix="", d_prefix="", pad="right", trc=False),
    "arctic-m2": dict(repo="Snowflake/snowflake-arctic-embed-m-v2.0", rev="95c2741480856aa9666782eb4afe11959938017f",
                      pool="cls", params=305,
                      q_prefix="query: ", d_prefix="", pad="right", trc=True,
                      # its remote code defaults to xformers memory-efficient
                      # attention; force the eager path instead of installing a
                      # kernel we do not need at these sequence lengths.
                      extra=dict(use_memory_efficient_attention=False,
                                 unpad_inputs=False)),
    "qwen3-06b": dict(repo="Qwen/Qwen3-Embedding-0.6B", rev="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
                      pool="last", params=596,
                      q_prefix=("Instruct: Given a web search query, retrieve "
                                "relevant passages that answer the query\nQuery:"),
                      d_prefix="", pad="left", trc=False),
    # Requested as "qwen3.5 1.5B". No such model exists: the Qwen3.5 line ships
    # no official embedding model and has no 1.5B size. This is the only
    # Qwen3.5 embedding repo on the Hub -- a community fine-tune of
    # Qwen3.5-0.8B-Base, Apache-2.0, targeted at agent-memory retrieval.
    # Convention from its embedding_config.json + README, not inferred.
    "qwen35-08b": dict(repo="Rebine/Qwen3.5-Embedding-0.8B",
                       rev="3f77c4599cc3", pool="last", params=752,
                       q_prefix=("Instruct: Given a query, retrieve relevant "
                                 "passages that answer the query\nQuery: "),
                       d_prefix="", pad="left", trc=False),
    # Conventions read from each model card, not inferred from a sibling model.
    "nomic-v15":  dict(repo="nomic-ai/nomic-embed-text-v1.5", rev="main",
                       pool="mean", params=137,
                       q_prefix="search_query: ", d_prefix="search_document: ",
                       pad="right", trc=True, mrl_layernorm=True),
    "granite-s2": dict(repo="ibm-granite/granite-embedding-small-english-r2",
                       rev="main", pool="cls", params=48,
                       q_prefix="", d_prefix="", pad="right", trc=False),
    "mxbai-l1":   dict(repo="mixedbread-ai/mxbai-embed-large-v1", rev="main",
                       pool="cls", params=335,
                       q_prefix="Represent this sentence for searching relevant passages: ",
                       d_prefix="", pad="right", trc=False),
    # EmbeddingGemma is NOT a bare transformer: sentence-transformers applies
    # Pooling -> Dense(768->3072) -> Dense(3072->768) -> Normalize. Running it
    # as AutoModel + mean pooling alone silently skips two trained projections
    # and measures the wrong thing. Prefixes from config_sentence_transformers.
    "embgemma":   dict(repo="google/embeddinggemma-300m", rev="main",
                       pool="mean", params=303,
                       q_prefix="task: search result | query: ",
                       d_prefix="title: none | text: ",
                       pad="right", trc=False, dense="google/embeddinggemma-300m"),
    "biolord":   dict(repo="FremyCompany/BioLORD-2023", rev="main", pool="mean", params=109,
                      q_prefix="", d_prefix="", pad="right", trc=False),
}


def load_dense(repo_or_dir):
    """The two trained Dense projections sentence-transformers applies after
    pooling. Loaded directly so every model stays on one code path. Accepts a
    hub repo id or a local checkpoint directory (fine-tuned weights)."""
    from safetensors.torch import load_file
    from pathlib import Path as _P
    ws = []
    local = _P(str(repo_or_dir))
    for d in ("2_Dense", "3_Dense"):
        if (local / d / "model.safetensors").exists():
            f = local / d / "model.safetensors"
        else:
            from huggingface_hub import hf_hub_download
            f = hf_hub_download(str(repo_or_dir), f"{d}/model.safetensors")
        ws.append(load_file(str(f))["linear.weight"])
    return ws


def apply_mrl(v, dim, layernorm=False):
    """Truncate to `dim` and renormalise. Nomic documents a layer_norm first."""
    if not dim or dim >= v.shape[-1]:
        return F.normalize(v, dim=-1)
    if layernorm:
        v = F.layer_norm(v, normalized_shape=(v.shape[-1],))
    return F.normalize(v[:, :dim], dim=-1)


def pool_hidden(out, mask, how):
    h = out.last_hidden_state
    if how == "cls":
        return h[:, 0, :]
    if how == "last":                      # Qwen3-style, requires left padding
        return h[:, -1, :]
    m = mask.unsqueeze(-1).to(h.dtype)
    return (h * m).sum(1) / m.sum(1).clamp(min=1e-9)


@torch.no_grad()
def encode(texts, tok, model, how, max_len, device, batch=64,
           mrl_dim=None, mrl_layernorm=False, dense=None):
    vecs = []
    for i in range(0, len(texts), batch):
        enc = tok(texts[i:i + batch], truncation=True, padding=True,
                  max_length=max_len, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        v = pool_hidden(model(**enc), enc["attention_mask"], how)
        if dense is not None:
            for w in dense:
                v = v @ w.T.to(v.dtype).to(v.device)
        vecs.append(apply_mrl(v, mrl_dim, mrl_layernorm).float().cpu())
    return torch.cat(vecs)


def target_text(t, mode: str) -> str:
    """How a target is rendered for the document encoder."""
    stem = t["stem"] or ""
    opt = t["option"] or ""
    if mode == "stem_option":              # principled: stem, then option
        return f"{stem} {opt}".strip() if opt else stem
    if mode == "stem_option_dup":          # reproduces the published run
        return f"{stem} {opt}".strip() if opt else f"{stem} {stem}".strip()
    if mode == "stem_dash_option":
        return f"{stem} - {opt}".strip() if opt else stem
    if mode == "verbatim":
        return t["wording"]
    raise ValueError(mode)


def load(targets_path: Path, fixture_path: Path, expect_hash: str):
    T = json.loads(targets_path.read_text())
    if T["dictionary_version_hash"] != expect_hash:
        raise SystemExit(f"targets built from {T['dictionary_version_hash']}, "
                         f"expected {expect_hash} -- stale vectors give wrong "
                         f"answers silently")
    fx = json.loads(fixture_path.read_text())
    rows = fx["queries"] if isinstance(fx, dict) else fx
    return T, rows


def evaluate(T, rows, Q, D, targets):
    by_key = {}
    for t in targets:
        for m in t["members"]:
            by_key[m] = t["target_id"]

    sims = Q @ D.T
    order = sims.argsort(dim=-1, descending=True)
    rank_of = order.argsort(dim=-1)        # rank position of every target

    scored, missing = [], 0
    for i, r in enumerate(rows):
        gid = by_key.get(r["key"])
        if gid is None:
            missing += 1
            continue
        g = targets[gid - 1]
        top = targets[int(order[i, 0])]
        scored.append(dict(
            query=r["query"], gold_key=r["key"], gold_target=gid,
            rank=int(rank_of[i, gid - 1]) + 1,
            top_target=top["target_id"], top_key=top["canonical_key"],
            top_construct=top["construct_key"], gold_construct=g["construct_key"],
            right_construct=top["construct_key"] == g["construct_key"],
            gold_multi_option=bool(g["siblings"]),
            gold_folded=g["fold_size"] > 1,
            cos_gold=float(sims[i, gid - 1]), cos_top=float(sims[i, int(order[i, 0])]),
        ))
    return scored, missing, sims


def subset_stats(rows_subset, ks=(1, 5, 10, 25, 50)):
    n = len(rows_subset)
    if not n:
        return {"n": 0}
    ranks = sorted(s["rank"] for s in rows_subset)
    return {
        "n": n,
        **{f"@{k}": round(sum(1 for s in rows_subset if s["rank"] <= k) / n, 3)
           for k in ks},
        "rank_p50": ranks[int(0.5 * (n - 1))],
        "rank_p90": ranks[min(n - 1, int(0.9 * n))],
        "rank_max": ranks[-1],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--model", default="bge-small", choices=sorted(MODELS))
    ap.add_argument("--weights", type=Path, default=None,
                    help="fine-tuned checkpoint dir; convention comes from --model")
    ap.add_argument("--target-text", default="stem_option_dup",
                    choices=["stem_option", "stem_option_dup",
                             "stem_dash_option", "verbatim"])
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dictionary-hash", default=EXPECTED_HASH)
    ap.add_argument("--save-vectors", type=Path, default=None)
    ap.add_argument("--label", default=None)
    ap.add_argument("--mrl-dim", type=int, default=None,
                    help="truncate embeddings to this many dims, then renormalise")
    ap.add_argument("--dtype-from-config", action="store_true",
                    help="DIAGNOSTIC ONLY. Load in the dtype the repo's config "
                         "declares instead of forcing fp32. Reproduces the "
                         "pre-fp32 numbers in out/frozen_sweep.log and "
                         "out/round2.log for the repos that declare bf16/fp16. "
                         "Never use for a reported score: it makes models loaded "
                         "at different precisions incomparable.")
    a = ap.parse_args()

    T, rows = load(a.targets, a.fixture, a.dictionary_hash)
    targets = T["targets"]
    cfg = MODELS[a.model]
    src = str(a.weights) if a.weights else cfg["repo"]

    tok_kw = dict(trust_remote_code=cfg["trc"])
    mdl_kw = dict(trust_remote_code=cfg["trc"], **cfg.get("extra", {}))
    if not a.weights:
        tok_kw["revision"] = cfg["rev"]
        mdl_kw["revision"] = cfg["rev"]
    tok = AutoTokenizer.from_pretrained(src, **tok_kw)
    # Qwen3-Embedding pools the last token, which is only correct under left padding.
    tok.padding_side = cfg["pad"]
    # transformers v5 honours the config's dtype, so several repos would load
    # in fp16/bf16 while others load fp32 -- an unfair comparison, and fp16
    # training NaNs on the first step. Force fp32 everywhere.
    if not a.dtype_from_config:
        mdl_kw["dtype"] = torch.float32
    model = AutoModel.from_pretrained(src, **mdl_kw).to(a.device).eval()

    doc_texts = [cfg["d_prefix"] + target_text(t, a.target_text) for t in targets]
    t0 = time.time()
    mrl_ln = cfg.get("mrl_layernorm", False)
    dense = None
    if cfg.get("dense"):
        dense = load_dense(a.weights if a.weights else cfg["dense"])
    if dense is not None:
        dense = [w.to(a.device) for w in dense]
    D = encode(doc_texts, tok, model, cfg["pool"], 256, a.device,
               mrl_dim=a.mrl_dim, mrl_layernorm=mrl_ln, dense=dense)
    encode_s = time.time() - t0

    reqs = [cfg["q_prefix"] + r["query"] for r in rows]
    t1 = time.time()
    Q = encode(reqs, tok, model, cfg["pool"], 64, a.device,
               mrl_dim=a.mrl_dim, mrl_layernorm=mrl_ln, dense=dense)
    query_ms = (time.time() - t1) / max(1, len(reqs)) * 1000

    scored, missing, sims = evaluate(T, rows, Q, D, targets)

    # within-construct document cosine: does the model separate sibling options?
    sib = []
    for t in targets:
        if not t["siblings"]:
            continue
        v = D[t["target_id"] - 1]
        for sid in t["siblings"][:8]:
            sib.append(float(v @ D[sid - 1]))

    overall = subset_stats(scored)
    singleton = subset_stats([s for s in scored if not s["gold_folded"]])
    folded = subset_stats([s for s in scored if s["gold_folded"]])
    neardup = subset_stats([s for s in scored if s["gold_multi_option"]])
    errs = [s for s in scored if s["rank"] > 1]
    right_construct_err = [s for s in errs if s["right_construct"]]

    rep = {
        "schema": "compass_scores/2",
        "label": a.label or a.model,
        "model": a.model, "source": src, "revision": cfg["rev"], "params_m": cfg["params"],
        "target_text": a.target_text, "mrl_dim": a.mrl_dim,
        "embed_dim": None,
        "pool": cfg["pool"], "q_prefix": cfg["q_prefix"], "d_prefix": cfg["d_prefix"],
        "device": a.device,
        "dtype": "from_config" if a.dtype_from_config else "float32",
        "dictionary_version_hash": T["dictionary_version_hash"],
        "n_targets": len(targets), "n_rows_total": len(rows),
        "n_rows_scored": len(scored), "n_rows_unreachable": missing,
        "overall": overall, "singleton": singleton, "folded_family": folded,
        "near_duplicate": neardup,
        "near_duplicate_ratio_to_own_at1": (
            round(neardup["@1"] / overall["@1"], 3)
            if neardup.get("n") and overall["@1"] else None),
        "errors": {
            "n_top1_errors": len(errs),
            "right_construct_wrong_option": len(right_construct_err),
            "wrong_construct": len(errs) - len(right_construct_err),
            "wrong_construct_frac": (round((len(errs) - len(right_construct_err)) / len(errs), 3)
                                     if errs else None),
        },
        "within_construct_cosine": {
            "n_pairs": len(sib),
            "p50": round(st.median(sib), 4) if sib else None,
            "p90": round(sorted(sib)[int(0.9 * len(sib))], 4) if sib else None,
        },
        "cost": {"target_encode_s": round(encode_s, 1),
                 "query_ms_per_row": round(query_ms, 2)},
        "rows": scored,
    }
    a.out.write_text(json.dumps(rep, indent=1))
    if a.save_vectors:
        torch.save({"D": D, "dictionary_version_hash": T["dictionary_version_hash"],
                    "target_text": a.target_text, "model": src}, a.save_vectors)

    o = overall
    print(f"{rep['label']}  [{a.model} | {a.target_text} | {a.device}]")
    print(f"  targets {len(targets)}   rows scored {len(scored)}   unreachable {missing}")
    print(f"  @1 {o['@1']}  @5 {o['@5']}  @10 {o['@10']}  @25 {o['@25']}  @50 {o['@50']}")
    print(f"  rank p50 {o['rank_p50']}  p90 {o['rank_p90']}  max {o['rank_max']}")
    print(f"  singleton @1 {singleton.get('@1')} (n={singleton['n']})   "
          f"folded @1 {folded.get('@1')} (n={folded['n']})")
    print(f"  near-dup @1 {neardup.get('@1')} (n={neardup['n']})  "
          f"ratio-to-own-@1 {rep['near_duplicate_ratio_to_own_at1']}")
    print(f"  top1 errors {len(errs)}: wrong-construct {rep['errors']['wrong_construct']}"
          f" ({rep['errors']['wrong_construct_frac']}), "
          f"right-construct-wrong-option {len(right_construct_err)}")
    print(f"  within-construct cos p50 {rep['within_construct_cosine']['p50']} "
          f"p90 {rep['within_construct_cosine']['p90']}")
    print(f"  encode {encode_s:.1f}s   query {query_ms:.2f} ms/row")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
