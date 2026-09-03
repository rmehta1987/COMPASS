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
RUFF_CEILING: int = 232
MYPY_CEILING: int = 59


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


def test_google_docstring_convention_is_configured() -> None:
    """The convention is config, not habit, so it survives a new contributor."""
    cfg: str = (ROOT / "pyproject.toml").read_text()
    assert 'convention = "google"' in cfg
    assert '"ANN"' in cfg, "annotation rules must stay enabled"
    assert '"D"' in cfg, "docstring rules must stay enabled"
