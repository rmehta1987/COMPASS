"""Schema invariants, exercised against the P-014 specimen.

P-014 is the study card in COMPASS.md. Its layout is real and its numbers are
invented, so we use its structure and its variable keys — all nine of which
resolve against the built dictionary with verbatim matching wording — and treat
every quantity as illustrative.

The point of these tests is not that a valid record validates. It is that each
validator refuses the specific thing it exists to refuse, loudly, rather than
letting a decoder silently relabel it into something that looks correct.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.schema import (
    Access,
    CausalAdjustment,
    CausalRole,
    Comparator,
    DerivationRef,
    Direction,
    Estimability,
    ExpectedDirection,
    FalsifierThreshold,
    GateDecision,
    ModelSpec,
    NSource,
    ProtocolSpecification,
    Provenance,
    SelectionMode,
    SelectionRationale,
    SmallestDetectableEffect,
    Status,
    UnitOfAnalysis,
    UnresolvedCovariate,
    VariableRef,
    derive_status,
)

ROOT = Path(__file__).resolve().parent.parent
DICT = json.loads((ROOT / "build" / "dictionary.json").read_text())
WORDING = {e["key"]: e["question_text"] for e in DICT["entries"]}


def V(key: str) -> VariableRef:
    """A reference whose wording is taken from the dictionary, never typed by hand."""
    return VariableRef(key=key, quoted_wording=WORDING[key])


def adj(key, role, mech, just, **kw) -> CausalAdjustment:
    return CausalAdjustment(variable=V(key), mechanism=mech, justification=just,
                            role=role, **kw)


def p014(**overrides) -> ProtocolSpecification:
    """The specimen: perceived neighbourhood crime -> total physical activity."""
    base = dict(
        protocol_id="P-014",
        dictionary_version=DICT["version_hash"],
        question=("Is perceived neighbourhood crime associated with lower total "
                  "physical activity, independent of socioeconomic position?"),
        exposure=V("m3:Q16.2"),
        outcome=DerivationRef(
            derivation_id="met_hours_week",
            unit="MET-hours/week",
            component_keys=["m3:Q2.33", "m3:Q2.62"],
        ),
        expected_direction=ExpectedDirection(direction=Direction.decrease),
        falsifier="CI excludes a decrease of 1 MET-hour/week across the Likert range.",
        falsifier_threshold=FalsifierThreshold(value=1.0, unit="MET-hours/week",
                                               comparator=Comparator.gte),
        model_spec=ModelSpec(form="linear regression",
                             unit_of_analysis=UnitOfAnalysis.participant,
                             clustering="cluster-robust SE at community area"),
        adjusted_covariates=[
            adj("m1:Q3.11", CausalRole.confounder,
                "Education shapes both neighbourhood of residence and physical activity habits.",
                "Common cause of exposure and outcome; pre-exposure by life course."),
            adj("m1:Q5.4", CausalRole.confounder,
                "Household income determines residential options and leisure-time activity.",
                "Common cause; interpretable only jointly with household size."),
            adj("m1:Q5.5", CausalRole.precision,
                "Household size rescales income into a per-person standard of living.",
                "Precision variable; income alone is uninterpretable without it."),
            adj("m1:Q3.10", CausalRole.proxy,
                "Race stands in for structural exposure to disinvested neighbourhoods.",
                "Included as a proxy for structural exposure, not as a biological cause.",
                proxy_for="structural exposure to residential disinvestment"),
        ],
        excluded_variables=[
            adj("m3:Q16.3", CausalRole.mediator,
                "Crime perception reduces outdoor exercise, which reduces total activity.",
                "Adjusting for this attenuates the very effect under study."),
            adj("m3:Q16.1_1", CausalRole.not_a_cause_of_either,
                "Willingness of neighbours to help is not judged a cause of either anchor.",
                "Excluded as not a cause of exposure or outcome; contestable.",
                contestable=True),
        ],
        undetermined_covariates=[],
        estimability=Estimability(
            analytic_n=None,
            n_source=NSource.unknown,
            modules_required=["1", "3"],
            exposure_contrast="highest versus lowest Likert category",
            collinearity_max=None,
            smallest_detectable_effect=SmallestDetectableEffect(
                value=0.8, unit="MET-hours/week", at_n=1500,
                assumptions="two-sided alpha 0.05, power 0.80, SD 12 MET-hours/week"),
        ),
        access=Access(decision=GateDecision.pass_, reconstruction_load=0, budget=3,
                      location_bearing_keys=[],
                      per_place_working="no location-bearing variables named"),
        derivation_ref="met_hours_week",
        selection_rationale=SelectionRationale(
            selection_mode=SelectionMode.enumerated_screen, screened_from=4120,
            prior_work="literature density tag: moderate",
            why_this_cohort="cross-module perceptual exposure with an activity battery"),
        provenance=Provenance(dictionary_version=DICT["version_hash"],
                              module_version="0.1", prompt_hash="deadbeef",
                              model_id="unset"),
        status=Status.draft,
        blocked_on=["module_co_completion_counts"],
    )
    base.update(overrides)
    return ProtocolSpecification(**base)


# --- the specimen round-trips ------------------------------------------------ #

def test_specimen_validates():
    p = p014()
    assert p.protocol_id == "P-014"
    assert p.status is Status.draft


def test_specimen_keys_resolve_against_the_dictionary():
    """Every key names a real variable and quotes it verbatim."""
    p = p014()
    for e in p.adjusted_covariates + p.excluded_variables:
        assert e.variable.key in WORDING
        assert e.variable.quoted_wording == WORDING[e.variable.key]


def test_specimen_pins_a_dictionary_version():
    assert p014().dictionary_version == DICT["version_hash"]


# --- roles cannot wander between lists --------------------------------------- #

def test_mediator_cannot_be_adjusted():
    """Conditioning on a mediator changes the estimand. This must fail loudly,
    not be silently relabelled into something that looks correct.
    """
    bad = adj("m3:Q16.3", CausalRole.mediator,
              "Crime perception reduces outdoor exercise, which reduces activity.",
              "Wrongly placed in the adjusted list to prove the validator fires.")
    with pytest.raises(ValidationError, match="cannot appear in adjusted_covariates"):
        p014(adjusted_covariates=[bad])


def test_confounder_cannot_be_excluded():
    good = adj("m1:Q3.11", CausalRole.confounder,
               "Education shapes both neighbourhood of residence and activity habits.",
               "A common cause wrongly placed in the excluded list.")
    with pytest.raises(ValidationError, match="cannot appear in excluded_variables"):
        p014(excluded_variables=[good])


def test_collider_is_not_in_the_vocabulary():
    """Asserting a collider needs two named parent constructs with evidence. A
    true M-bias collider is neither cause nor effect of either anchor, so it
    lands in not_a_cause_of_either and is correctly excluded anyway.
    """
    assert not hasattr(CausalRole, "collider")
    assert "collider" not in {r.value for r in CausalRole}


def test_exposure_and_outcome_are_positions_not_roles():
    assert "exposure" not in {r.value for r in CausalRole}
    assert "outcome" not in {r.value for r in CausalRole}


# --- the excluded list is required ------------------------------------------- #

def test_excluded_list_cannot_be_empty():
    """An omitted-by-accident variable and an omitted-on-purpose one are
    indistinguishable unless exclusions are stated with a causal role.
    """
    with pytest.raises(ValidationError):
        p014(excluded_variables=[])


def test_adjusted_list_cannot_be_empty():
    with pytest.raises(ValidationError):
        p014(adjusted_covariates=[])


# --- per-covariate floors ----------------------------------------------------- #

def test_mechanism_is_required_and_floored():
    with pytest.raises(ValidationError, match="mechanism below min_length"):
        adj("m1:Q3.11", CausalRole.confounder, "because", "A long enough justification here.")


def test_justification_is_floored():
    with pytest.raises(ValidationError, match="justification below min_length"):
        adj("m1:Q3.11", CausalRole.confounder,
            "Education shapes neighbourhood and activity.", "too short")


def test_proxy_requires_proxy_for():
    with pytest.raises(ValidationError, match="requires proxy_for"):
        adj("m1:Q3.10", CausalRole.proxy,
            "Race stands in for structural exposure to disinvested neighbourhoods.",
            "Included as a proxy for structural exposure, not a biological cause.")


def test_proxy_for_is_meaningless_without_the_proxy_role():
    with pytest.raises(ValidationError, match="only meaningful when role=proxy"):
        adj("m1:Q3.11", CausalRole.confounder,
            "Education shapes neighbourhood of residence and activity habits.",
            "A common cause, wrongly carrying a proxy_for field.",
            proxy_for="something")


# --- anchors and duplicates ---------------------------------------------------- #

def test_outcome_cannot_also_be_a_covariate():
    """Gate 4's in-record half. Bundle-level incoherence is the measured failure
    locus; field-level checks alone do not see it.
    """
    p = p014()
    dup = adj("m3:Q16.2", CausalRole.confounder,
              "Deliberately re-naming the exposure as a covariate.",
              "Should be refused because it is an anchor of this design.")
    with pytest.raises(ValidationError, match="is an anchor of this design"):
        p014(adjusted_covariates=p.adjusted_covariates + [dup])


def test_a_covariate_cannot_appear_in_two_lists():
    p = p014()
    dup = adj("m1:Q3.11", CausalRole.not_a_cause_of_either,
              "Same variable, second opinion, opposite list.",
              "Present in adjusted and excluded at once; must be refused.")
    with pytest.raises(ValidationError, match="appears in both"):
        p014(excluded_variables=p.excluded_variables + [dup])


# --- cross-field comparisons -------------------------------------------------- #

def test_falsifier_below_smallest_detectable_effect_is_refused():
    """A falsifier the study cannot detect cannot be falsified by that study."""
    with pytest.raises(ValidationError, match="below the smallest detectable effect"):
        p014(falsifier_threshold=FalsifierThreshold(
            value=0.2, unit="MET-hours/week", comparator=Comparator.gte))


def test_magnitude_requires_a_source():
    with pytest.raises(ValidationError, match="magnitude requires magnitude_source"):
        p014(expected_direction=ExpectedDirection(
            direction=Direction.decrease, magnitude="2 to 5 MET-hours/week"))


def test_magnitude_with_a_source_is_fine():
    p = p014(expected_direction=ExpectedDirection(
        direction=Direction.decrease, magnitude="2 to 5 MET-hours/week",
        magnitude_source="Tasmin 2024, Table 3"))
    assert p.expected_direction.magnitude_source


def test_n_and_source_must_agree():
    with pytest.raises(ValidationError, match="analytic_n present but n_source=unknown"):
        Estimability(analytic_n=1500, n_source=NSource.unknown,
                     exposure_contrast="x",
                     smallest_detectable_effect=SmallestDetectableEffect(assumptions="a"))


def test_enumerated_screen_requires_a_denominator():
    with pytest.raises(ValidationError, match="screened_from is required"):
        SelectionRationale(selection_mode=SelectionMode.enumerated_screen,
                           screened_from=None, prior_work="x", why_this_cohort="y")


# --- status is derived, never asserted ---------------------------------------- #

def test_unknown_n_cannot_be_ready_for_review():
    with pytest.raises(ValidationError, match="status=ready_for_review"):
        p014(status=Status.ready_for_review)


def test_blockers_force_draft():
    p = p014()
    assert derive_status(p) is Status.draft
    assert p.blocked_on


def test_clearing_every_blocker_yields_ready_for_review():
    """The degraded mode is safe to ship precisely because nothing else changes
    when the counts arrive.
    """
    p = p014(
        estimability=Estimability(
            analytic_n=1500, n_source=NSource.computed_from_counts,
            modules_required=["1", "3"],
            exposure_contrast="highest versus lowest Likert category",
            smallest_detectable_effect=SmallestDetectableEffect(
                value=0.8, unit="MET-hours/week", at_n=1500, assumptions="alpha .05")),
        blocked_on=[],
        status=Status.ready_for_review)
    assert p.status is Status.ready_for_review


# --- namespace ----------------------------------------------------------------- #

def test_survey_only_keys_are_not_the_whole_namespace():
    """The namespace decision, encoded: a protocol can name a linked area
    measure. Under a survey-only grammar this design is unrepresentable, and
    every one of the eight benchmark papers needs at least one of these.
    """
    from agent.schema import AreaMeasureRef
    ref = AreaMeasureRef(measure_id="pm25_annual", source="MESA Air",
                         grain="tract", entity="residence", years="2013-2018")
    p = p014(exposure=ref)
    assert p.exposure.measure_id == "pm25_annual"


def test_bad_key_prefix_is_refused():
    with pytest.raises(ValidationError):
        VariableRef(key="m4:Q1.1", quoted_wording="no such module")


def test_bare_qid_is_refused():
    """121 qids are not globally unique, so a bare qid is not a variable name."""
    with pytest.raises(ValidationError):
        VariableRef(key="Q2.4", quoted_wording="ambiguous across modules")


def test_occurrence_suffix_is_accepted():
    ref = VariableRef(key="m2:Q785~1", quoted_wording=WORDING["m2:Q785~1"])
    assert ref.registry == "m2"


def test_derived_anchor_requires_a_signed_derivation_file():
    """Inline recipes are forbidden: a recipe cannot be invented mid-protocol."""
    with pytest.raises(ValidationError, match="requires derivation_ref"):
        p014(derivation_ref=None)


# --- what is deliberately absent ---------------------------------------------- #

def test_no_novelty_confidence_or_notes_fields():
    props = set(ProtocolSpecification.model_fields)
    assert not ({"novelty", "confidence", "notes", "score"} & props)


def test_unknown_fields_are_forbidden():
    with pytest.raises(ValidationError):
        p014(novelty_score=9)


def test_attestations_cannot_be_set_false():
    """Attestation only — nothing verifies it. Its purpose is to put the claim on
    the record so a later violation is visible.
    """
    with pytest.raises(ValidationError):
        p014(derivation_not_fitted_to_outcome=False)


# --------------------------------------------------------------------------- #
# the covariate that has no key
#
# Measured on this repo 2026-08-31: over `run/*.json` plus
# `run/superseded/*.json`, excluding `mcp_config.json`, 21 saved records carry
# `adjusted_covariates` and exactly ONE names a covariate whose wording is about
# the respondent's own age. The other twenty are silent, and a silent record
# cannot be told apart from one where the construct was sought and refused.
# --------------------------------------------------------------------------- #

def _gap(**over: object) -> UnresolvedCovariate:
    """A specimen gap, shaped like the one the live runs could not write down."""
    d = dict(
        construct_sought="the respondent's own age at enrolment",
        search_phrases=["age", "age at enrollment", "how old are you"],
        why_rejected=("the search returned an item recording a RELATIVE's year "
                      "of birth, which measures somebody other than the "
                      "respondent, so it was refused."),
        exposes_the_estimate_to=("residual confounding by a common cause of both "
                                 "anchors, with a direction that cannot be "
                                 "signed in advance."),
    )
    d.update(over)
    return UnresolvedCovariate(**d)


def test_a_sought_but_unresolved_covariate_is_representable():
    """C24 acceptance (a): the record can carry what was sought and what was tried.

    This is the whole point of the field. Before it existed the only shapes
    available were the three covariate lists, and every one of them requires a
    `Ref` that resolves — so a construct with no key had nowhere legal to go and
    was dropped instead.
    """
    p = p014(sought_covariates=[_gap()])
    assert len(p.sought_covariates) == 1
    e = p.sought_covariates[0]
    assert e.search_phrases == ["age", "age at enrollment", "how old are you"]
    assert "RELATIVE" in e.why_rejected
    # Records are saved and reloaded as JSON, so representable has to survive
    # the round trip, not just the constructor.
    again = ProtocolSpecification.model_validate_json(p.model_dump_json())
    assert again.sought_covariates[0].construct_sought == e.construct_sought


def test_the_three_covariate_lists_still_cannot_hold_a_gap():
    """The positive control on the diagnosis, not a restatement of it.

    C24 says the model "had nowhere legal to write it". That claim is only worth
    anything if the alternatives actually refuse: `CausalAdjustment` requires a
    `variable`, and `ProtocolSpecification` forbids extra fields. If either ever
    softens, the new field stops being necessary and this test says so.
    """
    with pytest.raises(ValidationError):
        CausalAdjustment(
            mechanism="a common cause of both anchors, if it could be named",
            justification="sought in the instrument and matched to no key at all",
            role=CausalRole.unadjudicated)
    with pytest.raises(ValidationError):
        p014(covariate_i_could_not_find="the respondent's own age at enrolment")


@pytest.mark.parametrize("field, value", [
    ("construct_sought", "age"),
    ("why_rejected", "not it"),
    ("exposes_the_estimate_to", "bias"),
])
def test_a_gap_stated_in_a_token_is_rejected(field, value):
    """The floors are the same idiom as MIN_JUSTIFICATION and for the same reason.

    A grammar-level minLength manufactures padding instead of measuring it, so
    the floor is a validator with a reject-and-regenerate path. A one-word gap
    records nothing a reader could act on and would let the field be satisfied
    without being used.
    """
    with pytest.raises(ValidationError) as e:
        _gap(**{field: value})
    msg = str(e.value)
    assert "min_length" in msg and "pad" in msg
    assert field in msg


def test_a_gap_must_name_the_phrases_that_were_tried():
    """"I could not find it" without the phrases is unreviewable.

    A reader cannot tell a vocabulary mismatch from a construct the instrument
    genuinely lacks unless the record says what was actually searched for. The
    list floor and the per-phrase floor are two different failures: an empty list
    and a list of one blank string both satisfy "there is a list".
    """
    with pytest.raises(ValidationError):
        _gap(search_phrases=[])
    with pytest.raises(ValidationError) as e:
        _gap(search_phrases=["age", " "])
    assert "search_phrases[1]" in str(e.value)


def test_every_floor_violation_is_reported_at_once():
    """One repair, so one message. Reporting the first failure alone kills the entry.

    Transduction allows a SINGLE repair. `UnresolvedCovariate` adds three prose
    fields each with its own floor, so an entry undershooting two of them would
    be told about the first, spend its one repair, and die on the second --
    likeliest on the model's first use of the field, which is the case this whole
    change exists to get right.

    Every failing field must be named in the one message, and the failures are
    independent: none of these checks needs another to have passed.
    """
    with pytest.raises(ValidationError) as e:
        _gap(construct_sought="age", why_rejected="no",
             exposes_the_estimate_to="bias", search_phrases=["a", " "])
    msg = str(e.value)
    for field in ("construct_sought", "why_rejected", "exposes_the_estimate_to",
                  "search_phrases[1]"):
        assert field in msg, f"{field} not named; the repair cannot fix it"

    # A floor failure and a resolved-key failure can co-occur, and a construct
    # short enough to trip the floor is easily a bare key -- so these two must
    # not be reported one round apart either.
    with pytest.raises(ValidationError) as e2:
        _gap(construct_sought="Q2.15_3", why_rejected="no")
    both = str(e2.value)
    assert "why_rejected" in both and "adjusted_covariates" in both


def test_a_construct_that_resolved_is_not_a_gap():
    """`construct_sought` naming a key means the thing was found, not missed.

    Without this the field becomes a fourth covariate list that dodges the
    role-to-list mapping: a model could park a resolved variable here and never
    adjudicate it. The message has to carry the remedy as well as the diagnosis,
    because three live runs were lost to rejections that named a defect and no
    legal move.
    """
    with pytest.raises(ValidationError) as e:
        _gap(construct_sought="age, which the instrument holds as m1:Q2.15_3")
    msg = str(e.value)
    assert "m1:Q2.15_3" in msg
    assert "adjusted_covariates" in msg and "why_rejected" in msg
    # And the honest half stays legal: why_rejected exists to name the key that
    # came back and was turned down, so the ban must not reach it.
    ok = _gap(why_rejected="m1:Q2.15_3 is a relative's birth year, not the "
                           "respondent's, so it was refused.")
    assert "m1:Q2.15_3" in ok.why_rejected


@pytest.mark.parametrize("evasion", [
    "M1:Q2.15_3",     # uppercase module prefix
    "m1: Q2.15_3",    # one space after the colon
    "Q2.15_3",        # no module prefix at all
    "m1:q2.15_3",     # lowercase q
    "M1 : Q2.15_3",   # both, with padding
])
def test_a_key_in_a_construct_is_caught_however_it_is_cased_or_spaced(evasion):
    """The guard reads model-authored prose, so the canonical form is not enough.

    `_VARIABLE_KEY_TOKEN` was written to STRIP tool-returned keys before the
    coding scan, where the lowercase-module form is guaranteed. Reused here it
    scans free prose in order to REJECT it, and all five spellings below were
    ACCEPTED while the canonical `m1:Q2.15_3` was rejected — measured, not
    supposed. That is not a theoretical hole: transduction allows ONE repair and
    the loop rewards the smallest edit that passes, so shifting a letter's case
    was strictly cheaper than moving the entry to a covariate list and giving it
    a role. The cheapest repair therefore dodged role adjudication, which is the
    only thing this validator exists to prevent.
    """
    with pytest.raises(ValidationError) as e:
        _gap(construct_sought=f"the construct recorded as {evasion} in module 1")
    assert "adjusted_covariates" in str(e.value)


@pytest.mark.parametrize("legal", [
    "usual occupation over the working life",
    "self-rated health measured on a 5 point scale",
    "IQ, Q-sort or any cognitive battery",
    "smoking status: current, former or never",
])
def test_the_looser_key_pattern_does_not_eat_plain_prose(legal):
    """The other half of the D2 fix, and the one a looser regex gets wrong.

    A guard that fires on normal operation gets disabled by whoever it annoys.
    The bare-key branch requires `Q<digits>.<digits>`, so a lone capital Q, a
    numeral, or a colon in ordinary words does not trip it.
    """
    assert _gap(construct_sought=legal).construct_sought == legal


def test_the_strict_key_token_is_left_alone_for_the_coding_scan():
    """`_states_a_coding` must keep the STRICT pattern; loosening it is the bug.

    The coding scan strips keys so that disclosing a coding gap while naming a
    key stays legal. If it were handed the free-prose pattern it would also strip
    bare `Q<digits>.<digits>` runs out of text it is supposed to read, and a
    stated coding could be hidden behind one.
    """
    import agent.schema as S
    assert S._states_a_coding("the response coding for m1:Q2.15_3 is unpublished") is None
    # The strict pattern still refuses every spelling the free-prose one catches,
    # which is exactly why the second pattern had to exist.
    assert S._VARIABLE_KEY_TOKEN.search("M1:Q2.15_3") is None
    assert S._KEY_TOKEN_IN_FREE_PROSE.search("M1:Q2.15_3") is not None


def test_one_entry_per_construct():
    """Repeating a construct is the cheap way around three prose floors."""
    with pytest.raises(ValidationError) as e:
        p014(sought_covariates=[_gap(), _gap(search_phrases=["how old"])])
    assert "repeats the construct" in str(e.value)
    # Two genuinely different constructs are the normal case and stay legal.
    p = p014(sought_covariates=[
        _gap(), _gap(construct_sought="usual occupation over the working life")])
    assert len(p.sought_covariates) == 2


@pytest.mark.parametrize("restated", [
    "the respondent's own age at enrolment.",      # a trailing period
    "the respondent's own age at enrolment!",
    "The respondent's own age at enrolment,",
    # `\u2019` rather than the literal glyph: ruff flags the ambiguous
    # character, and the same escape idiom is used in CODING_ASSERTION_PATTERNS.
    "the respondent\u2019s own age at enrolment",
    "the respondent's own-age-at-enrolment",       # hyphens for spaces
])
def test_punctuation_is_not_a_second_construct(restated):
    """A period was cheaper than either floor this check defends.

    The validator's own docstring says repeating an entry is "the cheap way
    around" the three prose floors. `_norm` collapses whitespace and casefolds
    and does nothing about punctuation, so two entries identical up to a trailing
    period validated together -- measured. That is cheaper than the floors and
    cheaper than saying which construct the second search was for, so it was the
    move the repair loop would find first.
    """
    with pytest.raises(ValidationError) as e:
        p014(sought_covariates=[_gap(), _gap(construct_sought=restated)])
    assert "repeats the construct" in str(e.value)


def test_the_new_field_did_not_invalidate_a_saved_record():
    """`sought_covariates` defaults empty, so older records needed no editing.

    SCOPE, because the denominator is not the one a shell glob gives. This walks
    `pathlib.Path.glob`, which MATCHES DOTFILES, over `run/` and
    `run/superseded/` less `mcp_config.json`. `run/` holds two dotfile records
    (`.fe7cbe643d35ef50.json`, `.unitgap_968ee8b566b7e8fa.json`) that `ls *.json`
    never shows, so the count here is 24 and not the 21 a shell glob reports.
    The 11 failures fail identically under the schema at the parent of the commit
    that added this field — they are superseded records pinned to older
    validators, which is what `run/superseded/` is for.

    TWO POPULATIONS, AND THE FIRST VERSION OF THIS TEST CONFLATED THEM. It
    asserted `sought_covariates == []` on EVERY record, which held only because
    no record used the field yet — a fact about the corpus on the morning it was
    written, pinned as though it were a guarantee. The first live run to record a
    covariate gap turned it red, so the field WORKING broke the test that was
    meant to protect it. Records are split on whether the raw JSON carries the
    key: absent means written before the field and the default must apply
    cleanly; present means written after, and the entries must survive a
    round-trip. Red here means the new field started demanding something of
    records written before it, or stopped round-tripping for records that use it.
    """
    before = after = failed = dotfiles = 0
    for f in (sorted((ROOT / "run").glob("*.json"))
              + sorted((ROOT / "run" / "superseded").glob("*.json"))):
        if f.name == "mcp_config.json":
            continue
        d = json.loads(f.read_text())
        if "adjusted_covariates" not in d:
            continue
        dotfiles += f.name.startswith(".")
        try:
            p = ProtocolSpecification.model_validate(d)
        except ValidationError:
            failed += 1
            continue                       # pinned failure, not this field's doing
        if "sought_covariates" not in d:
            assert p.sought_covariates == [], (
                f"{f.name} predates the field and must get the empty default")
            before += 1
            continue
        # Written after the field landed. Round-trip rather than pin a count: the
        # corpus grows every live run, and a test that counts live records is a
        # guard that names a changed number instead of a defect.
        assert p.sought_covariates == [
            UnresolvedCovariate.model_validate(e) for e in d["sought_covariates"]
        ], f"{f.name} does not round-trip its recorded covariate gaps"
        after += 1
    assert before >= 12, f"expected the pre-field batch, saw {before}"
    # The docstring's scope claim, pinned rather than asserted in prose. Without
    # this the "24" above is a number no code touches, and the next reader
    # measures 21 with a shell glob and calls the docstring wrong.
    assert dotfiles >= 2, (
        f"the stated denominator counts dotfile records; saw {dotfiles}")
    assert before + after + failed >= 24, (
        f"stated scope is 24 records carrying adjusted_covariates; "
        f"saw {before + after + failed}")


# --- k=5 selection -------------------------------------------------------------- #

def test_canonical_form_ignores_prose_but_not_design():
    """Two samples that differ only in wording dedup to one record; two that
    differ in a covariate role do not. Prose outputs cannot be deduplicated this
    way at all.
    """
    a = p014()
    b = p014(question="Does perceived neighbourhood crime lower physical activity?")
    assert a.record_hash() == b.record_hash()

    changed = list(a.adjusted_covariates)
    changed[2] = adj("m1:Q5.5", CausalRole.confounder,
                     "Household size treated as a common cause rather than precision.",
                     "A different design decision, so a different record.")
    c = p014(adjusted_covariates=changed)
    assert c.record_hash() != a.record_hash()


def test_recording_a_gap_does_not_change_the_design():
    """`sought_covariates` is deliberately outside `canonical_form`.

    Two reasons, and a cost that is stated rather than hidden. This dict is
    prose-free by construction — the test above pins that — and a sought
    construct is nothing but prose, so folding it in would turn two samples that
    phrased one gap differently into two designs. And every saved record carries
    its `record_hash` in its FILENAME, so adding a key here would change the hash
    of all of them without any design having changed. The cost: two samples for
    one pair differing ONLY in whether they disclose a gap dedup to one, and
    something outside `canonical_form` has to pick the survivor. NOT hash order —
    equal hashes have no order, and this docstring said otherwise until the
    behaviour below was measured. `specifier::specify` picks it, on
    `specifier::_disclosure`; see
    `test_specifier::test_a_disclosing_sample_is_not_discarded_for_a_silent_twin`.
    """
    a = p014()
    b = p014(sought_covariates=[_gap()])
    assert a.record_hash() == b.record_hash()
    assert "sought" not in json.dumps(a.canonical_form())


def test_json_schema_emits_reasoning_before_verdict():
    """Field order is load-bearing: under a constrained grammar the model must
    emit fields in declaration order, so `role` follows the reasoning that
    justifies it.
    """
    schema = ProtocolSpecification.model_json_schema()
    order = list(schema["$defs"]["CausalAdjustment"]["properties"])
    assert order.index("mechanism") < order.index("role")
    assert order.index("justification") < order.index("role")


def test_a_gap_states_what_was_sought_before_what_it_costs():
    """`UnresolvedCovariate`'s field order is load-bearing and was pinned nowhere.

    Its maintainer comment makes the same promise the test above enforces for
    `CausalAdjustment`: under a constrained grammar the model emits fields in
    declaration order, so what was sought and what was tried must both be on the
    page before the consequence is stated. `CausalAdjustment`'s order was pinned;
    this one was a guarantee stated in a comment and enforced nowhere, which is
    this codebase's signature failure one assert short of closed.
    """
    schema = ProtocolSpecification.model_json_schema()
    order = list(schema["$defs"]["UnresolvedCovariate"]["properties"])
    assert order.index("construct_sought") < order.index("why_rejected")
    assert order.index("search_phrases") < order.index("why_rejected")
    # The consequence is last: a model that has not yet written down what came
    # back cannot be asked what its absence costs.
    assert order.index("why_rejected") < order.index("exposes_the_estimate_to")
    assert order.index("exposes_the_estimate_to") == len(order) - 1


def test_schema_forbids_additional_properties_throughout():
    schema = ProtocolSpecification.model_json_schema()
    assert schema.get("additionalProperties") is False
    for name, d in schema.get("$defs", {}).items():
        if d.get("type") == "object":
            assert d.get("additionalProperties") is False, name


def test_a_null_sde_cannot_wave_a_falsifier_through():
    """Found live on 2026-08-26: Haiku put the detectability curve in the
    free-text assumptions field and left value/at_n null. The falsifier check
    then compared against nothing and passed. A check that silently abstains is
    worse than no check.
    """
    d = p014().model_dump(mode="json")
    d["estimability"]["smallest_detectable_effect"] = {
        "value": None, "unit": "percentage points", "at_n": None,
        "assumptions": "n=500 yields 11.48 pp; n=1000 yields 8.12 pp"}
    with pytest.raises(ValidationError, match="cannot be checked against"):
        ProtocolSpecification.model_validate(d)


def test_the_only_real_record_fails_the_verbatim_check():
    """The record Haiku produced on 2026-08-26 (hash 83489d75372a6eb4) carried
    'Race' for m1:Q3.10 and 'Education level' for m1:Q3.11. Six of its seven
    quoted_wording fields were labels, not instrument text, and no validator
    existed. This pins the real failure, not a synthetic one.
    """
    f = (ROOT / "run" /
         "m3q16.1_to_m2q5.8_neighborhood_cohesion_hypertension.83489d75372a6eb4.json")
    if not f.exists():
        pytest.skip("live record not present")
    with pytest.raises(ValidationError, match="verbatim"):
        ProtocolSpecification.model_validate(json.loads(f.read_text()))


# --------------------------------------------------------------------------- #
# identity and provenance: written by the wrapper, floored here
# --------------------------------------------------------------------------- #

#: The record Haiku produced on 2026-08-26. Every identity and provenance field
#: in it is the empty string and both its derivation references contradict the
#: signed files they name, so it is the failing case for this whole section.
LIVE_RECORD = ROOT / "run" / ".fe7cbe643d35ef50.json"


def _live() -> dict:
    if not LIVE_RECORD.exists():
        pytest.skip("live record not present")
    return json.loads(LIVE_RECORD.read_text())


@pytest.mark.parametrize("field", ["protocol_id", "dictionary_version"])
def test_an_empty_identity_field_is_refused(field):
    """"" pins nothing, and the record saved as a dotfile because of it.

    dictionary_version's own Field description says it "pins this record to a
    build hash". An empty string pins no hash, and protocol_id is what the
    driver builds the filename from — `run/.<hash>.json` was invisible to `ls`
    and to every glob in the repo.
    """
    with pytest.raises(ValidationError, match="at least 1 character"):
        p014(**{field: ""})


@pytest.mark.parametrize("field", ["dictionary_version", "module_version",
                                   "prompt_hash", "model_id"])
def test_an_empty_provenance_field_is_refused(field):
    """An ablation cannot tell two runs apart on a field that is "" in both."""
    d = p014().model_dump(mode="json")
    d["provenance"][field] = ""
    with pytest.raises(ValidationError, match="at least 1 character"):
        ProtocolSpecification.model_validate(d)


def test_the_live_records_blank_identity_is_now_rejected():
    """Pins the real failure, not a synthetic one.

    Six empty strings across identity and provenance, all of them things the
    driver knew before the model was called. `Field(description=...)` claiming
    a field pins a build hash is not a constraint.
    """
    with pytest.raises(ValidationError) as exc:
        ProtocolSpecification.model_validate(_live())
    blank = {".".join(str(x) for x in e["loc"]) for e in exc.value.errors()
             if "at least 1 character" in e["msg"]}
    assert blank == {"protocol_id", "dictionary_version",
                     "provenance.dictionary_version", "provenance.module_version",
                     "provenance.prompt_hash", "provenance.model_id"}


# --------------------------------------------------------------------------- #
# a derivation reference is bound to the file it names
# --------------------------------------------------------------------------- #

def test_a_derivation_ref_that_contradicts_its_signed_file_is_rejected():
    """30 component keys against a signed file declaring 2.

    §5 rule 5's sibling: a derivation that does not match its signature is an
    inline recipe wearing a reference's clothes, and inline recipes are exactly
    what DerivationRef exists to forbid. Pinned on the live record's excluded
    exposure, which carried all 30 constituent item keys.
    """
    ref = _live()["excluded_variables"][0]["variable"]
    assert len(ref["component_keys"]) == 30           # what the model wrote
    with pytest.raises(ValidationError, match="declares component_keys"):
        DerivationRef.model_validate(ref)


def test_a_derivation_ref_that_restates_the_unit_in_its_own_words_is_rejected():
    """A paraphrased unit silently switches the falsifier check off.

    _falsifier_is_detectable compares the threshold to the smallest detectable
    effect only when the two unit strings are equal, so "MET-hours per week"
    against a signed "MET-hours/week" is not a cosmetic difference. Pinned on
    the live record's exposure, which reworded a five-item scale's unit.
    """
    ref = _live()["exposure"]
    assert ref["unit"] == "mean Likert score, 5-item scale"     # what the model wrote
    with pytest.raises(ValidationError, match="declares unit"):
        DerivationRef.model_validate(ref)


def test_a_derivation_ref_to_a_file_that_was_never_signed_is_rejected():
    """A named file that was never signed is not a reference.

    Three docstrings and two tool return values promised this and none of them
    enforced it: there was no validate_protocol and no existence check anywhere.
    """
    with pytest.raises(ValidationError, match="no signed derivation"):
        DerivationRef(derivation_id="physical_activity_index",
                      unit="MET-hours/week", component_keys=["m3:Q2.33"])


def test_a_derivation_ref_that_matches_its_signature_validates():
    """The rule was fixed, not the fixture: P-014's outcome already matched."""
    signed = json.loads((ROOT / "curated" / "derivations" /
                         "met_hours_week.json").read_text())
    r = DerivationRef(derivation_id="met_hours_week", unit=signed["unit"],
                      component_keys=signed["component_keys"])
    assert r.component_keys == signed["component_keys"]


def test_the_first_green_live_record_is_the_unit_gap_pinned():
    """A real record that passed everything with its falsifier checked against nothing.

    Produced live by Haiku on 2026-08-27 — the first run to reach a written
    record. Every gate field matched its own tool log, identity and provenance
    were complete, the derivation matched its signature, and the curve was in the
    record. Its falsifier was `0.68 odds ratio` against a percentage-point curve,
    so the floor comparison was skipped and the record asserted a falsifier no
    check had touched.
    """
    f = ROOT / "run" / ".unitgap_968ee8b566b7e8fa.json"
    if not f.exists():
        pytest.skip("record not present")
    d = json.loads(f.read_text())
    assert d["falsifier_threshold"]["unit"] == "odds ratio"
    assert d["estimability"]["smallest_detectable_effect"]["unit"] == "percentage points"
    with pytest.raises(ValidationError, match="cannot be checked against the study"):
        ProtocolSpecification.model_validate(d)


# --------------------------------------------------------------------------- #
# the records the prevalence rule superseded, kept and pinned
# --------------------------------------------------------------------------- #

#: Every live record that existed when the falsifier check moved off the
#: caller-asserted curve on 2026-08-27. They are kept, with their own tool logs,
#: because "the rule was changed and the old records quietly vanished" and "the
#: rule was changed and the old records fail" are indistinguishable otherwise.
SUPERSEDED = sorted((ROOT / "run" / "superseded").glob("*.json"))


def test_every_superseded_record_is_refused_by_the_current_rule():
    """§5 rule 8: fix the fixture, not the rule.

    All eight live records that existed before this round set their falsifier at
    or barely above the floor computed under their OWN asserted outcome
    frequency, which is the pattern the change exists to stop. Not one of them
    clears the caller-independent bound. None was weakened to save it.
    """
    assert len(SUPERSEDED) == 8, f"expected the eight, found {SUPERSEDED}"
    for f in SUPERSEDED:
        d = json.loads(f.read_text())
        with pytest.raises(ValidationError) as exc:
            ProtocolSpecification.model_validate(d)
        assert "worst_case_curve" in str(exc.value), (
            f"{f.name} was refused, but not for the reason this test pins")


def test_seven_of_the_eight_also_predate_the_environments_n_grid():
    """Two holes, closed in two rounds, and the older one is still visible.

    Round 2 took the candidate n grid away from the caller. Seven of these eight
    were produced before that: their logs show estimate_detectability returning
    no bound at all, and their curves sit on grids the model passed in as
    `n_values`. Only the eighth ran against the current environment, which is why
    it is the clean demonstration of the prevalence hole on its own.

    Half of the eight also name an `at_n` the environment no longer evaluates at.
    That is a weaker signal than the missing bound — a caller-chosen grid can
    still contain a round number the environment's grid also contains — so both
    counts are pinned rather than one.
    """
    from env.tools import DETECTABILITY_N_GRID

    def det(f: Path) -> dict:
        """This record's own estimate_detectability return, from its own log."""
        log = f.with_suffix(".tool_log.jsonl")
        return next(json.loads(x)["result"] for x in log.read_text().splitlines()
                    if x.strip()
                    and json.loads(x).get("tool") == "estimate_detectability")

    no_bound = [f.name for f in SUPERSEDED
                if "sde_by_n_worst_case_prevalence" not in det(f)]
    assert len(no_bound) == 7, no_bound

    off_grid = [f.name for f in SUPERSEDED
                if json.loads(f.read_text())["estimability"]
                ["smallest_detectable_effect"]["at_n"] not in DETECTABILITY_N_GRID]
    assert len(off_grid) == 4, off_grid


def test_the_last_pre_rule_record_fails_on_the_prevalence_alone():
    """The clean case: nothing wrong with it except the floor it was judged on.

    `fac31fa6f38c7de4` was produced on 2026-08-27 under the environment's own n
    grid, so its `at_n` is a real evaluation point and its curve is not of its
    own choosing. Its falsifier is exactly its asserted floor, and its asserted
    floor is below the bound — the hole, with every other variable held fixed.
    """
    f = ROOT / "run" / "superseded" / "m3q16.1_to_m2q5.8.fac31fa6f38c7de4.json"
    if not f.exists():
        pytest.skip("record not present")
    d = json.loads(f.read_text())
    sde = d["estimability"]["smallest_detectable_effect"]
    threshold = d["falsifier_threshold"]["value"]
    curve = {p["n"]: p["sde_percentage_points"] for p in sde["curve"]}

    # Its own tool log carries the bound, so no formula is reimplemented here.
    log = f.with_suffix(".tool_log.jsonl")
    det = next(json.loads(x)["result"] for x in log.read_text().splitlines()
               if x.strip() and json.loads(x).get("tool") == "estimate_detectability")
    bound = {p["n"]: p["sde_percentage_points"]
             for p in det["sde_by_n_worst_case_prevalence"]}

    assert threshold == curve[sde["at_n"]], "it set its falsifier AT its own floor"
    assert threshold < bound[sde["at_n"]], "and that floor is below the bound"
    # The record is otherwise complete: it named a blocker, it stayed draft, and
    # its gate fields matched its log. Only the comparator was wrong.
    assert d["status"] == "draft" and d["blocked_on"]


def test_every_saved_record_that_carries_a_bound_still_clears_it():
    """The live evidence, kept as a check instead of a paragraph in a report.

    Nine records were produced against claude-haiku-4-5 on 2026-08-27 after the
    comparator moved. Their asserted outcome frequencies are not all the same, so
    their disclosed curves differ — and their thresholds are all at or above the
    one bound, which is the property the change exists to produce. If a later
    edit lets any of them validate while sitting under their bound, the rule has
    been loosened and this fails.
    """
    from agent.schema import NotSpecifiable

    checked = 0
    for f in sorted((ROOT / "run").glob("*.json")):
        if f.name == "mcp_config.json":
            continue
        d = json.loads(f.read_text())
        if "reason" in d and "evidence" in d:
            # A refusal, not a protocol. Validated against its OWN schema rather
            # than skipped: it carries no estimability block, so the curve check
            # below would wave it through without ever looking at it, and a
            # saved record no test reads is a record no test protects.
            NotSpecifiable.model_validate(d)
            continue
        sde = (d.get("estimability") or {}).get("smallest_detectable_effect") or {}
        if not sde.get("worst_case_curve"):
            continue                    # produced before the bound existed
        ProtocolSpecification.model_validate(d)
        bound = {p["n"]: p["sde_percentage_points"] for p in sde["worst_case_curve"]}
        t = d.get("falsifier_threshold")
        if t:
            assert abs(t["value"]) >= abs(bound[sde["at_n"]]), f.name
        # The assumption is admitted, in the field and in the blocker, and the
        # record is held at draft on it.
        assert isinstance(sde["asserted_baseline_prevalence"], float)
        assert "outcome_prevalence_unconfirmed" in d["blocked_on"]
        assert d["status"] == "draft"
        checked += 1
    assert checked >= 9, f"expected the live batch, checked {checked}"


def test_the_transduce_schema_carries_no_study_content():
    """model_json_schema() copies docstrings into `description`, and that schema
    is pasted into the transduction prompt. Anything written in a docstring in
    agent/schema.py is prompt text the model reads at generation time.
    """
    s = json.dumps(ProtocolSpecification.model_json_schema())
    for leak in ("benchmark papers", "PM2.5", "NO2", "NDVI", "MOOSE", "Min-K",
                 "2836", "Capricorn", "WQS", "MAPSCorps"):
        assert leak not in s, f"transduce schema leaks {leak!r}"


# --------------------------------------------------------------------------- #
# the refusal path
# --------------------------------------------------------------------------- #

def _refusal(**over):
    from agent.schema import NotSpecifiable, Provenance, RefusalEvidence, RefusalReason
    d = dict(
        pair_id="linked:neighborhood_disadvantage -> m2:Q12.78",
        dictionary_version="6fcd02755bf3",
        reason=RefusalReason.registry_empty,
        statement=("The linked registry holds no area measures, so no exposure "
                   "for this pair can be named against the instrument."),
        evidence=[
            RefusalEvidence(tool="registry_coverage", argument="",
                            outcome="linked: coverage none"),
            RefusalEvidence(tool="resolve_variable",
                            argument="linked:household_poverty",
                            outcome="not_found"),
        ],
        blocked_on=["area_measure_inventory"],
        what_would_unblock="an area-measure inventory from the study team",
        provenance=Provenance(dictionary_version="6fcd02755bf3",
                              module_version="0.1", prompt_hash="t",
                              model_id="claude-haiku-4-5"),
    )
    d.update(over)
    return NotSpecifiable(**d)


def test_a_refusal_is_a_first_class_output():
    r = _refusal()
    assert r.reason.value == "registry_empty"
    assert len(r.record_hash()) == 16


def test_a_refusal_must_be_earned_by_lookups_that_ran():
    """Without this the refusal path is strictly easier than the work."""
    from agent.schema import RefusalEvidence
    with pytest.raises(ValidationError, match="must show the lookups"):
        _refusal(evidence=[RefusalEvidence(tool="search_variables",
                                           argument="poverty", outcome="ok")])


def test_an_empty_registry_refusal_must_name_the_remedy():
    with pytest.raises(ValidationError, match="pending request"):
        _refusal(blocked_on=[])


def test_a_refusal_cannot_carry_a_design():
    """A refusal that speculates about the study it would have written is a
    protocol with a disclaimer, which is the thing this class exists to stop.
    """
    with pytest.raises(ValidationError):
        _refusal(adjusted_covariates=[], model_spec={"form": "logistic"})


def test_an_invented_key_is_rejected_with_the_refusal_path_named():
    """`linked:household_poverty` satisfies KEY_PATTERN and exists in no
    registry. Before the key-existence check, this was the only way to produce a
    well-formed record for an unanswerable pair — the schema rewarded
    fabrication and counted it as yield.
    """
    d = p014().model_dump(mode="json")
    d["adjusted_covariates"][0]["variable"] = {
        "kind": "variable", "key": "linked:household_poverty",
        "quoted_wording": "Area household poverty rate"}
    with pytest.raises(ValidationError, match="NotSpecifiable"):
        ProtocolSpecification.model_validate(d)


def test_there_is_no_unfalsifiable_refusal_reason():
    """Every reason must name a condition a tool can confirm. A reason the
    environment cannot check is one the model can assert at will.
    """
    from agent.schema import RefusalReason
    vocab = {r.value for r in RefusalReason}
    for banned in ("insufficient_information", "too_uncertain", "unclear",
                   "not_enough_data", "low_confidence"):
        assert banned not in vocab


def test_the_refusal_schema_carries_no_study_content():
    """The refusal schema is prompt text too, as of 2026-08-28.

    The Specifier now pastes it into a second transduction call, so everything
    §3 says about ProtocolSpecification's docstrings is true of these.
    """
    from agent.schema import NotSpecifiable
    s = json.dumps(NotSpecifiable.model_json_schema())
    for leak in ("benchmark papers", "PM2.5", "NO2", "NDVI", "MOOSE", "Min-K",
                 "2836", "Capricorn", "WQS", "MAPSCorps"):
        assert leak not in s, f"the refusal schema leaks {leak!r}"


def test_the_refusal_schema_does_not_disclose_what_is_being_measured():
    """The schema must not tell the model which behaviour is being measured.

    The class docstring used to say a probe would read an invented key as
    recall. Nothing pasted it into a prompt then; something does now. A marker
    leak gives away an answer; this would give away the experiment.
    """
    from agent.schema import NotSpecifiable
    s = json.dumps(NotSpecifiable.model_json_schema()).lower()
    for term in ("probe", "recall", "contamina", "fabricat", "yield",
                 "pretrain", "memoris", "memoriz"):
        assert term not in s, f"the refusal schema discloses {term!r}"


def test_every_refusal_reason_declares_the_evidence_that_earns_it():
    """The evidence map is total over the enum.

    It is the single declaration three readers share: this validator, the
    Specifier's refusal gate, and the menu in the system prompt. A member added
    without an entry used to raise KeyError from inside a validator, which reads
    as a crash rather than as the design hole it is.
    """
    from agent.schema import REFUSAL_EVIDENCE, RefusalReason
    assert set(REFUSAL_EVIDENCE) == set(RefusalReason)
    assert all(v for v in REFUSAL_EVIDENCE.values()), "a reason with no evidence"


def test_a_reason_with_no_declared_evidence_fails_legibly():
    from agent.schema import REFUSAL_EVIDENCE, RefusalReason
    saved = REFUSAL_EVIDENCE.pop(RefusalReason.registry_empty)
    try:
        with pytest.raises(ValidationError, match="no entry in REFUSAL_EVIDENCE"):
            _refusal()
    finally:
        REFUSAL_EVIDENCE[RefusalReason.registry_empty] = saved


def test_status_is_a_protocol_concept_and_a_refusal_has_none():
    """Status is a protocol concept, pinned because an argument enforces nothing.

    `derive_status` is a function of n_source, blocked_on and the access
    decision — three fields a refusal does not have — and its two values
    describe a protocol's trajectory toward review. A third member would also
    appear in ProtocolSpecification's own schema, advertising `refused` as a
    status a PROTOCOL may claim, which is the protocol-with-a-disclaimer that
    NotSpecifiable exists to shut out.
    """
    from agent.schema import NotSpecifiable, Status
    assert [s.value for s in Status] == ["draft", "ready_for_review"]
    assert "status" not in NotSpecifiable.model_fields
    with pytest.raises(ValidationError):
        _refusal(status="draft")


# --------------------------------------------------------------------------- #
# HARD RULE 3 — a response coding the environment does not have
# --------------------------------------------------------------------------- #

#: One seed per pattern kept in `CODING_ASSERTION_PATTERNS`. Seeded failure is
#: the rule (AGENTS.md §Testing Patterns): a check that cannot fail is not
#: evidence, so every pattern names the string that makes it fire and the test
#: below asserts which pattern caught it, not merely that something did.
CODING_SEEDS: dict[str, str] = {
    "value_label_binding":
        "highest versus lowest category (1=strongly disagree, 5=strongly agree)",
    "anchored_scale_range":
        "contrast across the 1-5 Likert scale",
    "n_point_scale":
        "top versus bottom of the five-point response categories",
    "scored_range":
        "the battery is scored 0-30 and dichotomised at the median",
    "missing_code_convention":
        "highest versus lowest, treating 7/8/9 as missing codes",
    "enumerated_response_options":
        "the response options run 1 through 5 from never to always",
}


def test_every_coding_pattern_has_a_seed_that_fires_it() -> None:
    """No pattern lands without a demonstrated red state.

    Raises:
        AssertionError: If a pattern has no seed, or a seed is caught by a
            different pattern than the one it was written for.
    """
    from agent.schema import CODING_ASSERTION_PATTERNS, _states_a_coding
    assert set(CODING_SEEDS) == set(CODING_ASSERTION_PATTERNS), (
        "a pattern without a seed is a pattern nobody has seen fail")
    for name, seed in CODING_SEEDS.items():
        assert _states_a_coding(seed) == name, (
            f"{name}: {seed!r} was caught by {_states_a_coding(seed)!r}")


@pytest.mark.parametrize("pattern", sorted(CODING_SEEDS))
def test_a_stated_response_coding_is_rejected(pattern: str) -> None:
    """Each seed, injected into the field the gap was demonstrated in.

    `estimability.exposure_contrast` is where the 2026-08-27 injection landed
    and was accepted by both gates. It is the load-bearing case: the contrast
    IS the estimand.

    Args:
        pattern: Name of the pattern under test.
    """
    est = p014().estimability.model_dump(mode="json")
    est["exposure_contrast"] = CODING_SEEDS[pattern]
    with pytest.raises(ValidationError) as exc:
        p014(estimability=est)
    msg = str(exc.value)
    assert "states a response coding" in msg and pattern in msg
    # The remedy, not just the diagnosis.
    assert "response_coding" in msg and "blocked_on" in msg


@pytest.mark.parametrize("field,value", [
    ("question", "Does cohesion, scored 1-5, predict hypertension?"),
    ("falsifier", "CI excludes a 1-point shift on the 1-5 Likert scale."),
    ("model_spec", {"form": "logistic regression with the outcome coded 1=yes, "
                            "2=no",
                    "unit_of_analysis": "participant",
                    "clustering": "cluster-robust SE at community area"}),
    ("expected_direction", {"direction": "decrease",
                            "magnitude": "0.4 points on the 1-5 scale",
                            "magnitude_source": "assumed"}),
    ("falsifier_threshold", {"value": 1.0, "unit": "points on a 5-point scale",
                             "comparator": ">="}),
])
def test_every_gated_field_is_actually_gated(field: str, value: object) -> None:
    """One injection per member of CODING_GATED_FIELDS.

    A field named in the constant but never read by the validator is the
    "guarantee enforced nowhere" failure in miniature, so each is exercised.

    Args:
        field: The top-level field to overwrite.
        value: A value carrying a coding claim.
    """
    with pytest.raises(ValidationError, match="states a response coding"):
        p014(**{field: value})


def test_the_gated_set_is_exactly_what_the_validator_reads() -> None:
    """CODING_GATED_FIELDS documents the surface; the accessor is the surface."""
    from agent.schema import CODING_GATED_FIELDS
    p = p014(expected_direction={"direction": "decrease", "magnitude": "small",
                                 "magnitude_source": "assumed"})
    assert [w for w, _ in p._coding_gated_text()] == list(CODING_GATED_FIELDS)


def test_no_record_on_disk_trips_the_coding_gate() -> None:
    """Calibration, over every protocol record in the repository.

    All of `run/` and `run/superseded/`, valid or not, because a record that
    fails some other validator today is still a specimen of what the pipeline
    writes. Twenty-three files; the two dotfiles are the empty-protocol_id
    records and are included deliberately.

    If this fires, narrow the pattern — do not narrow the corpus. The corpus is
    already thin: 22 of the 23 records specify the same exposure-outcome pair,
    so zero hits here is weaker evidence than the count suggests, which is the
    argument for gating six fields rather than all free text.

    Raises:
        AssertionError: If any record states a coding in a gated field.
    """
    from agent.schema import CODING_GATED_FIELDS, _states_a_coding
    files = [f for d in (ROOT / "run", ROOT / "run" / "superseded")
             for f in sorted(d.glob("*.json")) if f.name != "mcp_config.json"]
    assert len(files) >= 20, f"corpus shrank to {len(files)}; check the paths"
    fired = {}
    for f in files:
        rec = json.loads(f.read_text())
        for path in CODING_GATED_FIELDS:
            node: object = rec
            for part in path.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, str) and _states_a_coding(node):
                fired[f"{f.name}::{path}"] = node
    assert not fired, f"the gate fires on records already on disk: {fired}"


def test_a_signed_derivations_own_recipe_is_not_an_assertion() -> None:
    """Transcription is the environment speaking; no exemption is needed for it.

    The advisory detector's `coding_claim` fires on "reverse-coding items 4 and
    5" and needed `_traces_to_a_signed_derivation` to excuse it. Requiring a
    numeral instead removes the need for the exemption, and an exemption is a
    bypass: "the record names a derivation whose file mentions Likert" would
    excuse an invented 1-5 scale in the same record.

    Raises:
        AssertionError: If any signed derivation's own text trips the gate.
    """
    from agent.schema import _states_a_coding
    d = ROOT / "curated" / "derivations"
    if not d.is_dir():
        pytest.skip("curated/derivations not present")
    signed = [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]
    assert signed, "no signed derivations to check"
    for obj in signed:
        for key in ("recipe", "unit", "construct_validity_basis", "caveat"):
            text = str(obj.get(key, ""))
            assert _states_a_coding(text) is None, (
                f"{obj['derivation_id']}.{key} trips the gate: {text!r}")
    # And the record may quote one into a gated field without being rejected.
    recipe = next(o["recipe"] for o in signed
                  if o["derivation_id"] == "social_cohesion_scale")
    assert "reverse-coding" in recipe
    assert p014(falsifier=recipe).falsifier == recipe


def test_naming_the_gap_is_not_stating_a_coding() -> None:
    """The disclosure the rule asks for must survive the rule.

    A gate that rejects "the response coding is not published" teaches the model
    to stop saying it, which inverts the rule it enforces. Variable keys carry
    digits, so key-stripping is what keeps the second and third of these legal.
    """
    from agent.schema import _states_a_coding
    for honest in (
            "Response coding is NOT in the public codebook; direction of the "
            "Likert scale must be confirmed by the study team before use.",
            "The response coding for m3:Q16.1_1 is unpublished.",
            "Missing codes for m2:Q19.86_1 are absent from the codebook.",
            "highest versus lowest Likert category",
            "per 5 MET-hours/week",
            "mean Likert score, 5 items",
            "a 0.5-point difference in the mean cohesion score"):
        assert _states_a_coding(honest) is None, honest
    p014(estimability=dict(p014().estimability.model_dump(mode="json"),
                           exposure_contrast="highest versus lowest Likert "
                                             "category, coding unpublished"))


def test_verbatim_instrument_wording_is_deliberately_not_gated() -> None:
    """The one instrument item that would put two validators in contradiction.

    m2:Q19.86_1's question text carries an inline value-label binding. Gating
    `quoted_wording` would mean `_wording_is_verbatim` demands the exact string
    this gate refuses, so a correct record naming that item could not exist.
    One item in 2,804 — and one is enough.

    Raises:
        AssertionError: If the item stops carrying the binding, or if
            quoted_wording is ever added to the gated set.
    """
    from agent.schema import CODING_GATED_FIELDS, _states_a_coding
    text = WORDING.get("m2:Q19.86_1")
    if text is None:
        pytest.skip("m2:Q19.86_1 not in this build")
    assert _states_a_coding(text) == "value_label_binding", text
    assert not any("quoted_wording" in f for f in CODING_GATED_FIELDS)
    # A record naming it validates, binding and all.
    p = p014(exposure=V("m2:Q19.86_1"),
             estimability=dict(p014().estimability.model_dump(mode="json"),
                               modules_required=["1", "2", "3"]))
    assert p.exposure.quoted_wording == text


def test_a_coding_claim_outside_the_gated_fields_still_validates() -> None:
    """The limit of this gate, pinned so it is not mistaken for total coverage.

    `selection_rationale.prior_work` is where the advisory detector's only
    real-corpus false positive landed, and `CausalAdjustment.justification` is
    where `CausalRole.unreliable_coding` requires the model to discuss coding.
    Neither is gated, both are still scanned by
    `benchmark/unearned_assertions.py::scan_record`. If someone widens the gate
    to cover them, this test fails and they have to argue for it.
    """
    sr = p014().selection_rationale.model_dump(mode="json")
    sr["prior_work"] = "Sampson's 5-item scale, scored 1-5 after reverse-coding"
    assert p014(selection_rationale=sr).selection_rationale.prior_work == \
        sr["prior_work"]


def test_the_rejection_survives_the_repair_loops_truncation() -> None:
    """The remedy has to reach the model, not just the diagnosis.

    `agent/specifier.py::_transduce` re-prompts with `str(exc)[:1800]`. This
    message is the longest in the module, and a rejection whose actionable half
    is cut off costs the whole sample — three live runs ended on errors that
    named a defect and no legal move.
    """
    from agent.specifier import MAX_TRANSDUCE_ATTEMPTS
    assert MAX_TRANSDUCE_ATTEMPTS >= 2, "no repair pass; the message never lands"
    est = p014().estimability.model_dump(mode="json")
    est["exposure_contrast"] = "highest versus lowest (1=strongly disagree)"
    with pytest.raises(ValidationError) as exc:
        p014(estimability=est)
    seen = str(exc.value)[:1800]
    assert "response_coding" in seen and "blocked_on" in seen
    assert "estimability.exposure_contrast" in seen


def test_a_refusal_may_not_cite_a_call_that_contradicts_it() -> None:
    """Naming the tool is not enough; the call must have returned the reason.

    VERIFIED 2026-08-28 on merged main, before this landed: a NotSpecifiable
    claiming `access_gate_refused` validated while citing check_access with
    outcome "ok" — a call in which the gate did not refuse. `check_access` is in
    REQUIRED_CALLS, so that evidence exists on every run, which made this the
    cheapest refusal in the enum to fabricate. `RefusalEvidence.outcome` carried
    "the tool's own outcome string, verbatim" by its own field description and
    nothing read it: the eighth instance of a guarantee stated and unenforced.

    Raises:
        AssertionError: If a contradicted citation validates, or an entailing
            one does not.
    """
    import pytest
    from pydantic import ValidationError

    from agent.schema import NotSpecifiable, Provenance

    def build(tool: str, outcome: str, reason: str) -> NotSpecifiable:
        return NotSpecifiable(
            pair_id="x -> y", dictionary_version="6fcd02755bf3", reason=reason,
            statement="No protocol is specifiable for this pair as posed.",
            what_would_unblock="study-team confirmation of variable provenance",
            evidence=[{"tool": tool, "argument": "{}", "outcome": outcome}],
            provenance=Provenance.model_construct())

    with pytest.raises(ValidationError, match="entails the refusal"):
        build("check_access", "ok", "access_gate_refused")

    # The same shape for a reason the environment CAN produce: a resolution that
    # succeeded cannot support a claim that it failed.
    with pytest.raises(ValidationError, match="entails the refusal"):
        build("resolve_variable", "unique", "exposure_unresolvable")

    # And the entailing citation still passes, so this is a check, not a ban.
    ok = build("resolve_variable", "not_found", "exposure_unresolvable")
    assert ok.reason.value == "exposure_unresolvable"


def test_every_refusal_outcome_entry_names_a_tool_the_reason_requires() -> None:
    """REFUSAL_OUTCOMES may not drift away from REFUSAL_EVIDENCE.

    The outcome check only runs for tools the reason already requires, so an
    entry naming a tool that REFUSAL_EVIDENCE does not list is silently dead —
    exactly the shape of a guarantee that looks enforced and is not.

    Raises:
        AssertionError: If an outcome entry names a tool its reason does not
            require, or a reason has outcomes declared but no evidence entry.
    """
    from agent.schema import REFUSAL_EVIDENCE, REFUSAL_OUTCOMES

    for reason, wanted in REFUSAL_OUTCOMES.items():
        need = REFUSAL_EVIDENCE.get(reason)
        assert need is not None, f"{reason} has outcomes but no required evidence"
        for tool in wanted:
            assert tool in need, (
                f"{reason}: REFUSAL_OUTCOMES names {tool!r}, which "
                f"REFUSAL_EVIDENCE does not require, so the check never runs")
