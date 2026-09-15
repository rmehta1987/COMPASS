"""Mechanical enforcement of the project's coding standards.

The standards are Google-style docstrings, full type annotations, and ruff's
default correctness rules. The codebase predates them, so these are RATCHETS, not
absolutes: the counts may only go down. A ratchet is enforceable from day one,
where a clean-slate rule would either be ignored or force a repo-wide rewrite
before any real work got done.

Lower these numbers whenever you clean something up. Raising one is a review
failure, not a config change.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT: Path = Path(__file__).resolve().parent.parent

# Resolve the checkers next to the running interpreter, not under ROOT. A git
# worktree has no .venv of its own — lanes run against the main venv by absolute
# path — so ROOT/".venv"/"bin"/"ruff" does not exist there and these tests died
# with a bare "File not found". Found the first time a worktree was created.
BIN: Path = Path(sys.executable).parent


def _tool(name: str) -> Path | None:
    """Locate a checker beside the interpreter, or on PATH.

    Args:
        name: Executable name, e.g. "ruff".

    Returns:
        Path to the executable, or None when it is not installed.
    """
    local: Path = BIN / name
    if local.exists():
        return local
    from shutil import which
    found: str | None = which(name)
    return Path(found) if found else None

# Baseline recorded 2026-08-26 after `ruff check --fix`. Lowered twice on
# 2026-08-27 by two lanes working in parallel, for disjoint reasons that
# compound: Lane B annotated and documented env/tools.py's ToolCall/ToolLog/
# _logged block; Lane C added docstrings to generate/funnel.py and fixed
# load_constructs' return annotation, which claimed `dict[str, Construct]`
# while returning a 2-tuple and so hid 9 mypy errors as `Any` at call sites in
# four files. Both branches edited this constant and collided at merge; the
# resolution is the MEASURED post-merge count, not the lower of the two
# guesses. A ratchet nobody lowers is a ceiling.
#
# LOWERED 2026-08-31 after five merges in one session, on the count measured
# on the merged tree rather than in any lane: ruff 236 -> 232 (C23 generated
# agent/registry.py from pydantic argument models and the old hand-written
# SCHEMAS carried three errors), mypy 62 -> 59 (the C24 dedup fix narrowed
# a.protocol to a local and cleared two pre-existing union-attr errors).
# Three lanes moved these two numbers; none of their individual counts was
# the right one, which is why this is re-measured at merge and not relayed.
#
# LOWERED 2026-09-11, mypy 59 -> 54, operator-approved: `specify()` was typed to
# take a chat `Backend` that `ClaudeCliBackend` is not, which cost three
# attr-defined errors in agent/specifier.py and one arg-type in each driver.
# `agent/backends.py::CliBackend` and `specifier::_drives_own_loop` type the two
# paths apart. (27b6949 had raised the count 59 -> 62; bee2890 restored it.)
RUFF_CEILING: int = 232
MYPY_CEILING: int = 54


def _count(argv: list[str]) -> int:
    """Run a checker and return the number of errors it reports.

    Args:
        argv: Command line to execute, relative to the project root.

    Returns:
        The integer parsed from the tool's "Found N error(s)" summary, or 0 when
        the tool reports no such line.
    """
    out: str = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Found ") and "error" in line:
            return int(line.split()[1])
    return 0


def test_ruff_count_does_not_increase() -> None:
    ruff: Path | None = _tool("ruff")
    if ruff is None:
        pytest.skip("ruff not installed: pip install ruff mypy")
    n: int = _count([str(ruff), "check", "."])
    assert n <= RUFF_CEILING, (
        f"ruff errors rose {RUFF_CEILING} -> {n}. New code must be clean: "
        f"Google docstrings, typed parameters and returns. Run "
        f"`.venv/bin/ruff check . --fix` and fix what remains.")
    if n < RUFF_CEILING:
        print(f"\nRUFF_CEILING can be lowered to {n}")


def test_mypy_count_does_not_increase() -> None:
    mypy: Path | None = _tool("mypy")
    if mypy is None:
        pytest.skip("mypy not installed: pip install ruff mypy")
    n: int = _count([str(mypy)])
    assert n <= MYPY_CEILING, (
        f"mypy errors rose {MYPY_CEILING} -> {n}. Annotate every parameter and "
        f"return on code you add or materially edit.")
    if n < MYPY_CEILING:
        print(f"\nMYPY_CEILING can be lowered to {n}")


def test_serve_type_checks_clean() -> None:
    """`serve/` is outside mypy's `files`, so the ceiling above never sees it.

    The first import of `serve.api` from inside `files` -- the resolver
    benchmark's deployed pool arm -- would have pulled ten old errors into that
    count. They were fixed first, and this keeps `serve/` clean whether or not
    anything in `files` imports it.
    """
    mypy: Path | None = _tool("mypy")
    if mypy is None:
        pytest.skip("mypy not installed: pip install ruff mypy")
    out: str = subprocess.run(
        [str(mypy), "serve"], cwd=ROOT, capture_output=True, text=True).stdout
    errors = [ln for ln in out.splitlines()
              if ln.startswith("serve/") and ": error:" in ln]
    assert not errors, "serve/ has type errors:\n" + "\n".join(errors)


def test_google_docstring_convention_is_configured() -> None:
    """The convention is config, not habit, so it survives a new contributor."""
    cfg: str = (ROOT / "pyproject.toml").read_text()
    assert 'convention = "google"' in cfg
    assert '"ANN"' in cfg, "annotation rules must stay enabled"
    assert '"D"' in cfg, "docstring rules must stay enabled"


def test_withheld_artifacts_are_ignored_as_symlinks_too() -> None:
    """A linked artifact must be as unstageable as a real one.

    `.gitignore` spelled these `build/`, `raw/`, `run/`, `fixtures/`. A
    trailing slash matches a directory and never a symlink to one, and on the
    training machine these are routinely links into a sibling clone -- so
    `git add -A` would stage a link pointing straight at the withheld
    instrument. Asks git itself rather than parsing the file, so the guarantee
    holds however the pattern is later rewritten.
    """
    git: Path | None = _tool("git")
    if git is None:  # pragma: no cover - git is present wherever this runs
        pytest.skip("git not installed")
    names = ["build", "raw", "run", "runs", "parked",
             "fixtures", "benchmark/fixtures"]
    out: str = subprocess.run(
        [str(git), "check-ignore", "--no-index", *names],
        cwd=ROOT, capture_output=True, text=True).stdout
    ignored = set(out.split())
    missing = [n for n in names if n not in ignored]
    assert not missing, (
        f"not ignored without a trailing slash: {missing}. A symlinked "
        "artifact would be stageable and would point at the instrument.")


def test_every_withheld_key_module_is_unstageable() -> None:
    """An answer key must not be committable by accident, in any clone.

    The instrument was ignored in every form and the ANSWER KEYS were not.
    `.gitignore` named none of the three, so in the scoring clone -- the only
    one where they exist -- `git add -A` reached them and nothing stopped it.
    Measured 2026-09-15: `benchmark/prevalence_key.py` has zero commits in the
    whole history, which is the discipline working by hand, and
    `benchmark/leak_facts.py` has two, which is it failing
    (`TASKS.md` §Known-open defects).

    Asks git rather than parsing `.gitignore`, like the test above, so the
    guarantee survives a rewrite of the pattern. Reads the module list from
    `WITHHELD_MODULES` rather than repeating it, so a FOURTH withheld module
    reddens this instead of arriving unignored -- the list has one owner
    (`AGENTS.md` §Testing Patterns).

    What this does NOT claim: an ignore rule is not history. `leak_facts.py`
    stays reachable from the published `origin/main` and
    `tests/test_withheld.py::test_no_new_withheld_module_is_reachable_from_a_published_ref`
    is what watches that. Nor does it stop `git add -f`.
    """
    git: Path | None = _tool("git")
    if git is None:  # pragma: no cover - git is present wherever this runs
        pytest.skip("git not installed")

    sys.path.insert(0, str(ROOT))
    from benchmark.contamination_check import WITHHELD_MODULES

    paths = sorted(m.replace(".", "/") + ".py" for m in WITHHELD_MODULES)
    # Anti-vacuity: an empty registry would satisfy the assertion below.
    assert len(paths) >= 3, f"only {len(paths)} withheld module(s) registered"

    out: str = subprocess.run(
        [str(git), "check-ignore", "--no-index", *paths],
        cwd=ROOT, capture_output=True, text=True).stdout
    ignored = set(out.split())
    missing = [p for p in paths if p not in ignored]
    assert not missing, (
        f"withheld answer-key module(s) {missing} are not ignored, so "
        f"`git add -A` in the scoring clone would stage a published paper's "
        f"answers. Add each to .gitignore. This is how "
        f"benchmark/leak_facts.py reached a public ref.")

    # Anti-vacuity the other way: the rule must be specific, not a blanket that
    # would also hide the code these modules are read BY.
    live: str = subprocess.run(
        [str(git), "check-ignore", "--no-index",
         "benchmark/scorability.py", "benchmark/design_anchor.py",
         "benchmark/contamination_check.py"],
        cwd=ROOT, capture_output=True, text=True).stdout
    assert not live.split(), (
        f"the ignore rule also hides tracked source: {live.split()}")
