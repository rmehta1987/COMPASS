"""generate/run_specifier.py — the Specifier, end to end, on one real pair.

    ./.venv/bin/python generate/run_specifier.py

No weights are wired up in this environment (no keys set, ports 8000/8080/11434
closed), so the model's two replies come from a fixture. Everything AROUND the
replies is the real system: the funnel produces the pair, the registry builds the
toolset, the tools execute against the built dictionary and return real research
logs, the gate inspects the real call log, the record is validated by the real
schema, and selection reads the real records.

That is the point of the seam. What is proven here is the control flow — the part
that deterministic code owns. What is not proven here is the model's judgment,
which cannot be proven without weights and is exactly what the benchmark is for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.backends import Reply, ScriptedBackend, tool_call  # noqa: E402
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
from agent.specifier import MAX_TRANSDUCE_ATTEMPTS, specify  # noqa: E402
from generate.funnel import load_constructs, run  # noqa: E402
from generate.live_specifier import run_identity  # noqa: E402

DICT = json.loads((ROOT / "build" / "dictionary.json").read_text())
W = {e["key"]: e["question_text"] for e in DICT["entries"]}
V = lambda k: VariableRef(key=k, quoted_wording=W[k])                  # noqa: E731


def adj(k, role, mech, just, **kw):
    return CausalAdjustment(variable=V(k), mechanism=mech, justification=just,
                            role=role, **kw)


# --------------------------------------------------------------------------- #
# the fixture record — what a correct transduction of the analysis looks like
# --------------------------------------------------------------------------- #

def fixture(version, screened_from, shuffle=False) -> str:
    adjusted = [
        adj("m1:Q3.11", CausalRole.confounder,
            "Education shapes both where a person can afford to live and their risk "
            "of hypertension.",
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
    ]
    if shuffle:                      # same set, different order: must dedup to one
        adjusted = [adjusted[2], adjusted[0], adjusted[3], adjusted[1]]

    p = ProtocolSpecification(
        protocol_id="P-022", dictionary_version=version,
        question=("Is lower perceived neighbourhood social cohesion associated with "
                  "higher self-reported hypertension, independent of socioeconomic "
                  "position?"),
        exposure=DerivationRef(derivation_id="social_cohesion_scale",
                               unit="mean Likert score, 5 items",
                               component_keys=[f"m3:Q16.1_{i}" for i in range(1, 6)]),
        outcome=V("m2:Q5.8"),
        expected_direction=ExpectedDirection(direction=Direction.decrease),
        # 9 pp AT A STATED n, not the 27 pp this fixture carried for one day and
        # not the 3 pp it carried before that. The 3 pp version asserted a number
        # no tool in its own log returned. The 27 pp version was what pinning the
        # SMALLEST candidate n as a universal floor costs: baseline_prevalence
        # 0.32 floors at 26.14 pp for n=100, so the only way to pass was to claim
        # a falsifier no epidemiologist would write. A rule satisfied by making
        # the claim absurd fails as surely as one satisfied vacuously. The record
        # now names the candidate n it claims detectability at and is checked
        # there. The numbers are points on DETECTABILITY_N_GRID and go stale if
        # it moves; test_the_fixtures_detectability_numbers_are_on_the_
        # environments_curve turns that into one legible failure, not seven.
        falsifier=("CI excludes a 9 percentage-point difference in hypertension "
                   "prevalence between the highest and lowest cohesion quintile, "
                   "at a realised n of 1000."),
        falsifier_threshold=FalsifierThreshold(value=9.0, unit="percentage points",
                                               comparator=Comparator.gte),
        model_spec=ModelSpec(form="modified Poisson regression with robust variance",
                             unit_of_analysis=UnitOfAnalysis.participant,
                             clustering="cluster-robust SE at community area"),
        adjusted_covariates=adjusted,
        excluded_variables=[
            adj("m2:Q5.10", CausalRole.descendant_of_outcome,
                "Being prescribed antihypertensive medicine follows a hypertension "
                "diagnosis and cannot precede it.",
                "Descendant of the outcome; conditioning on it induces selection bias."),
            adj("m3:Q16.3", CausalRole.mediator,
                "Low cohesion reduces outdoor activity, which raises blood pressure.",
                "Adjusting for this attenuates the very pathway under study."),
        ],
        undetermined_covariates=[
            adj("m1:Q4.1", CausalRole.confounder_or_mediator,
                "Employment may precede neighbourhood selection or follow from it; "
                "the instrument does not date either.",
                "Temporality unrecoverable from a two-column codebook. Ships as a "
                "paired sensitivity specification: with and without."),
        ],
        estimability=Estimability(
            analytic_n=None, n_source=NSource.unknown,
            modules_required=["m1", "m2", "m3"],
            exposure_contrast="highest versus lowest cohesion quintile",
            collinearity_max=None,
            # curve left empty on purpose: apply_tool_authority writes it from
            # estimate_detectability's own return value, and a fixture that
            # hand-wrote one would stop testing that it does.
            smallest_detectable_effect=SmallestDetectableEffect(
                value=8.27, unit="percentage points", at_n=1000,
                assumptions="two_sided_alpha=0.05; power=0.8; "
                            "baseline_prevalence=0.32; allocation=1:1; "
                            "test=two-proportion normal approximation")),
        access=Access(decision=GateDecision.pass_, reconstruction_load=0, budget=3,
                      location_bearing_keys=[],
                      per_place_working="no location-bearing variable named"),
        derivation_ref="social_cohesion_scale",
        selection_rationale=SelectionRationale(
            selection_mode=SelectionMode.enumerated_screen,
            screened_from=screened_from,
            prior_work="unscored: literature tools absent in benchmark mode",
            why_this_cohort="cross-module perceptual exposure against a self-reported "
                            "diagnosis, the canonical COMPASS design"),
        provenance=Provenance(dictionary_version=version, module_version="0.1",
                              prompt_hash="fixture", model_id="scripted"),
        status=Status.draft, blocked_on=["module_co_completion_counts"])
    return p.model_dump_json()


ANALYSIS = """\
The exposure construct group:m3:Q16.1 is a five-item grid battery on perceived
neighbourhood social cohesion; resolve_variable returned outcome='group', so it
cannot be an anchor directly. list_derivations offers social_cohesion_scale, a
signed 5-item mean, which I name rather than writing a recipe. The outcome
m2:Q5.8 resolves uniquely; I quote its wording verbatim.

Expected direction: decrease. Lower cohesion, higher hypertension.

Confounders are socioeconomic: education (m1:Q3.11) and income (m1:Q5.4) are
common causes of both neighbourhood of residence and cardiovascular risk.
Household size (m1:Q5.5) is not a confounder but a precision variable — income
without it is uninterpretable. Race (m1:Q3.10) enters explicitly as a proxy for
structural exposure to residential disinvestment, not as a biological cause.

Two exclusions, both stated rather than silent. m2:Q5.10 (antihypertensive
medication) is a descendant of the outcome; conditioning on it induces selection
bias. m3:Q16.3 is a mediator — cohesion acts partly through outdoor activity — and
adjusting for it would attenuate the pathway under study. get_design_convention
on mediator_exclusion supports keeping it out of the primary model.

m1:Q4.1 (employment) is undetermined: it may precede neighbourhood selection or
follow from it, and the two-column codebook dates neither. It ships as a paired
sensitivity specification rather than a guess.

estimate_n over the full key set spans modules 1, 2 and 3 and returned n=null,
n_source=unknown, blocked on module_co_completion_counts. I do not invent an n.
estimate_detectability at baseline prevalence 0.32 returns a curve, not a
number: 26.14 percentage points at n=100 falling to 2.61 at n=10000. The
analytic n is unknown, so I state the candidate this design claims
falsifiability at — n=1000, where the smallest detectable effect is 8.27
percentage points — and set a 9-point threshold above it. That claim is
contingent on reaching n=1000 and the record stays draft on
module_co_completion_counts until it can be checked. check_access returns pass
with reconstruction load 0.
"""

REASON_CALLS_A = [
    tool_call("resolve_variable", {"key": "m3:Q16.1"}, "c1"),
    tool_call("resolve_variable", {"key": "m2:Q5.8"}, "c2"),
    tool_call("get_item_group", {"group_id": "group:m3:Q16.1"}, "c3"),
    tool_call("list_derivations", {}, "c4"),
]
# FIXTURE FIXED, NOT THE RULE. Until 2026-08-26 both calls named six keys while
# the record they justify names eleven: the exposure derivation's five component
# keys collapsed to one, and the undetermined covariate was missing entirely. The
# environment's access verdict and module list were then stamped onto a record
# describing a larger design than the one the tools had seen. That is T3, and the
# fixture was one of its instances rather than a bystander.
FIXTURE_DESIGN_KEYS = ["m3:Q16.1_1", "m3:Q16.1_2", "m3:Q16.1_3", "m3:Q16.1_4",
                       "m3:Q16.1_5", "m2:Q5.8", "m1:Q3.11", "m1:Q5.4",
                       "m1:Q5.5", "m1:Q3.10", "m1:Q4.1"]
REASON_CALLS_B = [
    tool_call("get_design_convention", {"topic": "mediator_exclusion"}, "c5"),
    tool_call("get_design_convention", {"topic": "clustering:community_area"}, "c6"),
    tool_call("estimate_n", {"keys": FIXTURE_DESIGN_KEYS}, "c7"),
    tool_call("estimate_detectability", {"baseline_prevalence": 0.32}, "c8"),
    tool_call("check_access", {"keys": FIXTURE_DESIGN_KEYS}, "c9"),
]


def demo_script(good: str, shuffled: str) -> list[Reply]:
    """The five scripted samples this demo replays.

    Deliberately not five identical ones: the interesting behaviour is what
    happens when they differ. Seeds 0 and 1 are the same record, seed 2 reorders
    its covariates, seed 3 never reaches check_access, and seed 4 never produces
    a valid object.

    BROKEN FROM 2026-08-27 UNTIL 2026-08-28, and the break is why the last list
    is generated. MAX_TRANSDUCE_ATTEMPTS went from 2 to 4 that day; seed 4's two
    hand-written rejections then ran the ScriptedBackend dry on the third
    attempt, and `python generate/run_specifier.py` — the command this module's
    own docstring gives — died with "ScriptedBackend exhausted after 19 calls".
    A count written by hand beside a bound that moves is a stale count waiting
    to happen, so it is now read off the bound.

    Args:
        good: The valid fixture record, as JSON.
        shuffled: The same record with its covariates reordered.

    Returns:
        The reply script, in the order the five samples consume it.
    """
    reason = [Reply(tool_calls=REASON_CALLS_A), Reply(tool_calls=REASON_CALLS_B),
              Reply(content=ANALYSIS)]
    return [
        *reason, Reply(content=good),                              # seed 0
        *reason, Reply(content=good),                              # seed 1: dup
        *reason, Reply(content=shuffled),                          # seed 2: reorder
        Reply(tool_calls=REASON_CALLS_A[:2]), Reply(content=ANALYSIS),  # seed 3: gate
        *reason,                                                   # seed 4: never valid
        *[Reply(content='{"protocol_id":"P-022","question":"too short"}')
          for _ in range(MAX_TRANSDUCE_ATTEMPTS)],
    ]


def main() -> None:
    C, version = load_constructs()
    exposures = sorted([c for c in C.values()
                        if c.module == "3" and c.base_id.startswith("Q16.")],
                       key=lambda c: c.base_id)
    outcomes = sorted([c for c in C.values()
                       if c.module == "2" and c.base_id.startswith("Q5.")],
                      key=lambda c: c.base_id)
    cands, counts = run(exposures, outcomes)
    pair = next(c for c in cands if c.exposure.construct_key == "m3:Q16.1"
                and c.outcome.construct_key == "m2:Q5.8")

    backend = ScriptedBackend(demo_script(
        fixture(version, counts["enumerated"]),
        fixture(version, counts["enumerated"], shuffle=True)))
    # The same wrapper the live driver uses. protocol_id, dictionary_version and
    # all four provenance fields are written here from what this process already
    # knows; the fixture's own values for them are overwritten and never read.
    identity = run_identity(pair, version, counts["enumerated"], backend.name)
    res = specify(backend, pair, k=5, mode="benchmark",
                  parked_dir=ROOT / "parked", identity=identity)

    bar = "=" * 76
    print(bar); print("SPECIFIER  —  one pair, k=5, benchmark registry"); print(bar)
    print(f"  pair            {pair.pair_id}")
    print(f"  dictionary      {version}")
    print(f"  backend         {backend.name}  ({backend.i} model calls consumed)")

    print(f"\n{bar}\nPER-SAMPLE\n{bar}")
    print(f"  {'seed':<5}{'gate':<16}{'steps':<7}{'tool calls made':<38}hash")
    for a in res.attempts:
        h = a.protocol.record_hash() if a.protocol else "-"
        names = ", ".join(dict.fromkeys(a.tool_names)) or "-"
        print(f"  {a.seed:<5}{a.gate:<16}{a.steps:<7}{names[:36]:<38}{h}")
        if a.error:
            print(f"        └─ {a.error.splitlines()[0][:110]}")

    print(f"\n{bar}\nSELECTION\n{bar}")
    print(f"  yield           {res.yield_line}")
    print(f"  {res.reason}")
    print("  seeds 0,1 identical and seed 2 reorders the same covariate set")
    print("  → all three collapse to ONE record: dedup is by typed-record set")
    print("    equality, not by string, so covariate order is not a difference.")
    p = res.selected
    print(f"\n  selected        {p.protocol_id}  {p.record_hash()}  status={p.status.value}")
    print(f"  exposure        derivation:{p.exposure.derivation_id}")
    print(f"  outcome         {p.outcome.key}  \"{p.outcome.quoted_wording[:44]}…\"")
    print(f"  adjusted        {[e.variable.key for e in p.adjusted_covariates]}")
    print(f"  excluded        {[e.variable.key for e in p.excluded_variables]}")
    print(f"  undetermined    {[e.variable.key for e in p.undetermined_covariates]}")
    print(f"  n               {p.estimability.analytic_n} "
          f"({p.estimability.n_source.value}) blocked_on "
          f"{[b.value for b in p.blocked_on]}")
    sde = p.estimability.smallest_detectable_effect
    print(f"  falsifier       {p.falsifier_threshold.value} pp  >  SDE "
          f"{sde.value} pp at n={sde.at_n}  (both from the run's own tool log)")
    print(f"  access          {p.access.decision.value}, load "
          f"{p.access.reconstruction_load}/{p.access.budget}")
    print(f"  parked          {len(res.parked)} record(s)")

    print(f"\n{bar}\nWHAT THE MODEL DID NOT DO\n{bar}")
    for line in ("chose the pair            — enumeration did",
                 "decided k, or when to stop — code did",
                 "ranked its own outputs     — _rank reads the records only",
                 "asserted any lookup fact   — every key, wording and number came "
                 "from a tool",
                 "reasoned and formatted at  — two calls; the schema constrained "
                 "only the second\n     the same time"):
        print(f"     {line}")


if __name__ == "__main__":
    main()
