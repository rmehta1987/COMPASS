# ADR 003 — Selection by index, not by transcribed key

Status: accepted, 2026-09-01

## Problem

The resolver rendered each candidate as one line and explained in prose how to
read it:

```
m2:1_Q16.8#1_3 [roster row 1] | Was this sibling ever diagnosed with any ...
of the following types of cancer? ... - 1 - Breast cancer  (module 2; asked
of each of 20 roster members)
```

Measured on GQ012, `searched` arm, one row, three model tiers:

- The rule said the key is the text before the first ` | `. On the 1,520 roster
  entries that is the key **plus** the tag `env/labels.py::_roster_tag` appends.
  `claude-haiku-4-5` returned `m2:1_Q16.8#1_3 [roster row 1]` — copied exactly
  as instructed — and scored `malformed` on a verdict whose reasoning was right.
- The replacement fixed where a key *starts* and never said where a wording
  *ends*. `claude-opus-5` returned four keys whose wording carried the trailing
  fact clause, and scored `malformed` on the same row, again with the verdict
  and reasoning right. `claude-sonnet-5` guessed both boundaries correctly.

Three models read one delimiter rule three ways. These were parse failures, not
reasoning failures. Prose describing a delimited format *is* a parser
specification, and every ambiguity in it is a defect that presents as a model
error.

## Decision

Candidates are typed records. The model selects by integer index; the harness
resolves the index to a key. `key` and `wording` are separate fields, so there
are no delimiters to disagree about and the failure class is unrepresentable
rather than discouraged.

Corollaries:

- Keys are withheld from the production prompt (`render(debug=True)` shows them
  for auditing). Nothing to copy means nothing to copy wrongly.
- Derived facts such as `roster_family_size` are read by the harness via
  `facts_for`, never returned by the model. Asking a model to copy an integer it
  was handed reintroduces the same failure at smaller scale.
- An out-of-range index raises rather than clamps: it means the model selected
  something not offered, which is a result to record.

## Prior art

Four comparable systems read at source, commit-pinned, 2026-08-30. Attribution
in `references/PRIOR_ART_CONTAMINATION.md`; the mechanisms:

1. Renders its entire catalogue — tools, data items, libraries; 55,234
   characters at its pinned commit — into one prompt and asks for **indices**,
   parsed with a regex. Its registry has no search or rank method. Selection by
   index is the part worth taking.
2. Walks a fixed corpus in contiguous slices, 15 items per call, keeping 3, at
   temperature 0.0 — the screener shape for a frozen local corpus.
3. Runs query rewrite, fetch, index, abstention gates, cited answer. The working
   shape for a literature tool.
4. Calls its agents with an empty retrieval field on the first iteration and
   retrieves per hypothesis afterwards.

## Where we diverge

System 1 instructs its model *against* abstention — include a resource rather
than exclude it when in doubt — and none of the four returns a per-hit score or
thresholds a retrieval path. COMPASS cannot copy either posture. Its measured
failure runs the opposite way: on the 2026-09-01 run, all four requests the
codebook cannot pin down were answered with one confident item — 5 false
positives in 21 rows.

So `refusal` is a required field of every contract, and it must name a value the
output schema can actually produce. Never a downstream text heuristic: system 3
gates abstention with a length test, a substring test and a second length test,
two of them inside a pinned dependency rather than its own tree. A refusal only
a grep can see is one an output schema cannot guarantee.

## Deferred surfaces

Neither is implemented, and neither is represented in code — a placeholder whose
`render()` raises is a design doc that runs validation.

**Literature.** No `search_literature` tool exists in
`agent/registry.py::build_registry`, and `prior_work` is a field of
`agent/schema.py::SelectionRationale` that nothing populates. Agreed shape:
system 3's pipeline, with two constraints — abstention gates as schema values,
not text heuristics; and a frozen local corpus rather than live search, since a
live source changes what the benchmark measures between runs.

Ordering is already settled and not reopened: retrieval runs *after*
transduction, as annotation into `selection_rationale.prior_work`. This is
system 4's ordering.

**Specifier.** Does not render through `prompt_contract` by design.
`agent/specifier.py::PromptTemplate` derives its variable list from its own body
via the `string.Formatter` that renders it, and `AGENTS.md` §Hard Constraints
forbids a second list of a prompt's variables. A contract re-declaring them
would be that second list.

Its refusal is model-shaped rather than value-shaped: `ProtocolSpecification`
holds no literal field, and a run that cannot specify emits `NotSpecifiable` —
a different type down a different branch in `_emit`. If a second model-shaped
refusal ever appears, reintroduce the `Refusal(kind, name)` record then. One
instance does not justify the type.
