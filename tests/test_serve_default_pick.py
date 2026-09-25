"""`/api/pair` fills an `ambiguous` role with a default, beside the verdict.

MEASURED 2026-09-24 on "does have access to primary care decrease depression":
the exposure resolved, the outcome came back `ambiguous` over two diagnosis
items and a symptom item, and the field stayed empty, so the question could not
run until the reader picked by hand. The verdict is right and stays; a second
call supplies the default (`serve/api.py::_default_pick`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

KEYS = ["m3:Q4.2", "m2:Q5.8", "m3:Q2.1"]

_AMBIGUOUS = json.dumps({"verdict": "ambiguous", "indices": [],
                         "missing_dimension": "which measure", "reason": "several"})
_RESOLVED = '{"verdict": "resolved", "indices": [1]}'


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replies: list[str],
         costs: list[float | None] | None = None,
         family: dict[str, int] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Drive `_pair` with scripted replies over one shared pool.

    Args:
        tmp_path: Scratch root.
        monkeypatch: Patcher for the backend and the pool.
        replies: The model's replies, in call order. A call past the end
            raises inside the job, so an unexpected call fails the job.
        costs: Each call's `last_cost`, in call order; None throughout if unset.
        family: `roster_family_size` per key, 1 where unset.

    Returns:
        The finished job and every prompt the backend was sent.
    """
    from agent import cli_backend
    from agent import prompt_contract as PC
    from agent.backends import Reply
    from serve import api

    script, prices = iter(replies), iter(costs or [None] * len(replies))
    prompts: list[str] = []
    facts = {k: {"module": k[1], "roster_family_size": (family or {}).get(k, 1)}
             for k in KEYS}

    def fake_pool(_state: object, query: str, _role: str, _k: int) -> dict:
        return {"cands": PC.candidates_from_keys(KEYS, facts),
                "cos": dict.fromkeys(KEYS, 0.5), "skipped": [],
                "rendered": f"q:{query}"}

    class _Scripted:
        """A backend that answers from a script and prices each call."""

        name = "scripted"

        def __init__(self, **_: object) -> None:
            self.last_cost: float | None = None

        def transduce(self, prompt: str, *_: object) -> Reply:
            prompts.append(prompt)
            self.last_cost = next(prices)
            return Reply(content=next(script))

    monkeypatch.setattr(cli_backend, "ClaudeCliBackend", _Scripted)
    monkeypatch.setattr(api, "_role_candidates", fake_pool)
    st = api.State(tmp_path / "deploy", tmp_path / "site", tmp_path / "run",
                   show_instrument=True)
    ticket = api._pair(st, {"request": "does a raise b"})["ticket"]
    deadline = time.time() + 30
    while st.jobs[ticket]["status"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    return st.jobs[ticket], prompts


def _pick(index: int | None, verdict: str = "default") -> str:
    return json.dumps({"verdict": verdict, "index": index, "reason": "most direct"})


def test_an_ambiguous_role_gets_a_default_beside_its_unchanged_verdict(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The verdict is reported as it came back; the default travels next to it."""
    done, prompts = _run(tmp_path, monkeypatch, [_RESOLVED, _AMBIGUOUS, _pick(2)])
    assert done["status"] == "done", done
    out = done["run"]["roles"]["outcome"]
    assert out["verdict"] == "ambiguous"
    assert out["proposed_indices"] == [], "a default is not a committed choice"
    assert out["default_pick"] == {"status": "chosen", "index": 2,
                                   "reason": "most direct"}
    assert [c["key"] for c in out["candidates"] if c["default"]] == [KEYS[1]]
    assert not any(c["proposed"] for c in out["candidates"])
    # The third prompt is the default surface, and it carries what would settle
    # the ambiguity; the second is the retrieval surface, which must not ask
    # for a default at all.
    assert "which measure" in prompts[2] and "OUTCOME" in prompts[2]
    from agent import prompt_contract as PC
    assert PC.DEFAULT_GUIDANCE in prompts[2]
    assert PC.DEFAULT_GUIDANCE not in prompts[1]


def test_a_resolved_role_spends_no_second_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only `ambiguous` asks for a default; a third call would exhaust the script."""
    done, prompts = _run(tmp_path, monkeypatch, [_RESOLVED, _RESOLVED])
    assert done["status"] == "done", done
    assert len(prompts) == 2
    for role in ("exposure", "outcome"):
        assert done["run"]["roles"][role]["default_pick"] is None
        assert not any(c["default"] for c in done["run"]["roles"][role]["candidates"])


@pytest.mark.parametrize("verdict", ["absent", "derive", "family"])
def test_a_verdict_other_than_ambiguous_asks_for_no_default(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verdict: str) -> None:
    """`absent` has nothing to default to; `derive` and `family` are not one item."""
    reply = json.dumps({"verdict": verdict, "indices": []})
    done, prompts = _run(tmp_path, monkeypatch, [_RESOLVED, reply])
    assert done["status"] == "done", done
    assert len(prompts) == 2
    assert done["run"]["roles"]["outcome"]["default_pick"] is None


@pytest.mark.parametrize(("reply", "why"), [
    (_pick(4), "not one of the 3 offered"),
    (_pick(0), "not one of the 3 offered"),
    (_pick(None), "not one of the 3 offered"),
    (_pick(3), "roster family of 5"),
])
def test_a_default_the_harness_cannot_take_is_refused_not_filled(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str, why: str) -> None:
    """Range and roster membership are the harness's rules, not the prompt's."""
    done, _ = _run(tmp_path, monkeypatch, [_RESOLVED, _AMBIGUOUS, reply],
                   family={KEYS[2]: 5})
    out = done["run"]["roles"]["outcome"]
    assert out["verdict"] == "ambiguous"
    assert out["default_pick"]["status"] == "refused"
    assert why in out["default_pick"]["why"]
    assert not any(c["default"] for c in out["candidates"])


def test_a_declined_default_fills_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`none` is an answer, and it leaves the field empty."""
    done, _ = _run(tmp_path, monkeypatch,
                   [_RESOLVED, _AMBIGUOUS, _pick(None, verdict="none")])
    out = done["run"]["roles"]["outcome"]
    assert out["default_pick"]["status"] == "declined"
    assert not any(c["default"] for c in out["candidates"])


def test_an_unreadable_default_loses_the_default_not_the_verdict(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad second reply must not turn a finished verdict into a job error."""
    done, _ = _run(tmp_path, monkeypatch, [_RESOLVED, _AMBIGUOUS, "no json here"])
    assert done["status"] == "done", done
    out = done["run"]["roles"]["outcome"]
    assert out["verdict"] == "ambiguous"
    assert out["default_pick"]["status"] == "failed"
    assert out["default_pick"]["index"] is None


def test_the_run_prices_every_call_not_the_last(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`last_cost` is per call: reporting it alone priced one call of three."""
    done, _ = _run(tmp_path, monkeypatch, [_RESOLVED, _AMBIGUOUS, _pick(2)],
                   costs=[0.01, 0.02, 0.04])
    assert done["run"]["model_calls"] == 3
    assert done["run"]["cost_usd"] == pytest.approx(0.07)


def test_one_unpriced_call_makes_the_total_unknown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial sum would read as the price of the run; None says it is not known."""
    done, _ = _run(tmp_path, monkeypatch, [_RESOLVED, _AMBIGUOUS, _pick(2)],
                   costs=[0.01, None, 0.04])
    assert done["run"]["model_calls"] == 3
    assert done["run"]["cost_usd"] is None
