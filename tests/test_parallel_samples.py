"""Concurrent samples: each one's authority check reads the log its own calls wrote.

User amendment of 2026-09-04: a k=5 pair took 41 minutes in series, five
sequential agent loops of 25-33 tool calls each. Running the samples at once
is safe only because every sample gets its own backend; on one shared
instance `reason()` repoints the tool log for whoever starts next.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agent.backends import Reply
from agent.specifier import specify
from generate.funnel import load_constructs
from pipeline.resolved_pair import ResolvedPair, from_records
from pipeline.retrieval_record import Hit, RequestSnapshot, RetrievalRecord

TAU = 0.729476


class ForkingFake:
    """A CLI-shaped backend: drives its own loop, owns a tool log, can fork.

    `reason` sleeps so two samples overlap when run at once, records which
    thread ran it and which log path it wrote, and `read_tool_log` returns what
    THIS instance's log holds. On a shared instance the second `reason` moves
    `tool_log` before the first sample reads it, which is the defect the fork
    exists to prevent; the fake mirrors that so the guarantee is testable.
    """

    drives_own_tool_loop = True
    name = "fake-cli"

    def __init__(self, log_dir: Path, shared: dict[str, Any]) -> None:
        """One instance; `shared` is the bookkeeping every fork appends to."""
        self.log_dir = log_dir
        self.shared = shared            # one dict across parent and children
        self._samples = 0
        self.tool_log = log_dir / "tool_log.00.jsonl"
        self.tool_logs: list[Path] = []
        self.forks = 0
        self.last_cost = None

    def fork(self, k: int) -> list[ForkingFake]:
        self.forks += 1
        base = self._samples
        self._samples += k
        out = []
        for i in range(k):
            c = ForkingFake.__new__(ForkingFake)
            c.__dict__.update(self.__dict__)
            c._samples = base + i
            c.tool_log = self.log_dir / f"tool_log.{base + i:02d}.jsonl"
            out.append(c)
        return out

    def reason(self, system: str, prompt: str, tool_names: list[str]) -> Reply:
        self.tool_log = self.log_dir / f"tool_log.{self._samples:02d}.jsonl"
        self._samples += 1
        self.tool_logs.append(self.tool_log)
        self.tool_log.write_text(json.dumps({"tool": "resolve_variable",
                                             "args": {"key": self.tool_log.name},
                                             "outcome": "unique", "ms": 1.0}) + "\n")
        with self.shared["lock"]:
            self.shared["in_flight"] += 1
            self.shared["peak"] = max(self.shared["peak"], self.shared["in_flight"])
        time.sleep(0.15)
        with self.shared["lock"]:
            self.shared["in_flight"] -= 1
        self.shared["reasoned"].append((threading.get_ident(), self.tool_log.name))
        return Reply(content="analysis without a verdict")

    def read_tool_log(self) -> list[dict]:
        rows = [json.loads(line) for line in
                self.tool_log.read_text().splitlines() if line.strip()]
        self.shared["read"].append((self.tool_log.name, rows[0]["args"]["key"]))
        return rows

    def transduce(self, prompt: str) -> Reply:
        return Reply(content="{}")      # rejected by the schema; the sample fails


def _rec(role: str, key: str, ck: str, members: tuple[str, ...]) -> RetrievalRecord:
    return RetrievalRecord(
        request=RequestSnapshot(construct_text="stem", role=role, source="instrument"),
        query="stem", dictionary_hash="h", min_cos=TAU, best_cos=0.9, margin=0.9 - TAU,
        margin_12=0.1, abstained=False, nearest_key=key,
        hit=Hit(key=key, construct_key=ck, dict_construct_key=ck, module=ck[1],
                target_id=1, fold_size=1, n_siblings=0, members=members,
                stratum="chronic_condition", unmeasured_stratum=False))


@pytest.fixture(scope="module")
def pair() -> ResolvedPair:
    try:
        C, _ = load_constructs()
    except FileNotFoundError:
        pytest.skip("build/dictionary.json is withheld from the public tree")
    e = [c for c in C.values() if c.construct_key == "m3:Q16.1"]
    o = [c for c in C.values() if c.construct_key == "m2:Q5.8"]
    rec_e = _rec("exposure", e[0].member_keys[0], "m3:Q16.1", tuple(e[0].member_keys))
    rec_o = _rec("outcome", o[0].member_keys[0], "m2:Q5.8", tuple(o[0].member_keys))
    return from_records(rec_e, rec_o, C, estimability="blocked_no_metadata")


def _shared() -> dict[str, Any]:
    return {"lock": threading.Lock(), "in_flight": 0, "peak": 0, "reasoned": [],
            "read": []}


def test_concurrent_samples_overlap_and_each_reads_its_own_log(pair, tmp_path):
    shared = _shared()
    b = ForkingFake(tmp_path, shared)
    res = specify(b, pair, k=4, workers=4, parked_dir=tmp_path / "parked")
    assert len(res.attempts) == 4 and res.selected is None
    assert b.forks == 1
    assert shared["peak"] >= 2, "samples never overlapped: they ran in series"
    assert len({t for t, _ in shared["reasoned"]}) >= 2
    # every read saw the log the same sample wrote, and every log was read once
    names = [f"tool_log.{i:02d}.jsonl" for i in range(4)]
    assert sorted(shared["read"]) == [(n, n) for n in names]
    assert sorted(p.name for p in b.tool_logs) == [f"tool_log.{i:02d}.jsonl"
                                                   for i in range(4)]


def test_a_second_pair_on_the_same_backend_gets_fresh_log_names(pair, tmp_path):
    shared = _shared()
    b = ForkingFake(tmp_path, shared)
    specify(b, pair, k=2, workers=2, parked_dir=tmp_path / "parked")
    specify(b, pair, k=2, workers=2, parked_dir=tmp_path / "parked")
    assert sorted(p.name for p in b.tool_logs) == [f"tool_log.{i:02d}.jsonl"
                                                   for i in range(4)]


def test_workers_one_never_forks_and_runs_in_series(pair, tmp_path):
    shared = _shared()
    b = ForkingFake(tmp_path, shared)
    specify(b, pair, k=3, workers=1, parked_dir=tmp_path / "parked")
    assert b.forks == 0 and shared["peak"] == 1
    assert [n for _, n in shared["reasoned"]] == [f"tool_log.{i:02d}.jsonl"
                                                  for i in range(3)]


def test_the_cli_backend_forks_with_distinct_logs_and_a_shared_seal():
    from agent.cli_backend import ClaudeCliBackend
    b = ClaudeCliBackend(model="claude-haiku-4-5")
    kids = b.fork(3)
    assert [k.tool_log.name for k in kids] == [f"tool_log.{b.run_id}.{i:02d}.jsonl"
                                                for i in range(3)]
    assert all(k.sandbox == b.sandbox and k.mcp_config == b.mcp_config
               and k.seal == b.seal and k.tool_logs is b.tool_logs for k in kids)
    again = b.fork(2)
    assert [k.tool_log.name for k in again] == [f"tool_log.{b.run_id}.{i:02d}.jsonl"
                                                for i in (3, 4)]
