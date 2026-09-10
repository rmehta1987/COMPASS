# The discovery ceiling under the variable inventory

Pre-registered. Every rule below was written and committed before the code that
computes a number under it, so the rules could not be bent to fit a number that
already existed. Nothing here reads the inventory: this branch holds no
`inventory/`, and the only inventory exercised in this clone is the synthetic
fixture `tests/fake_tiered_inventory.json`.

## Why the ceiling is what needs fixing

The discovery baseline `b3-20260904` scored 0 matches with a ceiling of 0, so it
measured nothing about hypothesis quality. `benchmark/baseline_score.py` builds
its per-paper table in `load_key_table` from two sources that were never meant
to be a variable inventory:

* the outcome side reads `benchmark/scorability.py::outcome_keys_on_record`,
  which draws on a PREVALENCE key. A prevalence key records what a paper
  reported, not what the analysis measured, and it names an outcome key for a
  minority of the bibliography.
* the exposure side splits a prose design line into fragments in
  `benchmark/scorability.py::exposure_terms` and hands each to the deployed
  retriever in `baseline_score.resolve_exposures`. Under that rule a retriever
  MISS and a genuine ABSENCE are indistinguishable: both produce no key.
  `scorability.EXPOSURE_KEYS` is empty by design and stays empty; its form is
  the user's decision (`TASKS.md` C12) and this document does not reopen it.

The per-paper variable inventory that C12 calls for exists already, authored by
a person on the key side. This document fixes what a number computed against it
will mean, before that number exists.

## Rule 1 — two ceilings, side by side, never pooled

The report carries both, each on its own line, each with its denominator:

| line | what it bounds |
|---|---|
| `ceiling_under_prevalence_key` | today's rule, unchanged: an outcome key on record AND an exposure term the retriever resolved |
| `ceiling_under_inventory` | the rule in §Rule 2 below |
| `papers_matchable_and_in_frame` | papers matchable under Rule 2 whose construct pair the run's frame actually contained |

There is no third, combined figure. The two ceilings are never averaged,
summed, maximised over, or described by one sentence: they are computed from
different key sources and a reader who pools them has invented a rule nobody
registered.

**`papers_matchable_and_in_frame` is the only line the observed rate may be
compared to.** A paper the run could never have reached bounds nothing. The
report says this in words, beside the numbers, not only here.

## Rule 2 — the match rule under the inventory

A record matches paper P when BOTH sides hold:

* **outcome.** The record's outcome variable, a folded member of its retrieval
  target, or its construct — the set `baseline_score.keys_of` returns — meets
  one of P's `outcomes[].key` on a row whose `status == "present"` and whose
  `confident == true`.
* **exposure.** The same, against P's `exposures[].key`, on a row whose
  `status == "present"` and whose `confident == true`.

Both sides are folded to the CONSTRUCT before they are compared, through the
index in §Rule 4. The inventory names a VARIABLE key and a run resolves a term
to a CONSTRUCT, so comparing the two as strings scores a correct resolution as
a miss: the fixture's own note records that trap. Folding means a paper's
member key meets a record that resolved to the construct holding it, a paper's
construct key meets a record that resolved to a member of it, and a paper's
member key meets a record that resolved to a DIFFERENT member of the same
construct. The third follows from the first two and is stated because it does
not read as obvious: the comparison is construct equality, and the pipeline
generates at construct level throughout — `generate/funnel.py` enumerates
construct pairs, and `baseline_score.keys_of` already folds a record's target
to its whole member set. Matching at any finer grain would compare a
construct-level hypothesis against a variable-level key. A key the
built dictionary does not hold folds to nothing, matches nothing, and is
COUNTED as unresolvable rather than passed over.

`modality` rows NEVER match. An analogue is a different measurement of the same
construct, not the same measurement (`TIER_STATE.md`, the note on tier B), so a
record that adjusts the self-report analogue of a measured exposure is not a
rediscovery of the paper that measured it. `analogue_key` is not read by the
match rule at all.

A consequence, stated here rather than discovered later: a paper reachable on
both sides only through analogues is UNMATCHABLE under this rule. It is not
binned into a tier that would flatter it, and the report says which papers this
covers by count. That is the tier-B question `TIER_STATE.md` leaves open for the
operator; this rule does not settle it, it declares which side of it the number
falls on.

## Rule 3 — `confident == false` is excluded and counted

A row with `confident == false` is excluded from matching and COUNTED, per side,
in the report. It is never silently dropped. This is the discipline
`benchmark/tiered_score.py::covariate_exclusions` already applies to covariates,
applied to the two anchor sides.

An excluded side is reported as `excluded_sides`, split by reason, so a paper
that fell out because a human reader was unsure is distinguishable from a paper
whose variable the instrument does not carry.

## Rule 4 — the frame test

A paper is IN FRAME when both of its confident present keys resolve, through the
dictionary index the funnel itself uses, to a construct pair that
`generate/funnel.py::s2_prune` leaves live for the frame the scored run was
generated from.

* the key-to-construct fold is `pipeline/pose.py::construct_index` over
  `generate/funnel.py::load_constructs`, the same index the posed-pair driver
  and `benchmark/tiered_score.py` use. Comparing a variable key against a
  construct key as strings scores a correct resolution as a miss.
* the live pairs are ENUMERATED, by `python -m pipeline.run <id> --frame-only`
  against the same frame definition the run used. Never a hand-typed list of
  pairs: a hand list drifts from the funnel silently and cannot be re-derived.
* the frame is an INPUT to the scorer, not something it invents. Where the
  caller supplies none, the in-frame count is reported as UNKNOWN, never as 0 —
  "could not enumerate the frame" is not "no paper was in it".

## What this cannot settle

* **Whether the frame should contain published pairs at all.** `TASKS.md` C13
  says to prune published pairs from the generation frame once C12 lands;
  `DESIGN.md` §6 says a published pair is the only scorable kind. If C13 is
  applied to the discovery frame, `ceiling_under_inventory` is zero by
  construction, and discovery must either be retired as a metric or given a
  frame chosen on purpose. That is the operator's decision. This document only
  makes `papers_matchable_and_in_frame` visible, so the decision is made against
  a number instead of an intuition.
* **The reliability of the inventory itself.** It was authored by one reader.
  Nothing here estimates how often a second reader, given the same paper and the
  same codebook, would name the same key or the same status. That estimate is a
  separate operator-driven task in the scoring clone; until it exists, every
  figure computed under Rule 2 inherits an unmeasured author-agreement term.
* **Anything about the contamination verdict or its marker set.** That is
  `benchmark/contamination_check` policy, re-run per `AGENTS.md`, not this
  document's.

## What this document does not author

This document does not author, extend or correct the inventory.
`benchmark/PAPER_INVENTORY_GUIDE.md` §Who writes it: a person, on the key side,
never an agent. Where a rule above needs a row the inventory does not carry, the
work stops and says so rather than inferring the row.

## The operator's run

Not run here, and not runnable here: the inventory and the answer key are on the
scoring side, and this clone bars both by design. What follows is the exact
command sequence, with two corrections to the form it was first written in. Both
were found by checking the command against the code rather than by reading it.

```bash
cd /home/mehta5/compass-score
git fetch origin ralph-loop && git checkout fd6c4a1
python -m benchmark.contamination_check --live

# The harness scores exactly the ledger's EMITTED set and refuses any other
# set of paths. Derive it from the ledger; never a shell glob.
RUN=artefacts/b3-20260904
EMITTED=$(python -c "
from pathlib import Path
from pipeline import ledger as L
d = Path('$RUN')
print(' '.join(str(d / r.artefact)
               for r in L.read_rows(d / L.LEDGER_NAME)
               if r.outcome == 'emitted' and r.artefact))")

python -m benchmark.baseline_score $EMITTED \
    --sha 703a1779c8bad8c1e6a829a24bf2bdc15361f3c9 \
    --inventory inventory/ --harness handoff/for_harness.json \
    --out $RUN/BASELINE_inventory.md
```

`fd6c4a1` is the last commit that changed code under this brief, at the time
this paragraph was written. It is a floor, not a pin: later work on
`ralph-loop` is fine and the tip of the branch is the right thing to score.
Check with `git log --oneline -1 origin/ralph-loop` and use that, and re-read
this section if it has moved -- a sha written into prose goes stale the moment
the next commit lands, which is what happened to the first draft of this line.

### Correction 1: the report path must not end in `.json`

`baseline_score.main` writes the markdown to `--out` and then writes the JSON to
the same path with a `.json` suffix. Given `--out …/BASELINE_inventory.json`
those are the SAME path: the report is written, overwritten a line later, and
the operator ends up with JSON, no report, and no error. The CLI now refuses
that path at argument-parsing time, before a retriever is loaded or a live
contamination check has run. Name the report `.md`; the JSON takes the same
stem automatically, so `BASELINE_inventory.json` is still what appears beside
it.

### Correction 2: the emitted set, never a glob

`m2q*.json` matches every artefact the run wrote, emitted and discarded alike;
the ledger's emitted set is a strict subset of it. `load_artefacts` refuses a
path set that is not exactly the emitted set, so the glob form does not
silently score the wrong denominator -- it stops. The command above derives the
set from the ledger, which is also what `STATE.md` item 15d records for the
first baseline run.

### Two new flags, and what they do not change

`--inventory` and `--harness` are given together or not at all. `--harness` is
never defaulted: a harness guessed at is a pin that checks nothing. Without both
flags the CLI behaves exactly as it did before this brief -- one ceiling, from
the prevalence key and the retriever -- and the prevalence-key ceiling is
byte-identical with the flags or without them on the same inputs, pinned in
`tests/test_baseline_score.py`.

### After the run

The operator re-derives every number in the output before it is quoted
anywhere. The site's `metrics.json` is rebuilt from `BASELINE.md` by
`site/tools/build_metrics.py` in the site clone, and is never edited by hand.

## The second reading

The reliability term named in §What this cannot settle is estimated by a second
reader, blind, in the scoring clone, driven by the operator. That procedure is
`BRIEF_inventory_discovery.md` task S; it is not run by the loop and not run
here. Its report goes through `benchmark/inventory_key.py::agreement`, which
lands with this work so that the second reading and the ceiling above share one
fold and one schema pin.

`agreement` reports three quantities per side, with n on each and never pooled
into one percentage: status agreement over the labels both readers listed, key
agreement over the labels both called present, and the variables one reader
listed and the other did not. It joins on the LABEL, because joining on the key
would compare only the rows that already agree. It decides nothing: every
disagreement is a row for the operator to adjudicate by reading the paper, and
only the operator moves a row into `inventory/`.
