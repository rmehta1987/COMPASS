# place-level versus person-level claims
**Topic id:** `place_level_vs_person_level_claims` · authored 2026-08-26 · unconfirmed by study team
**Source:** `authored-unconfirmed` — written by the pipeline author, not supplied or reviewed by the study team.

A measure attached to a place and a measure reported by a person licence different
claims, and the record must not blur them.

**Convention.**
1. An `AreaMeasureRef` supports a claim about *places and the people living in them*. It
   does not support a claim about individual behaviour without an explicit assumption
   that the area value applies to the individual — state that assumption in the
   justification or do not make the claim.
2. A perceived-environment item (`m3:Q16.*`) is a **person-level** measure of perception.
   It is not a measurement of the neighbourhood. A protocol using it must phrase its
   question as perception, not as environment.
3. Ecological aggregates may not be used to support individual-level effect claims.

**Consequence for the record.** `question` and `expected_direction` must be phrased at
the level the exposure actually measures. "Perceived crime" and "crime" are different
exposures, and only one of them is in this instrument.
