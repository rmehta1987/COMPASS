"""Tests for benchmark/calibration_set.py — C5, the calibration set.

Three things are pinned. First, the row counts and their balance (§5 rule 9:
a guarantee stated in a docstring and enforced nowhere is this codebase's
signature failure, so every size and balance claim the module docstring makes
is re-checked here, not just narrated). Second, that every row's verdict is
RE-DERIVABLE — re-running `_evaluate` independently on a row's own keys must
reproduce its `refusal_reason`, and a sample of rows must match the CURRENT
live return value of the tool named in their own evidence, not a value typed
in when the row was built. Third, the module docstring's two negative claims
about the environment — `access_gate_refused` is unreachable from a bare pair,
and `no_contrast_definable` has no failure path today — are backed here as
live checks, not left as unverified prose.

C4 (wiring the refusal path into the Specifier) is not merged. Nothing here
drives a model or calls agent.specifier; every check is offline, against the
dictionary and the live env.tools functions only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.schema import RefusalReason  # noqa: E402
from benchmark.calibration_set import (  # noqa: E402
    ANSWERABLE_ROWS,
    ROWS_PER_REGISTRY_EMPTY_PREFIX,
    ROWS_PER_UNANSWERABLE_CATEGORY,
    CalibrationPair,
    _empty_registry_prefixes,
    _evaluate,
    build_calibration_set,
    category_counts,
)
from env.tools import (  # noqa: E402
    check_access,
    dictionary_version,
    get_contrast_convention,
)


def test_row_counts_match_the_documented_balance() -> None:
    """Pins the module docstring's SIZE AND BALANCE section exactly.

    Three unanswerable categories at 20 rows each (free_text_anchor,
    anchors_are_the_same_construct, registry_empty), a 60-row answerable control
    arm, 120 total. `registry_empty` is internally 4 prefixes x 5, which sums to
    the same 20 as the other two.

    The control arm is sized 1:1 against the unanswerable rows so that a
    per-category refusal rate and the control's over-refusal rate share a
    denominator. It moved 80 -> 60 with the category count, and that coupling is
    the reason this test pins both numbers rather than only the total.

    `no_signed_derivation` was dropped 2026-08-28 — see
    `benchmark/calibration_set.py::WHY_NO_SIGNED_DERIVATION_WAS_DROPPED`. Its
    pool contained compound-field questions such as "What is your birthday? -
    Month / - Day / - Year", where a refusal citing a missing signed derivation
    would penalise the correct answer.
    """
    pairs = build_calibration_set()
    counts = category_counts(pairs)

    assert counts == {
        "free_text_anchor": ROWS_PER_UNANSWERABLE_CATEGORY,
        "anchors_are_the_same_construct": ROWS_PER_UNANSWERABLE_CATEGORY,
        "registry_empty": ROWS_PER_UNANSWERABLE_CATEGORY,
        "answerable_control": ANSWERABLE_ROWS,
    }
    assert len(pairs) == 120
    # The 1:1 ratio the module docstring argues for: total unanswerable rows
    # equal the control arm, so a refusal rate and an over-refusal rate sit on
    # the same denominator scale.
    unanswerable = sum(n for cat, n in counts.items() if cat != "answerable_control")
    assert unanswerable == counts["answerable_control"]


def test_registry_empty_is_five_rows_per_environment_reported_empty_registry() -> None:
    """`registry_empty`'s internal 4x5 shape, and which four prefixes."""
    prefixes = _empty_registry_prefixes()
    assert set(prefixes) == {"clinical", "ehr", "lab", "linked"}, (
        "registry_coverage() no longer reports the four registries this "
        "module was built against — re-derive the category, do not just "
        "widen this assertion")

    pairs = build_calibration_set()
    registry_rows = [p for p in pairs if p.category == "registry_empty"]
    assert len(registry_rows) == len(prefixes) * ROWS_PER_REGISTRY_EMPTY_PREFIX

    seen_prefixes = set()
    for p in registry_rows:
        prefix = p.exposure_key.split(":", 1)[0]
        if prefix not in prefixes:
            prefix = p.outcome_key.split(":", 1)[0]
        seen_prefixes.add(prefix)
    assert seen_prefixes == set(prefixes)


def test_linked_registry_row_names_the_spec_mismatch_in_its_own_rationale() -> None:
    """`linked` is not in the C5 spec's prose (`clinical:/lab:/ehr:` only).

    A row built for it must say so in its own rationale — the finding lives on
    the row, not only in the module docstring, so a reader checking one row by
    hand sees the judgement call without having to read the source file too.
    """
    pairs = build_calibration_set()
    linked_rows = [p for p in pairs if p.category == "registry_empty"
                   and "linked:" in (p.exposure_key + p.outcome_key)]
    assert linked_rows, "no linked: row was built"
    for row in linked_rows:
        assert "spec text" in row.rationale and "linked" in row.rationale


def test_category_equals_refusal_reason_value_for_every_unanswerable_row() -> None:
    """A row's `category` string and its `refusal_reason.value` must match.

    This is a property `build_calibration_set` relies on internally
    (`_EXPECTED_REASON`); pinned here so a future edit that breaks the
    invariant fails a test, not just an internal assertion nobody re-runs.
    """
    pairs = build_calibration_set()
    for p in pairs:
        if p.category == "answerable_control":
            assert p.refusal_reason is None
            continue
        assert p.refusal_reason is not None
        assert p.category == p.refusal_reason.value


def test_every_unanswerable_verdict_is_independently_re_derivable() -> None:
    """Re-running `_evaluate` on a row's own keys reproduces its verdict.

    This is the "derivable, not asserted" property from first principles: a
    row is not just internally self-consistent (checked at build time by
    `_build_row`), it survives a completely fresh call, exercised here outside
    the cached `build_calibration_set()` result.
    """
    pairs = build_calibration_set()
    for p in pairs:
        verdict = _evaluate(p.exposure_key, p.outcome_key)
        assert verdict.reason is p.refusal_reason, (
            f"{p.pair_id}: cached reason {p.refusal_reason} but a fresh "
            f"_evaluate call says {verdict.reason}")


def test_evidence_matches_the_tools_current_live_return_value() -> None:
    """A sample row's Evidence.value must equal the tool's CURRENT return value.

    Not a string that was merely plausible when the row was built.
    """
    pairs = build_calibration_set()
    by_cat = {}
    for p in pairs:
        by_cat.setdefault(p.category, p)  # first row of each category

    import env.tools as T

    checked = 0
    for row in by_cat.values():
        for ev in row.evidence:
            tool_fn = getattr(T, ev.tool)
            live = tool_fn(ev.argument) if ev.tool != "registry_coverage" \
                and ev.tool != "list_derivations" else tool_fn()
            field_path = ev.field.split(".")
            val: object = live
            for part in field_path:
                val = val[part]
            assert str(val) == ev.value, (
                f"{row.pair_id} evidence {ev.tool}({ev.argument!r}).{ev.field} "
                f"was recorded as {ev.value!r} but the live tool now returns "
                f"{val!r}")
            checked += 1
    assert checked >= len(by_cat), "no evidence was actually checked"


def test_answerable_rows_clear_evaluate_and_check_access() -> None:
    """Every control-arm row clears `_evaluate` AND the live `check_access` gate.

    `check_access` is a fifth gate `_evaluate` does not itself compute.
    """
    pairs = build_calibration_set()
    answerable = [p for p in pairs if p.category == "answerable_control"]
    assert len(answerable) == ANSWERABLE_ROWS
    for p in answerable:
        assert p.refusal_reason is None
        access = check_access([p.exposure_key, p.outcome_key])
        assert access["decision"] == "pass"


def test_no_duplicate_pair_ids_or_duplicate_answerable_pairs() -> None:
    pairs = build_calibration_set()
    ids = [p.pair_id for p in pairs]
    assert len(ids) == len(set(ids)), "pair_id collision"

    answerable = [(p.exposure_key, p.outcome_key) for p in pairs
                 if p.category == "answerable_control"]
    assert len(answerable) == len(set(answerable)), "duplicate answerable pair"


def test_every_row_carries_the_current_dictionary_version() -> None:
    pairs = build_calibration_set()
    version = dictionary_version()
    assert all(p.dictionary_version == version for p in pairs)


def test_access_gate_refused_is_unreachable_from_a_bare_two_key_pair() -> None:
    """Backs the module docstring's claim about `RefusalReason.access_gate_refused`.

    `check_access`'s budget is 3 distinct location-bearing PLACES; a bare pair
    supplies at most 2 keys, so at most 2 places, so `decision` can never be
    `"refer"`. Tried against several real location-bearing keys, not asserted.
    """
    location_bearing = ["m1:Q2.9#1_1", "m1:Q2.9#2_1"]  # residence-ish address items
    for a in location_bearing:
        for b in location_bearing:
            if a == b:
                continue
            access = check_access([a, b])
            assert access["decision"] == "pass", (
                f"check_access([{a!r}, {b!r}]) returned {access['decision']!r} — "
                f"the module docstring's access_gate_refused claim is wrong, "
                f"fix the docstring, not this test")


def test_no_contrast_definable_has_no_failure_path_today() -> None:
    """Backs the module docstring's claim that get_contrast_convention never fails.

    It has no branch that reports "no convention for this kind", so nothing
    can currently entail `RefusalReason.no_contrast_definable`.
    """
    for probe in ("likert", "scale", "binary", "completely_unrecognised_kind",
                 "", "m1:Q3.10"):
        result = get_contrast_convention(probe)
        assert result["outcome"] == "ok", (
            f"get_contrast_convention({probe!r}) returned "
            f"{result['outcome']!r} — a failure path now exists and "
            f"no_contrast_definable may be buildable; update the module "
            f"docstring's claim, do not just loosen this test")


def test_evaluate_rejects_a_key_that_is_in_neither_index() -> None:
    """`_evaluate` only reasons about real dictionary content.

    Module docstring: "NOTHING PAPER-DERIVED... could be built if COMPASS had
    never published anything." A fabricated key must raise, never silently
    resolve.
    """
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _evaluate("m1:Q999.99_invented", "m2:Q5.8")


def test_calibration_pair_is_the_exported_row_type() -> None:
    """Cheap smoke check that build_calibration_set returns the documented type."""
    pairs = build_calibration_set()
    assert all(isinstance(p, CalibrationPair) for p in pairs)
    assert all(p.refusal_reason is None or isinstance(p.refusal_reason, RefusalReason)
              for p in pairs)
