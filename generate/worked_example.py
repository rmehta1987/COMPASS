"""generate/worked_example.py — one pair, all the way through.

    ./.venv/bin/python generate/worked_example.py

Shows what "hypothesis generation" actually is in this system: a deterministic
funnel produces the candidate, and the model is handed a stated pair and asked
only to SPECIFY a design for it. No model is wired up yet, so the record below is
hand-specified — it is the acceptance-test target the Specifier must hit, and the
fact that it validates is the evidence that the schema can express this design.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.schema import (  # noqa: E402
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
    VariableRef,
)
from env.tools import estimate_detectability  # noqa: E402
from generate.funnel import load_constructs, run  # noqa: E402

DICT = json.loads((ROOT / "build" / "dictionary.json").read_text())
WORDING = {e["key"]: e["question_text"] for e in DICT["entries"]}


def V(key: str) -> VariableRef:
    return VariableRef(key=key, quoted_wording=WORDING[key])


def adj(key, role, mech, just, **kw):
    return CausalAdjustment(variable=V(key), mechanism=mech, justification=just,
                            role=role, **kw)


def main() -> ProtocolSpecification:
    """Build and print the one-pair worked example.

    Returns:
        The validated record, so a test can assert on its fields directly
        instead of parsing this function's console narration.
    """
    C, version = load_constructs()

    # ----- the frame: one curated slice, not the whole instrument ------------ #
    exposures = sorted([c for c in C.values()
                        if c.module == "3" and c.base_id.startswith("Q16.")],
                       key=lambda c: c.base_id)
    outcomes = sorted([c for c in C.values()
                       if c.module == "2" and c.base_id.startswith("Q5.")],
                      key=lambda c: c.base_id)

    cands, counts = run(exposures, outcomes)

    print("=" * 74)
    print(f"S1-S4  DETERMINISTIC FUNNEL          dictionary {version}")
    print("=" * 74)
    print(f"  frame                 {len(exposures)} exposures x {len(outcomes)} outcomes")
    print(f"  S1 enumerated         {counts['enumerated']}")
    print(f"  S2 pruned             {counts['pruned_S2']}   (mechanical, reasons recorded)")
    print(f"  S3 parked             {counts['parked_S3']}   "
          f"(not_estimable is reserved, unassigned: always 0, see funnel.py)")
    print(f"  live                  {counts['live']}")
    print(f"     estimable          {counts['estimable']}")
    print(f"     unknown            {counts['unknown']}   <- every pair is cross-module")
    print(f"     needs derivation   {counts['requires_derivation']}")
    print("\n  No model has been called. Nothing above was judged, ranked or scored.")

    # ----- pick the pair the funnel produced -------------------------------- #
    pair = next(c for c in cands
                if c.exposure.construct_key == "m3:Q16.1"
                and c.outcome.construct_key == "m2:Q5.8")

    print("\n" + "=" * 74)
    print("ONE CANDIDATE, AS HANDED TO THE SPECIFIER")
    print("=" * 74)
    print(f"  pair               {pair.pair_id}")
    print(f"  exposure stem      {pair.exposure.stem_text[:66]}")
    print(f"  exposure members   {', '.join(pair.exposure.member_keys)}")
    print(f"  outcome            {pair.outcome.stem_text[:66]}")
    print(f"  estimability       {pair.estimability}  ({pair.tags.get('blocked_on')})")
    print(f"  derivation needed  {pair.requires_derivation}  (exposure is a 5-item battery)")
    print(f"  screened_from      {counts['enumerated']}")

    # ----- detectability: a real curve point, not an invented number -------- #
    # A cold critic found value=2.1 at_n=1800 hand-written below: 1800 is on no
    # DETECTABILITY_N_GRID this project has ever used, so it was a number no
    # tool would return for any input — the exact fabrication
    # agent/tool_authority.py's GateMismatch exists to catch, except this script
    # never passes through the authority layer, so nothing caught it here. Pull
    # the number from the same environment tool the live Specifier calls,
    # instead of a constant that goes stale the moment the grid changes.
    # analytic_n is None below (co-completion counts do not exist), so use the
    # SMALLEST candidate n on the curve — the same convention
    # agent/tool_authority.py applies when a record names no n.
    detect = estimate_detectability(baseline_prevalence=0.32)
    floor = min(detect["sde_by_n"], key=lambda pt: pt["n"])
    sde_value, sde_at_n = floor["sde_percentage_points"], floor["n"]
    a = detect["assumptions"]
    sde_assumptions = (f"two_sided_alpha={a['two_sided_alpha']}; power={a['power']}; "
                       f"baseline_prevalence={a['baseline_prevalence']}; "
                       f"allocation={a['allocation']}; test={a['test']}")
    # floor(x)+1 clears x for every real x, so this is a falsifier the study
    # above could actually falsify, not a hand-picked number that happens to.
    falsifier_value = float(math.floor(sde_value) + 1)

    # ----- what the Specifier must return ----------------------------------- #
    p = ProtocolSpecification(
        protocol_id="P-022",
        dictionary_version=version,
        question=("Is lower perceived neighbourhood social cohesion associated with "
                  "higher self-reported hypertension, independent of socioeconomic "
                  "position?"),
        exposure=DerivationRef(
            derivation_id="social_cohesion_scale",
            unit="mean Likert score, 5 items",
            component_keys=pair.exposure.member_keys,
        ),
        outcome=V("m2:Q5.8"),
        expected_direction=ExpectedDirection(direction=Direction.decrease),
        falsifier=(f"CI excludes a {falsifier_value:.0f} percentage-point difference "
                   "in hypertension prevalence between the highest and lowest "
                   "cohesion quintile."),
        falsifier_threshold=FalsifierThreshold(value=falsifier_value,
                                               unit="percentage points",
                                               comparator=Comparator.gte),
        model_spec=ModelSpec(
            form="modified Poisson regression with robust variance",
            unit_of_analysis=UnitOfAnalysis.participant,
            clustering="cluster-robust SE at community area"),
        adjusted_covariates=[
            adj("m1:Q3.11", CausalRole.confounder,
                "Education shapes both where a person can afford to live and their "
                "risk of hypertension.",
                "Common cause of exposure and outcome; fixed well before exposure."),
            adj("m1:Q5.4", CausalRole.confounder,
                "Household income determines neighbourhood options and access to care.",
                "Common cause; interpretable only jointly with household size."),
            adj("m1:Q5.5", CausalRole.precision,
                "Household size rescales income into a per-person standard of living.",
                "Precision variable; income alone is uninterpretable without it."),
            adj("m1:Q3.10", CausalRole.proxy,
                "Race stands in for structural exposure to residential disinvestment.",
                "Included as a proxy for structural exposure, not a biological cause.",
                proxy_for="structural exposure to residential disinvestment"),
        ],
        excluded_variables=[
            adj("m2:Q5.10", CausalRole.descendant_of_outcome,
                "Being prescribed antihypertensive medicine follows a hypertension "
                "diagnosis and cannot precede it.",
                "Descendant of the outcome; conditioning on it induces selection bias."),
            adj("m2:Q5.9", CausalRole.descendant_of_outcome,
                "Age at first diagnosis is defined only for those already diagnosed.",
                "Descendant of the outcome and undefined for the unexposed stratum."),
            adj("m3:Q16.3", CausalRole.mediator,
                "Low cohesion reduces outdoor activity, which raises blood pressure.",
                "Adjusting for this attenuates the very pathway under study."),
        ],
        undetermined_covariates=[
            adj("m1:Q4.1", CausalRole.confounder_or_mediator,
                "Employment may precede neighbourhood selection or follow from it; "
                "the instrument does not date either.",
                "Temporality unrecoverable from a two-column codebook. Ships as a "
                "paired sensitivity specification: with and without.")
        ],
        estimability=Estimability(
            analytic_n=None,
            n_source=NSource.unknown,
            modules_required=["1", "2", "3"],
            exposure_contrast="highest versus lowest cohesion quintile",
            collinearity_max=None,
            smallest_detectable_effect=SmallestDetectableEffect(
                value=sde_value, unit="percentage points", at_n=sde_at_n,
                assumptions=sde_assumptions),
        ),
        access=Access(decision=GateDecision.pass_, reconstruction_load=0, budget=3,
                      location_bearing_keys=[],
                      per_place_working="no location-bearing variable named; "
                                        "community-area clustering is a model term, "
                                        "not a protocol variable"),
        derivation_ref="social_cohesion_scale",
        selection_rationale=SelectionRationale(
            selection_mode=SelectionMode.enumerated_screen,
            screened_from=counts["enumerated"],
            prior_work="unscored: literature tools absent in benchmark mode",
            why_this_cohort="cross-module perceptual exposure against a "
                            "self-reported diagnosis, the canonical COMPASS design"),
        provenance=Provenance(dictionary_version=version, module_version="0.1",
                              prompt_hash="unset", model_id="none: hand-specified "
                              "acceptance-test target"),
        status=Status.draft,
        blocked_on=["module_co_completion_counts"],
    )

    print("\n" + "=" * 74)
    print("THE RECORD THE SPECIFIER MUST RETURN — validated")
    print("=" * 74)
    print(f"  {p.protocol_id}  status={p.status.value}  blocked_on="
          f"{[b.value for b in p.blocked_on]}")
    print(f"  exposure   derivation:{p.exposure.derivation_id} "
          f"({len(p.exposure.component_keys)} items)")
    print(f"  outcome    {p.outcome.key}")
    print(f"             \"{p.outcome.quoted_wording[:60]}...\"")
    print(f"  model      {p.model_spec.form}, per {p.model_spec.unit_of_analysis.value}")
    print("\n  ADJUSTED")
    for e in p.adjusted_covariates:
        print(f"    {e.variable.key:12s} {e.role.value:22s} {e.mechanism[:44]}")
    print("  EXCLUDED  (an omission you can audit)")
    for e in p.excluded_variables:
        print(f"    {e.variable.key:12s} {e.role.value:22s} {e.mechanism[:44]}")
    print("  UNDETERMINED  (honest abstention, ships as a paired sensitivity spec)")
    for e in p.undetermined_covariates:
        print(f"    {e.variable.key:12s} {e.role.value:22s} {e.mechanism[:44]}")
    print(f"\n  estimability  n={p.estimability.analytic_n} "
          f"source={p.estimability.n_source.value}  "
          f"SDE={p.estimability.smallest_detectable_effect.value} "
          f"{p.estimability.smallest_detectable_effect.unit} "
          f"at n={p.estimability.smallest_detectable_effect.at_n}")
    print(f"  falsifier     {p.falsifier_threshold.value} "
          f"{p.falsifier_threshold.unit} — above the SDE, so it is falsifiable")
    print(f"  record_hash   {p.record_hash()}   <- k=5 samples dedup on this")

    print("\n" + "=" * 74)
    print("WHY status IS draft AND NOT ready_for_review")
    print("=" * 74)
    print("  n_source is unknown because m1 x m2 x m3 co-completion counts do not")
    print("  exist. derive_status() refuses ready_for_review while that holds. The")
    print("  protocol is still fully specified and fully auditable — it simply")
    print("  states what it does not know instead of inventing an n.")

    return p


if __name__ == "__main__":
    main()
