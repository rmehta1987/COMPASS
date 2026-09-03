# adjustment set: area-level exposure
**Topic id:** `adjustment_set:area_exposure` · authored 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

When the exposure is a linked place-based measure (`linked:` registry), the
adjustment set is not the same as for a survey item. Which measures that registry
holds is a question for `registry_coverage()`, not for this document.

**Convention.**
1. Adjust for individual socioeconomic position (education, income with household size)
   as a common cause of both residential location and the outcome.
2. Do **not** adjust for one area-level index alongside another area-level exposure
   when the first is a proxy that partly *contains* the second. State this exclusion
   with role `not_a_cause_of_either` or `descendant_of_exposure` and a mechanism sentence.
3. Race is included as a `proxy`, with `proxy_for` naming structural exposure to
   residential disinvestment — never as a biological cause.

**Consequence.** A protocol whose exposure is an `AreaMeasureRef` and whose adjusted set
contains no individual-level socioeconomic variable should be treated as under-specified.
