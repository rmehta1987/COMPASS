# Brief — derivation provenance, build half (compass-gen)

Run in `/home/mehta5/compass-gen`, branch `ralph-loop`. The verification half is
`BRIEF_derivation_source_score.md` and runs in the scoring clone; you cannot do it here.

Scope: **items 1 and 2 only.** Items 3-4 (the propose path) are a user amendment and are
recorded in `TASKS.md` as C28; do not build them. Cite `path::symbol`, never line numbers.

## 0. What you cannot verify here

`benchmark.contamination_check` **cannot run in this clone**: it fails at import with
`ModuleNotFoundError: No module named 'benchmark.prevalence_key'`, raised from
`benchmark/input_leakage.py` at module level. The key lives on the orphan branch
`scoring-key`, which this single-branch clone must never fetch. Items 1-2 edit that
module. Exercise the changed rule in a scratch script if you like, but report that AS a
standalone exercise, never as having run the check.

`tests/test_specifier.py::test_contamination_check_passes_offline` asserts
`check_provenance()` is empty. `check.sh` deselects it by node id, so it stays green here.
**Land items 1 and 2 as ONE commit** so no commit is ever red in the scoring clone.

Re-run `./check.sh` before starting. At handoff: `1125 passed, 4 deselected`,
`ruff 226 <= 232`, `mypy 59 <= 59`, `smoke_test ALL PASS`, GREEN.

## 1. Add a fourth `ALLOWED_SOURCES` value

`benchmark/contamination_check.py::ALLOWED_SOURCES` is
`{"study-team", "instrument-derived", "authored-unconfirmed"}`. `SOURCE_RE` accepts
`[a-z-]+`, so a hyphenated value is already legal.

Add `prior-art`, and state in the code comment exactly what it asserts: that the
CONSTRUCT or SCALE is taken from a named external work. It asserts nothing about the
binding of that work to instrument keys, nothing about response coding, and nothing about
study-team confirmation.

That distinction is load-bearing, because both existing files bind an external construct
to instrument keys in ways the cited work does not supply:

* `curated/derivations/met_hours_week.json` cites Ainsworth for MET values; its
  seasonally-weighted sum over the activity battery is authored, not Ainsworth's.
* `curated/derivations/social_cohesion_scale.json` cites Sampson for a five-item scale;
  its own `caveat` says the direction must be confirmed by the study team.

Set `source` on both. If you conclude `prior-art` would drop the word "unconfirmed" from
something the study team has not confirmed, STOP and report instead of relabelling.

Both files carry `author: "R. Mehta"`. Decide and state in the commit message what
`author` means beside `prior-art`; do not silently leave a human's name on a file
relabelled as needing no human authorship.

🛑 **Do not touch `component_keys`, `unit` or `recipe` on either file.**
`met_hours_week.json` declares two component keys while its recipe says ten activities and
its caveat says thirty items. That inconsistency is KNOWN and PINNED by
`tests/test_schema.py::test_a_derivation_ref_that_contradicts_its_signed_file_is_rejected`,
which asserts a thirty-key reference is rejected against the file's declared two.
"Fixing" it breaks that test, changes what `DerivationRef` accepts, and moves
`benchmark/calibration_set.py::_signed_component_sets`.

`ALLOWED_SOURCES` also governs `curated/conventions/*.md`, all six of which declare
`authored-unconfirmed`. Confirm you have not made a previously-illegal convention source
legal by accident.

## 2. Require `source` on derivations

`benchmark/contamination_check.py::check_provenance` has two loops: conventions are
checked for `**Source:**` against `ALLOWED_SOURCES`; derivations are checked only for
`construct_validity_basis` (non-empty) and `fitted_to_outcome` (falsy). Add the `source`
requirement to the derivations loop, against the same set. Update that function's
docstring, which currently speaks only of conventions.

Fail hard, do not grandfather: `AGENTS.md` §Testing Patterns prefers a red that names a
defect. With item 1 done, every file passes.

**Do not use `signed` for provenance.** `agent/schema.py::_signed_derivations` loads every
`*.json` regardless of it; `agent/schema.py::DerivationRef::_matches_the_signature_it_names`
validates only `component_keys` and `unit`. Its one value-reader is
`tests/test_contamination_surface.py::_traces_to_a_signed_derivation`, where it WIDENS a
contamination exemption. It records permissiveness, not provenance.

**Report, do not silently fix:** `env/tools.py::list_derivations` reports every file in
the directory as signed regardless of the flag. A `signed is True` rule in
`check_provenance` would be a benchmark-side alarm only; the serving path is
`env/tools.py` (Lane B) and `agent/schema.py::_signed_derivations` (Lane A). Decide
whether the alarm is in scope for this brief, say which, and name the lane if you propose
more.

### Test shape — required, or you turn the gate red

* **In-body import** of `benchmark.contamination_check`, never module level. A
  module-level import breaks COLLECTION of the test file, and `check.sh` step 2 forbids
  `--continue-on-collection-errors`, so the gate goes RED.
* **Seed against a `tmp_path` root**, never by writing a bad file into the real
  `curated/derivations/`. That directory is inside `tests/test_contamination_surface.py::SCANNED`
  and a planted file enters the model-visible surface. `check_provenance` reads a
  module-global `ROOT` and takes no path argument, so parameterise it or monkeypatch.
* **Seed BOTH ways** — a missing `source`, and a value outside the set. Absence-only
  detection is half a check.
* **Add the new node id to `check.sh`'s deselect list.** `check.sh` is assigned to no lane
  in `AGENTS.md` §Parallel Lanes; assign it before editing.
* Red/green for this test is observed in the scoring clone, not here. Say so.

## 3. `bmi.json` — decide, do not inherit

An agent-authored BMI derivation was written into `curated/derivations/` during the
session that produced this brief, then removed when `env/tools.py::list_derivations` was
found to report it to the model as one of "3 signed derivations" despite `signed: false`.
No model call ever saw it. It is inlined here because it exists in no clone:

    {
      "derivation_id": "bmi",
      "author": "Claude Opus 5 (pipeline agent), session 2026-09-08",
      "date": "2026-09-08",
      "source": "authored-unconfirmed",
      "signed": false,
      "unit": "kg/m^2",
      "component_keys": [two height items (feet, inches) and the weight item],
      "recipe": "703 * weight_lb / inches^2, where inches = 12 * height_ft + height_in",
      "construct_validity_basis": "Quetelet index, the standard anthropometric
        weight-for-height ratio; 703 converts pounds and inches to kg/m^2",
      "fitted_to_outcome": false,
      "caveat": "Self-reported height and weight, not clinic anthropometry."
    }

"Quetelet index" names an eponym, not a citable work, so item 1's verify-the-citation step
has nothing to verify. Decide explicitly and report: reconstruct it with a citable work
and a `source`, or leave it out until a human signs it. **Do not restore it silently.**
If restored it is an agent authoring a scanned surface and must be named for the scoring
clone's contamination run.

## 4. Contamination

`curated/` is scanned (`tests/test_contamination_surface.py::SCANNED`).
`env/tools.py::get_derivation` returns the WHOLE file, so every field you write is text
the model reads in call 1; `agent/specifier.py::_RESULT_BEARING` projects only a subset
into transduction. `benchmark/contamination_check.py::tool_samples` globs derivation ids,
so a new file is sampled automatically.

🛑 **You must NOT perform the paper-record read.** `benchmark/contamination_check.py`'s
docstring names the residual control as a human re-reading each curated sentence against
the paper record. That is the operator's, not yours. Do not open
`benchmark/cohort_papers.py` rows to check a citation: `AGENTS.md` §Contamination Practice
says an agent reading paper content is itself a channel, because it also authors
`curated/`. Note for the operator that `social_cohesion_scale` deserves that read most,
and stop there.

`benchmark/cohort_papers.py` carries no titles or author names, so grepping it for an
author matches nothing and proves nothing. A previous attempt did exactly that and
reported a false clean.

## 5. Limits

* Do not fetch `scoring-key`; do not create `benchmark/prevalence_key.py`.
* Do not edit `tests/test_contamination_surface.py`'s markers or exemption counts.
* Do not touch `deploy/`, the manifest or `smoke_test.py` — the proof chain is open
  pending a serving-machine run recorded at `6f6508e`.
* Do not change `agent/specifier.py::_rank`. C28 amends it; this brief does not.
* Do not build items 3-4.
* No `git add -A`; check `.git/info/exclude` first.

## 6. Done when

* `ALLOWED_SOURCES` carries `prior-art` with its meaning stated in a comment; both
  existing derivations declare a `source`; conventions unaffected.
* `check_provenance` requires `source` on derivations; its docstring updated; the
  `signed is True` question decided and reported with its lane.
* The new test uses an in-body import and a `tmp_path` root, is seeded both ways, and its
  node id is in `check.sh`.
* Items 1 and 2 are ONE commit.
* `./check.sh` green; test count not fallen; ceilings not raised; the
  `contamination_check` import failure quoted verbatim in your report.
* `bmi.json`'s fate decided in writing.
* Your report states that items 1-2 are MERGE-GATED on a green `contamination_check` in
  the scoring clone, per `BRIEF_derivation_source_score.md`.
