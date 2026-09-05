# Authoring the paper inventory

This is the README for `benchmark/paper_inventory_key.py` on the `scoring-key`
branch. Copy it there beside the key. The schema it describes is
`benchmark/paper_inventory.py` on the working branch; the key must import from
it and validate against it.

## What it is

One `PaperInventory` per paper in `benchmark/cohort_papers.py`: every variable
the published analysis used, resolved to instrument keys, with the design and
the reported direction. It is the answer key for the **specification** benchmark:
given a paper's exposure and outcome, does the pipeline recover the covariates
the authors adjusted for, the design, and the direction. It is not used for
**discovery**, which stays with `benchmark/prevalence_key.py` and the funnel
baseline, and the two are never pooled.

## Who writes it

A person, reading the paper, on `scoring-key`, never on the working branch. An
agent that reads paper content to author a key also writes prompts and curated
text in the same clone, and is therefore a leak channel. Do not delegate this.

## The covariate boundary has moved; say so here

`prevalence_key.py` keeps its 9 covariate rows out of evidence, because a
covariate a paper adjusted for is not the paper's finding. That reasoning is
right for contamination, and it is exactly why those rows are safe to score
against: they say nothing about what the paper found, only what it controlled
for. This inventory makes the adjustment set the answer key on purpose. A
hypothesis is scored on whether it adjusted for what the paper adjusted for. It
is still never scored on the paper's result, and no result, prevalence, effect
size or sample figure belongs in this file.

## Start from the template

```
python -c "from benchmark.paper_inventory import template; print(template())" > benchmark/paper_inventory_key.py
```

Replace the synthetic paper. One `PaperInventory` per pmid; every pmid must be
in `cohort_papers.py`; no pmid twice.

## Per variable

| field | what to write |
|---|---|
| `role` | `exposure`, `outcome` or `covariate`, matching the tuple it sits in |
| `label` | the paper's own name for the variable, verbatim, so a reader can check you |
| `key` | the instrument variable key, or `None` |
| `in_instrument` | `False` when the questionnaire does not hold the variable at all |
| `absent_reason` | required when `in_instrument=False`: where it lives instead, e.g. `linked spatial measure`, `clinic measurement` |
| `resolution` | `verified`, `found_by_search`, or `absent` (see below) |
| `confident` | `False` if you could not pin the variable to one key |
| `covariate_role` | optional, covariates only: the role the paper gave it, in the pipeline's `CausalRole` vocabulary |

**Every covariate the paper adjusted for goes in**, including the ones the
instrument lacks. A paper the pipeline *cannot* reproduce because the variable
is absent is a different result from one it *failed* to reproduce, and this file
is the only place that distinction can live.

## `resolution`: verify with the tools, never find with them

Two uses of the environment's tools look alike and are not:

| use | verdict | write |
|---|---|---|
| `resolve_variable(key)` to check a key you already have exists and names a variable, not a stem | fine | `resolution="verified"` |
| `search_variables(term)` to find which key the paper's variable is | circular: retriever error enters the answer key and the pipeline is then scored against its own mistakes | `resolution="found_by_search"`, `confident=False` |

The harness excludes `found_by_search` and `confident=False` rows from scoring
and reports how many it excluded. A key partly authored by the retriever cannot
measure the retriever. If you must search to orient yourself, do it, then find
the key by reading the codebook, and record `verified` only when you did.

Run the checks before committing:

```
python -c "
from benchmark.paper_inventory import load_inventory, validate_against_dictionary
from env.tools import resolve_variable
inv = load_inventory()
print(validate_against_dictionary(inv, resolve_variable) or 'every key names a variable')"
```

A key that names a group or a construct fails: a protocol may never name a stem.

## Per paper

| field | what to write |
|---|---|
| `design` | one of `cross-sectional`, `prospective`, `repeated-measures`, `nested case-control`, `case-control`, `other` |
| `direction` | the reported direction of the exposure-outcome association: `increase`, `decrease`, `no_difference`, `non_monotonic`; `mixed` when the paper's pairs disagree, with the per-pair directions in `notes` |
| `notes` | subgroup restrictions, ambiguous definitions, anything a scorer should know |
| `read_on` | the date you read the paper |

Direction is the paper's reported association, not a judgement about harm.

## Before anyone adopts design or direction agreement

Print the degeneracy report and put it in the key's commit message:

```
python -c "from benchmark.paper_inventory import load_inventory, degeneracy; print(degeneracy(load_inventory()).model_dump())"
```

If one design covers every paper, design agreement is not a metric and the
harness drops it. The direction majority is the base rate agreement is reported
against. A metric whose base rate is not published beside it is not reported.

## What the harness then does with it

```
python -c "from benchmark.paper_inventory import load_inventory, posed_pairs; import json; [print(json.dumps(r)) for r in posed_pairs(load_inventory())]" > run/posed.jsonl
```

Only that file, keys and pmids, travels to the generation clone for
`pipeline.pose`. The labels never leave this branch. Scoring runs in the scoring
clone with `benchmark.specification_score`, which reports covariate recall and
precision per paper and pooled, the same for the modal covariate set, the margin
between them, design and direction agreement with their base rates, the rows it
excluded, the papers it could not reproduce, and n on every figure.
