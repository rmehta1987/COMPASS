# Pointing the Specifier at real weights

**Two backends exist, and they are not interchangeable in practice yet.**
`agent/cli_backend.py:ClaudeCliBackend` drives Claude via the headless CLI and
is what `generate/live_specifier.py` actually calls today — that is the
pipeline's current live path; see HANDOFF_AGENT_PIPELINE.md §2, §4b and T2 for
its status, and run it with:

```bash
./.venv/bin/python generate/live_specifier.py [k] [model]     # e.g. k=1 claude-haiku-4-5
```

This document is about the *other* backend: `agent/backends.py:OpenAICompatBackend`,
for Gemma 4 or Qwen3 8-27B behind an OpenAI-compatible server (vLLM, or
llama.cpp/GBNF) — the actual target the two-call design and the format-tax
rationale below are built for. It is unit-tested end-to-end against
`ScriptedBackend` (see `tests/test_specifier.py`), and `agent/backends.py:from_env()`
reads `COMPASS_LLM_MODEL` / `COMPASS_LLM_URL` and returns it — but **no driver
script calls `from_env()` yet.** Setting those environment variables and running
`generate/live_specifier.py` today has no effect: that script always constructs
`ClaudeCliBackend`, ignoring both variables. Wiring a `--backend` switch (or an
equivalent) into a live driver is open work for whoever next touches
`agent/specifier.py`'s callers — out of this document's scope, and out of
Lane C's file set at the time this was last edited.

Nothing in this repo has been run end-to-end against a served OpenAI-compatible
model. No API keys were set and ports 8000, 8080, 11434 and 1234 were all closed
at authoring time. What has been proven is the control flow; what has not been
proven is the model's judgment, or the two server-dependent choices below.

## Start a server

```bash
vllm serve Qwen/Qwen3-14B \
  --port 8000 \
  --guided-decoding-backend xgrammar \
  --max-model-len 16384 \
  --enable-auto-tool-choice --tool-call-parser hermes    # Qwen3
# Gemma 4: --tool-call-parser pythonic

export COMPASS_LLM_MODEL=Qwen/Qwen3-14B
export COMPASS_LLM_URL=http://localhost:8000/v1
```

## Two settings that must be confirmed on first contact

| setting | why it can differ | how to tell |
|---|---|---|
| `enforce=` | older vLLM takes `guided_json` in the extra body; newer takes `response_format: json_schema` | a 400 naming the field. Try `guided_json` first, then `response_format`. It never silently falls back — see `test_backend_refuses_to_degrade_to_prompted_json` |
| tool-call parser | Qwen3 emits Hermes-style, Gemma emits pythonic | `Reply.tool_calls` empty while `content` holds a call means the parser is wrong |

## Two consequences of this model choice

INHERITED (HANDOFF_AGENT_PIPELINE.md §7, not re-verified this session):

**Qwen3 publishes no knowledge cutoff.** Tier B in the benchmark is defined as
"first public after the model's stated cutoff." With no stated cutoff no Tier B is
constructible, and all eight benchmark papers collapse to Tier C. This is not a
tuning problem — it is a property of the model card, and much of Qwen3's 36T
tokens are synthetic Qwen2.5 output, so even an inferred date would not be
defensible. Gemma 3 published one (Aug 2024); Gemma 4's must be read off its card
before any Tier B claim is made.

**If both families are available, put the Reviewer on the other one.** Same-family
Specifier/Reviewer pairs carry +0.076 excess error agreement, and a judge inflates
the scores of models that share its mistakes.

## Why two calls and not one

INHERITED (HANDOFF_AGENT_PIPELINE.md §7, not re-verified this session): this size
class loses 4–10 points of combined reasoning-and-formatting quality in a single
constrained pass. Guided decoding alone costs about 1.6 points of reasoning while
lifting parse validity from 55.7% to 92.2%. Prompted JSON with no grammar was
malformed 30–40% of the time on a 7B. So the reasoning call is unconstrained and
the transduction call is constrained, and
`test_only_the_transduction_call_is_schema_constrained` fails if anyone merges them.

**A run against a frontier Claude model is NOT evidence about this size class**
(HANDOFF §7): there is no grammar enforcement through the Claude CLI, and the
format tax that motivates the two-call design does not bite a frontier model.
Never report a `ClaudeCliBackend` run as evidence for Qwen3 or Gemma; this vLLM
path is how that claim actually gets tested.

## First real run — once a driver wires up `OpenAICompatBackend`

```bash
export COMPASS_LLM_MODEL=Qwen/Qwen3-14B
export COMPASS_LLM_URL=http://localhost:8000/v1
./.venv/bin/python -c "from agent.backends import from_env; print(from_env().name)"
```

confirms the environment variables resolve to a backend; there is currently no
end-to-end driver beyond that. Once one exists, check, in this order: did the
model call `resolve_variable` before naming keys; did it quote wording verbatim;
did it invent an `n`; did it write an inline derivation recipe; did anything land
in `undetermined`. An empty `undetermined` list across many pairs is a warning
sign, not a success — it means the model is not abstaining.
