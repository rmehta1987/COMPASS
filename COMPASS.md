P-014                                            build 8573993d8450

Is perceived neighbourhood crime associated with lower total physical
activity, independent of socioeconomic position?

EXPOSURE   m3:Q16.2  "How strongly do you agree or disagree with this
           statement: Crime and violence are a serious problem…"

OUTCOME    MET-hours/week, derived from 30 items (m3:Q2.33–Q2.62)
           seasonal weighting · compendium v2011
           ⚠ response coding not in the public codebook

MODEL      Linear regression · one row per participant
           cluster-robust SE at community area

ADJUSTED   m1:Q3.11  education        common cause
           m1:Q5.4   income          common cause  ┐ jointly; income alone
           m1:Q5.5   household size  precision     ┘ is uninterpretable
           m1:Q3.10  race            proxy for structural exposure

NOT ADJUSTED
  m3:Q16.3  "choose not to exercise outdoors due to crime"
            MEDIATOR — adjusting attenuates the effect studied
  m3:Q16.1_1 "people willing to help their neighbors"
            possible COLLIDER — contestable, flagged for you

EXPECTED   negative, plausibly 2–5 MET-hours/week across the Likert range
FALSIFIER  CI excludes a decrease of 1 MET-hour/week

n unknown — module 1 × module 3 co-completion count unavailable
Reconstruction load 0 · no location variables · gate: pass

──────────────────────────────────────────────────────────────
Completeness  1  2  3  4  5        Accuracy  1  2  3  4  5

Any variable that does not measure what this claims: ______________