"""What `env/tools.py` can and cannot return, measured rather than described.

`tests/` files follow the module they cover and there was no file covering
`env/tools.py`; its behaviour was tested inside `tests/test_specifier.py`, which
covers another lane's module. This is that file.

WHY IT EXISTS NOW. Two claims about this environment are load-bearing elsewhere
and enforced nowhere. `agent/specifier.py::PAIR_ADJUDICABLE`'s comment states
"MEASURED 2026-08-28, neither is reachable from this environment at all"; the
retired handoff's calibration paragraph names three empty registries. A claim
about `env/tools.py` written into another lane's comment is the exact shape of
the collision `6160b99` produced — a blocker one lane added to the environment
while the enum lived in another lane's file, and every live record failed
validation. These tests put the measurement next to the code it is about.
"""

from __future__ import annotations

import ast
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.schema import REFUSAL_EVIDENCE, RefusalReason  # noqa: E402
from agent.specifier import PAIR_ADJUDICABLE  # noqa: E402
from env import tools as T  # noqa: E402

#: Keys spanning every branch check_access has: three location precisions at
#: three distinct places, a non-location key, and two that resolve nowhere.
_KEY_POOL = ("m1:Q2.4", "m1:Q85", "m2:Q25.5_2", "m2:Q27.4_2", "m2:Q5.8",
             "m2:Q12.78", "m3:Q16.1_1", "linked:example_measure", "nonsense:key")


def test_check_access_returns_only_pass_or_refer():
    """Exhaustive over every subset of a nine-key pool up to size four.

    255 calls, and `decision` takes two values. `access_gate_refused` names a
    third that no return value produces, so nothing in this environment can
    earn it.
    """
    decisions, outcomes = set(), set()
    calls = 0
    for size in range(len(_KEY_POOL) + 1):
        if size > 4:
            break
        for combo in itertools.combinations(_KEY_POOL, size):
            r = T.check_access(list(combo))
            decisions.add(r["decision"])
            outcomes.add(r["outcome"])
            calls += 1
    assert calls > 200, calls
    assert decisions == {"pass", "refer"}, decisions
    assert outcomes == {"ok"}, outcomes


def test_get_contrast_convention_has_no_branch_that_fails_to_return_one():
    """Structural, not sampled: the function has exactly one exit.

    Sampling inputs shows a contrast for the inputs sampled. The claim being
    checked is stronger — that NO input reaches an exit without one — and a
    single `return` of a dict that always carries `exposure_contrast` is what
    makes that true rather than probable.
    """
    # Parsed from the FILE, not from `inspect.getsource` on the callable:
    # every tool here is wrapped by `@_logged`, so the callable's source is the
    # wrapper and an AST check over it would silently examine the decorator.
    tree = ast.parse((ROOT / "env" / "tools.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "get_contrast_convention")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(returns) == 1, "more than one exit; re-check every one of them"
    keys = {k.value for k in returns[0].value.keys}      # type: ignore[union-attr]
    assert "exposure_contrast" in keys and "outcome" in keys
    # And the if/elif chain that chooses it ends in a bare `else`, so no input
    # falls through without a contrast assigned.
    chains = [n for n in ast.walk(fn) if isinstance(n, ast.If)]
    assert chains and chains[-1].orelse, "the contrast chain has no else branch"
    for probe in ("likert", "derived scale", "binary", "continuous", "", "zzz",
                  "not definable", "free text"):
        assert T.get_contrast_convention(probe)["exposure_contrast"]


def test_two_refusal_reasons_have_no_producing_return_value():
    """The finding, stated once and in the file it is about.

    `RefusalReason`'s own docstring: "Every value names a condition a tool in
    this environment can confirm." Two do not. They are already absent from
    `PAIR_ADJUDICABLE`, so the system prompt never offers them and `adjudicate`
    never settles on one — this test is the guard that keeps those two facts
    from drifting apart, since the enum and the environment live in different
    lanes' files.

    NOT a request to add failure paths. Inventing an environment behaviour so a
    schema member becomes reachable is fitting the instrument to the form.
    """
    unproducible = {RefusalReason.access_gate_refused,
                    RefusalReason.no_contrast_definable}
    assert not (unproducible & PAIR_ADJUDICABLE), (
        "a reason no return value produces is being offered to the model")
    # Each still declares its evidence, so the schema stays self-consistent and
    # `_refusal_is_earned` cannot raise its design-hole error on one.
    for reason in unproducible:
        assert REFUSAL_EVIDENCE[reason]
    # The third non-adjudicable member is a different case and must not be
    # folded in with these two: `list_derivations` returning a set that lacks a
    # derivation DOES confirm no_signed_derivation. It is excluded from
    # PAIR_ADJUDICABLE to avoid over-refusal, not because it is unreachable.
    assert RefusalReason.no_signed_derivation not in PAIR_ADJUDICABLE
    assert T.list_derivations()["outcome"] == "ok"
    assert RefusalReason.no_signed_derivation not in unproducible


def test_registry_coverage_reports_four_empty_registries_not_three():
    """The retired spec named three. There are four.

    `git show 0a01d7e:HANDOFF_AGENT_PIPELINE.md`, T6b's calibration paragraph:
    "any `clinical:`/`lab:`/`ehr:` key". `linked` is empty by the identical
    mechanism — same `coverage: none`, same shape — and is the one the
    refusal-path acceptance actually uses.
    """
    registries = T.registry_coverage()["registries"]
    empty = {k for k, v in registries.items() if v["coverage"] != "populated"}
    assert empty == {"clinical", "lab", "ehr", "linked"}, empty
    assert {k for k, v in registries.items() if v["coverage"] == "populated"} \
        == {"m1", "m2", "m3"}


def test_only_one_empty_registry_is_scheduled_to_be_populated():
    """Which matters for the calibration set, and is why four is not three.

    `linked` is blocked on `area_measure_inventory` — an artefact this project
    plans to build, and populating it is the one-shot act C6 must run before.
    `clinical`, `lab` and `ehr` are blocked on `study_team_confirmation`, which
    nothing here schedules. So a calibration arm resting on `linked:` evaporates
    the day the registry fills, while the other three are stable ground.
    """
    registries = T.registry_coverage()["registries"]
    blockers = {k: v.get("blocked_on") for k, v in registries.items()
                if v["coverage"] != "populated"}
    assert blockers["linked"] == "area_measure_inventory"
    assert {blockers[k] for k in ("clinical", "lab", "ehr")} \
        == {"study_team_confirmation"}


def test_no_tool_accepts_a_parameter_it_ignores():
    """A dead parameter is how a docstring guarantee gets an alibi.

    MEASURED 2026-08-31: `check_access(keys, measures=None)` promised in its
    docstring that "deliberately excluded variables still resolve and have their
    wording checked but consume NO budget". `measures` was referenced ZERO times
    in the executable body — the promise had no code behind it, and the
    parameter was the only thing that made it look like it did. The test that
    named the guarantee, `tests/test_specifier.py::
    test_excluded_variables_do_not_consume_access_budget`, passes two
    non-location keys and no exclusions at all, so it cannot fail for the reason
    it is named after.

    Structural rather than sampled: a caller cannot probe for an argument that is
    silently discarded, and `agent/registry.py::_checked` unions the real
    signature into `accepted`, so a dead parameter is accepted at the boundary
    too. Seeded 2026-08-31 by adding an unused parameter back to `check_access` —
    this test went red and no other test in the suite moved.
    """
    tree = ast.parse((ROOT / "env" / "tools.py").read_text(encoding="utf-8"))
    functions = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
    dead: dict[str, list[str]] = {}
    for name in T.TOOLS:
        fn = functions[name]
        a = fn.args
        params = [p.arg for p in a.posonlyargs + a.args + a.kwonlyargs]
        body = fn.body
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant):
            body = body[1:]          # the docstring is not the implementation
        read = {n.id for stmt in body for n in ast.walk(stmt)
                if isinstance(n, ast.Name)}
        ignored = [p for p in params if p not in read]
        if ignored:
            dead[name] = ignored
    assert not dead, (
        f"these tools take arguments their bodies never read: {dead}. A "
        f"parameter the code ignores is prompt-adjacent surface promising "
        f"behaviour that does not exist; delete it, or read it.")
