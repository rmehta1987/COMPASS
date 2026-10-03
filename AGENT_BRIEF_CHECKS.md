<!-- Companion to the agent brief template (v4, 2026-10-02): the build-time checks that
     were its §11 in v3, moved here unchanged so a brief's §11 holds only what is
     specific to its build. Copied into brief/ as CHECKS.md and applied unedited. -->

# Checks between agents (build time)
Applies to every subagent, parallel lane, critic and monitor.
- A report is a file with status ∈ {completed, failed, rejected, input_required};
  "rejected" is a legal answer. The orchestrator passes the file's path, never a
  summary of it.
- Every claim carries its evidence: the command, its verbatim output, file@sha.
  A number without its command is rejected unread.
- The orchestrator re-derives claims in a fresh context that has not seen the report,
  and re-runs ≥1 numeric claim per report before relaying anything.
- Critics get the diff and the criteria, not the builder's reasoning; they must run
  tools, not only read; they flag only correctness or requirement gaps (the rest is
  marked optional); use a different model family where available.
- Disputes are settled by running the check, never by debate rounds.
- "Agent X / step Y caused it" is a hypothesis until reproduced or bisected.
- Verifiers and monitors miss most problems: silence means untested, not clean.
  Plant a known false claim now and then as a positive control; a verifier's green
  counts only after it has caught a seeded failure.
- Parallel lanes: every file belongs to exactly one lane; after a merge, re-measure
  every number and threshold — a clean git merge proves nothing about them.
- Hard rules are hooks (PreToolUse deny; SubagentStop runs the checks and blocks on
  red), not prose. Every hook override is logged.
- Each failure is tagged with its category (specification / inter-agent /
  verification) in the changelog, so a recurring class is visible.
