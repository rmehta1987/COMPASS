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
        {"benchmark.prevalence_key", "benchmark.leak_facts"}), (
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
