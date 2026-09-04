# clustering: community area
**Topic id:** `clustering:community_area` · authored 2026-08-26 · revised 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

Community area is the coarsest place label a protocol on this instrument can name.
Two participants who share one share their place, so their residuals are not
independent and naive standard errors are anticonservative. That is a property of
the sampling unit, not a finding about any cohort.

**Convention.** Report cluster-robust standard errors at the community area for any
model whose exposure is measured at, or plausibly varies by, place. Do not cluster at
census tract in v1: tract is not present as a variable in the survey codebooks, and a
clustering level the instrument cannot name is not specifiable.

**Consequence for the record.** `model_spec.clustering` is a required string. Where an
exposure is person-level and place-invariant (e.g. age at first diagnosis), state
`no clustering: exposure does not vary by place` rather than leaving it implicit.

**Limit.** The realised number of clusters is UNKNOWN and this document will not
supply one. It is a count of participants' places, and participant counts do not exist
in this environment — see `small_cells`. What is knowable without them is the shape:
the number of clusters is bounded by the number of community areas the city defines,
which is small enough that the small-cluster regime is the default assumption rather
than the exception, and cluster-robust standard errors are downward biased there.
State the cluster count your design assumes, state that it is an assumption, and put
both in the protocol rather than in a limitations paragraph. Do not assert a count.
