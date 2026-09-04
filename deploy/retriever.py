"""COMPASS variable retriever -- CPU-only runtime for the frozen deploy bundle.

    from retriever import CompassRetriever
    r = CompassRetriever()                      # asserts the dictionary hash
    for hit in r.search("exogenous hormone medication", k=5):
        print(hit["cos"], hit["key"], hit["stem"], hit["option"])

    r.select("ambient PM2.5 exposure")           # -> None (abstains)

Design commitments, all of them because the alternative fails silently:

  * The dictionary build hash in manifest.json is asserted against targets.json
    and RAISES. A stale vector file returns wrong answers with no error.
  * Every shipped file's sha256 is verified against the manifest at load.
  * The device is pinned to CPU. The checkpoint has one GPU/CPU top-1
    disagreement in 224 rows, on the hardest query in the benchmark.
  * The query prefix, CLS pooling, fp32 and the max sequence lengths come from
    the manifest, never from a default. Dropping the BGE query prefix costs
    accuracy and raises no error.
  * `select()` abstains below the manifest's threshold. `search()` returns
    everything and lets the caller decide.
  * The torch thread count is read from the manifest (4) unless the caller
    overrides it: an unpinned count makes latency unreproducible.
  * The query template ships in the bundle (template.py, sha256 in the
    manifest) and is re-exported here as RetrievalRequest / VariableRole with
    search_request() / select_request(). Shipped contract: instances only.

No torch.load, no pickle: weights and vectors are both safetensors.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parent


def _load_template(root: Path):
    """template.py ships in the bundle (sha256 in the manifest). Loaded by path
    so this works whether retriever.py is imported as a module or by path."""
    spec = importlib.util.spec_from_file_location("compass_deploy_template",
                                                  root / "template.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod        # dataclasses resolves annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


_template = _load_template(ROOT)
RetrievalRequest = _template.RetrievalRequest      # re-exported: the shipped template
VariableRole = _template.VariableRole


class DictionaryHashMismatch(RuntimeError):
    """Raised, never warned: stale vectors return wrong answers silently."""


class BundleIntegrityError(RuntimeError):
    pass


class CompassRetriever:
    def __init__(self, root: Path | str = ROOT, *,
                 expect_dictionary_hash: str | None = None,
                 verify_checksums: bool = True,
                 threads: int | None = None):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        m = self.manifest

        want = expect_dictionary_hash or m["dictionary_version_hash"]
        if verify_checksums:
            self._verify_files()

        T = json.loads((self.root / m["corpus"]["targets_file"]).read_text())
        if T["dictionary_version_hash"] != want:
            raise DictionaryHashMismatch(
                f"targets built from {T['dictionary_version_hash']}, "
                f"bundle declares {want}. Refusing to serve: a stale vector file "
                f"returns wrong answers silently. Rebuild with "
                f"src/compass_build.py and re-run src/freeze_deploy.py.")
        self.targets = T["targets"]

        V = load_file(str(self.root / m["corpus"]["vectors_file"]))
        self.D = V["target_vectors"]
        if self.D.shape[0] != len(self.targets):
            raise BundleIntegrityError(
                f"{self.D.shape[0]} vectors for {len(self.targets)} targets")
        if self.D.shape[1] != m["encoder"]["embed_dim"]:
            raise BundleIntegrityError(
                f"vector dim {self.D.shape[1]} != manifest "
                f"{m['encoder']['embed_dim']}")
        # row i must be target_id i+1: the manifest claims it, so check it
        for i, t in enumerate(self.targets):
            if t["target_id"] != i + 1:
                raise BundleIntegrityError(
                    f"target row {i} has target_id {t['target_id']}, expected {i+1}")

        c = m["conventions"]
        self.q_prefix = c["query_prefix"]
        self.pool = c["pooling"]
        self.max_len_query = c["max_len_query"]
        self.padding_side = c["padding_side"]
        self.min_cos = m["abstention"]["default_min_cos"]

        # thread count comes from the manifest unless the caller overrides it:
        # an unpinned count makes latency unreproducible across machines
        if threads is None:
            threads = m.get("device", {}).get("threads")
        if threads:
            torch.set_num_threads(int(threads))
        self.threads = torch.get_num_threads()
        mdir = str(self.root / "model")
        self.tok = AutoTokenizer.from_pretrained(mdir)
        self.tok.padding_side = self.padding_side
        # device pinned: see manifest["device"]["why"]
        self.model = AutoModel.from_pretrained(
            mdir, dtype=torch.float32).to("cpu").eval()

    # ---------------------------------------------------------------- internals

    def _verify_files(self) -> None:
        for rel, meta in self.manifest["files"].items():
            p = self.root / rel
            if not p.exists():
                raise BundleIntegrityError(f"missing shipped file: {rel}")
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != meta["sha256"]:
                raise BundleIntegrityError(
                    f"{rel} sha256 {h.hexdigest()[:12]} != manifest "
                    f"{meta['sha256'][:12]}; the bundle has been modified")

    @torch.no_grad()
    def encode_queries(self, texts: list[str]) -> torch.Tensor:
        enc = self.tok([self.q_prefix + t for t in texts], truncation=True,
                       padding=True, max_length=self.max_len_query,
                       return_tensors="pt")
        h = self.model(**enc).last_hidden_state
        if self.pool == "cls":
            v = h[:, 0, :]
        elif self.pool == "mean":
            mk = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
            v = (h * mk).sum(1) / mk.sum(1).clamp(min=1e-9)
        else:
            raise BundleIntegrityError(f"unsupported pooling {self.pool!r}")
        return torch.nn.functional.normalize(v, dim=-1)

    def _hit(self, tid_idx: int, cos: float) -> dict:
        t = self.targets[tid_idx]
        return {"target_id": t["target_id"], "key": t["canonical_key"],
                "construct_key": t["construct_key"], "module": t["module"],
                "stem": t["stem"], "option": t["option"],
                "fold_size": t["fold_size"], "n_siblings": len(t["siblings"]),
                "members": t["members"], "cos": round(cos, 6)}

    # ------------------------------------------------------------------- public

    def search(self, query: str, k: int = 10) -> list[dict]:
        """Top-k by cosine. Returns hits regardless of confidence."""
        sims = (self.encode_queries([query]) @ self.D.T)[0]
        k = min(k, sims.numel())
        cos, idx = torch.topk(sims, k)
        return [self._hit(int(i), float(c)) for c, i in zip(cos, idx)]

    def select(self, query: str, min_cos: float | None = None) -> dict | None:
        """Argmax with abstention -- the deployed operating point.

        Returns None when the best cosine falls below the threshold, i.e. when
        the requested construct is probably not in the instrument. A returned
        hit is NOT verified: see manifest["abstention"]["what_it_does_NOT_do"].
        """
        thr = self.min_cos if min_cos is None else min_cos
        top = self.search(query, k=2)
        if top[0]["cos"] < thr:
            return None
        top[0]["margin_12"] = round(top[0]["cos"] - top[1]["cos"], 6)
        return top[0]

    # --- the shipped template, so a caller cannot load the retriever and forget it.
    # Contract is INSTANCES ONLY: see manifest["template"]. `population` stays None.

    def search_request(self, req: "RetrievalRequest", k: int = 10) -> list[dict]:
        return self.search(req.to_query(), k=k)

    def select_request(self, req: "RetrievalRequest",
                       min_cos: float | None = None) -> dict | None:
        return self.select(req.to_query(), min_cos=min_cos)


if __name__ == "__main__":
    import sys
    r = CompassRetriever()
    m = r.manifest
    print(f"COMPASS retriever  dict {m['dictionary_version_hash']}  "
          f"{m['corpus']['n_targets']} targets  dim {m['encoder']['embed_dim']}  "
          f"device {m['device']['pinned']}  min_cos {r.min_cos:.4f}")
    qs = sys.argv[1:] or ["exogenous hormone medication",
                          "primary method used to get to work",
                          "ambient PM2.5 exposure at the residential address",
                          "polygenic risk score for breast cancer"]
    for q in qs:
        hit = r.select(q)
        if hit is None:
            best = r.search(q, k=1)[0]
            print(f"\n{q!r}\n  ABSTAIN (best cos {best['cos']:.4f} < "
                  f"{r.min_cos:.4f}; nearest was {best['key']})")
        else:
            print(f"\n{q!r}\n  {hit['key']}  cos {hit['cos']:.4f}  "
                  f"margin {hit['margin_12']:.4f}\n  {hit['stem']}"
                  + (f"\n  option: {hit['option']}" if hit["option"] else ""))
