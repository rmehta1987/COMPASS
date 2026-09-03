---
name: compass-prose
description: Write the answer as scientific prose for COMPASS's human readers — mechanism before jargon, evidence attached, every claim tagged ran / per the handoff / UNVERIFIED, no cohort-paper content into the environment
argument-hint: <the request>
disable-model-invocation: true
---

$ARGUMENTS

Write the answer as scientific prose for a human reader. These rules stay active for the
rest of this session, and they govern ONLY prose addressed to a person: chat answers,
write-ups, verdicts, summaries, emails, paragraphs for a talk or grant.

They do NOT apply to: code or docstrings (`AGENTS.md` §Code Standards governs those, and
`agent/schema.py` docstrings are prompt text); anything under `curated/` or any prompt
(model-visible surfaces with their own rules); edits to `AGENTS.md` or `DESIGN.md` (their
legend is VERIFIED / INHERITED — never the chat tags below); commit messages;
or the per-item acceptance record `/compass-build` asks for — criterion, command, real
output, `surface_hash` — which is pasted verbatim, no gloss, no added commentary.

## Who is reading

COMPASS documents are read by the PI and cohort study team (epidemiology, survey
methods) and by the agent/LLM side (tool calling, benchmarks, contamination). A term
from either side may be borrowed vocabulary to the other, and a reader assumes a
borrowed word means what it means in THEIR field. Gloss a borrowed term once per
document at first use, or drop it. Identifiers that are also code (`surface_hash`,
`seal_hash`, `linked:`, a question id like `m2:Q5.8`) are named, not defined.

## Rules

- **Mechanism first, name second.** Explain what is happening in plain words, then name
  it. If a term appears before the thing it names has been explained, it is doing no work.
- **Say what a number means before what it is.** "None of the 2,804 dictionary entries
  says how its answers are coded" lands; "0/2,804 carry `value_labels`" needs that
  sentence first.
- **Quote primaries verbatim with location** — `AGENTS.md §Section` / `DESIGN.md §N`, the built dictionary (`build/dictionary.json` key), code (`path::symbol`), a
  study-team message (date). Never paraphrase a load-bearing claim: a paraphrase hides
  whether the source was opened and drifts on every retelling.
- **Tag every quantitative or status claim.** To me, `/compass-build`'s two states:
  **ran** (this session — show the command and its real output) or **per the handoff**
  (repeated, not re-run). Anything else is **UNVERIFIED**, which is a reason to stop and
  check, not a licence to proceed. **cited** (source + location) is for external prior
  work only, never for this project's own results. This binds throwaway estimates
  ("~2 h", "~3x") as much as results — an untagged guess propagates into the handoff and
  becomes an oracle.
- **Scope limit and the single strongest objection go in the headline paragraph** —
  which modules, which pairs, which n, what the result does NOT cover, and the one thing
  that would most change the conclusion. Do not add a closing caveats section.
- **"Could not detect X" is never "X is absent."** That step needs a positive control.
  Without one, the word is *untested*. The marker scan printing clean is the standing
  example: it catches quotation, not paraphrase, so "clean" is not "uncontaminated".
- **Distinguish what a source argues from what was measured here.** Cite prior work as
  prior work; do not cite this project's inconclusive runs as support for it.
- **No hedging register.** "It may be that a confound could be operative" is evasion.
  Caution is: "we could not detect it, and here is why that is not the same as absence."

## The contamination boundary (overrides the quoting rule)

The verbatim-quote rule is for the handoff, the instrument, code and study-team sources.
It is NOT for the cohort's published papers. Prose written under this skill can be
copied into `curated/`, `env/`, an `agent/` docstring or a prompt — the surfaces
`tests/test_contamination_surface.py::SCANNED` and `benchmark.contamination_check`
cover — so:

- Never quote OR paraphrase a paper's design choice — exposure–outcome pairing,
  adjustment set, model form, realised analytic n — into any of those surfaces.
  Instrument metadata sourced from the study team is allowed there; paper content is not.
- Handoff §3's paper table, `benchmark/cohort_papers.py`, the T5 lane report, and
  any memory file naming scorable PMIDs are paper content wearing project clothing:
  quote them to me only, never into a surface, and never label them "per the handoff"
  as if that made them safe.
- If the prose you are asked for needs a paper's design (e.g. a scorability summary for
  me), write it, and say in the same paragraph that it is user-facing only.
- After any edit to those surfaces, run `./.venv/bin/python -m benchmark.contamination_check`
  and report `surface_hash`, whether or not `/compass-build` is loaded.

## Self-check

If the mechanism cannot be stated in plain words, say so — that is a finding about the
work, not a formatting problem.
