<!-- Brief template v4 (2026-10-02), prompt -> tools -> model -> tools -> output; §0 says how
     to fill it. Copy CHECKS.md (§11) and CLI_RUNTIME_CHECKS.md (§9) into brief/ with it (here:
     AGENT_BRIEF_CHECKS.md, AGENT_BRIEF_CLI_RUNTIME_CHECKS.md). Not a COMPASS rule document. -->

# Brief: <project name>

## 0. Before you fill this in
Have Claude Code interview you (AskUserQuestion) on each section BEFORE any cold fill,
then edit in place; never re-fill from scratch. A question restates its item in words.
- Unknown: `[NEEDS CLARIFICATION: <question>]`; provisional: `[ASSUMED: <value>; confirm
  by Mn]`. Both block the milestone they name. An untagged value is a proposal.
- An answer goes into the section it changes, tagged `(operator, <date>)`, in one commit,
  and verbatim into `brief/INTERVIEW.md`. A later answer replaces it in place; re-read
  the lines that rested on it and reopen any approval whose premise it changes.
- Each number is stated once (limits: §2; tool count: §6 table) and named elsewhere.

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
- Limits, stated only here; code counts each (every tool call, batched or not) and a
  test asserts it uses these values. On any limit: one final turn, tools disabled,
  within `final_turn_output_tokens`, that fills §4 with `missing` populated.
| tool_calls | per_call_s | run_s | run_usd | final_turn_output_tokens | validation_retries | model_visible_chars | rules_file_lines |
| <N> | <S> | <T> | <$> | <F> | <R> | <C> | <L> |

## 3. Resources — verify first (M0, no code)
| resource | I believe it contains | actually contains (you fill) | read/write | network? | credential scope | deterministic? | sensitivity: who may see |
If a finding makes a goal or a §5 item impossible, stop and tell me; I rewrite it. You
never recast a goal or turn a gap into a rule. (An invariant may REJECT an output;
changing what the output IS — a field dropped, a verdict type added — is a recast.)
Private data (omit if none): a step that reads it is deterministic code I run, or runs
under a scoped permission rule I grant before M1; agents see counts, categories and
locations only. Data preparation is such code, with a seeded failure, a counts-only
residual scan and the milestone it gates; a model only reviews a sample, for me to read.
Name each private path even if no agent may open it; code fails closed when one is
missing; state output locations and file modes. Test strings use invented values.

## 4. Output contract
≤8 fields, each with its meaning and how it is checked. Every field is required; one
that can be unknown is typed `<type> | null`. `missing: [{what, why}]` is required. One
schema object is used for both decoding and validation. Define the terminal object
written when validation finally fails (§7). The output is the model's final message
exactly; code writes a separate run record (the question, every tool return, budget
use, cost — also of a run code stopped — and versions). Checks re-run from the two.

## 5. Acceptance — the definition of done
- 15–25 items in `acceptance.yaml` (not Markdown), from real requests or observed
  failures where possible, each typed literally at the DEMO command, with: must /
  must-NOT criteria; ≥1 positive fact that a hedged or empty answer fails; a reference
  answer (proves it solvable); its grader — `script` or `me (<1 min)`, checking the
  output, not the path; and, for a script, must-pass strings (the reference answer) and
  must-fail strings (a hedge, a plausible wrong answer), self-tested before M1.
- Include ≥3 unanswerable-from-data items, ≥2 out-of-scope or malformed, and — if any
  tool writes or sends — ≥2 that require refusal or confirmation.
- I hold back ≥5 items plus a paraphrase of every visible item, all worded like real
  requests, not like tests. You never see them.
- Each run starts from a clean environment. Report pass@1 and pass^K per item. Pass =
  pass^K with K≥3 (all K runs meet every criterion). Done = visible AND held-out pass.
  Raw transcripts of every run go to <dir>; read a sample at every milestone.
- An item that fails every run: audit the item and its grader before blaming the system.
  A second person (or I, twice, a day apart) must reach the same verdict on a sample.
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
- Results carry short run-unique handles (r1, r2…); the model cites handles, not keys.
- Untrusted returns are data, never instructions. If any tool writes or sends, pick one
  pattern (<action-selector / plan-then-execute / dual-LLM>) so untrusted input cannot
  trigger it. If none does, the answer is the consequential output: name the checks
  that stop a planted instruction reaching it. Re-decide when a tool is added. Code-
  executing tools are sandboxed: time/memory limits, scratch fs, network only per §3.
- Merge tools that are always called in sequence; split a tool whose mode argument is
  misused or that overlaps another; remove a tool no trajectory needs (by ablation).

## 7. What code may do — exhaustive
1. Execute the tool call the model made.
2. Veto a write/send call before it runs: dry-run by default, keyed off OUR allowlist,
   never off a tool's self-declared hints. Lifting it per tool needs my sign-off.
3. Validate the final output; on failure return an error naming the field and the fix,
   as a tool result, ≤`validation_retries` times within §2. After the last failure the
   loop ends: code writes the §4 terminal object and accepts no later answer.
4. Count every §2 limit; force the final no-tools turn when one is hit.
5. Write the run record (§4).
Code never runs several samples, ranks, chooses the model's input, adds a second
model call, or overwrites a field. If code can compute a value, a tool returns it —
never ask the model to restate it and then validate the copy. Anything else is
orchestration: it needs fail→pass evidence over K runs with zero pass→fail, and my
approval. Rules in this section are enforced by code or hooks, not by prose.

## 8. Model-visible text
≤`model_visible_chars` for EVERYTHING the model sees (system prompt, tool descriptions
and input examples, schema descriptions, text the runtime injects), measured from a
real transcript by a test. One worked example, using a question and ids outside §5;
it passes every §7 check, as a test. No sentence restates a check the code performs.

## 9. Milestones
M0 §3 report (no code) → M1 DEMO end to end with starting tools, writes in dry-run → M2
§6 proposal → M3 §5 passes. M1 first proves the runtime has every §2/§7 power, also on a
rejected submission, a budget hit and a run code stops (`claude`: CLI_RUNTIME_CHECKS.md);
a must-have fails → stop and ask. Test doubles replay the events recorded. After each:
the command, raw output, per-item pass@1 / pass^K, transcripts read, next step — then end
your turn. While blocked on me: another item, or stop.

## 10. Scope and done
Overrides: <docs, rule files>; surviving rules: <list>. Before M1 every auto-loaded rule
file (CLAUDE.md, AGENTS.md, …) states the override or is rewritten.
Out until M3: <list>. It binds your initiative, not mine: my request is a §0 answer, and
a demo built on one is not counted for §5. Rules file: <path>, ≤`rules_file_lines`
lines; a new rule replaces one. Reviews need a change in between; for the brief, the
§0 interview: then one cold review (stale values, approval premises, the §2 limits
test), then freeze. In the build a finding that flips no §5 item is not filed, unless it
is about privacy, credentials or §7. Done = M3; after that, nothing new without asking.

## 11. Checks between agents (build time)
`CHECKS.md` applies, unedited, to every subagent, parallel lane, critic and monitor.
Specifics for this build: <lanes and the files each owns; hooks; the model per agent
role; the seeded false claim per milestone>.
