#!/usr/bin/env bash
# check.sh — the Ralph loop's gate. Green means every step below passed; it does
# NOT mean contamination is covered: contamination_check, input_leakage,
# scorability and tier_gate import benchmark/prevalence_key.py, which lives only
# on the scoring-key branch and is unreachable in this single-branch clone by
# design. Those run in item 15 phase 2, in the scoring clone. See STATE.md.
#
# Every threshold is READ from the module that owns it (tests/test_dictionary.py,
# tests/test_code_standards.py); nothing here may be widened to pass. Cheap steps
# run first so a red tree is reported in seconds; the smoke test (~80 s) is last.
set -u
cd "$(dirname "$0")"
PY=./.venv/bin/python
OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT
fail() { echo; echo "RED at step $1: $2"; exit 1; }

# 0. the generation clone must not be able to see the answer key
if git show scoring-key:benchmark/prevalence_key.py >/dev/null 2>&1; then
    fail 0 "scoring-key is reachable in this clone; every artefact here is void"
fi
[ -f benchmark/prevalence_key.py ] && fail 0 "benchmark/prevalence_key.py is in the tree"

# 1. dictionary: build.py runs checks.py itself; hash must equal the pin
PIN=$($PY -c "from tests.test_dictionary import BUILD_HASH; print(BUILD_HASH)")
BUILT=$($PY build.py | head -1) || fail 1 "build.py failed"
echo "$BUILT"
case "$BUILT" in *"$PIN"*) ;; *) fail 1 "dictionary hash moved off $PIN" ;; esac

# 2. tests, never piped (a pipe would return tail's exit code).
#    --ignore: one path per file that imports a scorer at module level.
#    --deselect: one node id per test that imports the key inside its body.
#    Never --continue-on-collection-errors: it would hide a real import break.
$PY -m pytest tests/ -q -p no:cacheprovider \
    --ignore=tests/test_contamination_surface.py \
    --ignore=tests/test_input_leakage.py \
    --ignore=tests/test_scorability.py \
    --ignore=tests/test_tier_gate.py \
    --deselect tests/test_catalogue.py::test_no_index_position_reads_as_a_withheld_figure \
    --deselect tests/test_specifier.py::test_contamination_check_passes_offline \
    --deselect tests/test_specifier.py::test_the_check_actually_catches_a_planted_leak \
    --deselect tests/test_specifier.py::test_the_refusal_prompt_and_schema_carry_no_study_content \
    >"$OUT" 2>&1
RC=$?
tail -1 "$OUT"
[ "$RC" -eq 0 ] || { tail -15 "$OUT"; fail 2 "pytest exit $RC"; }

# 3/4. lint and type ceilings, read from the test module, compared on "Found N"
count() { grep -E "^Found [0-9]+ error" | awk '{print $2}'; }
RUFF_CEIL=$($PY -c "from tests.test_code_standards import RUFF_CEILING; print(RUFF_CEILING)")
MYPY_CEIL=$($PY -c "from tests.test_code_standards import MYPY_CEILING; print(MYPY_CEILING)")
RUFF_N=$(./.venv/bin/ruff check . 2>&1 | count); RUFF_N=${RUFF_N:-0}
MYPY_N=$(./.venv/bin/mypy 2>&1 | count);        MYPY_N=${MYPY_N:-0}
echo "ruff $RUFF_N <= $RUFF_CEIL ; mypy $MYPY_N <= $MYPY_CEIL"
[ "$RUFF_N" -le "$RUFF_CEIL" ] || fail 3 "ruff $RUFF_N > $RUFF_CEIL"
[ "$MYPY_N" -le "$MYPY_CEIL" ] || fail 4 "mypy $MYPY_N > $MYPY_CEIL"

# 5. retrieval gate (AGENTS.md verify list); its ratchets live in tests, this must exit 0
$PY -m benchmark.retrieval_eval >"$OUT" 2>&1 || { tail -5 "$OUT"; fail 5 "benchmark.retrieval_eval"; }
echo "retrieval_eval ok"

# 6. the adapter reproduces the shipped arm through the pipeline's own call
#    path: 224 positives through pipeline.retrieve(), R@1 must equal the
#    expectation read from deploy/smoke_test.py (not restated anywhere).
$PY -m pipeline.retrieve --reproduce >"$OUT" 2>&1 \
    || { grep -v "Loading weights" "$OUT" | tail -5; fail 6 "pipeline.retrieve --reproduce"; }
grep "R@1" "$OUT"

# 7. canaries C1-C3 (pipeline/canary.py): current behaviour on a resolving
#    chronic-condition request, five absent constructs, and the household-vs-
#    neighbourhood income conflation that must stay visible.
$PY -m pipeline.canary >"$OUT" 2>&1 \
    || { grep -v "Loading weights" "$OUT"; fail 7 "pipeline.canary"; }
grep "canaries:" "$OUT"

# 8. auto intake (pipeline/auto_intake.py): the worked pair resolves on both
#    sides, and the worked-example frame's both-resolved count holds its floor.
$PY -m pipeline.auto_intake --pair m3:Q16.1 m2:Q5.8 --frame >"$OUT" 2>&1 \
    || { grep -v "Loading weights" "$OUT"; fail 8 "pipeline.auto_intake"; }
grep -E "^(pair|frame)" "$OUT"

# 9. estimability gate (pipeline/gate.py) on the worked frame: without the
#    flag zero pairs pass and both missing exports are named; with it every
#    pair passes marked blocked_no_metadata. Both runs must agree.
$PY -m pipeline.gate >"$OUT" 2>&1 || { cat "$OUT"; fail 9 "pipeline.gate (blocking)"; }
grep -E "^(gate|missing)" "$OUT"
$PY -m pipeline.gate --allow-unestimable >"$OUT" 2>&1 \
    || { cat "$OUT"; fail 9 "pipeline.gate --allow-unestimable"; }
grep -E "^(gate|passed)" "$OUT"

# 10. retrieval tripwire, last because slow: frozen and validated, a pipeline
#     change is never the fix. Exact R@1, min_cos and 43/44 negatives.
$PY deploy/smoke_test.py >"$OUT" 2>&1 || { tail -5 "$OUT"; fail 10 "deploy/smoke_test.py"; }
echo "smoke_test ALL PASS"

echo; echo "GREEN"
