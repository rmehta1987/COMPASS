"""mcp/compass_server.py — env/tools.py exposed over stdio MCP.

Lets a headless `claude -p` call the COMPASS environment directly, with no API
key: the CLI's existing auth is used, and every tool call still executes in this
process, so the research log is logged at the function boundary exactly as it is
in the Python loop. A model cannot forge a call it never made.

Deliberately dependency-free: JSON-RPC 2.0 over line-delimited stdio. Adding an
MCP SDK here would put a third-party package between the model and the
environment for no gain, and this protocol surface is three methods wide.

The mode is read from COMPASS_MODE and passed to build_registry, so the tool set
this server can offer is decided by the same single construction site as
everywhere else. Combined with `--strict-mcp-config` and `--allowed-tools`, that
gives benchmark mode a process-level guarantee rather than a convention.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.registry import build_registry  # noqa: E402

MODE = os.environ.get("COMPASS_MODE", "benchmark")
LOG_PATH = Path(os.environ.get("COMPASS_TOOL_LOG", ROOT / "run" / "tool_log.jsonl"))
CALLABLES, OPENAI_SCHEMAS = build_registry(MODE)

# OpenAI-shaped schemas -> MCP tool descriptors. Same source of truth, one
# translation, so a tool can never be exposed here that the registry withheld.
TOOLS = [{"name": s["function"]["name"],
          "description": s["function"]["description"],
          "inputSchema": s["function"].get("parameters", {"type": "object", "properties": {}})}
         for s in OPENAI_SCHEMAS]


def _log(name: str, args: dict, outcome: str, ms: float, result=None) -> None:
    """Append one call to the research log.

    `result` is written because the log is the ONLY authentic record of what the
    environment returned — the model's transcription of it is not evidence. An
    earlier version stored only name/args/outcome, which made it impossible to
    check a record's gate fields against what the gate actually said, and left
    `access.budget: 0` in a record while check_access returned 3.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"tool": name, "args": args, "outcome": outcome,
                            "ms": round(ms, 2), "result": result}) + "\n")


def _call(name: str, args: dict) -> dict:
    fn = CALLABLES.get(name)
    if fn is None:
        # Withheld by the registry for this mode, or misspelled. Say which, so a
        # benchmark run that tries to reach a retrieval tool is visible in the
        # log rather than looking like a typo.
        _log(name, args, "not_available", 0.0, None)
        return {"outcome": "not_available",
                "log": (f"No tool {name!r} in mode {MODE!r}. Available: "
                        f"{sorted(CALLABLES)}")}
    t0 = time.perf_counter()
    try:
        out = fn(**args)
    except TypeError as exc:
        out = {"outcome": "error", "log": f"bad arguments for {name}: {exc}"}
    _log(name, args, out.get("outcome", "ok"),
         (time.perf_counter() - t0) * 1000, out)
    return out


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            # Echo the client's protocol version rather than pinning one, so a
            # CLI upgrade does not silently fail to negotiate.
            result = {
                "protocolVersion": req.get("params", {}).get("protocolVersion",
                                                             "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "compass-env", "version": "0.1",
                               "mode": MODE},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = req.get("params", {})
            out = _call(p.get("name", ""), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out)}],
                      "isError": out.get("outcome") in ("error", "not_available")}
        elif method and method.startswith("notifications/"):
            continue                                    # no response to a notification
        elif rid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {
                "code": -32601, "message": f"method not found: {method}"}}) + "\n")
            sys.stdout.flush()
            continue
        else:
            continue

        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid,
                                     "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
