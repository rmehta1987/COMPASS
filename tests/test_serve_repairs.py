"""Tests for an endpoint job's repair history (TASKS.md C19 residue).

C19 made `generate/live_specifier.py` write `.repairs.json` beside each record,
because a repair error can quote a signed file and a record that passed on a
later transduction can carry a derivation key set no tool returned. The job
record `serve/api.py::_specify` keeps did not, so a record specified through
the endpoint had no visible source for such a value.

Driven through `_specify` itself, with a scripted backend standing in for
`claude -p`, so what is asserted is what the route persists and not what a
helper would return if something called it.
"""

from __future__ import annotations

import json
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.backends import Reply, ScriptedBackend  # noqa: E402
from generate.funnel import DEFAULT_FRAME, FRAMES, load_constructs, walk  # noqa: E402
from generate.run_specifier import (  # noqa: E402
    ANALYSIS,
    REASON_CALLS_A,
    REASON_CALLS_B,
    fixture,
)
from serve import api  # noqa: E402

#: The pair the fixture record is written for.
PAIR = {"exposure": "m3:Q16.1", "outcome": "m2:Q5.8"}


def _script() -> tuple[list[Reply], str, list[str]]:
    """A run whose derivation key set reaches the model only through a repair.

    The same script as `tests/test_specifier.py::_repaired_through_the_validator`:
    the reasoning never calls `get_derivation`, the first transduction drops one
    component key, and the validator's error quotes the signed list.

    Returns:
        The replies, the rejected first transduction, and the signed key list.
    """
    C, version = load_constructs()
    _, counts = walk(FRAMES[DEFAULT_FRAME], C)
    good = json.loads(fixture(version, counts["enumerated"]))
    signed = good["exposure"]["component_keys"]
    wrong = json.dumps({**good, "exposure": {**good["exposure"],
                                             "component_keys": signed[:-1]}})
    replies = [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
               Reply(content=ANALYSIS), Reply(content=wrong),
               Reply(content=json.dumps(good))]
    return replies, wrong, signed


def _run_specify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 replies: list[Reply]) -> tuple[api.State, str, dict]:
    """Run `_specify` to completion on a scripted backend.

    Args:
        tmp_path: pytest's per-test directory.
        monkeypatch: pytest's monkeypatch fixture.
        replies: What the backend answers, in order.

    Returns:
        The state, the ticket and the finished job record.
    """
    from agent import cli_backend

    class _Scripted(ScriptedBackend):
        """Takes `ClaudeCliBackend`'s arguments and answers from the script."""

        last_cost = 0.0

        def __init__(self, **_: object) -> None:
            script: list[Reply | Callable[[list[dict]], Reply]] = list(replies)
            super().__init__(script)

    monkeypatch.setattr(cli_backend, "ClaudeCliBackend", _Scripted)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    ticket = api._specify(st, dict(PAIR))["ticket"]
    deadline = time.time() + 60
    while st.jobs[ticket]["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    return st, ticket, st.jobs[ticket]


def test_an_endpoint_job_keeps_its_repairs_and_traces_them(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The repair that showed the model its key set is on disk beside the job.

    Two halves. The persisted history holds the rejected transduction, and the
    trace run over it finds every derivation value accounted for. Without the
    repair the same record traces nowhere, which the anti-vacuity lines check:
    the script never fetched the derivation, so the repair is the only source.
    """
    replies, wrong, signed = _script()
    st, ticket, done = _run_specify(tmp_path, monkeypatch, replies)
    assert done["status"] == "done", done
    run_ = done["run"]
    assert run_["selected"] is not None, run_["samples"]
    assert "get_derivation" not in run_["samples"][0]["distinct_tools"]

    kept = api._job_path(st, ticket).with_suffix(".repairs.json")
    assert kept.is_file(), "the endpoint job kept no repair history"
    data = json.loads(kept.read_text(encoding="utf-8"))
    # The trace first: with the repair dropped, the key set traces nowhere,
    # and this is the line that says so.
    assert data["untraced"] == [], data["untraced"]
    assert [r["rejected"] for r in data["repairs"]] == [wrong]
    assert str(signed) in data["repairs"][0]["error"]
    assert run_["repairs"] == {"kept": 1, "untraced": [],
                               "file": str(kept.relative_to(st.run_dir))}

    # The job record written to disk says the same as the one in memory.
    on_disk = json.loads(api._job_path(st, ticket).read_text(encoding="utf-8"))
    assert on_disk["run"]["repairs"] == run_["repairs"]


def test_the_repair_history_is_an_output_the_site_guard_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The new file sits under a directory `OWN_OUTPUT_MARKERS` already names.

    It holds the rejected transductions unscrubbed, like the job record beside
    it, so a stale run directory inside `--site-dir` must be refused for it.
    """
    replies, _, _ = _script()
    st, ticket, done = _run_specify(tmp_path, monkeypatch, replies)
    assert done["status"] == "done", done
    kept = api._job_path(st, ticket).with_suffix(".repairs.json")
    assert kept.is_file(), "the endpoint job kept no repair history"
    rel = kept.relative_to(st.run_dir)
    assert rel.parts[0] in api.OWN_OUTPUT_MARKERS, rel

    site = tmp_path / "served"
    (site / "old-run" / rel.parent).mkdir(parents=True)
    (site / "old-run" / rel).write_text("{}", encoding="utf-8")
    why = api._refuse_unsafe_site_dir(site.resolve(), (tmp_path / "live").resolve())
    assert why is not None and rel.parts[0] in why


def test_the_record_attempt_is_found_by_identity_for_both_kinds() -> None:
    """A protocol and a refusal each resolve to the attempt that made them.

    By identity: two samples can carry equal records, and the one whose
    repairs are kept must be the one `specify` selected.
    """
    twin_a, twin_b = object(), object()
    first = types.SimpleNamespace(protocol=twin_a, refusal=None)
    second = types.SimpleNamespace(protocol=twin_b, refusal=None)
    res = types.SimpleNamespace(selected=twin_b, refusal=None, attempts=[first, second])
    assert api._record_attempt(res) is second

    ref = object()
    refused = types.SimpleNamespace(protocol=None, refusal=ref)
    res = types.SimpleNamespace(selected=None, refusal=ref,
                                attempts=[types.SimpleNamespace(protocol=None,
                                                                refusal=object()),
                                          refused])
    assert api._record_attempt(res) is refused

    none = types.SimpleNamespace(selected=None, refusal=None, attempts=[first])
    assert api._record_attempt(none) is None


def test_a_run_with_no_record_says_there_is_nothing_to_trace(
        tmp_path: Path) -> None:
    """No record, no file, and `untraced` is None rather than an empty pass."""
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run")
    res = types.SimpleNamespace(selected=None, refusal=None, attempts=[])
    out = api._keep_repairs(st, "120000-abcdef", res)
    assert out["kept"] is None and out["untraced"] is None
    assert "no record" in out["note"]
    assert not (st.run_dir / api.JOBS_DIR_NAME).exists()
