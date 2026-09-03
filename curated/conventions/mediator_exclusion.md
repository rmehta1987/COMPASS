# mediator exclusion
**Topic id:** `mediator_exclusion` · authored 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

Adjusting for a mediator attenuates the total effect under study and changes the
estimand. This is the single most consequential covariate error a protocol can make,
because it is invisible in the output — the model still fits and the coefficient is
still reported.

**Convention.** A variable that lies on the causal path from exposure to outcome is
excluded, with role `mediator` and a mechanism sentence naming the path. It is never
silently omitted: an omitted-by-accident variable and an omitted-on-purpose one are
indistinguishable unless the exclusion is stated.

**Worked case in this instrument.** For any protocol whose exposure is perceived crime
(`m3:Q16.2`), the item "how often do you choose not to exercise outdoors due to concerns
over crime" (`m3:Q16.3`) is a mediator, not a confounder. Same for `m3:Q16.4`.

**Where a mediation design is wanted,** that is a different protocol with a different
estimand, and pair enumeration cannot express it. Park it and say so.
