# CLAUDE.md

@AGENTS.md

🛑 **Never remove the `@AGENTS.md` import above.** It loads the rules at session start and
re-expands them after compaction; a "read it first" pointer loads nothing.

Claude Code specifics only; rank: `AGENTS.md` §Source of Truth. Rules: `AGENTS.md`.
Architecture: `DESIGN.md`. Backlog: `TASKS.md`. History: `CHANGELOG.md`.

## Why project rules are safe in this file

- The pipeline's model cannot see it: each headless run gets a `mkdtemp` cwd outside the
  project (`agent/sealed.py::SealedWorktree.__init__`), and
  `agent/sealed.py::SealedWorktree._claude_md_sources` records what stayed reachable.
- Never move a project rule into a file the Specifier can read;
  `benchmark/contamination_check.py::check_seal_config` goes red if one becomes reachable.

## Claude Code notes

- Seed a subagent with the PRIMARY, never your summary — hand it verbatim via
  `git show <rev>:<path>` where it moved. Subagents have caught orchestrator paraphrase.
- `/code-review ultra` (branch or PR#) is user-triggered and billed; never run it.
- `/compass-contam` (a command) works the backlog; `compass-prose` (a skill, invoked via
  the Skill tool) sets the rules for prose addressed to a person
  (`.claude/skills/compass-prose/SKILL.md`).
- A slash command carries no task list, state or count — backlog `TASKS.md`, ordering the
  operator's. Never restore `/compass-build`: it pinned a stale count (`a02eda7`).
- Temporary files go in the session scratchpad, never `/tmp` directly — parallel jobs
  share `/tmp` and clobber each other.
- A `-k` selector silently narrows a seeded-failure check: `-k gate` matched 2 of 8 new
  gate tests and reported a mutation as undetected. Seed against the whole file.
- A `build.py` mutation is invisible to tests that read `build/dictionary.json`. Re-run
  the build between seeding and testing, and rebuild after reverting. (Training machine
  only: `raw/` and `build/` are withheld from the public tree.)
- `git worktree` checkouts under `.claude/` on the training machine are inside the repo, so
  `ruff check .` walked them and double-counted every error. Excluded in `pyproject.toml`;
  leave it excluded even though the public tree holds no worktrees.

## Critical anchors

Preserve these three pointers if all else is lost; the rules are stated only in
`AGENTS.md`.

1. §Hard Constraints: the `agent/schema.py` docstring rule.
2. §Hard Constraints: the `env/` network ban and the participant-data rule.
3. §Testing Patterns: the same-commit test rule.
