"""Contrastive fine-tune of a bi-encoder on synthetic (request, target) pairs.

In-batch negatives plus hard negatives mined from the FROZEN base model's own
top-k retrievals. Those errors are predominantly wrong-construct, which is where
57-92% of top-1 errors actually land; in-construct sibling negatives are a
retired idea and are not used here.

Saves safetensors with tensors on CPU. No pickled objects.
"""
from __future__ import annotations

import argparse, hashlib, json, math, random, sys, time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, str(Path(__file__).parent))
from compass_score import MODELS, target_text, pool_hidden, load_dense


def embed(model, enc, how, dense):
    """Pool, then apply any trained Dense projections, then L2-normalise.
    EmbeddingGemma's two Dense layers are part of the model; training without
    them would fit a different architecture than the one we score."""
    v = pool_hidden(model(**enc), enc["attention_mask"], how)
    if dense is not None:
        for lin in dense:
            v = lin(v)
    return F.normalize(v, dim=-1)


def encode_all(texts, tok, model, how, max_len, device, batch=64, dense=None):
    vecs = []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(texts), batch):
            enc = tok(texts[i:i + batch], truncation=True, padding=True,
                      max_length=max_len, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            vecs.append(embed(model, enc, how, dense).float())
    return torch.cat(vecs)


class PairSet(Dataset):
    def __init__(self, pairs, negs, n_neg):
        self.pairs, self.negs, self.n_neg = pairs, negs, n_neg

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, i):
        p = self.pairs[i]
        pool = self.negs.get(p["target_id"], [])
        chosen = random.sample(pool, min(self.n_neg, len(pool))) if pool else []
        while len(chosen) < self.n_neg:
            chosen.append(random.randrange(1, self.n_targets + 1))
        return p["query"], p["target_id"], chosen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--model", default="bge-small", choices=sorted(MODELS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--target-text", default="stem_option_dup")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--temp", type=float, default=0.05)
    ap.add_argument("--n-neg", type=int, default=4)
    ap.add_argument("--mine-topk", type=int, default=30)
    ap.add_argument("--pool", default=None, help="override the model's pooling")
    ap.add_argument("--seed", type=int, default=20260903)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--q-len", type=int, default=32)
    ap.add_argument("--d-len", type=int, default=128)
    ap.add_argument("--max-gpu-gb", type=float, default=80.0,
                    help="hard cap on this process's GPU allocation. The GB10's "
                         "128 GB RAM is unified, so GPU allocation counts against "
                         "system memory; ~110 GB is usable, so cap well under that "
                         "and leave room for concurrent CPU scoring.")
    ap.add_argument("--encode-batch", type=int, default=256)
    a = ap.parse_args()

    random.seed(a.seed); torch.manual_seed(a.seed)
    if a.device.startswith("cuda") and torch.cuda.is_available():
        total_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        frac = min(0.95, a.max_gpu_gb / total_gb)
        torch.cuda.set_per_process_memory_fraction(frac)
        print(f"  gpu cap {a.max_gpu_gb:.1f} GB of {total_gb:.0f} GB unified "
              f"(fraction {frac:.4f})", flush=True)
    cfg = MODELS[a.model]
    how = a.pool or cfg["pool"]
    dev = a.device

    T = json.loads(a.targets.read_text())
    targets = T["targets"]
    n_t = len(targets)
    P = json.loads(a.pairs.read_text())
    pairs = P["pairs"]

    tok = AutoTokenizer.from_pretrained(cfg["repo"], revision=cfg["rev"],
                                        trust_remote_code=cfg["trc"])
    tok.padding_side = cfg["pad"]
    # Force fp32: several configs declare fp16/bf16, and fp16 training without
    # loss scaling produces NaN hidden states after the first optimizer step.
    model = AutoModel.from_pretrained(cfg["repo"], revision=cfg["rev"],
                                      trust_remote_code=cfg["trc"],
                                      dtype=torch.float32).to(dev)
    dense = None
    if cfg.get("dense"):
        ws = load_dense(cfg["dense"])
        dense = torch.nn.ModuleList()
        for w in ws:
            lin = torch.nn.Linear(w.shape[1], w.shape[0], bias=False)
            lin.weight.data = w.clone()
            dense.append(lin)
        dense = dense.to(dev)
        print(f"  loaded {len(dense)} trained Dense projections "
              f"{[tuple(l.weight.shape) for l in dense]}", flush=True)

    doc_texts = [cfg["d_prefix"] + target_text(t, a.target_text) for t in targets]
    q_texts = [cfg["q_prefix"] + p["query"] for p in pairs]

    # ---- mine hard negatives from the frozen model's own top-k -------------
    t_mine = time.time()
    D0 = encode_all(doc_texts, tok, model, how, a.d_len, dev, a.encode_batch, dense)
    Q0 = encode_all(q_texts, tok, model, how, a.q_len, dev, a.encode_batch, dense)
    negs: dict[int, list[int]] = {}
    with torch.no_grad():
        for i in range(0, len(pairs), 1024):
            sims = Q0[i:i + 1024] @ D0.T
            top = sims.topk(a.mine_topk, dim=-1).indices.cpu()
            for r, p in enumerate(pairs[i:i + 1024]):
                gid = p["target_id"]
                cand = [int(x) + 1 for x in top[r] if int(x) + 1 != gid]
                negs.setdefault(gid, [])
                negs[gid].extend(cand)
    for k in negs:
        negs[k] = list(dict.fromkeys(negs[k]))[: 4 * a.mine_topk]
    mine_s = time.time() - t_mine
    del D0, Q0
    torch.cuda.empty_cache()

    ds = PairSet(pairs, negs, a.n_neg); ds.n_targets = n_t

    def collate(b):
        qs = [cfg["q_prefix"] + x[0] for x in b]
        pos = [x[1] for x in b]
        neg = [n for x in b for n in x[2]]
        return qs, pos, neg

    dl = DataLoader(ds, batch_size=a.batch_size, shuffle=True,
                    collate_fn=collate, drop_last=True)
    params = list(model.parameters()) + (list(dense.parameters()) if dense else [])
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.01)
    steps = len(dl) * a.epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr,
                                                total_steps=steps, pct_start=0.1)

    t0 = time.time()
    model.train()
    losses = []
    for ep in range(a.epochs):
        for qs, pos, neg in dl:
            docs = [doc_texts[i - 1] for i in pos] + [doc_texts[i - 1] for i in neg]
            eq = tok(qs, truncation=True, padding=True, max_length=a.q_len,
                     return_tensors="pt").to(dev)
            ed = tok(docs, truncation=True, padding=True, max_length=a.d_len,
                     return_tensors="pt").to(dev)
            vq = embed(model, eq, how, dense)
            vd = embed(model, ed, how, dense)
            logits = (vq @ vd.T) / a.temp
            # Row i's positive is column i. Columns beyond len(pos) are mined
            # negatives shared across the batch; other rows' positives act as
            # in-batch negatives. Mask duplicate positives so a repeated target
            # is not scored as its own negative.
            b = len(pos)
            allids = torch.tensor(pos + neg, device=dev)
            posids = torch.tensor(pos, device=dev)
            dup = (allids.unsqueeze(0) == posids.unsqueeze(1))
            eye = torch.zeros_like(dup)
            eye[torch.arange(b, device=dev), torch.arange(b, device=dev)] = True
            logits = logits.masked_fill(dup & ~eye, float("-inf"))
            loss = F.cross_entropy(logits, torch.arange(b, device=dev))
            if not torch.isfinite(loss):
                raise RuntimeError(
                    f"non-finite loss ({loss}) at epoch {ep+1}; refusing to "
                    f"continue and save a diverged checkpoint")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            losses.append(float(loss))
        print(f"  epoch {ep+1}/{a.epochs}  loss {sum(losses[-len(dl):])/len(dl):.4f}",
              flush=True)
    train_s = time.time() - t0

    a.out.mkdir(parents=True, exist_ok=True)
    model.cpu().eval()
    model.save_pretrained(a.out, safe_serialization=True)   # safetensors, CPU
    tok.save_pretrained(a.out)
    if dense is not None:
        # save in the sentence-transformers layout the scorer already reads
        from safetensors.torch import save_file
        for name, lin in zip(("2_Dense", "3_Dense"), dense):
            d = a.out / name; d.mkdir(parents=True, exist_ok=True)
            save_file({"linear.weight": lin.weight.data.cpu().contiguous()},
                      str(d / "model.safetensors"))
    meta = {
        "base_model": cfg["repo"], "base_revision": cfg["rev"],
        "params_m": cfg["params"], "pool": how, "target_text": a.target_text,
        "training_set_sha256": P["training_set_sha256"],
        "training_pairs": len(pairs), "n_targets": n_t,
        "dictionary_version_hash": T["dictionary_version_hash"],
        "negative_strategy": "in-batch + frozen-model top-k mined (wrong-construct dominant)",
        "mine_topk": a.mine_topk, "n_neg_per_query": a.n_neg,
        "epochs": a.epochs, "batch_size": a.batch_size, "lr": a.lr,
        "temperature": a.temp, "seed": a.seed,
        "q_len": a.q_len, "d_len": a.d_len,
        "mine_wall_s": round(mine_s, 1), "train_wall_s": round(train_s, 1),
        "max_gpu_gb_cap": a.max_gpu_gb,
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)
        if dev.startswith("cuda") else None,
        "device": dev, "machine": "DGX Spark GB10, 20-core Arm CPU, SM12.1 GPU",
        "final_loss": round(sum(losses[-max(1, len(dl)):]) / max(1, len(dl)), 4),
    }
    (a.out / "compass_train_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"mined {mine_s:.1f}s  trained {train_s:.1f}s  -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
