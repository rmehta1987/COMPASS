---
description: Work the COMPASS backlog as orchestrator
model: claude-opus-5
---

You are the orchestrator. `CLAUDE.md` imports `AGENTS.md`, so the operating rules are
already in context. Architecture is `DESIGN.md`, the backlog is `TASKS.md`, history is
`CHANGELOG.md`.

**This command carries no task list, no state and no counts** — that is why it cannot go
stale the way the retired `/compass-build` command did (`a02eda7`, private history).
Everything it would have restated lives in a file that owns it.

1. Run the six commands in `AGENTS.md` §Verify current state and paste the real output.
   Do not summarise them. Two stop conditions only, both named there. In the public tree
   four of the six cannot run (withheld inputs, undeclared dependencies; see the note in
   `AGENTS.md` §Verify current state): run what runs, and say which did not.
2. Read `TASKS.md` in full and work in dependency order. Ask me before touching C12: its
   key form is settled and reopening it is my call, not a lane's.
3. Dispatch lanes per `AGENTS.md` §Parallel Lanes — own worktree, explicit file list
   including what not to touch, cold critic on a different family after each merge.
4. Before accepting a lane's report, run the suite, `ruff`, `mypy` and the contamination
   check in its worktree yourself, and re-derive its load-bearing claims.

Hand me back, per task: the acceptance criterion, MET or NOT MET without softening, the
command you ran with its real unedited output including failures, and for a live run the
record beside its own tool log. Move each closed item from `TASKS.md` to `CHANGELOG.md`,
hoisting any rule it leaves behind into `AGENTS.md` or `DESIGN.md` rather than the
changelog line.

You will read paper content to build the answer key and the probe, so **you are yourself a
contamination channel** — you also author `curated/`, `agent/schema.py` docstrings and the
prompts. `DESIGN.md` §5.2 applies to your own writing.
