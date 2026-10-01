"""Prove each check goes red on a planted violation.

A scan that has never fired is not known to work. The site is copied to a
scratch directory, one violation is planted, and the check runs against the
copy; it must exit non-zero. Steps 1–6 take the copy through ``SITE_ROOT``;
steps 7 and 8 are node and take it as an argument. The instrument run planted
for step 2 is taken from the dictionary at run time and written only to the
scratch copy.

NOTHING HERE TOUCHES THE REAL TREE. Step 6 is about a fact that only a git
repository has -- whether a file is tracked -- and it used to get that by
doctoring the real ``site/artifacts/index.json`` and restoring it afterwards.
That made the harness unsafe to run twice at once: two overlapping runs each
restore the other's stale copy, over uncommitted work. It now commits the copy
into a throwaway repository instead, which `common.REPO` follows because it is
derived from ``SITE_ROOT``.

    python3 site/tools/plant.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent
REPO = SITE.parent


def run(step: str, root: Path, **extra: str) -> int:
    env = dict(os.environ, SITE_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1", **extra)
    r = subprocess.run([sys.executable, str(HERE / f"{step}.py")], env=env,
                       capture_output=True, text=True)
    return r.returncode


def run_node(step: str, root: Path) -> int:
    """Run a node harness against a planted copy.

    Steps 7 and 8 are node, take the site directory as an argument rather than
    through ``SITE_ROOT``, and stub the route they drive, so they need no
    server.

    Args:
        step: Harness basename under ``site/tools`` without its suffix.
        root: The planted site directory to run against.

    Returns:
        The harness's exit status; non-zero means it caught the violation.
    """
    r = subprocess.run(["node", str(HERE / f"{step}.js"), str(root)],
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
    sys.path.insert(0, str(HERE))
    from no_instrument import dictionary_path
    dic = dictionary_path()
    if dic is None:
        raise SystemExit("dictionary not found; set COMPASS_DICTIONARY")
    for e in json.loads(dic.read_text(encoding="utf-8"))["entries"]:
        w = " ".join(str(e.get("question_text", "")).split()).split()
        if len(w) >= 8:
            return " ".join(w[:5])
    raise SystemExit("no dictionary entry long enough to plant")


#: One page plant: the check that must go red, its label, the text replaced on
#: the page (first occurrence), what replaces it, and how the check is run.
PagePlant = tuple[str, str, str, str, Callable[[str, Path], int]]

_MAIN = '<main class="wrap">'
_VERDICTS = '<p class="sec">verdicts on this scoring run</p>'


def page_plants(instrument: str) -> list[PagePlant]:
    """Every plant that edits the page, one row each, in report order.

    Args:
        instrument: Five instrument words, from `instrument_run`, for step 2a.

    Returns:
        The rows; `main` copies the site, plants one row and runs its check.
    """
    return [
        # 1a a literal on the page
        ("no_fabrication", "numeric literal on the page",
         _MAIN, _MAIN + "<p>cos 0.8214</p>", run),
        # 2a five instrument words
        ("no_instrument", "five-word instrument run",
         _MAIN, f"{_MAIN}<p>{instrument}</p>", run),
        # 2b a variable key
        ("no_instrument", "variable key",
         _MAIN, _MAIN + "<p>" + "m1:" + "Q5.4" + "</p>", run),
        # 3 dead anchor and missing fetch target
        ("links", "dead anchor", _MAIN, _MAIN + '<a href="#nowhere">x</a>', run),
        ("links", "missing fetch target",
         "<script>", '<script>fetch("artifacts/missing.json");', run),
        # 4 unbalanced tag and a syntax error
        ("parse", "stray close tag", "</main>", "</section></main>", run),
        ("parse", "script syntax error", "<script>", "<script>const = ;", run),
        ("parse", "renamed artifact field renders undefined",
         "r.top_cos", "r.top_cosine_renamed", run),
        # 4b the five 2026-09-09 review fixes, each re-seeded: render.js must
        # catch the defect coming back, not only the page as it stands.
        ("parse", "unmatched query hides Metrics",
         'if(typed!==null&&!cur&&sel==="intake") return noRun();',
         "if(typed!==null&&!cur) return noRun();", run),
        # The rule inverted on the operator's instruction (2026-09-25): a
        # committed panel's footer is now empty, so the planted violation is
        # the removed provenance line put back.
        ("parse", "removed provenance line back on a committed panel",
         'a second run may differ.`:"";',
         'a second run may differ.`:"Every figure above loads from '
         '<code>site/artifacts/</code> with its run id or commit.";', run),
        ("parse", "pipeline button live with no server",
         'el("#ask").disabled=!window.COMPASS_ENDPOINT;',
         'el("#ask").disabled=false;', run),
        ("parse", "Enter in the search box does nothing",
         'if(e.key==="Enter")', 'if(e.key==="Escape")', run),
        # Was planted in `placeholder()`. After `record` and `specifier` merged
        # away, no stage renders a placeholder in the STATIC drive -- every
        # remaining stop has an artifact or a committed example -- so the plant
        # landed on a string `render.js` never rendered and the step silently
        # stopped proving anything. Moved onto the retriever panel's own
        # withholding note, which is rendered for all five examples.
        ("parse", "jargon reaches the reader",
         "withheld on this page", "withheld on this endpoint", run),
        # 5 an external script, a font stylesheet, a fetch to a host
        ("offline", "external script",
         "<head>", '<head><script src="https://cdn.example.com/x.js"></script>', run),
        ("offline", "font @import",
         "<style>", "<style>@import url(https://fonts.googleapis.com/css);", run),
        ("offline", "fetch to a host",
         "<script>", '<script>fetch("https://example.com/a");', run),
        # 7 the live branch. Each of these shipped at some point: the attribute
        # break was live until a planted quote found it, and the pipeline's own
        # output was published as a per-record table and then, after that went,
        # as the counts and caveats left behind. Both read as evidence, so both
        # are pinned out; the ceiling is pinned IN, because that is the result.
        ("render_endpoint", "a key with a quote breaks out of its attribute",
         'data-genex="${att(pr.exposure)}"', 'data-genex="${esc(pr.exposure)}"',
         run_node),
        ("render_endpoint", "the run's own counts are reported again",
         _VERDICTS, '<p class="sec">observed</p><dl><dt>x</dt><dd>y</dd></dl>'
         + _VERDICTS, run_node),
        ("render_endpoint", "the per-record listing is published again",
         _VERDICTS, "<table><thead><tr><th>record</th></tr></thead><tbody><tr>"
         "<td>x</td></tr></tbody></table>" + _VERDICTS, run_node),
        # Rename it OUT of the asserted phrase. An earlier plant appended a
        # character, which left the phrase intact as a substring and passed.
        ("render_endpoint", "the ceiling stops being stated",
         'row("records that could have matched"',
         'row("records that could have been matched"', run_node),
        # 8 a stage change decided after an await must be forfeited if the
        # reader has moved; `steer` is the whole guarantee, in one line.
        ("render_race", "a finished run drags the reader off the stage they picked",
         "function steer(nav,stage){ if(nav===navGen) sel=stage; }",
         "function steer(nav,stage){ sel=stage; }", run_node),
        # 9 the comparison against a paper. A MATCH discloses the paper's key,
        # so the one thing the page must never do with it is put it in the file
        # the download button writes.
        ("render_compare", "the JSON download carries the comparison",
         "  if(gen) doc.enumeration=gen;\n",
         "  if(gen) doc.enumeration=gen;\n  if(cmp) doc.compare=cmp;\n", run_node),
    ]


def main() -> int:
    results: list[tuple[str, str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="site-plant-") as t:
        tmp = Path(t)
        # CONTROL FIRST. Every step below reads a non-zero exit as "violation
        # caught", so a check that cannot run at all reports as a check that
        # works. MEASURED 2026-09-16: `common.REPO` was briefly derived from
        # `SITE`, so `no_instrument` against a scratch copy could not find the
        # withheld dictionary and exited 2; both instrument plants went green
        # while the scan they certify was disabled. An unplanted copy must be
        # clean, and the harness stops if it is not.
        clean = copy_site(tmp / "control")
        for step in ("no_fabrication", "no_instrument", "links", "parse", "offline"):
            code = run(step, clean)
            if code != 0:
                raise SystemExit(
                    f"plant: {step} exits {code} on an UNPLANTED copy, so every red "
                    f"below could be this rather than the planted violation. Run "
                    f"`SITE_ROOT={clean} python site/tools/{step}.py` and fix the "
                    "harness, not the check.")
        # 1b an artifact without provenance. This plant and 1c write files
        # rather than edit the page, so they are not rows of the table below.
        root = copy_site(tmp / "b")
        (root / "artifacts").mkdir(exist_ok=True)
        prov = {"source": "plant", "run_id": "x"}
        (root / "artifacts" / "index.json").write_text(json.dumps(
            {"files": ["planted.json"], "provenance": prov}))
        (root / "artifacts" / "planted.json").write_text(json.dumps({"cos": 0.5}))
        results.append(("no_fabrication", "artifact without provenance",
                        run("no_fabrication", root) != 0))
        # 1c a figure retyped inside a string
        (root / "artifacts" / "planted.json").write_text(json.dumps(
            {"note": "cos 0.7316 cleared", "provenance": prov}))
        results.append(("no_fabrication", "figure inside a string",
                        run("no_fabrication", root) != 0))
        for i, (check, label, anchor, payload, runner) in enumerate(
                page_plants(instrument_run())):
            root = copy_site(tmp / f"p{i}")
            plant_page(root, anchor, payload)
            results.append((check, label, runner(check, root) != 0))
    # 6 an untracked artifact. THIS USED TO DOCTOR THE REAL TREE: it wrote a
    # planted artifact into `site/artifacts/`, overwrote the real `index.json`,
    # and restored both in a `finally`. Whether a file is tracked is a fact
    # about a git repository, so a copy alone was not enough -- but it does not
    # have to be THIS repository. Five review sessions ran in one checkout on
    # 2026-09-16 and none of them was allowed to run this harness, because two
    # overlapping runs would each restore the other's stale `index.json` over
    # uncommitted work. A throwaway repo removes the hazard and the check is
    # unchanged: `common.REPO` follows `SITE_ROOT`, so `tracked` asks git about
    # the tree it was pointed at.
    with tempfile.TemporaryDirectory(prefix="site-plant-repo-") as t:
        repo = Path(t)
        git = ["git", "-C", str(repo)]
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                       capture_output=True)
        dst = repo / "site"
        shutil.copytree(SITE, dst, ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        subprocess.run([*git, "-c", "user.email=plant@invalid",
                        "-c", "user.name=plant", "commit", "-qm", "seed"],
                       check=True, capture_output=True)
        # Green on the copy first: without this the red below could come from
        # the repository being wrong rather than from the planted file.
        control = run("tracked", dst)
        idx = dst / "artifacts" / "index.json"
        doc = json.loads(idx.read_text(encoding="utf-8"))
        (dst / "artifacts" / "planted_untracked.json").write_text(json.dumps(
            {"provenance": {"source": "plant", "run_id": "x"}}))
        doc["files"] = list(doc.get("files", [])) + ["planted_untracked.json"]
        idx.write_text(json.dumps(doc))
        if control != 0:
            raise SystemExit(
                "plant: the freshly committed copy is not clean before anything is "
                "planted, so a red result below would say nothing about the planted "
                "file. Fix the harness, not the check.")
        results.append(("tracked", "untracked artifact", run("tracked", dst) != 0))
    bad = 0
    for step, what, red in results:
        print(f"{'red ' if red else 'MISS'}  {step:16s} {what}")
        bad += not red
    print("every planted violation caught" if not bad else f"{bad} violation(s) NOT caught")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
