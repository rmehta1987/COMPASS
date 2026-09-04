# small cells
**Topic id:** `small_cells` · authored 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

**Convention.** Never derive power, prevalence or analytic n from cohort size. A
recruitment count is not an analytic denominator: realised n depends on which modules a
participant completed and which items they answered, and both are unknown until the
study team supplies counts. Treat the gap between them as unbounded rather than
estimating it.

**Where n is unavailable,** `analytic_n` is null and `n_source` is `unknown`, and the
protocol cannot reach `ready_for_review`. A fabricated n is worse than an admitted gap.

**Smallest detectable effect** is reported as a curve across candidate n values with the
assumption set recorded, not as a scalar. It is computable from formulas alone and needs
no data, which is what lets the field stay honest while n is unknown.

**Rare outcomes.** Where an outcome's expected count at any plausible n is too small to
support the stated model form, the pair is parked at S3 with reason
`outcome_prevalence_too_low` — a deterministic ground, not a judgement.
