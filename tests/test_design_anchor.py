"""Pins for `benchmark/design_anchor.py` — the design key's shape and validator.

C36. Every test here is KEY-FREE and runs in this clone, which is the point of
splitting the shape out of the withheld `benchmark/design_key.py`:
`tests/test_withheld.py::GUARD_CEILING` fires on ADDING a guarded test, so a
claim about the anchor type that could only be checked where the rows live
would be coverage leaving the clone where the code is written.

The terms in the fixtures below are NOT any paper's. `term` is load-bearing in
production and deliberately meaningless here: a test fixture carrying a real
design-line phrase beside a real pmid would put a published pairing in
`tests/`, which no holdout covers.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark import design_anchor as da  # noqa: E402
from benchmark.cohort_papers import COHORT_PAPERS  # noqa: E402

#: A real pmid, so the validator's "unknown pmid" branch is the only thing
#: under test when one is wrong. Read from the bibliography, never typed.
PMID = COHORT_PAPERS[0].pmid

#: A neutral phrase. Not a design line.
TERM = "a phrase"


def _resolving_key() -> str:
    """A key `resolve_variable` calls `unique`, found live rather than assumed.

    Returns:
        One resolving instrument key.
    """
    from env.tools import resolve_variable
    for key in ("m2:Q5.8", "m2:Q5.2", "m3:Q16.1_1", "m2:Q9.117"):
        if resolve_variable(key)["outcome"] == da.RESOLVED:
            return key
    pytest.skip("no resolving key found to test with")


def _construct_key() -> str:
    """A KEY_PATTERN-shaped key that resolves to a stem, not a variable.

    Returns:
        One group or construct key.
    """
    from env.tools import resolve_variable
    for key in ("m1:Q2.2", "m2:Q5.15", "m1:Q6.2"):
        if resolve_variable(key)["outcome"] in ("group", "construct"):
            return key
    pytest.skip("no construct/group key found to test with")


def _row(exposure: tuple[da.Anchor, ...], outcome: tuple[da.Anchor, ...],
         pmid: str = PMID) -> da.DesignKeyRow:
    """A well-formed row apart from what a caller varies.

    Args:
        exposure: Exposure-side anchors.
        outcome: Outcome-side anchors.
        pmid: PubMed identifier.

    Returns:
        One row.
    """
    return da.DesignKeyRow(pmid=pmid, exposure=exposure, outcome=outcome,
                           provenance="fixture", filled_by="test")


# --------------------------------------------------------------------------- #
# the vocabulary
# --------------------------------------------------------------------------- #


def test_the_kinds_are_the_schemas_ref_discriminator_plus_one() -> None:
    """A key recording a `Ref` kind the schema lost is another benchmark's key.

    Read off `agent/schema.py` by parsing, not by importing the models and
    inspecting pydantic internals: the assertion is about the discriminator
    values the source declares, and an `Annotated` union's runtime shape has
    changed across pydantic versions before.
    """
    src = (ROOT / "agent" / "schema.py").read_text()
    tree = ast.parse(src)
    declared: set[str] = set()
    for node in ast.walk(tree):
        # `kind: Literal["variable"] = "variable"` — the discriminator, as each
        # Ref member declares it.
        if (isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "kind"
                and isinstance(node.annotation, ast.Subscript)):
            for const in ast.walk(node.annotation):
                if isinstance(const, ast.Constant) and isinstance(
                        const.value, str):
                    declared.add(const.value)
    assert declared, (
        "no `kind: Literal[...]` found in agent/schema.py. The Ref "
        "discriminator moved, and this test is now blind.")
    assert set(da.SCHEMA_KINDS) == declared, (
        f"anchor kinds borrowed from the schema are {sorted(da.SCHEMA_KINDS)}; "
        f"agent/schema.py::Ref declares {sorted(declared)}. An anchor kind "
        f"with no Ref to match records an exposure no protocol can express.")


def test_the_extra_kind_records_a_refutation_and_not_a_ref() -> None:
    """`not_in_instrument` has no schema counterpart, on purpose."""
    assert da.NOT_IN_INSTRUMENT in da.ANCHOR_KINDS
    assert da.NOT_IN_INSTRUMENT not in da.SCHEMA_KINDS, (
        "the schema has no way to name a thing that is not there, so this "
        "kind must not be expected to match a Ref member")
    assert set(da.ANCHOR_KINDS) == set(da.SCHEMA_KINDS) | {
        da.NOT_IN_INSTRUMENT}, (
        "ANCHOR_KINDS gained a member that is neither a Ref kind nor the "
        "refutation. Say which resolver it selects, or drop it.")


# --------------------------------------------------------------------------- #
# __post_init__, fail-closed, one seeded illegal combination at a time
# --------------------------------------------------------------------------- #


def test_the_legal_combinations_are_constructible() -> None:
    """Anti-vacuity. A validator that rejects everything pins nothing."""
    assert da.Anchor(TERM, da.VARIABLE, key="m2:Q5.8").key == "m2:Q5.8"
    assert da.Anchor(TERM, da.DERIVATION, key="met_hours_week").kind == (
        da.DERIVATION)
    blocked = da.Anchor(TERM, da.AREA_MEASURE,
                        blocked_on=da.AREA_MEASURE_INVENTORY)
    assert blocked.key is None and blocked.blocked_on
    absent = da.Anchor(TERM, da.NOT_IN_INSTRUMENT)
    assert absent.key is None and absent.blocked_on is None


@pytest.mark.parametrize("kind", [da.VARIABLE, da.DERIVATION])
def test_a_resolvable_kind_without_a_key_is_refused(kind: str) -> None:
    """Its key is the whole of its evidence, so a blank one asserts nothing."""
    with pytest.raises(ValueError, match="no key"):
        da.Anchor(TERM, kind)
    with pytest.raises(ValueError, match="no key"):
        da.Anchor(TERM, kind, key="")


@pytest.mark.parametrize("kind", [da.VARIABLE, da.DERIVATION])
def test_a_resolvable_kind_cannot_also_be_blocked(kind: str) -> None:
    """A key that resolves is not waiting on a delivery; both is incoherent."""
    with pytest.raises(ValueError, match="both a key and a blocker"):
        da.Anchor(TERM, kind, key="m2:Q5.8",
                  blocked_on=da.AREA_MEASURE_INVENTORY)


def test_an_area_measure_with_neither_key_nor_blocker_is_refused() -> None:
    """C35 answer C is explicit out-of-scope, not a blank cell."""
    with pytest.raises(ValueError, match="neither a key nor a blocker"):
        da.Anchor(TERM, da.AREA_MEASURE)


def test_a_refutation_names_nothing_to_resolve_or_wait_for() -> None:
    """`not_in_instrument` forbids both fields.

    There is no lookup to make and no delivery to wait for.
    """
    with pytest.raises(ValueError, match="names a key or a blocker"):
        da.Anchor(TERM, da.NOT_IN_INSTRUMENT, key="m2:Q5.8")
    with pytest.raises(ValueError, match="names a key or a blocker"):
        da.Anchor(TERM, da.NOT_IN_INSTRUMENT,
                  blocked_on=da.AREA_MEASURE_INVENTORY)


def test_an_unknown_kind_is_refused_because_nothing_resolves_it() -> None:
    """The `Literal` is a type-checker claim; this is the runtime one.

    `mypy` cannot see a row the operator pastes, and a dataclass does not
    enforce its own annotations.
    """
    with pytest.raises(ValueError, match="not an anchor kind"):
        da.Anchor(TERM, "linked_measure", key="linked:x")  # type: ignore[arg-type]


def test_an_anchor_with_no_term_is_refused() -> None:
    """The term is what makes a key checkable against the side it was filed on.

    Without it, PMID 38715087's covariate key and an outcome key are the same
    object — which is the failure this file's module docstring records.
    """
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="no term"):
            da.Anchor(blank, da.VARIABLE, key="m2:Q5.8")


def test_an_anchor_cannot_be_mutated_after_construction() -> None:
    """Frozen, so the checks above cannot be bypassed by assignment."""
    anchor = da.Anchor(TERM, da.NOT_IN_INSTRUMENT)
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError
        anchor.key = "m2:Q5.8"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# the validator, over a fixture table
# --------------------------------------------------------------------------- #


def test_a_well_formed_table_produces_no_complaints() -> None:
    """Anti-vacuity for the validator.

    Uses the same live resolution the production criterion does.
    """
    good = _row((da.Anchor(TERM, da.VARIABLE, key=_resolving_key()),),
                (da.Anchor("another phrase", da.NOT_IN_INSTRUMENT),))
    assert da.validate_design_key((good,)) == []


def test_an_empty_table_is_not_a_complaint_and_is_not_a_row() -> None:
    """Nothing asserted is nothing wrong.

    A caller wanting to know whether any row exists must count rows.
    """
    assert da.validate_design_key(()) == []


def test_an_unknown_pmid_is_named() -> None:
    """A typo'd pmid would otherwise sit in the table doing nothing."""
    row = _row((da.Anchor(TERM, da.NOT_IN_INSTRUMENT),),
               (da.Anchor(TERM, da.NOT_IN_INSTRUMENT),), pmid="00000000")
    assert any("not a pmid" in c for c in da.validate_design_key((row,)))


def test_two_rows_for_one_paper_are_refused() -> None:
    """The strongest objection to a second answer key, made checkable.

    Two rows that can disagree about one paper's design is worse than one row
    with a blank side, and nothing picks between them.
    """
    row = _row((da.Anchor(TERM, da.NOT_IN_INSTRUMENT),),
               (da.Anchor(TERM, da.NOT_IN_INSTRUMENT),))
    problems = da.validate_design_key((row, row))
    assert any("a second row for one paper" in c for c in problems), problems


@pytest.mark.parametrize("side", ["exposure", "outcome"])
def test_an_empty_side_is_a_row_that_asserts_nothing(side: str) -> None:
    """Both sides, because the exposure column's old type only had one."""
    filled = (da.Anchor(TERM, da.NOT_IN_INSTRUMENT),)
    row = _row(() if side == "exposure" else filled,
               () if side == "outcome" else filled)
    problems = da.validate_design_key((row,))
    assert any(f"empty {side} tuple" in c for c in problems), problems


def test_a_repeated_key_on_one_side_is_named() -> None:
    """One key twice is one piece of evidence counted twice."""
    key = _resolving_key()
    row = _row((da.Anchor(TERM, da.VARIABLE, key=key),
                da.Anchor("second phrase", da.VARIABLE, key=key)),
               (da.Anchor(TERM, da.NOT_IN_INSTRUMENT),))
    assert any("repeats a key" in c for c in da.validate_design_key((row,)))


def test_one_term_may_carry_several_keys() -> None:
    """The operator's decided depression row, as a shape claim.

    38961645's design line says "depression" unqualified and the questionnaire
    splits that construct across two labels, so two anchors share one term and
    name different keys. A validator that refused repeated terms made the
    decided row unrepresentable -- the same failure as the bare key tuple this
    table replaces, where the type could not express the settled form.
    """
    from env.tools import resolve_variable
    pair = [k for k in ("m2:Q5.15#1_15", "m2:Q5.15#1_37", "m2:Q5.8", "m2:Q5.2")
            if resolve_variable(k)["outcome"] == da.RESOLVED][:2]
    if len(pair) < 2:
        pytest.skip("need two resolving keys to test one term carrying both")
    row = _row((da.Anchor("other", da.NOT_IN_INSTRUMENT),),
               (da.Anchor(TERM, da.VARIABLE, key=pair[0]),
                da.Anchor(TERM, da.VARIABLE, key=pair[1])))
    assert da.validate_design_key((row,)) == []


def test_a_missing_provenance_or_filler_is_named() -> None:
    """A key nobody can recheck is an assertion, not a key.

    An unattributed row also hides which rows are not the operator's.
    """
    anchors = (da.Anchor(TERM, da.NOT_IN_INSTRUMENT),)
    blank = da.DesignKeyRow(PMID, anchors, anchors, provenance=" ",
                            filled_by="")
    problems = da.validate_design_key((blank,))
    assert any("no provenance" in c for c in problems), problems
    assert any("no filled_by" in c for c in problems), problems


# --------------------------------------------------------------------------- #
# one check per kind, which is what `kind` buys over a bare key string
# --------------------------------------------------------------------------- #


def test_a_variable_key_of_the_wrong_shape_is_named() -> None:
    """KEY_PATTERN is checked before the live lookup.

    So the complaint names which of the two problems it is.
    """
    row = _row((da.Anchor(TERM, da.VARIABLE, key="not a key"),),
               (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    problems = da.validate_design_key((row,))
    assert any("is not a variable key" in c for c in problems), problems


def test_a_variable_key_naming_a_stem_is_refused_live() -> None:
    """The check reads `resolve_variable`'s actual return, not the key's shape.

    A group id is a stem a protocol may never name, so an anchor on one points
    at a question nobody can answer.
    """
    row = _row((da.Anchor(TERM, da.VARIABLE, key=_construct_key()),),
               (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    problems = da.validate_design_key((row,))
    assert any("not 'unique'" in c for c in problems), problems


def test_a_derivation_anchor_is_checked_against_the_signed_file() -> None:
    """`kind` selects the resolver, and a derivation's is `get_derivation`.

    A bare key string would have been sent to `resolve_variable` instead.
    """
    bad = _row((da.Anchor(TERM, da.DERIVATION, key="no_such_derivation"),),
               (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    problems = da.validate_design_key((bad,))
    assert any("no signed derivation" in c for c in problems), problems

    from env.tools import get_derivation
    signed = next((d for d in ("met_hours_week", "social_cohesion_scale")
                   if get_derivation(d)["outcome"] == da.DERIVATION_OK), None)
    if signed is None:
        pytest.skip("no signed derivation in this tree to test the pass half")
    good = _row((da.Anchor(TERM, da.DERIVATION, key=signed),),
                (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    assert da.validate_design_key((good,)) == []


def test_an_area_measure_carrying_a_key_is_refused_as_answer_d() -> None:
    """C35 answer D, refused by name.

    No authority resolves an area measure, so a key here asserts exactly as
    much as the word test did.
    """
    row = _row((da.Anchor(TERM, da.AREA_MEASURE, key="linked:some_index"),),
               (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    problems = da.validate_design_key((row,))
    assert any("C35 answer D is forbidden" in c for c in problems), problems


def test_a_blocked_area_measure_and_a_refutation_need_no_resolver() -> None:
    """The two kinds with no live check must not be complained about."""
    row = _row((da.Anchor(TERM, da.AREA_MEASURE,
                          blocked_on=da.AREA_MEASURE_INVENTORY),),
               (da.Anchor("other", da.NOT_IN_INSTRUMENT),))
    assert da.validate_design_key((row,)) == []


# --------------------------------------------------------------------------- #
# the holdout, driven rather than grepped
# --------------------------------------------------------------------------- #


def test_the_holdout_check_catches_a_copy_of_the_design_key(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A copy of the design key on a globbed tool path must be caught.

    `tests/test_scorability.py` pins its equivalent by asserting a quoted
    filename appears in the source. This drives the function instead
    (`AGENTS.md` §Testing Patterns: assert the wiring, not a substring), so it
    also fails if the name is present but the loop stops reaching it.

    `curated/` is globbed by the tool layer and `agent/` ships docstrings into
    the transduction prompt, so a copy under either is not a near miss.
    `cc.ROOT` is redirected at a tmp tree rather than writing a file named
    `design_key.py` into the real `curated/` even briefly.

    Args:
        tmp_path: pytest's per-test directory, standing in for the repo root.
        monkeypatch: Used to redirect `cc.ROOT`.
    """
    # Deferred: `benchmark.contamination_check` imports agent.specifier,
    # agent.registry, benchmark.retrieval_eval and more at module scope, so at
    # collection time an unrelated Lane A import error would turn every test in
    # this file into a collection error naming the wrong file. TASKS.md carries
    # that coupling as an open defect for tests/test_scorability.py; this does
    # not add a second instance of it.
    from benchmark import contamination_check as cc

    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "tools.py").write_text("# nothing forbidden here\n")
    (tmp_path / "curated").mkdir()
    (tmp_path / "agent").mkdir()
    monkeypatch.setattr(cc, "ROOT", tmp_path)

    assert cc.check_holdout_not_reachable() == [], (
        "the empty tmp tree must be clean, or the assertion below passes for "
        "some reason other than the copy")

    for directory in ("curated", "agent"):
        planted = tmp_path / directory / "design_key.py"
        planted.write_text("")
        problems = cc.check_holdout_not_reachable()
        planted.unlink()
        assert any("design_key.py" in p for p in problems), (
            f"a copy at {directory}/design_key.py went undetected. It holds one "
            f"row per paper naming both sides of a published design arrow, "
            f"which is the most direct statement of the answer there is.")
