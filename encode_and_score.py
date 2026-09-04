"""Arm E: zero-shot biomedical embedding retrieval over the COMPASS dictionary.

Encodes the 1,352 selection targets (1,241 before the 2026-09-02 free-text fix)
and the fixture's requests with a frozen model, selects by argmax cosine, and
reports the figures docs/arm-e-results.md and arm_hybrid_e_D.md carry. The
retrieval tree's src/compass_score.py supersedes this driver for RESULTS.md.
This file has been edited since it produced arm_e.medcpt_a.json (d_prefix,
load_dense, pool="last", more configs); the MODELS dict below, not the list in
this docstring, is the authority on configs.

No training. No fine-tuning. Frozen weights only.

    python build_targets.py --dictionary build/dictionary.json --out targets.json
    python encode_and_score.py --targets targets.json \
        --fixture benchmark/fixtures/<the 224-row file>.json \
        --model medcpt-a --out arm_e.medcpt_a.json

Models:
    medcpt-a   ncbi/MedCPT-*        title=option,  abstract=stem
    medcpt-b   ncbi/MedCPT-*        title=stem,    abstract=option
    biolord    FremyCompany/BioLORD-2023   symmetric
    bge-small  BAAI/bge-small-en-v1.5      symmetric, query prefix
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

MODELS = {
    "medcpt-a": {"q": "ncbi/MedCPT-Query-Encoder",
                 "d": "ncbi/MedCPT-Article-Encoder",
                 "order": "option_first", "pool": "cls", "q_prefix": ""},
    "medcpt-b": {"q": "ncbi/MedCPT-Query-Encoder",
                 "d": "ncbi/MedCPT-Article-Encoder",
                 "order": "stem_first", "pool": "cls", "q_prefix": ""},
    "biolord":  {"q": "FremyCompany/BioLORD-2023",
                 "d": "FremyCompany/BioLORD-2023",
                 "order": "stem_first", "pool": "mean", "q_prefix": ""},
    "bge-small": {"q": "BAAI/bge-small-en-v1.5",
                  "d": "BAAI/bge-small-en-v1.5",
                  "order": "stem_first", "pool": "cls",
                  "q_prefix": "Represent this sentence for searching "
                              "relevant passages: "},
    # --- size ladder, everything but parameter count held constant ---------
    "bge-base": {"q": "BAAI/bge-base-en-v1.5", "d": "BAAI/bge-base-en-v1.5",
                 "order": "stem_first", "pool": "cls",
                 "q_prefix": "Represent this sentence for searching "
                             "relevant passages: "},
    "bge-large": {"q": "BAAI/bge-large-en-v1.5", "d": "BAAI/bge-large-en-v1.5",
                  "order": "stem_first", "pool": "cls",
                  "q_prefix": "Represent this sentence for searching "
                              "relevant passages: "},
    # --- the prefix control ------------------------------------------------
    # bge-small won the four-config comparison WITH an asymmetric query prefix
    # while biolord ran symmetric with none, so the winner had a treatment the
    # runner-up did not. BioLORD's card documents NO query prefix and describes
    # a symmetric similarity model, so the confound cannot be closed by giving
    # biolord one -- that would be inventing a convention. It is closed from the
    # other side: the same winner, its documented prefix removed.
    "bge-small-noprefix": {"q": "BAAI/bge-small-en-v1.5",
                           "d": "BAAI/bge-small-en-v1.5",
                           "order": "stem_first", "pool": "cls",
                           "q_prefix": ""},
    # --- Qwen3, which is not the BGE shape ---------------------------------
    # Per its model card: last-token pooling, queries carry
    # "Instruct: {task}\nQuery:{q}", documents carry NO instruction, and
    # embeddings are L2-normalised (which `encode` already does). The card
    # recommends left padding; `pool(how="last")` indexes the last non-pad token
    # instead, which the card names as the equivalent for right-padded input.
    # Running it under the BGE prefix would understate it by a documented 1-5%.
    # --- EmbeddingGemma: one encoder, but query and document prompts differ ---
    # Verbatim from the model card, 2026-09-03:
    #   query    "task: search result | query: {content}"
    #   document "title: {title | \"none\"} | text: {content}"
    # so this is the first config needing a DOCUMENT prefix as well as a query
    # one -- `d_prefix`, added for it. The card also warns that activations do
    # not support float16 (float32 or bfloat16 only); this script runs float32,
    # so that is already satisfied.
    #
    # POOLING VERIFIED 2026-09-03 from `1_Pooling/config.json` at revision
    # 57c266a740f5: pooling_mode_mean_tokens true, every other mode false.
    # The same file's modules list is [Transformer, Pooling, Dense, Dense,
    # Normalize], so `dense` below is not optional -- without it this config
    # embeds in the pre-projection space and measures a model nobody ships.
    "embeddinggemma": {"q": "google/embeddinggemma-300m",
                       "d": "google/embeddinggemma-300m",
                       "order": "stem_first", "pool": "mean",
                       "q_prefix": "task: search result | query: ",
                       "d_prefix": "title: none | text: ",
                       "dense": ["2_Dense", "3_Dense"]},
    "qwen3-0.6b": {"q": "Qwen/Qwen3-Embedding-0.6B",
                   "d": "Qwen/Qwen3-Embedding-0.6B",
                   "order": "stem_first", "pool": "last",
                   "q_prefix": "Instruct: Given a researcher's request for a "
                               "variable, retrieve the survey question that "
                               "measures it\nQuery:"},
}


def pool(out, mask, how):
    h = out.last_hidden_state
    if how == "cls":
        return h[:, 0, :]
    if how == "last":
        # Qwen3-Embedding pools the LAST token. Its card recommends left padding
        # and then h[:, -1]; with the right padding this script already uses,
        # the documented alternative is the last NON-PAD token, which is what
        # this indexes. Equivalent, and it does not require the tokenizer's
        # padding side to be changed underneath every other config.
        idx = mask.sum(dim=1) - 1
        return h[torch.arange(h.size(0), device=h.device), idx]
    m = mask.unsqueeze(-1).float()
    return (h * m).sum(1) / m.sum(1).clamp(min=1e-9)


def load_dense(repo, dirs, device="cpu"):
    """Post-pooling projection layers, for models whose embedding is not the pool.

    `AutoModel` gives the transformer; it does NOT give the sentence-transformers
    head. EmbeddingGemma's `modules.json` is
    [Transformer, Pooling, Dense, Dense, Normalize] -- two 768->3072->768 linear
    layers with no bias and Identity activation -- so pooling and normalising
    alone embeds in the PRE-projection space and is not the published model.
    Every other config in MODELS is [Transformer, Pooling(, Normalize)] and needs
    none of this; checked against each repo's modules.json 2026-09-03.
    """
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    mats = []
    for d in dirs:
        w = load_file(hf_hub_download(repo, f"{d}/model.safetensors"))
        mats.append(w["linear.weight"].to(device))
    return mats


@torch.no_grad()
def encode(texts, tok, model, how, max_len, device, batch=32, pair=False,
           dense=None):
    vecs = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        if pair:
            enc = tok([c[0] for c in chunk], [c[1] for c in chunk],
                      truncation=True, padding=True, max_length=max_len,
                      return_tensors="pt")
        else:
            enc = tok(chunk, truncation=True, padding=True,
                      max_length=max_len, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        v = pool(model(**enc), enc["attention_mask"], how)
        for w in (dense or ()):                # Pooling -> Dense -> Normalize
            v = v @ w.T
        vecs.append(torch.nn.functional.normalize(v, dim=-1).cpu())
    return torch.cat(vecs)


def target_text(t, order):
    stem, opt = t["stem"] or "", t["option"] or ""
    if not opt:
        return (stem, stem)
    return (opt, stem) if order == "option_first" else (stem, opt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--model", choices=sorted(MODELS), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dictionary-hash", default=None,
                    help="assert targets were built from this build")
    a = ap.parse_args()

    T = json.loads(a.targets.read_text())
    if a.dictionary_hash and T["dictionary_version_hash"] != a.dictionary_hash:
        # A stale vector file gives wrong answers silently. Fail loudly.
        print(f"targets built from {T['dictionary_version_hash']}, "
              f"expected {a.dictionary_hash}", file=sys.stderr)
        return 2
    targets = T["targets"]
    by_key = {}
    for t in targets:
        for m in t["members"]:
            by_key[m] = t["target_id"]

    rows = json.loads(a.fixture.read_text())
    if isinstance(rows, dict):                     # tolerate {"rows": [...]}
        rows = next(v for v in rows.values() if isinstance(v, list))

    cfg = MODELS[a.model]
    tok_q = AutoTokenizer.from_pretrained(cfg["q"])
    mod_q = AutoModel.from_pretrained(cfg["q"]).to(a.device).eval()
    if cfg["d"] == cfg["q"]:
        tok_d, mod_d = tok_q, mod_q
    else:
        tok_d = AutoTokenizer.from_pretrained(cfg["d"])
        mod_d = AutoModel.from_pretrained(cfg["d"]).to(a.device).eval()

    dense = (load_dense(cfg["d"], cfg["dense"], a.device)
             if cfg.get("dense") else None)

    t0 = time.time()
    pairs = [target_text(t, cfg["order"]) for t in targets]
    if cfg["d"] == cfg["q"]:                       # symmetric: one flat string
        d_prefix = cfg.get("d_prefix", "")
        D = encode([d_prefix + f"{x[0]} {x[1]}".strip() for x in pairs],
                   tok_d, mod_d, cfg["pool"], 256, a.device, dense=dense)
    else:
        D = encode(pairs, tok_d, mod_d, cfg["pool"], 256, a.device, pair=True,
                   dense=dense)
    encode_s = time.time() - t0

    reqs = [cfg["q_prefix"] + r["query"] for r in rows]
    t1 = time.time()
    Q = encode(reqs, tok_q, mod_q, cfg["pool"], 64, a.device, dense=dense)
    query_ms = (time.time() - t1) / max(1, len(reqs)) * 1000

    sims = Q @ D.T                                 # (rows, targets)
    order = sims.argsort(dim=-1, descending=True)

    scored, missing = [], 0
    for i, r in enumerate(rows):
        gid = by_key.get(r["key"])
        if gid is None:                            # excluded as identifier/free text
            missing += 1
            continue
        pos = (order[i] == (gid - 1)).nonzero()
        rank = int(pos[0, 0]) + 1
        top = targets[int(order[i, 0])]
        scored.append({
            "query": r["query"], "gold_key": r["key"], "gold_target": gid,
            "rank": rank,
            "top_target": top["target_id"], "top_key": top["canonical_key"],
            "top_option": top["option"],
            "cos_gold": float(sims[i, gid - 1]),
            "cos_top": float(sims[i, int(order[i, 0])]),
            "gold_in_multi_option": bool(targets[gid - 1]["siblings"]),
        })

    def at(k): return sum(1 for s in scored if s["rank"] <= k)
    n = len(scored)
    multi = [s for s in scored if s["gold_in_multi_option"]]

    # sibling cosine: does the frozen model separate options within a construct?
    sibcos = []
    for t in targets:
        if not t["siblings"]:
            continue
        v = D[t["target_id"] - 1]
        for sid in t["siblings"][:8]:
            sibcos.append(float(v @ D[sid - 1]))

    rep = {
        "schema": "arm_e_scores/1",
        "model": a.model,
        "hf_repos": {"query": cfg["q"], "doc": cfg["d"]},
        "order": cfg["order"],
        "device": a.device,
        "dictionary_version_hash": T["dictionary_version_hash"],
        "n_targets": len(targets),
        "n_rows_scored": n,
        "n_rows_gold_excluded_from_targets": missing,
        "recall": {f"@{k}": round(at(k) / n, 3) for k in (1, 5, 10)},
        "rank": {
            "p50": st.median(s["rank"] for s in scored),
            "p90": sorted(s["rank"] for s in scored)[int(0.9 * n)],
            "max": max(s["rank"] for s in scored),
        },
        "near_duplicate": {
            "n_rows": len(multi),
            "recall@1": round(sum(1 for s in multi if s["rank"] == 1)
                              / max(1, len(multi)), 3),
            "recall@10": round(sum(1 for s in multi if s["rank"] <= 10)
                               / max(1, len(multi)), 3),
        },
        "sibling_cosine": {
            "n_pairs": len(sibcos),
            "p50": round(st.median(sibcos), 4) if sibcos else None,
            "p90": round(sorted(sibcos)[int(0.9 * len(sibcos))], 4) if sibcos else None,
            "max": round(max(sibcos), 4) if sibcos else None,
        },
        "cost": {"target_encode_s": round(encode_s, 1),
                 "query_ms_per_row": round(query_ms, 1)},
        "rows": scored,
    }
    a.out.write_text(json.dumps(rep, indent=1))

    print(f"{a.model}  ({cfg['order']}, {a.device})")
    print(f"  rows scored        {n}   gold not a target: {missing}")
    print(f"  recall@1/5/10      {rep['recall']['@1']} / "
          f"{rep['recall']['@5']} / {rep['recall']['@10']}")
    print(f"  rank p50/p90/max   {rep['rank']['p50']} / "
          f"{rep['rank']['p90']} / {rep['rank']['max']}")
    print(f"  near-dup @1/@10    {rep['near_duplicate']['recall@1']} / "
          f"{rep['near_duplicate']['recall@10']}  "
          f"(n={rep['near_duplicate']['n_rows']})")
    print(f"  sibling cos p50    {rep['sibling_cosine']['p50']}  "
          f"p90 {rep['sibling_cosine']['p90']}")
    print(f"  encode {rep['cost']['target_encode_s']}s   "
          f"query {rep['cost']['query_ms_per_row']}ms/row")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
