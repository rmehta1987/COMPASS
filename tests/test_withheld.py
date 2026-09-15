"""Pins for `tests/withheld.py` — the mechanism that decides what does not run.

Written 2026-09-14 after review found the guard module had no test at all,
which is the wrong shape for a thing that can silence 45 contamination tests.
`benchmark/contamination_check.py`'s skip semantics carry nine tests; its pytest
counterpart carried none, and the one artefact that would have supplied the
"this is not a pass" half was dead code.

The asymmetry that motivates the ceiling below: `AGENTS.md` §Verify current
state makes a FALLING test count a stop condition, and turning a failure into a
skip leaves the collected count untouched. So the stop condition is blind to
this class of change by construction, and a one-line module-level `pytestmark`
could silence a whole file without tripping anything. The guarded count is
therefore a ratchet in its own right, in the direction skips should travel.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark.contamination_check import WITHHELD_MODULES  # noqa: E402
from tests import withheld  # noqa: E402

#: Guarded tests may only become FEWER. Direction, not a target: every guard is
#: a contamination test that does not run in the clone where prompts and
#: conventions are edited, so the honest move is always to split a test until
#: its key-free half runs here. Read from this module, never from a document
#: (`AGENTS.md` §Testing Patterns). Was 45 when the guards landed; 42 after the
#: 11 over-guarded tests were split; 34 after C36 made both sides of a design
#: verdict read one substitutable reader, so eight scorability tests became
#: key-free rather than reaching the withheld prevalence key. Lowering it is
#: progress; raising it is a review failure.
GUARD_CEILING = 34


def _guard_decorations() -> dict[str, int]:
    """Count `@needs_*` decorations per test file, by parsing rather than grep.

    A `pytestmark` assignment silences a whole module with no decorator to
    count, so that is looked for separately and treated as a hard failure.

    Returns:
        Mapping of file name to number of guard DECORATIONS. A test needing
        both keys carries two, and counts twice: it is two pieces of coverage
        that do not run here.
    """
    out: dict[str, int] = {}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                n += sum(1 for d in node.decorator_list
                         if isinstance(d, ast.Name) and d.id.startswith("needs_"))
        if n:
            out[path.name] = n
    return out


def test_the_guards_name_only_modules_the_gate_holds_out() -> None:
    """A guard on a module nobody withholds is an unconditional skip.

    This is the check that used to live as a module-level `assert` inside
    `tests/withheld.py`. It moved here because an import-time failure there
    cost 98 collected tests across three collection errors naming the wrong
    file; here its red state costs one test and names what drifted.
    """
    drifted = set(withheld.GUARDED_MODULES) - WITHHELD_MODULES
    assert not drifted, (
        f"these guards name modules WITHHELD_MODULES does not hold out: "
        f"{sorted(drifted)}. A skipif on a module that is always present is a "
        f"skip with no condition.")


def test_every_withheld_module_has_a_guard() -> None:
    """The direction nothing checked, whose red state is a permanently red suite.

    `test_the_guards_name_only_modules_the_gate_holds_out` catches a guard with
    no holdout. Nothing caught the reverse: adding a module to
    `WITHHELD_MODULES` without adding a guard here leaves the tests that need
    it FAILING in every clone but the scoring one, which is the exact state
    this module was written to end. Found when `benchmark.design_key` joined
    the set for C36.

    Both directions are asserted, and both are kept as separate tests rather
    than one equality: the two red states are different defects and the message
    should say which.
    """
    unguarded = WITHHELD_MODULES - set(withheld.GUARDED_MODULES)
    assert not unguarded, (
        f"{sorted(unguarded)} are withheld but have no guard in "
        f"tests/withheld.py. Every test needing one is red here rather than "
        f"skipped, and a permanently red suite says nothing about the change "
        f"you just made.")


def test_only_a_withheld_module_can_excuse_a_failure() -> None:
    """`present` refuses to launder an ordinary broken import into a skip."""
    with pytest.raises(ValueError, match="not withheld"):
        withheld.present("numpy")
    for module in withheld.GUARDED_MODULES:
        assert isinstance(withheld.present(module), bool)


def test_a_skip_says_what_did_not_run_and_that_it_is_not_a_pass() -> None:
    """The reason is the only thing an operator sees, so it has to say both.

    `pytest -q` prints a count and no reasons, which is why `AGENTS.md`
    §Verify current state now passes `-ra`.
    """
    for mark in (withheld.needs_prevalence_key, withheld.needs_leak_facts,
                 withheld.needs_design_key):
        reason = mark.kwargs["reason"]
        assert "withheld from this clone" in reason
        assert "NOT a pass" in reason, (
            "a skip that does not say it is not a pass is how 'could not "
            "detect X' becomes 'X is absent'")


def test_no_module_silences_itself_wholesale() -> None:
    """A module-level `pytestmark` is a one-line, uncounted mass skip.

    The decorator ceiling cannot see one, so it is banned outright: if a whole
    file genuinely needs a key, that is worth stating test by test.
    """
    offenders = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "pytestmark"
                    for t in node.targets):
                offenders.append(path.name)
    assert not offenders, (
        f"{offenders} silence every test in the file from one line, which no "
        f"count in this file can see. Guard the tests individually.")


def test_the_number_of_guarded_tests_only_falls() -> None:
    """The ratchet. A rising guarded count is coverage leaving this clone."""
    per_file = _guard_decorations()
    total = sum(per_file.values())
    assert total <= GUARD_CEILING, (
        f"guarded tests rose {GUARD_CEILING} -> {total} ({per_file}). Each one "
        f"is a contamination test that does not run where prompts are edited. "
        f"Split the test so its key-free half runs here, rather than guarding "
        f"the whole of it.")
    if total < GUARD_CEILING:
        print(f"\nGUARD_CEILING can be lowered to {total}")


def test_the_ceiling_is_not_vacuous() -> None:
    """A ceiling over zero guards would pass forever and mean nothing."""
    per_file = _guard_decorations()
    assert per_file, (
        "no guarded tests found at all. Either the guards are gone -- in which "
        "case lower GUARD_CEILING to 0 and delete this -- or the AST walk "
        "stopped matching the decorator, and the ratchet is now blind.")


# --------------------------------------------------------------------------- #
# Reachability of a withheld module from a PUBLISHED ref
# --------------------------------------------------------------------------- #
#
# WHY THIS EXISTS. Deleting an answer key removes it from the tip and from no
# other commit. `benchmark/leak_facts.py` was added by the publication commit
# b3d818d (2026-09-03) and deleted by 37a37dd the next day; the adding commit is
# still an ancestor of `origin/main`, and the repository is public, so the blob
# is in the pack anyone gets by cloning. `WITHHELD_MODULES` says what must not
# be readable; nothing said it must not be FETCHABLE, and the two came apart
# without a red test. Found by review 2026-09-15.

#: Withheld modules already reachable from a published ref, as repo-relative
#: paths. A record of a known breach, not permission for another. Remediating one
#: means rewriting published history and force-pushing, and a rewrite does not
#: un-distribute what was already fetched -- the user's call, not a lane's
#: (`TASKS.md` §Known-open defects). DIRECTION: this set may only SHRINK.
KNOWN_PUBLIC_EXPOSURE = frozenset({"benchmark/leak_facts.py"})


def _git() -> Path | None:
    """Locate git on PATH.

    Resolved here rather than imported from `tests/test_code_standards.py`: a
    test module is not an API, and this file already owns what it needs.

    Returns:
        Path to the executable, or None when git is not installed.
    """
    from shutil import which
    found: str | None = which("git")
    return Path(found) if found else None


def _published_refs(git: Path) -> list[str]:
    """Remote-tracking refs: what a stranger could clone.

    Args:
        git: The git executable.

    Returns:
        Fully-qualified remote-tracking ref names, empty when there are none.
    """
    out = subprocess.run(
        [str(git), "for-each-ref", "--format=%(refname)", "refs/remotes/"],
        cwd=ROOT, capture_output=True, text=True).stdout
    return [r for r in out.split() if r]


def _exposed_withheld_paths(git: Path, refs: list[str]) -> set[str]:
    """Which withheld modules any published ref carries a commit for.

    Asks about the PATH's history rather than the tip, because a deletion leaves
    the adding commit reachable.

    Args:
        git: The git executable.
        refs: Remote-tracking refs to search.

    Returns:
        Repo-relative paths reachable from at least one published ref.
    """
    exposed: set[str] = set()
    for module in sorted(WITHHELD_MODULES):
        path = module.replace(".", "/") + ".py"
        for ref in refs:
            n = subprocess.run(
                [str(git), "rev-list", "--count", ref, "--", path],
                cwd=ROOT, capture_output=True, text=True).stdout.strip()
            if n.isdigit() and int(n) > 0:
                exposed.add(path)
                break
    return exposed


def test_no_new_withheld_module_is_reachable_from_a_published_ref() -> None:
    """A withheld module must not be fetchable by cloning, pin or no pin.

    Two-sided on purpose. An unpinned exposure is a new breach. A pinned path
    that is no longer reachable means the history was cleaned and the pin is
    now stale cover for nothing -- so the pin must come out, and this test says
    so rather than passing quietly.
    """
    git: Path | None = _git()
    if git is None:
        pytest.skip("git not installed, so reachability cannot be asked. "
                    "NOT a pass -- run it where git is.")
    refs = _published_refs(git)
    if not refs:
        pytest.skip("no remote-tracking refs in this clone, so nothing is "
                    "published from here and reachability is unanswerable. "
                    "NOT a pass -- run it in a clone that has a remote.")
    exposed = _exposed_withheld_paths(git, refs)

    new = exposed - KNOWN_PUBLIC_EXPOSURE
    assert not new, (
        f"withheld module(s) {sorted(new)} are reachable from a published ref "
        f"({', '.join(refs)}). Deleting the file does not help: the adding "
        f"commit is still an ancestor. Treat the key as disclosed and tell the "
        f"user -- a history rewrite and force-push is theirs to decide, not a "
        f"lane's.")

    healed = KNOWN_PUBLIC_EXPOSURE - exposed
    assert not healed, (
        f"{sorted(healed)} is pinned in KNOWN_PUBLIC_EXPOSURE but is no longer "
        f"reachable from any published ref. If the history was rewritten, "
        f"remove it from the pin: the set may only shrink, and leaving it here "
        f"hides the next real exposure behind an allowance.")
