"""A withheld module makes a section SKIP loudly; it never makes it pass.

`benchmark/prevalence_key.py` and `benchmark/leak_facts.py` are held out of every
clone but the scoring one. Until 2026-09-10 they were imported at module scope,
so `python -m benchmark.contamination_check` -- the MANDATORY gate after any
prompt, convention or `env/tools.py` edit -- died with ModuleNotFoundError in
exactly the clones where that code is written. The gate could not run where it
was needed.

Deferring the imports fixes that, and creates a worse hazard it must not have: a
partial run reading as a clean one. `AGENTS.md` §Verification Discipline --
"could not detect X" is never "X is absent" -- so these pin the two halves of the
guarantee: a withheld module SKIPS and the exit status stays non-zero, and any
OTHER missing module still takes the run down rather than being laundered into a
skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark import contamination_check as cc  # noqa: E402


def test_the_withheld_set_names_only_the_held_out_modules() -> None:
    """The catch is named, not broad: a real missing dependency is not a skip."""
    assert cc.WITHHELD_MODULES == frozenset(
        {"benchmark.prevalence_key", "benchmark.leak_facts",
         "benchmark.design_key"}), (
        "WITHHELD_MODULES decides what may be downgraded to a skip. Widening it "
        "turns a genuine broken import into a section that silently did not run.")


def test_a_skipped_section_never_reports_as_clean(monkeypatch, capsys) -> None:
    """A section that could not run must not count toward a clean verdict."""
    def explode() -> list[str]:
        raise ModuleNotFoundError("No module named 'benchmark.prevalence_key'",
                                  name="benchmark.prevalence_key")

    # Every OTHER section is forced clean, so the skip is the only thing that
    # can make the exit status non-zero. Without this the test passes on
    # whatever unrelated section happens to be failing in this clone: seeded
    # 2026-09-10 by making a skip count as clean, and the test stayed GREEN
    # because a marker section was failing for its own reasons.
    monkeypatch.setattr(cc, "check_provenance", explode)
    for name in ("check_tool_coverage", "check_markers",
                 "check_markers_are_not_instrument_content",
                 "check_no_prevalence_figure_in_surface",
                 "check_input_does_not_contain_the_answer",
                 "check_no_platform_name_in_surface", "check_seal_config",
                 "check_holdout_not_reachable"):
        monkeypatch.setattr(cc, name, lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["contamination_check"])
    rc = cc.main()
    out = capsys.readouterr().out
    assert "SKIP" in out, "a section that did not run must say so"
    assert "NOT a pass" in out, "the skip must say what it is not"
    assert "0 problem" not in out
    assert rc != 0, (
        "every section that ran was clean and one was SKIPPED, and main() "
        "still exited 0. Any gate reading the exit status would treat an unrun "
        "contamination section as a clean one.")


def test_every_surface_section_scans_the_surface_whose_hash_is_printed(
        monkeypatch, capsys) -> None:
    """A verdict is over the surface `surface_hash` names, or it names nothing.

    The sections are deferred lambdas, so each one captures the surface rather
    than being handed it. A lambda that scanned a different or rebuilt surface
    would print one hash and report on text that hash does not identify.
    """
    surface = {"planted": "text only this test built"}
    seen: dict[str, object] = {}

    def recorder(name: str):  # noqa: ANN202 -- a monkeypatch shim
        def check(s: object) -> list[str]:
            seen[name] = s
            return []
        return check

    scanners = ("check_markers", "check_no_prevalence_figure_in_surface",
                "check_no_platform_name_in_surface")
    monkeypatch.setattr(cc, "model_visible_surface", lambda: surface)
    for name in scanners:
        monkeypatch.setattr(cc, name, recorder(name))
    for name in ("check_tool_coverage", "check_markers_are_not_instrument_content",
                 "check_input_does_not_contain_the_answer", "check_provenance",
                 "check_seal_config", "check_holdout_not_reachable"):
        monkeypatch.setattr(cc, name, lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["contamination_check"])
    cc.main()
    capsys.readouterr()
    assert set(seen) == set(scanners), f"sections never ran: {set(scanners) - set(seen)}"
    for name, s in seen.items():
        assert s is surface, f"{name} scanned a surface other than the hashed one"


def test_a_genuinely_missing_module_still_stops_the_run(monkeypatch) -> None:
    """Only the withheld modules are skippable; everything else still raises."""
    def explode() -> list[str]:
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(cc, "check_provenance", explode)
    monkeypatch.setattr(sys, "argv", ["contamination_check"])
    with pytest.raises(ModuleNotFoundError, match="numpy"):
        cc.main()


def test_the_split_prompt_is_in_the_scanned_surface() -> None:
    """C29-C: the splitter's prompt and schema reach a model, so the scan reads them."""
    surface = cc.model_visible_surface()
    assert {"split_prompt", "split_schema"} <= set(surface)
    assert "Use only the question's own words" in surface["split_prompt"]


_SECTIONS = ("check_tool_coverage", "check_markers",
             "check_markers_are_not_instrument_content",
             "check_no_prevalence_figure_in_surface",
             "check_input_does_not_contain_the_answer",
             "check_no_platform_name_in_surface", "check_provenance",
             "check_seal_config", "check_holdout_not_reachable")


def _live_run_without_the_scorer(monkeypatch: pytest.MonkeyPatch,
                                 missing: str) -> None:
    """Every section clean, the probes answering, the scorer import failing."""
    from agent import sealed

    def no_scorer(self: sealed.SealedWorktree, model: str = "") -> dict:
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

    monkeypatch.setattr(sealed.SealedWorktree, "verify", no_scorer)
    monkeypatch.setattr(sealed.SealedWorktree, "run",
                        lambda self, argv, timeout=900.0: {"result": "NO, planted"})
    for name in _SECTIONS:
        monkeypatch.setattr(cc, name, lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["contamination_check", "--live"])


def test_a_withheld_scorer_skips_the_live_probes_but_shows_the_answers(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """`--live` crashed in every clone without the scorer, answers and all."""
    from agent.sealed import PROBES

    _live_run_without_the_scorer(monkeypatch, "benchmark.leak_facts")
    rc = cc.main()
    out = capsys.readouterr().out
    assert "SKIP  live seal probes" in out and "NOT a pass" in out
    assert out.count("NO, planted") == len(PROBES), "every answer is shown, unscored"
    assert rc != 0, "an unscored seal probe is not a clean one"


def test_a_genuinely_missing_module_still_stops_the_live_probes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the withheld scorer turns the live probes into a skip."""
    _live_run_without_the_scorer(monkeypatch, "numpy")
    with pytest.raises(ModuleNotFoundError, match="numpy"):
        cc.main()


# --- The three-way exit status -------------------------------------------
#
# A skip and a failure were one exit status until 2026-09-14, and in the clone
# where prompts and conventions are EDITED a skip is unavoidable: the withheld
# modules are never there. So the gate was permanently red and the red carried
# no information -- "I just broke something" was indistinguishable from "the
# answer key does not live here". These pin the distinction, and pin that it
# did not become a way to read an unrun section as a pass.


def _all_sections_clean(monkeypatch: pytest.MonkeyPatch,
                        ran: list[str] | None = None) -> None:
    """Force every section clean, so only the planted condition moves the status.

    Args:
        monkeypatch: The fixture.
        ran: If given, each stub appends its own name, so a caller can put a
            floor under "every section ran".
    """
    def stub(name: str):  # noqa: ANN202 -- a monkeypatch shim
        def check(*a: object, **k: object) -> list[str]:
            if ran is not None:
                ran.append(name)
            return []
        return check

    for name in _SECTIONS:
        monkeypatch.setattr(cc, name, stub(name))
    monkeypatch.setattr(sys, "argv", ["contamination_check"])


def _skip_one_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `check_provenance` raise for a withheld module, as a real clone does."""
    def explode() -> list[str]:
        raise ModuleNotFoundError("No module named 'benchmark.prevalence_key'",
                                  name="benchmark.prevalence_key")

    monkeypatch.setattr(cc, "check_provenance", explode)


def test_a_complete_clean_run_exits_zero(monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    """The only status that is a pass, and it requires every section to have run.

    With a floor, because every section is stubbed: without it this passes if
    `main()` iterated NO sections at all (`AGENTS.md` §Testing Patterns, a floor
    per partition).
    """
    ran: list[str] = []
    _all_sections_clean(monkeypatch, ran)
    rc = cc.main()
    capsys.readouterr()
    assert rc == 0
    assert len(ran) == len(_SECTIONS), (
        f"only {len(ran)} of {len(_SECTIONS)} sections ran, so a status of 0 "
        f"says less than it appears to: {sorted(set(_SECTIONS) - set(ran))}")


def test_a_skip_alone_exits_two_and_not_one(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Incomplete has its own status, so a clone without the key can read it."""
    _all_sections_clean(monkeypatch)
    _skip_one_section(monkeypatch)
    rc = cc.main()
    out = capsys.readouterr().out
    # Against the LITERAL, not against the constant. Asserting `rc ==
    # cc.EXIT_INCOMPLETE` is self-referential: review found that setting
    # `EXIT_INCOMPLETE = 1` left every test in this block green, silently
    # reverting the whole split to the two-way semantics it replaced. An
    # unenforced guarantee is this codebase's recurring defect.
    assert cc.EXIT_INCOMPLETE == 2, (
        "the incomplete status is part of this command's interface; moving it "
        "is a change callers must see, not an implementation detail.")
    assert rc == 2, (
        "every section that ran was clean and one SKIPPED. That is neither a "
        "pass nor a failure, and collapsing it onto 1 is what made this gate "
        "unreadable in the clone where the edits happen.")
    assert rc != 1, "incomplete must be distinguishable from broken"
    assert rc != 0, "a skipped section is still not a clean one"
    assert "A skipped section is not a clean one." in out, (
        "the banner is the load-bearing part of the old conflation and stays "
        "verbatim; the exit status is what changed.")


def test_a_failure_outranks_a_skip(monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    """A planted marker reads as FAILED even in a clone that also skips.

    This is the direction that matters. `2` means "nothing I can see is wrong,
    and I could not see everything"; if a real problem could be laundered into
    it by an unrelated withheld module, the new status would be worse than the
    conflation it replaced.
    """
    _all_sections_clean(monkeypatch)
    _skip_one_section(monkeypatch)
    monkeypatch.setattr(cc, "check_markers",
                        lambda *a, **k: ["planted: PM2.5 reached the model"])
    rc = cc.main()
    out = capsys.readouterr().out
    assert "planted" in out
    assert rc == 1, (
        "a section FAILED and a section skipped, and the run reported "
        "incomplete instead of broken.")


def test_require_complete_collapses_a_skip_back_onto_one(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """What a benchmark run passes: only a complete clean run is acceptable."""
    _all_sections_clean(monkeypatch)
    _skip_one_section(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["contamination_check", "--require-complete"])
    rc = cc.main()
    capsys.readouterr()
    assert rc == 1, (
        "--require-complete exists so a benchmark gate can demand that every "
        "section RAN. It must not distinguish incomplete from broken.")


def test_require_complete_does_not_turn_a_clean_run_red(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The flag tightens what counts as a pass; it does not invent a failure."""
    _all_sections_clean(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["contamination_check", "--require-complete"])
    rc = cc.main()
    capsys.readouterr()
    assert rc == 0


def test_a_live_run_demands_that_every_section_ran(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """`--live` is the pre-benchmark gate, so it may not accept incomplete.

    Review found the hole this closes: a `--live` run in a clone without the
    answer keys returned `EXIT_INCOMPLETE` with the two answer-key scans unrun
    AND no seal probe scored -- the probes were printed for a human to read,
    never verdicted, and `failed` stayed 0 because `r["probes"]` was empty. A
    caller reading "only 1 is a failure" would have green-lit that run.
    """
    _live_run_without_the_scorer(monkeypatch, "benchmark.leak_facts")
    rc = cc.main()
    out = capsys.readouterr().out
    assert "SKIP  live seal probes" in out
    assert rc == 1, (
        "a --live run skipped the seal scoring and reported merely incomplete. "
        "--live must imply --require-complete.")


def test_the_run_says_which_gate_it_applied(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Stdout must distinguish the strict gate from the permissive one.

    `AGENTS.md` §Verification Discipline takes "command + real output" as the
    evidence that a gate ran. Before this, a skipping run printed byte-identical
    output whether it returned 1 or 2, so a pasted transcript could not show
    which gate had been satisfied.
    """
    _all_sections_clean(monkeypatch)
    _skip_one_section(monkeypatch)
    cc.main()
    permissive = capsys.readouterr().out

    _all_sections_clean(monkeypatch)
    _skip_one_section(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["contamination_check", "--require-complete"])
    cc.main()
    strict = capsys.readouterr().out

    assert permissive != strict, (
        "the two gates produce identical output, so the exit status is the "
        "only place the difference exists and a transcript cannot show it.")
    assert "permissive" in permissive and "strict" in strict


# THE REAL SKIP PATH. Every test above plants its skip on `check_provenance`,
# which imports nothing, so none of them ever ran a section that reads a key.
# MEASURED 2026-09-24: wrapping `check_no_platform_name_in_surface`'s import in
# `try/except ModuleNotFoundError: return []` left this file,
# `test_contamination_surface.py` and `test_withheld.py` green, and the gate
# printed `ok    survey platform named in surface` -- a section that scanned
# nothing reported clean. These run the real sections with the keys withheld.

#: Every function under the gate that imports a withheld key, and the section
#: `main` prints for it. Checked both ways against the source by
#: `test_every_key_reader_under_the_gate_is_listed`, so a new reader cannot
#: escape the tests below by not being named here.
_KEY_READERS = {
    ("contamination_check", "check_no_platform_name_in_surface"):
        "survey platform named in surface",
    ("contamination_check", "check_no_prevalence_figure_in_surface"):
        "published prevalence figures in surface",
    # Reached through `scan_frame`, which reads it before its loop.
    ("input_leakage", "_prevalence_tokens"):
        "input does not contain the answer",
}

#: The function `main` calls for each keyed section, and whether it takes the
#: surface.
_KEYED_SECTIONS = {
    "survey platform named in surface":
        ("check_no_platform_name_in_surface", True),
    "published prevalence figures in surface":
        ("check_no_prevalence_figure_in_surface", True),
    "input does not contain the answer":
        ("check_input_does_not_contain_the_answer", False),
}

_EMPTY_SURFACE = {"planted": "a surface with nothing in it to find"}


def _withhold_every_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make each withheld module unimportable, as it is in every clone but one.

    A `None` in `sys.modules` makes the import raise `ModuleNotFoundError` with
    `name` set, so this holds in the scoring clone too, where the files exist.
    The package attribute goes as well, or `from benchmark import X` would find
    an already-imported module there.

    Args:
        monkeypatch: The fixture.
    """
    import benchmark
    for module in cc.WITHHELD_MODULES:
        monkeypatch.setitem(sys.modules, module, None)
        monkeypatch.delattr(benchmark, module.rpartition(".")[2], raising=False)


@pytest.mark.parametrize("name", sorted(_KEYED_SECTIONS))
def test_a_keyed_section_raises_when_its_key_is_withheld(
        monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Without its key a section has nothing to scan for, so it may not return."""
    function, takes_surface = _KEYED_SECTIONS[name]
    section = getattr(cc, function)
    _withhold_every_key(monkeypatch)
    with pytest.raises(ModuleNotFoundError) as exc:
        section(_EMPTY_SURFACE) if takes_surface else section()
    assert exc.value.name in cc.WITHHELD_MODULES, (
        f"{name!r} raised for {exc.value.name!r}, which is not a withheld key, so "
        f"main() would take the run down instead of skipping")


def test_the_input_section_skips_on_an_empty_frame_too(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The key is read before the loop, so an empty frame cannot hide its absence.

    Seeded: with the read inside `scan_prompt` only, zero pairs never touched
    the key and the section returned `[]` -- `ok` with nothing scanned.
    """
    from benchmark import input_leakage as IL
    monkeypatch.setattr(IL, "enumerated_pairs", lambda: [])
    _withhold_every_key(monkeypatch)
    with pytest.raises(ModuleNotFoundError):
        IL.check_input_does_not_contain_the_answer()


def test_main_prints_skip_and_never_ok_for_a_section_whose_key_is_withheld(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Through `main`'s own section table, so the wiring is under test too."""
    keyed = {function for function, _ in _KEYED_SECTIONS.values()}
    monkeypatch.setattr(cc, "model_visible_surface", lambda: dict(_EMPTY_SURFACE))
    for function in set(_SECTIONS) - keyed:
        monkeypatch.setattr(cc, function, lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["contamination_check"])
    _withhold_every_key(monkeypatch)
    rc = cc.main()
    out = capsys.readouterr().out

    status: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0] in ("ok", "FAIL", "SKIP"):
            status[parts[1]] = parts[0]
    for name in _KEYED_SECTIONS:
        assert status.get(name) == "SKIP", (
            f"{name!r} printed {status.get(name)!r} with its key withheld. A "
            f"section that could not read its key scanned for nothing, and `ok` "
            f"reports that as clean.")
    assert rc == 2, "every other section was clean, so this run is incomplete"


def test_every_key_reader_under_the_gate_is_listed() -> None:
    """Both ways: a reader added or removed reddens this until it is declared."""
    import ast

    found: set[tuple[str, str]] = set()
    for module in ("contamination_check", "input_leakage"):
        tree = ast.parse((ROOT / "benchmark" / f"{module}.py").read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and any(
                    isinstance(n, ast.ImportFrom)
                    and n.module in cc.WITHHELD_MODULES
                    for n in ast.walk(fn)):
                found.add((module, fn.name))
    assert found == set(_KEY_READERS), (
        f"functions importing a withheld key: {sorted(found)}; declared: "
        f"{sorted(_KEY_READERS)}. A reader not declared has no test that it "
        f"skips rather than passes.")
    assert set(_KEY_READERS.values()) == set(_KEYED_SECTIONS), (
        "every key reader must map to a section the SKIP tests drive")
