"""Prove each check goes red on a planted violation.

A scan that has never fired is not known to work. For steps 1–5 the site is
copied to a scratch directory, one violation is planted, and the check runs
with ``SITE_ROOT`` pointing at the copy; it must exit non-zero. Step 6 needs
the real repository: an untracked artefact is created, the check runs, and
the file is removed again. The instrument run planted for step 2 is taken
from the dictionary at run time and written only to the scratch copy.

    python3 site/tools/plant.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent
REPO = SITE.parent


def run(step: str, root: Path) -> int:
    env = dict(os.environ, SITE_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(HERE / f"{step}.py")], env=env,
                       capture_output=True, text=True)
    return r.returncode


def copy_site(tmp: Path) -> Path:
    dst = tmp / "site"
    shutil.copytree(SITE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def plant_page(root: Path, marker: str, payload: str) -> None:
    p = root / "index.html"
    s = p.read_text(encoding="utf-8")
    assert marker in s, marker
    p.write_text(s.replace(marker, payload, 1), encoding="utf-8")


def instrument_run() -> str:
    dic = Path(os.environ["COMPASS_DICTIONARY"])
    for e in json.loads(dic.read_text(encoding="utf-8"))["entries"]:
        w = " ".join(str(e.get("question_text", "")).split()).split()
        if len(w) >= 8:
            return " ".join(w[:5])
    raise SystemExit("no dictionary entry long enough to plant")


def main() -> int:
    results: list[tuple[str, str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="site-plant-") as t:
        tmp = Path(t)
        # 1a a literal on the page
        root = copy_site(tmp / "a")
        plant_page(root, "<main class=\"wrap\">", "<main class=\"wrap\"><p>cos 0.8214</p>")
        results.append(("no_fabrication", "numeric literal on the page", run("no_fabrication", root) != 0))
        # 1b an artefact without provenance
        root = copy_site(tmp / "b")
        (root / "artefacts").mkdir(exist_ok=True)
        (root / "artefacts" / "index.json").write_text(json.dumps(
            {"files": ["planted.json"], "provenance": {"source": "plant", "run_id": "x"}}))
        (root / "artefacts" / "planted.json").write_text(json.dumps({"cos": 0.5}))
        results.append(("no_fabrication", "artefact without provenance", run("no_fabrication", root) != 0))
        # 1c a figure retyped inside a string
        (root / "artefacts" / "planted.json").write_text(json.dumps(
            {"note": "cos 0.7316 cleared", "provenance": {"source": "plant", "run_id": "x"}}))
        results.append(("no_fabrication", "figure inside a string", run("no_fabrication", root) != 0))
        # 2a five instrument words
        root = copy_site(tmp / "c")
        plant_page(root, "<main class=\"wrap\">", f"<main class=\"wrap\"><p>{instrument_run()}</p>")
        results.append(("no_instrument", "five-word instrument run", run("no_instrument", root) != 0))
        # 2b a variable key
        root = copy_site(tmp / "d")
        plant_page(root, "<main class=\"wrap\">", "<main class=\"wrap\"><p>" + "m1:" + "Q5.4" + "</p>")
        results.append(("no_instrument", "variable key", run("no_instrument", root) != 0))
        # 3 dead anchor and missing fetch target
        root = copy_site(tmp / "e")
        plant_page(root, "<main class=\"wrap\">", "<main class=\"wrap\"><a href=\"#nowhere\">x</a>")
        results.append(("links", "dead anchor", run("links", root) != 0))
        root = copy_site(tmp / "f")
        plant_page(root, "<script>", "<script>fetch(\"artefacts/missing.json\");")
        results.append(("links", "missing fetch target", run("links", root) != 0))
        # 4 unbalanced tag and a syntax error
        root = copy_site(tmp / "g")
        plant_page(root, "</main>", "</section></main>")
        results.append(("parse", "stray close tag", run("parse", root) != 0))
        root = copy_site(tmp / "h")
        plant_page(root, "<script>", "<script>const = ;")
        results.append(("parse", "script syntax error", run("parse", root) != 0))
        # 5 an external script, a font stylesheet, a fetch to a host
        root = copy_site(tmp / "i")
        plant_page(root, "<head>", "<head><script src=\"https://cdn.example.com/x.js\"></script>")
        results.append(("offline", "external script", run("offline", root) != 0))
        root = copy_site(tmp / "j")
        plant_page(root, "<style>", "<style>@import url(https://fonts.googleapis.com/css);")
        results.append(("offline", "font @import", run("offline", root) != 0))
        root = copy_site(tmp / "k")
        plant_page(root, "<script>", "<script>fetch(\"https://example.com/a\");")
        results.append(("offline", "fetch to a host", run("offline", root) != 0))
    # 6 an untracked artefact in the real tree
    art = SITE / "artefacts"
    art.mkdir(exist_ok=True)
    planted = art / "planted_untracked.json"
    idx = art / "index.json"
    had_index = idx.exists()
    saved = idx.read_text(encoding="utf-8") if had_index else None
    try:
        planted.write_text(json.dumps({"provenance": {"source": "plant", "run_id": "x"}}))
        files = (json.loads(saved).get("files", []) if saved else []) + ["planted_untracked.json"]
        idx.write_text(json.dumps({"files": files, "provenance": {"source": "plant", "run_id": "x"}}))
        results.append(("tracked", "untracked artefact", run("tracked", SITE) != 0))
    finally:
        planted.unlink(missing_ok=True)
        if had_index:
            idx.write_text(saved, encoding="utf-8")
        else:
            idx.unlink(missing_ok=True)
            if not any(art.iterdir()):
                art.rmdir()
    bad = 0
    for step, what, red in results:
        print(f"{'red ' if red else 'MISS'}  {step:16s} {what}")
        bad += not red
    print("every planted violation caught" if not bad else f"{bad} violation(s) NOT caught")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
