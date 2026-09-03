"""Prove the deploy bundle's guards FAIL rather than warn.

An assertion that is never exercised is a comment. This tampers with a copy of
the bundle three ways and asserts each one raises:

  1. targets.json built from a different dictionary  -> DictionaryHashMismatch
  2. a shipped file modified after freezing          -> BundleIntegrityError
  3. the vector row order permuted                   -> BundleIntegrityError

Also asserts the untampered bundle loads and reproduces R@1 0.567.

    python src/test_deploy_asserts.py --bundle deploy
"""
from __future__ import annotations

import argparse, importlib.util, json, shutil, sys, tempfile
from pathlib import Path


def load_retriever(bundle: Path):
    spec = importlib.util.spec_from_file_location(
        f"retriever_{abs(hash(str(bundle)))}", bundle / "retriever.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def expect_raise(fn, exc, what):
    try:
        fn()
    except exc as e:
        print(f"  PASS  {what}: {type(e).__name__}: {str(e).splitlines()[0][:90]}")
        return True
    except Exception as e:                       # noqa: BLE001
        print(f"  FAIL  {what}: raised {type(e).__name__}, expected {exc.__name__}")
        return False
    print(f"  FAIL  {what}: did NOT raise (a warning is not enough)")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=Path("deploy"))
    ap.add_argument("--fixture", type=Path, default=Path("retrieval_queries.json"))
    a = ap.parse_args()
    ok = []

    R = load_retriever(a.bundle)
    print("1. untampered bundle")
    r = R.CompassRetriever(a.bundle)
    rows = json.loads(a.fixture.read_text())["queries"]
    by_key = {m: t["target_id"] for t in r.targets for m in t["members"]}
    Q = r.encode_queries([x["query"] for x in rows])
    top1 = (Q @ r.D.T).argmax(dim=-1)
    hits = sum(1 for i, x in enumerate(rows)
               if by_key.get(x["key"]) == int(top1[i]) + 1)
    r_at1 = round(hits / len(rows), 3)
    print(f"  {'PASS' if r_at1 == 0.567 else 'FAIL'}  loads and scores "
          f"R@1 {r_at1} (expected 0.567)")
    ok.append(r_at1 == 0.567)

    with tempfile.TemporaryDirectory() as td:
        print("2. dictionary hash mismatch")
        b = Path(td) / "hashbad"
        shutil.copytree(a.bundle, b)
        T = json.loads((b / "targets.json").read_text())
        T["dictionary_version_hash"] = "deadbeefcafe"
        (b / "targets.json").write_text(json.dumps(T))
        ok.append(expect_raise(
            lambda: R.CompassRetriever(b, verify_checksums=False),
            R.DictionaryHashMismatch, "stale targets.json"))

        print("3. shipped file modified after freezing")
        b2 = Path(td) / "tamper"
        shutil.copytree(a.bundle, b2)
        T = json.loads((b2 / "targets.json").read_text())
        T["targets"][0]["stem"] = "TAMPERED"
        (b2 / "targets.json").write_text(json.dumps(T))
        ok.append(expect_raise(lambda: R.CompassRetriever(b2),
                               R.BundleIntegrityError, "checksum mismatch"))

        print("4. vector row order permuted")
        b3 = Path(td) / "reorder"
        shutil.copytree(a.bundle, b3)
        T = json.loads((b3 / "targets.json").read_text())
        T["targets"][0], T["targets"][1] = T["targets"][1], T["targets"][0]
        (b3 / "targets.json").write_text(json.dumps(T))
        ok.append(expect_raise(
            lambda: R.CompassRetriever(b3, verify_checksums=False),
            R.BundleIntegrityError, "target_id / row-order mismatch"))

    print(f"\n{sum(ok)}/{len(ok)} checks passed")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
