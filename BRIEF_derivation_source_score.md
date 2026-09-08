# Brief — derivation provenance, verification half (compass-score)

Run in `/home/mehta5/compass-score`, branch `ralph-loop`. This is the merge gate for the
work built under `BRIEF_derivation_source_gen.md`. **It is a VERIFICATION brief, not a
build brief.** Do not write pipeline code here.

🛑 **Never generate in this clone.** It can reach the answer key, so any artefact produced
here is void by construction — that is what `check.sh` step 0 exists to catch. No
`pipeline.run`, no `pipeline.pose_terms`, no live specifier calls.

## 0. Why this brief exists

`benchmark.contamination_check` cannot run in the generation clone: it fails at import
with `ModuleNotFoundError: No module named 'benchmark.prevalence_key'`, raised from
`benchmark/input_leakage.py` at module level. `AGENTS.md` §Contamination Practice requires
it after editing a convention, a prompt, an `agent/schema.py` docstring or `env/tools.py`.
Items 1-2 of the gen brief edit `benchmark/contamination_check.py` and
`curated/derivations/`, so they ship MERGE-GATED on this brief passing.

## 1. Bring the clone up to date

`origin/ralph-loop` in this clone is stale — it was at `ef03e96` when this brief was
written, while the remote carried the publication-boundary work at `1f868aa` and the
gen-brief work lands after that.

    git fetch origin ralph-loop
    git checkout ralph-loop && git merge --ff-only origin/ralph-loop

Report the sha you ended on. If the fast-forward refuses, stop and report rather than
merging.

## 2. Restore the two held-out keys into the working tree

They are absent from the working tree and present on the local `scoring-key` ref
(`eb76c849` when this was written). `scoring-key` is NOT on the remote's heads; that local
ref may be the only copy, so do not prune or force-update it.

    git show scoring-key:benchmark/prevalence_key.py > benchmark/prevalence_key.py
    git show scoring-key:benchmark/leak_facts.py     > benchmark/leak_facts.py

Both paths are already listed in `.git/info/exclude`, so they stay untracked. **Verify
that before and after** — `git status --short` must not show either file.

🛑 **Never commit them, never push them, never copy them to another clone.** Do not read
their contents beyond confirming the import works.

## 3. Run the check

    ./.venv/bin/python -m benchmark.contamination_check

Report, in full:

* every section's ok/FAIL line, and the text of any FAIL;
* `surface_hash`, and whether it moved from the value the gen brief's report recorded.
  A moved hash is NOT a failure — `AGENTS.md` §Contamination Practice says it is printed,
  never asserted. It IS something you must EXPLAIN: adding a `source` field to a
  derivation changes what `get_derivation` returns, so the surface is expected to move.
  An unexplained move is the finding.
* the surface size in characters and the number of surfaces.

Read a red section by meaning, per `AGENTS.md`: `every registry tool sampled` = an
unscanned tool return; `markers` / `prevalence figures` / `survey platform` = paper content
is model-reachable; `held-out registry unreachable` = an answer key reached a tool path.

Do NOT run `--live` unless the operator asks. It costs, and it is required before a
benchmark run, not before a merge.

## 4. Run the tests the generation clone cannot

`check.sh` excludes eight things by construction. All of them import the key. Run them
here:

    ./.venv/bin/python -m pytest \
      tests/test_contamination_surface.py tests/test_input_leakage.py \
      tests/test_scorability.py tests/test_tier_gate.py \
      tests/test_catalogue.py::test_no_index_position_reads_as_a_withheld_figure \
      tests/test_specifier.py::test_contamination_check_passes_offline \
      tests/test_specifier.py::test_the_check_actually_catches_a_planted_leak \
      tests/test_specifier.py::test_the_refusal_prompt_and_schema_carry_no_study_content \
      -q -p no:cacheprovider

`test_contamination_check_passes_offline` asserts `check_provenance()` is empty. If items
1 and 2 landed as one commit it passes; if it fails, the gen brief's one-commit rule was
broken and you should say so by name rather than fixing it here.

**Also observe the seeded red/green** for the new `source` test the gen brief adds. It is
deselected in `check.sh` and its red state is only observable here. Run it, confirm it is
green, then confirm it goes red when its seeded condition is restored, and report both.
Revert the seed and `rm -rf __pycache__` after — a block move fools `.pyc`.

## 5. Report back

* the sha verified, and the two key files' presence confirmed by import, not by `ls`;
* the full contamination-check output, `surface_hash` and its explanation;
* the pytest result for §4;
* the seeded red/green for the new test;
* a one-line verdict: MERGE-GATE PASSED or the named failure.

## 6. Limits

* No generation of any kind. No `--live` without the operator asking.
* Do not commit, do not push, do not create a branch.
* Do not copy `benchmark/prevalence_key.py` or `benchmark/leak_facts.py` anywhere.
* Do not edit `tests/test_contamination_surface.py`'s markers or exemption counts.
* Do not fix a failure you find in the gen work — name it and stop. The fix belongs in
  the generation clone, where its `check.sh` can see it.
* You are not the operator.
