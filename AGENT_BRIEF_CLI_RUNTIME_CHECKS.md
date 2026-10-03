<!-- Companion to the agent brief template (v4, 2026-10-02), §9: what M1 probes when the
     runtime is the headless `claude` CLI. Copied into brief/ as CLI_RUNTIME_CHECKS.md.
     Observed on CLI 2.1.285 in one project's M1 (2026-09-29/30); re-probe on your version
     and record `claude --version`, `claude --help` and the flags chosen, verbatim. -->

# Runtime checks: headless `claude` CLI

Each check names the evidence to save (stream-json events, tool-server log). A check on
the failure path counts only if it was run on the failure path.

## Must-haves (any failure: stop and ask)
1. **Loads the tool server.** `--mcp-config <run>/mcp.json --strict-mcp-config`; the
   init event lists the server as `connected`, and the server's own log shows
   `initialize → tools/list → tools/call`.
2. **Only those tools.** `--tools ""` disables every built-in; `--allowedTools` names the
   server's tools; `--disable-slash-commands` empties skills. Check the init event's
   `tools` list. `--json-schema` adds a `StructuredOutput` tool: it is model-visible.
3. **Schema-constrained final.** `--json-schema <schema>`: the model ends by calling
   `StructuredOutput`; `result.structured_output` holds the object. A `PreToolUse` hook
   on `StructuredOutput` that exits 2 returns its stderr to the model as a tool error,
   so validation retries need no extra tool. Probe a rejected submission:
   - the CLI's own schema check runs after the hook, so a schema slip can spend a retry;
   - after the hook's last rejection the CLI may still invite another submission — the
     hook must refuse every submission once the terminal object exists, and the harness
     stops the CLI (a valid late answer was otherwise discarded).
4. **Forced final turn.** `--max-turns` counts model turns, not tool calls: three batched
   calls ran under `--max-turns 2`. Count tool calls in a hook or the tool server. The
   final turn is `--resume <session-id>` with an empty `--mcp-config`,
   `--strict-mcp-config`, `--tools ""`; it needs session persistence, so never pass
   `--no-session-persistence` to the main run. `CLAUDE_CODE_MAX_OUTPUT_TOKENS` caps output
   (the run ends `is_error` when exceeded).
5. **Cost.** `total_cost_usd` in the `result` event is cumulative across `--resume`. A run
   the harness stops has no `result` event: take the last `cost-state` entry of the CLI's
   session file (equal to `total_cost_usd` on 121 of 121 runs that had both).

## Ambient configuration (turn each off; check the init event)
- Auto-memory is on by default: `--settings '{"autoMemoryEnabled":false}'`; `--settings`
  applies even with `--setting-sources ""`.
- Replace the default system prompt with `--system-prompt`; it is most of the input
  tokens otherwise, and counts toward §8 if kept.
- Strip the parent session's variables before launching (`env -u` each of `CLAUDECODE`,
  `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID`,
  `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`,
  `CLAUDE_CODE_SESSION_ATTENDED`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_EFFORT`; keep
  `CLAUDE_CONFIG_DIR`). Also for any model-driven helper, such as a sampled review.
- Each run: a fresh empty temporary cwd, a fresh `--session-id`, `--permission-mode
  dontAsk`, stdin from `/dev/null`.

## Model-visible text the CLI adds (count it toward §8)
- The `StructuredOutput` tool and its schema.
- A hook error is prefixed with the hook's full command line
  (`PreToolUse:StructuredOutput hook error: [<command>]: …`): keep the command short and
  free of paths.

## Test doubles
A fake CLI used in tests replays every behaviour above that the harness depends on, in
particular the post-hook schema check: the fake's omission of it is what hid the
late-answer bug.

## Permissions while building
The auto-mode classifier may deny a builder any step on private data ("PII Data
Handling", "Credential Exploration"), whatever the operator has said in chat. Decide
before M1 (template §3): operator-run scripts that print counts only, or a scoped
permission rule the operator grants.
