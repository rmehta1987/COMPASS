"""benchmark/prevalence_rows.py — accessors over the held-out prevalence key.

🛑 NOTHING HERE MAY BE READ FOR DESIGN. That is the whole reason this module
exists as a separate file, and `tests/test_scorability.py` enforces it by
import rather than by care.

C36 made `benchmark/design_key.py` the single answer key for a paper's design
arrow — one row per paper, both sides, typed anchors. The strongest objection to
adding a second answer key is that two keys which can disagree about one paper's
outcome are worse than one key with a blank cell, and the mitigation has to be
exclusivity rather than good intentions. These four accessors were the second
reader: they live in the prevalence key and they answered "where does this
paper's outcome sit", which is a design question. Moving them out of
`benchmark/scorability.py` means the scoring path cannot reach them by
accident — it does not import this module, and a test says so.

WHAT THE PREVALENCE KEY IS STILL FOR, and it loses nothing. `value`,
`quantity`, `arm`, `role`, `instrument_key` and `instrument_region` all stay,
and `instrument_key` goes on being what makes a published figure findable from
a variable. `benchmark/input_leakage.py` and
`benchmark/contamination_check.py::check_no_prevalence_figure_in_surface` are
its consumers, and neither is scoring a design.

WHY THE ACCESSORS SURVIVE AT ALL rather than being deleted with their callers.
They carry two measured facts about the key's own data that are worth keeping
under test: that every `instrument_region` parses (rather than an unrecognised
value defaulting to unreachable), and that a covariate-role key is never
returned as an outcome one — found by inspection on PMID 38715087, whose only
keyed row is `prevalent hypertension` as a covariate while its outcome is
central hemodynamics.

HELD OUT BY WHAT IT READS. `benchmark/prevalence_key.py` is withheld from every
clone but the scoring one, so every function here raises `ModuleNotFoundError`
elsewhere. The import is deferred in each, not module-level: at module scope it
took `benchmark.contamination_check` — the MANDATORY gate after any prompt or
convention edit — down on every other clone.
"""

from __future__ import annotations

#: `prevalence_key.py` rows carry a `role`, and only one of the three is this
#: paper's outcome. Measured 2026-08-28: 31 rows are `outcome`, 9 are
#: `covariate` and 1 is `recruitment`. Reading a covariate key as outcome
#: evidence would confirm a paper on a variable it ADJUSTED FOR — found by
#: inspection on PMID 38715087, whose only keyed row is `prevalent hypertension`
#: as a covariate while its outcome is central hemodynamics.
OUTCOME_ROLE = "outcome"


def outcome_keys_on_record(pmid: str) -> tuple[str, ...]:
    """Instrument keys the held-out prevalence key records as a paper's OUTCOME.

    Args:
        pmid: PubMed identifier.

    Returns:
        Sorted distinct `instrument_key` values from `role == OUTCOME_ROLE`
        rows, empty when the key records none. Not yet evidence: `_confirm_keys`
        decides which of these resolve.
    """
    # Deferred, not module-level: `benchmark/prevalence_key.py` is the held-out
    # answer key and is withheld from every clone but the scoring one. At module
    # scope this import took `benchmark.contamination_check` -- the MANDATORY gate
    # after any prompt or convention edit -- down with ModuleNotFoundError on every
    # other clone, so the check could not run where the code it checks is written.
    # The function that needs the key still raises there; nothing else does.
    from benchmark.prevalence_key import PREVALENCE_KEY

    return tuple(sorted({
        row.instrument_key for row in PREVALENCE_KEY
        if row.pmid == pmid and row.instrument_key
        and row.role == OUTCOME_ROLE}))


#: A region the instrument holds names the module it sits in. Measured
#: 2026-08-29 over all 41 rows: the reachable regions are `m2:Q5 diagnosed
#: conditions`, `m2:Q12 cancer history and screening` and `m2 female medical
#: history`; the unreachable ones say so in words — `clinical measurement, not
#: in the instrument`, `lab registry, declared and EMPTY in v1`, `not in the
#: instrument`, `recruitment, not in the instrument`, `anthropometry, not in the
#: instrument`. Prefix-matching the module is structural where matching that
#: prose would not be, and `test_every_instrument_region_parses` fails if a new
#: value fits neither shape rather than letting it default to unreachable.
_MODULE_PREFIXES = ("m1", "m2", "m3")


def region_is_in_the_instrument(region: str) -> bool:
    """Whether a prevalence-key region names a place inside the instrument.

    Args:
        region: A `prevalence_key.py` row's `instrument_region`.

    Returns:
        True when the region names a module of the questionnaire.
    """
    return region.startswith(_MODULE_PREFIXES)


def outcome_reachable_in_instrument(pmid: str) -> bool | None:
    """Whether the held-out key places this paper's outcome inside the instrument.

    Args:
        pmid: PubMed identifier.

    Returns:
        True when any outcome row sits in a module of the questionnaire, False
        when outcome rows exist and none does, and None when the key holds no
        outcome row for this paper — absence of evidence, which may not be read
        as refutation.
    """
    # Deferred, not module-level: `benchmark/prevalence_key.py` is the held-out
    # answer key and is withheld from every clone but the scoring one. At module
    # scope this import took `benchmark.contamination_check` -- the MANDATORY gate
    # after any prompt or convention edit -- down with ModuleNotFoundError on every
    # other clone, so the check could not run where the code it checks is written.
    # The function that needs the key still raises there; nothing else does.
    from benchmark.prevalence_key import PREVALENCE_KEY

    # A null region is dropped rather than counted as unreachable: the field is
    # Optional in the key, and reading "not recorded" as "not in the instrument"
    # would refute a paper on a blank cell. All 41 rows carry one today.
    regions = [r.instrument_region for r in PREVALENCE_KEY
               if r.pmid == pmid and r.role == OUTCOME_ROLE
               and r.instrument_region]
    if not regions:
        return None
    return any(region_is_in_the_instrument(r) for r in regions)

