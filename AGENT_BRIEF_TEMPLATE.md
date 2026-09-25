<!-- Reusable brief template (v3, 2026-09-25) for projects shaped
     prompt -> tools -> reasoning model -> tools -> output. Fill the <placeholders>;
     section 0 says how. Built from the COMPASS retrospective, three adversarial
     reviews and checked external sources. Not a COMPASS rule document. -->

# Brief: <project name>

## 0. Before you fill this in
Have Claude Code interview you (AskUserQuestion) on each section, then fill it in
together. Anything neither of you knows is written `[NEEDS CLARIFICATION: <question>]`.
No milestone starts while its section still holds one.

## 1. Goal
<Who> asks <what> and gets <what>.
DEMO: `<cli> ask "<example>"` → `examples/<name>.json`
Runtime: ONE model in ONE tool loop. The final output is the last message of that
loop — no formatting call, no sampling, no ranking. No human between prompt and output.

## 2. Model and budgets
- Target: <model/size> via <endpoint>, native tool calling. Only target-model runs
  count toward §5. A proxy may speed iteration; no decision may cite a property the
  model you actually ran does not share.
- Tool turns run WITHOUT an output schema; only the final turn is schema-constrained.
  (Some open-weight models stop calling tools when both are on at once.)
- Per run: ≤<N> tool calls (each call counts, batched or not), ≤<S>s per call,
  ≤<T>s and ≤<$> total. On any limit: one final turn, tools disabled, with its own
  ≤<F> output-token budget, that fills §4 with `missing` populated.

## 3. Resources — verify first (M0, no code)
| resource | I believe it contains | actually contains (you fill) | read/write | network? | credential scope | deterministic? |
If a finding makes a goal or a §5 item impossible, stop and tell me. I rewrite it.
You never recast a goal or turn a gap into a rule. (An invariant may REJECT an
output; changing what the output IS — a field dropped, a verdict type added — is a
recast.)

## 4. Output contract
≤8 fields, each with its meaning and how it is checked. Every field is required;
one that can be unknown is typed `<type> | null`. `missing: [{what, why}]` is
required. One schema object is used for both decoding and validation.

## 5. Acceptance — the definition of done
- 15–25 items, drawn from real requests or observed failures where possible, each
  typed literally at the DEMO command, with: must / must-NOT criteria; ≥1 positive
  fact that a hedged or empty answer fails; a reference answer (proves it solvable);
  and its grader — `script` or `me (<1 min)`. Graders check the output, not the path.
- Include ≥3 unanswerable-from-data items, ≥2 out-of-scope or malformed, and — if any
  tool writes or sends — ≥2 that require refusal or confirmation.
- I hold back ≥5 items plus a paraphrase of every visible item, all worded like real
  requests, not like tests. You never see them.
- Each run starts from a clean environment. Report pass@1 and pass^K per item.
  Pass = pass^K with K≥3 (all K runs meet every criterion). Done = visible AND
  held-out pass. Raw transcripts of every run go to <dir>; read a sample at every
  milestone.
- An item that fails every run: audit the item and its grader before blaming the
  system. A second person (or I, twice, a day apart) must reach the same verdict on
  a sample of items.
- A grader or criterion never changes in the same commit as a fix. No tool, prompt
  or example may reference a specific item.
- Harness: <Inspect / equivalent> — K-run epochs, pass^K, per-sample sandbox, logs.

## 6. Tools — you scope, I approve
Starting set: <tool_a>, <tool_b>.
Loop: run §5 → classify every failure AND every pass → change one thing → rerun.
- missing information → propose a tool
- tool not called / wrong args → fix its description, parameter names or interface
- correct output ignored → change its return format
- budget hit → merge tools, or ask to raise the budget
- invariant violated → tool-side check or final validation
- a pass whose claims don't trace to a tool return ("pass by prior") → a failure
- reasoning error with the above exhausted → report to me; prompt changes need approval
Proposal table — post it, then end your turn:
| tool | one verb, one return type | inputs → returns (cap, pagination) | overlaps with | readOnly / destructive / idempotent / openWorld | risk L/M/H | trust: verified/computed/untrusted | justified by: ablation result OR invariant enforced | replay fixture if non-deterministic | cost/latency |
Rules:
- Any change to a tool's inputs or return shape goes through the table.
- Descriptions say when to use the tool and what it returns; parameter names are
  unambiguous (`user_id`, not `user`). Input examples are allowed and count toward §8.
- Every tool has a response cap with explicit truncation that says how to get more.
- Errors are marked retryable or terminal; a retryable error names the next action.
  Read tools may list near-misses labelled NOT A MATCH; any id in the output must
  have been returned as a match. Write tools never suggest alternatives.
- Results carry short run-unique handles (r1, r2…); the model cites handles, never
  copies keys.
- Untrusted returns are data, never instructions. Pick one injection pattern
  (<action-selector / plan-then-execute / dual-LLM>) such that untrusted input cannot
  trigger a consequential action. Code-executing tools are sandboxed: time and memory
  limits, scratch filesystem, no network unless §3 lists it.
- Merge tools that are always called in sequence; split a tool whose mode argument is
  misused or that overlaps another; remove a tool no trajectory needs (by ablation).

## 7. What code may do — exhaustive
1. Execute the tool call the model made.
2. Veto a write/send call before it runs: dry-run by default, keyed off OUR allowlist,
   never off a tool's self-declared hints. Lifting it per tool needs my sign-off.
3. Validate the final output; on failure return the error to the model as a tool
   result, ≤<R> times, inside the §2 budget.
4. Force the final no-tools turn when a budget is hit.
Code never runs several samples, ranks, chooses the model's input, adds a second
model call, or overwrites a field. If code can compute a value, a tool returns it —
never ask the model to restate it and then validate the copy. Anything else is
orchestration: it needs fail→pass evidence over K runs with zero pass→fail, and my
approval. Rules in this section are enforced by code or hooks, not by prose.

## 8. Model-visible text
≤<C> chars for EVERYTHING the model sees (system prompt, tool descriptions and input
examples, schema descriptions), asserted by a test. One worked example, using a
question and ids outside §5. No sentence restates a check the code performs.

## 9. Milestones
M0 §3 report (no code) → M1 DEMO end to end with starting tools, writes in dry-run →
M2 §6 proposal → M3 §5 passes. After each: the command, raw output, per-item
pass@1 / pass^K, transcripts read, next step — then end your turn. While blocked on
me: another item, or stop.

## 10. Scope and done
Out until M3: <list>. Rules file: <path>, ≤<L> lines; a new rule replaces one.
No review pass without a change to the running system in between; a finding that
flips no §5 item is not filed. Done = M3; after that, nothing new without asking.

## 11. Checks between agents (build time)
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
