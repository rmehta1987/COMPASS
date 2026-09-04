"""agent/cli_backend.py — headless `claude -p` as the reasoning model. No API key.

Uses the CLI's existing auth instead of ANTHROPIC_API_KEY, and reaches the COMPASS
environment through mcp/compass_server.py, so tool calls still execute in our
process and are still logged at the function boundary.

WHY THIS IS STRONGER THAN THE API PATH, AND WHERE IT IS WEAKER
--------------------------------------------------------------
Stronger: contamination control stops being a convention. `--strict-mcp-config`
plus an explicit `--allowed-tools` list means benchmark mode cannot reach a
retrieval tool at the process boundary, not merely because a Python dict omitted
it. And DENY below is load-bearing: a headless Claude has Bash, Read, Glob, Grep,
WebSearch and WebFetch by default. Left enabled, the model would `cat`
build/dictionary.json instead of calling resolve_variable — producing a protocol
with an empty research log and no verbatim-wording guarantee — and in benchmark
mode would read the literature the benchmark exists to withhold. Both failures
look like success from the outside.

Weaker: there is no grammar enforcement through the CLI. `guided_json` /
`output_config.format` have no flag, so the transduction call is prompted JSON
plus the schema-validated repair loop. That is an ACCEPTED, NAMED degradation
here, not a silent one: on a frontier model prompted JSON is far more reliable
than the 30-40% malformed rate that motivated the two-call design on a 7B, but it
is unenforced, and a run through this backend is not evidence about the 8-27B
target. There is also no seed and no temperature, so k samples vary without being
reproducible.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agent.backends import Reply
from agent.sealed import DENY_TOOLS, SealedWorktree

ROOT = Path(__file__).resolve().parent.parent

# Every built-in that could bypass the environment. Not a hardening nicety —
# without this the research log is a fiction.
DENY = DENY_TOOLS  # single definition, in agent/sealed.py


class ClaudeCliBackend:
    """Drives its own tool loop, so the Specifier hands it the whole turn.

    `drives_own_tool_loop` is the flag the Specifier branches on: with MCP the
    request -> tool -> response cycle happens inside the CLI, and we recover the
    call log from the file the MCP server writes rather than from parsing model
    output.
    """

    drives_own_tool_loop = True

    def __init__(self, model: str = "claude-sonnet-5", mode: str = "benchmark",
                 mcp_config: Path | None = None, tool_log_dir: Path | None = None,
                 # 24 turns was not enough headroom: a live run on 2026-08-26
                 # made 49 tool calls on covariate discovery and never reached
                 # check_access, so the whole sample was discarded by the gate.
                 max_turns: int = 40, timeout: float = 900.0):
        self.name = f"claude-cli:{model}"
        self.model = model
        self.mode = mode
        self.worktree = SealedWorktree(mode=mode, keep=True)
        self.sandbox = self.worktree.cwd
        self.mcp_config = mcp_config or self._retarget_mcp_config(
            self.worktree.mcp_config)
        self.settings = self.worktree.settings_path
        self.seal = self.worktree.manifest()
        self.tool_log_dir = tool_log_dir or (ROOT / "run" / "logs")
        self.run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        self._samples = 0
        self.tool_log = self._tool_log_path(0)
        self.tool_logs: list[Path] = []
        self.max_turns = max_turns
        self.timeout = timeout
        self.last_cost: float | None = None
        self.last_session: str | None = None

    # ----------------------------------------------------------------- #

    @staticmethod
    def _retarget_mcp_config(path: Path) -> Path:
        """Point the sealed MCP config at the interpreter that is actually running.

        agent/sealed.py writes `ROOT/.venv/bin/python` as the server command. A
        git worktree has no `.venv` of its own — lanes run the main venv by
        absolute path — so `claude -p` failed to spawn the environment server
        with `ENOENT: posix_spawn '.../lane-a/.venv/bin/python'`, every tool was
        unreachable, and the model returned a well-formed BLOCKER analysis that
        the gate then rejected for missing calls. The failure read as the model
        refusing to work. Only the interpreter is rewritten, so the shape of the
        config stays owned by sealed.py rather than being duplicated here.

        Args:
            path: The mcp_config.json the sealed worktree just wrote.

        Returns:
            The same path, with the server command retargeted.
        """
        cfg = json.loads(path.read_text())
        cfg["mcpServers"]["compass"]["command"] = sys.executable
        path.write_text(json.dumps(cfg, indent=2))
        return path

    def _tool_log_path(self, sample: int) -> Path:
        """Where sample `sample` of this run writes its research log.

        The predecessor was a single `run/tool_log.jsonl` truncated at the start
        of every sample, so the only log that survived a k=5 run belonged to the
        last sample, and no saved record could be audited against the calls that
        produced it. VERIFIED 2026-08-26: the log on disk held 38 calls at
        baseline_prevalence 0.35 while the record sitting beside it stated 0.30
        and had been written two hours earlier. A per-sample filename is what
        makes agent/tool_authority.py's comparison meaningful at all.

        Args:
            sample: Zero-based index of the reasoning call within this backend.

        Returns:
            The path this sample's MCP server will append to.
        """
        return self.tool_log_dir / f"tool_log.{self.run_id}.{sample:02d}.jsonl"

    def _run(self, argv: list[str]) -> str:
        env = {**os.environ, "COMPASS_MODE": self.mode,
               "COMPASS_TOOL_LOG": str(self.tool_log)}
        p = subprocess.run(argv, cwd=self.sandbox, env=env, capture_output=True,
                           text=True, timeout=self.timeout)
        if p.returncode != 0:
            raise RuntimeError(f"claude -p exited {p.returncode}\n"
                               f"stderr: {p.stderr[:1500]}")
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            return p.stdout.strip()          # --output-format text
        if out.get("is_error"):
            raise RuntimeError(f"claude -p reported an error: "
                               f"{str(out.get('result'))[:800]}")
        self.last_cost = out.get("total_cost_usd")
        self.last_session = out.get("session_id")
        return out.get("result", "")

    def reason(self, system: str, prompt: str, tool_names: list[str]) -> Reply:
        """Call 1. Tools available via MCP; every built-in denied.

        Args:
            system: The Specifier's system prompt, appended to the CLI's own.
            prompt: The stated pair and what to establish about it.
            tool_names: The registry's tool names for this mode; anything not
                listed cannot be reached at the process boundary.

        Returns:
            The model's prose analysis.
        """
        self.tool_log = self._tool_log_path(self._samples)
        self._samples += 1
        self.tool_logs.append(self.tool_log)
        self.tool_log.parent.mkdir(parents=True, exist_ok=True)
        self.tool_log.write_text("")              # a NEW file per sample, not a truncate
        allowed = ",".join(f"mcp__compass__{n}" for n in sorted(tool_names))
        return Reply(content=self._run([
            "claude", "-p", prompt,
            "--model", self.model,
            "--append-system-prompt", system,
            "--mcp-config", str(self.mcp_config),
            "--settings", str(self.settings),
            "--strict-mcp-config",
            "--allowed-tools", allowed,
            "--disallowed-tools", ",".join(DENY),
            "--max-turns", str(self.max_turns),
            "--output-format", "json",
        ]))

    def transduce(self, prompt: str) -> Reply:
        """Call 2. No tools at all — it may only reformat what call 1 established."""
        return Reply(content=self._run([
            "claude", "-p", prompt,
            "--model", self.model,
            "--append-system-prompt",
            "You emit one JSON object matching the requested schema and nothing "
            "else. No prose, no markdown fence, no commentary.",
            "--settings", str(self.settings),
            "--strict-mcp-config",
            "--disallowed-tools", ",".join(DENY),
            "--output-format", "json",
        ]))

    def fork(self, k: int) -> list[ClaudeCliBackend]:
        """K copies of this backend, one per concurrent sample.

        The seal, sandbox, MCP config, settings and run id are shared; the
        per-sample state is not. `reason()` on one shared instance repoints
        `tool_log` for every sample, so with two samples in flight the second
        one's start makes the first read the wrong log at the authority check,
        and `agent/tool_authority.py` then compares a record against calls
        another sample made. Each child owns one sample index, handed out from
        this instance's counter, so file names stay unique across every pair
        this backend serves; the parent's `tool_logs` still lists every log.

        Args:
            k: How many samples will run.

        Returns:
            `k` children, in sample order.
        """
        base = self._samples
        self._samples += k
        children = []
        for i in range(k):
            child = copy.copy(self)
            child._samples = base + i
            child.tool_log = child._tool_log_path(base + i)
            child.tool_logs = self.tool_logs
            children.append(child)
        return children

    def read_tool_log(self) -> list[dict]:
        """The authentic call record — written by our MCP server, not the model."""
        if not self.tool_log.exists():
            return []
        return [json.loads(l) for l in self.tool_log.read_text().splitlines() if l.strip()]
