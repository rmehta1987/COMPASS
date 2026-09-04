"""benchmark/prevalence_key.py — held-out answer key for outcome prevalence.

WHY THIS EXISTS. `estimate_detectability` takes one input the model asserts and
the environment cannot supply: `baseline_prevalence`. No tool returns a
prevalence, the dictionary cannot yield one — `value_labels` are null for every
item and no response data exists in this project — so the number is the model's,
unverifiable, and it scales the smallest detectable effect it is then judged by
(sde is proportional to sqrt(p(1-p))). Measured over `run/*.tool_log.jsonl` on
2026-08-27: 10 saved runs, one `estimate_detectability` call each, all for the
same hypertension outcome, and the caller chose 0.35 five times and 0.25, 0.28,
0.30, 0.32 and 0.40 once each — a 13.1% swing in its own pass mark.

Two things follow, and they are separate. `env/tools.py` now judges the record
against the caller-independent worst-case curve, so the assertion no longer moves
the bar — that is the control. This file is the other half: the assertion is a
scored quantity in the rediscovery benchmark, and this is what it is scored
against.

WHY UNDER benchmark/, AND WHY THAT IS NOT NEGOTIABLE. This is paper content —
figures read out of published analyses of this cohort. `curated/`, `env/`, an
`agent/` docstring, a prompt and a tool return value are all model-visible, and
`tests/test_contamination_surface.py` scans the first three for markers.
`benchmark/` is scanned by nothing on a tool path, and
`check_holdout_not_reachable` asserts that `env/tools.py` does not so much as
name the directory. A prevalence figure that reaches `curated/` hands the model
the answer to the quantity this file exists to score, which is worse than not
scoring it. Verified on the commit that added this file: `surface_hash` moved
only for the tool-text edits made alongside it, and no figure below appears in
any of the 37 model-visible surfaces.

WHAT AN ABSENT VALUE MEANS. `value=None` with `printed_as=""` means the paper
reports no prevalence for that outcome and none is computable from what it
prints. It is recorded, not skipped, and never filled in from a related figure:
an absent value is data, an inferred one is fabrication. Where a figure is
computed rather than printed, `computed_from` carries the arithmetic so a reader
can check it.

THE IDENTIFICATION CAVEAT — READ THIS BEFORE SCORING ANYTHING WITH THIS FILE.

    A single asserted prevalence compared against a single published figure is
    NOT a recall test, and a scorer that reports it as one will be wrong in the
    direction that flatters the system.

    Hypertension prevalence in a low-income, predominantly Black, urban US adult
    population is widely published in national survey data. A model that has
    never heard of this cohort produces the same 30-40% range from general
    knowledge alone. The caller's observed 0.25-0.40 spread is inside that range,
    so its distance from any figure in this file measures general epidemiological
    knowledge, not knowledge of these papers. Closeness here is not evidence.

    What could be identifying is a DIFFERENTIAL: the caller's asserted prevalence
    for outcomes this cohort has published on, against its asserted prevalence
    for matched outcomes it has not, drawn from the same region of the same
    instrument. Only the first arm has a cohort-specific figure to recall. If the
    caller is no closer to the cohort's own value on the published arm than
    general knowledge explains, nothing has been identified; if it is
    systematically closer there and not on the control arm, something has.

    Two things that differential needs, and their status here. (1) Both arms are
    populated below: `arm="published"` rows carry the cohort's figure,
    `arm="matched_control"` rows carry `value=None` by construction, because the
    absence of a published figure is what makes them controls. (2) The comparison
    is against a GENERAL-POPULATION reference for the same outcome, which both
    arms have and only one arm has a cohort figure to beat.
    `general_population_reference` is empty on every row: it is NOT sourced, and
    a scorer must refuse to run rather than treat an empty string as zero or
    invent one. Sourcing it is the next piece of work, and it is deliberately not
    done here because a reference figure guessed from memory would silently
    become the thing the whole test rests on.

    A third limit, stated because it bounds the control arm rather than the
    method: `arm="matched_control"` means "no reported prevalence was found in
    the RETRIEVABLE text of the sixteen-paper inventory". `RETRIEVABILITY` below
    records which papers were read in full and which only in abstract. Two were
    abstract-only, so a figure inside their tables would not have been seen.

WHAT THIS FILE IS NOT. It is not a scorer, and it is not an exclusion list. The
benchmark grades rediscovery of published designs, so a published pair is the
only kind with ground truth. Nothing here says a pair may not be used.
"""

from __future__ import annotations

from typing import NamedTuple

#: Every row is `paper_free`, and that is a finding rather than a formality.
#: The environment supplies no prevalence for any outcome by any route: no tool
#: returns one, `build/dictionary.json` counts items and not participants, and
#: `value_labels` are null throughout. So no prevalence a caller states can be
#: environment-forced, and the whole column exists to join against answer keys
#: for design elements — clustering, contrast, adjustment set — where the split
#: is real and recovering the environment-forced ones proves nothing.
IDENTIFICATION_VALUES = ("paper_free", "environment_forced")

#: How much of each paper was readable when this key was built, 2026-08-27, via
#: NCBI E-utilities. `full_text` means the PMC record carried the body; the
#: `abstract` entries are papers whose PMC record is metadata-only or absent, so
#: a figure printed in a table there was not visible and their "reports none"
#: rows are weaker claims than the rest.
RETRIEVABILITY: dict[str, str] = {
    "32938600": "full_text", "36065817": "full_text", "37252073": "full_text",
    "38715087": "full_text", "38397711": "full_text", "32542493": "abstract",
    "33088675": "full_text", "36702470": "abstract", "36823587": "abstract",
    "37879000": "abstract", "37884074": "full_text", "38961645": "abstract",
    "39217205": "full_text", "39238838": "full_text", "41883377": "full_text",
    "42034153": "full_text",
}


class Prevalence(NamedTuple):
    """One outcome, and what the published record says its prevalence is.

    Attributes:
        pmid: PubMed id of the paper the figure comes from, or "" for a
            matched-control row, which by definition has no paper.
        outcome: Plain-language name of the quantity.
        definition: How the paper defined and ascertained it. Two papers can
            report very different prevalences for "hypertension" and both be
            right, so the definition is part of the answer, not an annotation.
        ascertainment: One of self_report, measured, lab, performance,
            administrative. `measured` and `self_report` are not comparable and
            must never be pooled.
        role: `outcome` when the paper analysed it as its outcome, `covariate`
            when it appears only in a descriptive table, `recruitment` for a
            response rate. A covariate figure is still a published figure about
            this cohort, so it is recorded, but it is weaker evidence of what the
            paper is "about".
        arm: `published` or `matched_control`. See the identification caveat.
        identification: `paper_free` or `environment_forced`; see
            IDENTIFICATION_VALUES. Uniformly `paper_free` in this file.
        instrument_key: The key in this instrument that measures the same thing,
            or None where the instrument has no such item. This is the join to
            what the caller actually asserted a prevalence for.
        instrument_region: Coarse region of the instrument, for matching a
            control to a published outcome. Rows sharing a region are comparable
            in a way rows from different regions are not.
        value: The proportion, 0-1, or None when the paper reports none.
        printed_as: The figure exactly as the paper prints it, "" when absent.
            Kept verbatim so a reader can find it without re-deriving anything.
        interval: Confidence interval as printed. Empty on every row here: none
            of these papers gives one for a prevalence.
        subgroup_range: (low, high) across the subgroups the paper prints, as
            proportions, or None when it prints no subgroup breakdown.
        subgroup_basis: What the subgroups are, when subgroup_range is set.
        analytic_sample: The sample the figure was computed on, in the paper's
            own terms, including its n.
        numerator: Count with the outcome, when printed.
        denominator: Count the figure is over, when printed or derivable.
        computed_from: The arithmetic, when the figure is computed from printed
            counts rather than printed as a percentage. Empty when printed.
        source_location: Where in the paper it appears.
        general_population_reference: A comparable general-population figure.
            EMPTY ON EVERY ROW — not sourced. A scorer must refuse to run rather
            than substitute anything for it. See the identification caveat.
        match_basis: For a matched_control row, why it is a fair control for the
            published rows in the same region.
    """

    pmid: str
    outcome: str
    definition: str
    ascertainment: str
    role: str
    arm: str
    identification: str
    instrument_key: str | None
    instrument_region: str | None
    value: float | None
    printed_as: str
    interval: str = ""
    subgroup_range: tuple[float, float] | None = None
    subgroup_basis: str = ""
    analytic_sample: str = ""
    numerator: int | None = None
    denominator: int | None = None
    computed_from: str = ""
    source_location: str = ""
    general_population_reference: str = ""
    match_basis: str = ""


#: Ordered by PMID within arm, for reading. Every paper in the sixteen-paper
#: inventory appears at least once, including those that report no prevalence at
#: all: "reports none" is the answer for that paper and has to be findable here,
#: or the next reader re-derives it and guesses.
PREVALENCE_KEY: tuple[Prevalence, ...] = (

    # ---- 32938600  Cohort profile, BMJ Open 2020 -------------------------- #
    Prevalence(
        pmid="32938600", outcome="hypertension",
        definition="self-reported physician-told diagnosis of hypertension",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.8",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.380, printed_as="38.0",
        analytic_sample="cohort enrolled to date, n=7728",
        numerator=2835, denominator=7728,
        source_location="Table 3, Medical history (self-report)"),
    Prevalence(
        pmid="32938600", outcome="hypertension",
        definition="measured as hypertensive at enrolment; the paper does not "
                   "state the threshold or the denominator for this figure",
        ascertainment="measured", role="covariate", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.664, printed_as="66.4%",
        analytic_sample="cohort at enrolment; denominator not printed with the "
                        "figure (Table 3 gives BP means over n=6646 systolic)",
        source_location="abstract, Findings to date"),
    Prevalence(
        pmid="32938600", outcome="type 2 diabetes",
        definition="self-reported physician-told diagnosis",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.6",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.101, printed_as="10.1",
        analytic_sample="cohort enrolled to date, n=7728",
        numerator=781, denominator=7728, source_location="Table 3"),
    Prevalence(
        pmid="32938600", outcome="high blood cholesterol",
        definition="self-reported physician-told diagnosis",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.14",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.242, printed_as="24.2",
        analytic_sample="cohort enrolled to date, n=7728",
        numerator=1874, denominator=7728, source_location="Table 3"),
    Prevalence(
        pmid="32938600", outcome="heart attack / myocardial infarction",
        definition="self-reported physician-told diagnosis",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.15#1_26",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.047, printed_as="4.7",
        analytic_sample="cohort enrolled to date, n=7728",
        numerator=367, denominator=7728, source_location="Table 3"),
    Prevalence(
        pmid="32938600", outcome="history of cancer",
        definition="self-reported personal history of cancer",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="m2:Q12 cancer history and screening",
        value=0.057, printed_as="5.7",
        analytic_sample="cohort enrolled to date, n=7728",
        numerator=441, denominator=7728, source_location="Table 3"),

    # ---- 36065817  Circ Cardiovasc Qual Outcomes 2022 --------------------- #
    # The paper the falsifier argument most nearly concerns: its outcome is
    # hypertension and its instrument item is the one the caller asserted a
    # prevalence for. Note the three figures below are all "hypertension" and
    # span 43.9% to 78.7%; a scorer that does not carry `definition` through
    # will grade against whichever it happens to pick.
    Prevalence(
        pmid="36065817", outcome="hypertension, self-reported",
        definition="'Has a doctor ever told you that you have hypertension?', "
                   "answered yes",
        ascertainment="self_report", role="outcome", arm="published",
        identification="paper_free", instrument_key="m2:Q5.8",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.439, printed_as="43.9%",
        subgroup_range=(0.407, 0.472),
        subgroup_basis="quartiles of the primary-care accessibility score",
        analytic_sample="n=5096 analysed; this figure is over the 5053 with a "
                        "non-missing self-report (2833 no + 2220 yes)",
        numerator=2220, denominator=5053,
        source_location="Results text and Table 1"),
    Prevalence(
        pmid="36065817", outcome="hypertension, measured (2017 ACC/AHA)",
        definition="average SBP >=130 mm Hg or average DBP >=80 mm Hg",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.787, printed_as="78.7%",
        analytic_sample="n=5096", source_location="abstract and Results"),
    Prevalence(
        pmid="36065817", outcome="hypertension, measured (pre-2017 guideline)",
        definition="the 140/90 mm Hg threshold, reported alongside the 130/80 one",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.536, printed_as="53.6%",
        analytic_sample="n=5096",
        source_location="Results, with supplemental table S2"),
    Prevalence(
        pmid="36065817", outcome="unaware hypertension",
        definition="measured hypertensive and did not self-report hypertension; "
                   "denominator is the measured-hypertensive group, NOT the cohort",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.410, printed_as="41.0%",
        analytic_sample="participants with measured hypertension",
        source_location="abstract and Results"),
    Prevalence(
        pmid="36065817", outcome="uncontrolled hypertension",
        definition="measured hypertensive and self-reported hypertension; "
                   "denominator is the measured-hypertensive group",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.377, printed_as="37.7%",
        analytic_sample="participants with measured hypertension",
        source_location="abstract and Results"),
    Prevalence(
        pmid="36065817", outcome="antihypertensive medication use",
        definition="'Do you currently take medicine to treat your high blood "
                   "pressure?', among those who self-reported hypertension",
        ascertainment="self_report", role="outcome", arm="published",
        identification="paper_free", instrument_key="m2:Q5.11",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.820, printed_as="82.0%",
        analytic_sample="the 2220 who self-reported hypertension",
        source_location="Results"),

    # ---- 37252073  Prev Med Rep 2023 -------------------------------------- #
    # The instrument item is word-for-word the paper's: m2:Q12.78 reads "Have
    # you ever had a colorectal cancer screening (colonoscopy, sigmoidoscopy, or
    # barium enema to examine the colon and rectum)?" and so does the paper's
    # Measures section. The wording is instrument content and legitimately
    # model-visible; the 42% is paper content and is not.
    Prevalence(
        pmid="37252073", outcome="ever had colorectal cancer screening",
        definition="'Have you ever had a colorectal cancer screening "
                   "(colonoscopy, sigmoidoscopy, or barium enema to examine the "
                   "colon and rectum)?' (yes/no)",
        ascertainment="self_report", role="outcome", arm="published",
        identification="paper_free", instrument_key="m2:Q12.78",
        instrument_region="m2:Q12 cancer history and screening",
        value=0.42, printed_as="42%",
        analytic_sample="2836 African American participants aged 50-75, "
                        "May 2013 to March 2020",
        denominator=2836, source_location="Results, first sentence, and Table 2"),

    # ---- 38715087  Environ Health 2024 ------------------------------------ #
    Prevalence(
        pmid="38715087", outcome="central hemodynamics and arterial stiffness",
        definition="central systolic/diastolic/pulse pressure, brachial artery "
                   "distensibility, compliance and resistance — all continuous",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=None, printed_as="",
        analytic_sample="n=2387",
        source_location="reports none: every outcome is continuous, so the "
                        "paper has no outcome prevalence to report"),
    Prevalence(
        pmid="38715087", outcome="prevalent hypertension",
        definition="self-reported physician-diagnosed hypertension OR current "
                   "antihypertensive medication use, or both",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.8",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.44, printed_as="44",
        analytic_sample="n~2387; the table's own denominator is 2383 "
                        "(1057 yes + 1326 no)",
        numerator=1057, denominator=2383, source_location="Table 1"),

    # ---- 38397711  Int J Environ Res Public Health 2024 ------------------- #
    Prevalence(
        pmid="38397711", outcome="uterine fibroid diagnosis",
        definition="self-reported diagnosis of uterine fibroids",
        ascertainment="self_report", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="m2 female medical history",
        value=0.21, printed_as="21%",
        analytic_sample="602 participants aged 35-76 who answered the uterine "
                        "fibroid question",
        numerator=127, denominator=602,
        computed_from="Table 1 prints 127 with and 475 without a diagnosis; "
                      "127/602 = 0.211, and the Results text prints 21%",
        source_location="Results, first sentence, and Table 1"),

    # ---- 32542493  J Racial Ethn Health Disparities 2021 ------------------ #
    # A response rate, not a health-outcome prevalence. Recorded because it IS a
    # published proportion about this cohort, and flagged so a scorer can drop
    # it: role="recruitment".
    Prevalence(
        pmid="32542493", outcome="biospecimen study participation",
        definition="address-level response rate to door-to-door recruitment",
        ascertainment="administrative", role="recruitment", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="recruitment, not in the instrument",
        value=0.580, printed_as="58.0%",
        subgroup_range=(0.304, 0.803),
        subgroup_basis="30.4% at non-African-American addresses; 58.0% at "
                       "African-American addresses; up to 80.3% at "
                       "African-American addresses in low-SES neighbourhoods",
        analytic_sample="residents of 5108 Chicago addresses solicited in the "
                        "first 6 years of the study",
        source_location="abstract"),

    # ---- 33088675  Prev Med Rep 2020 -------------------------------------- #
    Prevalence(
        pmid="33088675", outcome="elevated prostate-specific antigen",
        definition="serum PSA >= 4.0 ng/mL on clinical laboratory testing",
        ascertainment="lab", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="lab registry, declared and EMPTY in v1",
        value=0.073, printed_as="7.3%",
        subgroup_range=(0.045, 0.136),
        subgroup_basis="cigarette smoking history: never 4.5%, 0-1 pack-year "
                       "6.9%, >1 pack-year 13.6%",
        analytic_sample="928 African American men interviewed 2013-2018",
        numerator=68, denominator=928, source_location="Results and Table 1"),

    # ---- 36702470  Am J Epidemiol 2023 ------------------------------------ #
    Prevalence(
        pmid="36702470", outcome="asthma",
        definition="structured-questionnaire report of an asthma diagnosis in "
                   "childhood or adulthood",
        ascertainment="self_report", role="outcome", arm="published",
        identification="paper_free", instrument_key="m2:Q5.2",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.236, printed_as="23.6%",
        analytic_sample="6592 participants, 2013-2020",
        denominator=6592,
        source_location="abstract; PMC record is metadata-only, so any table "
                        "breakdown was not readable"),

    # ---- 36823587  BMC Cancer 2023 ---------------------------------------- #
    Prevalence(
        pmid="36823587", outcome="breast cancer case status",
        definition="125 breast cancer cases from a separate cohort against 125 "
                   "healthy controls drawn from COMPASS",
        ascertainment="administrative", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="not in the instrument",
        value=None, printed_as="",
        analytic_sample="125 cases and 125 controls, matched by design",
        source_location="reports none: a matched case-control design fixes the "
                        "case fraction at 50% by construction, which is not a "
                        "prevalence and must not be read as one"),

    # ---- 37879000  Am J Health Promot 2024 -------------------------------- #
    Prevalence(
        pmid="37879000", outcome="measured hypertension",
        definition="measured hypertension status by health insurance type and "
                   "clinic visit count; the paper reports odds ratios only",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=None, printed_as="",
        analytic_sample="1092 participants, 2013-2020",
        denominator=1092,
        source_location="reports none in retrievable text: the abstract gives "
                        "no prevalence and there is no PMC full text"),

    # ---- 37884074  Environ Res 2024 --------------------------------------- #
    Prevalence(
        pmid="37884074", outcome="ten cardiometabolic biomarkers",
        definition="ghrelin, resistin, leptin, C-peptide, CK-MB, MCP-1, "
                   "TNF-alpha, NT-proBNP, troponin, IL-6 — all continuous",
        ascertainment="lab", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="lab registry, declared and EMPTY in v1",
        value=None, printed_as="",
        analytic_sample="641 participants",
        source_location="reports none: every outcome is modelled continuously"),
    Prevalence(
        pmid="37884074", outcome="obesity",
        definition="BMI >= 30",
        ascertainment="measured", role="covariate", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="anthropometry, not in the instrument",
        value=0.405, printed_as="40.5%",
        analytic_sample="641 participants", source_location="Results"),
    Prevalence(
        pmid="37884074", outcome="type 2 diabetes",
        definition="self-reported diagnosis, as a descriptive characteristic",
        ascertainment="self_report", role="covariate", arm="published",
        identification="paper_free", instrument_key="m2:Q5.6",
        instrument_region="m2:Q5 diagnosed conditions",
        value=0.105, printed_as="10.5%",
        analytic_sample="641 participants", source_location="Results"),

    # ---- 38961645  Int J Epidemiol 2024 ----------------------------------- #
    Prevalence(
        pmid="38961645", outcome="anxiety, depression, bipolar disorder",
        definition="clinical diagnoses of anxiety, depression and bipolar "
                   "disorder; the paper reports odds ratios and g-estimation "
                   "sensitivity parameters only",
        ascertainment="administrative", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        analytic_sample="not stated in the abstract",
        source_location="reports none in retrievable text: the PMC record is "
                        "metadata-only, so a table figure would not have been "
                        "seen; this row is a weaker 'none' than the others"),

    # ---- 39217205  Sci Rep 2024 ------------------------------------------- #
    # The only rows in this file computed rather than printed. The paper prints
    # Table 1 as counts per hypertension type and never states a prevalence, so
    # these are derived — and marked as derived, because a computed figure and a
    # printed one are not equally strong evidence of what the authors claimed.
    Prevalence(
        pmid="39217205", outcome="any measured hypertension",
        definition="140/90 mm Hg criterion; the union of the paper's three "
                   "types (ISH, IDH, SDH) against its no-hypertension group",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.502, printed_as="",
        analytic_sample="6381 participants, 2013-2019",
        numerator=3202, denominator=6381,
        computed_from="Table 1 counts: 1071 ISH + 443 IDH + 1688 SDH = 3202; "
                      "3202/6381 = 0.5018. The paper prints no percentage.",
        source_location="Table 1, computed"),
    Prevalence(
        pmid="39217205", outcome="isolated systolic hypertension",
        definition="SBP >= 140 and DBP < 90",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.168, printed_as="",
        analytic_sample="6381 participants", numerator=1071, denominator=6381,
        computed_from="1071/6381 = 0.1678", source_location="Table 1, computed"),
    Prevalence(
        pmid="39217205", outcome="isolated diastolic hypertension",
        definition="SBP < 140 and DBP >= 90",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.069, printed_as="",
        analytic_sample="6381 participants", numerator=443, denominator=6381,
        computed_from="443/6381 = 0.0694", source_location="Table 1, computed"),
    Prevalence(
        pmid="39217205", outcome="systolic-diastolic hypertension",
        definition="the paper's third type, printed as 'SBP >= 140 or DBP >= 90'",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="clinical measurement, not in the instrument",
        value=0.265, printed_as="",
        analytic_sample="6381 participants", numerator=1688, denominator=6381,
        computed_from="1688/6381 = 0.2645", source_location="Table 1, computed"),

    # ---- 39238838  Environ Res Commun 2024 -------------------------------- #
    Prevalence(
        pmid="39238838", outcome="household fine particulate concentration",
        definition="continuously recorded household PM concentration, "
                   "summarised as hourly and 24-hour averages",
        ascertainment="measured", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="not in the instrument",
        value=None, printed_as="",
        analytic_sample="244 households",
        source_location="reports none: the outcome is a continuous "
                        "concentration and the unit of analysis is a household"),

    # ---- 41883377  Environ Health (Wash) 2025 ----------------------------- #
    Prevalence(
        pmid="41883377", outcome="elevated troponin",
        definition="troponin above the clinical threshold of 0.04 pg/mL",
        ascertainment="lab", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="lab registry, declared and EMPTY in v1",
        value=0.077, printed_as="50 (7.7%)",
        analytic_sample="648 participants enrolled March 2015 to November 2019",
        numerator=50, denominator=648, source_location="Results"),
    Prevalence(
        pmid="41883377", outcome="elevated TNF-alpha",
        definition="TNF-alpha above the clinical threshold of 8.1 pg/mL",
        ascertainment="lab", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="lab registry, declared and EMPTY in v1",
        value=0.086, printed_as="56 (8.6%)",
        analytic_sample="648 participants enrolled March 2015 to November 2019",
        numerator=56, denominator=648, source_location="Results"),

    # ---- 42034153  Environ Res 2026 --------------------------------------- #
    Prevalence(
        pmid="42034153", outcome="memory performance",
        definition="number of words recalled on a standardised 10-item delayed "
                   "word-recall list; scored 0-10, mean 3.26, SD 1.75",
        ascertainment="performance", role="outcome", arm="published",
        identification="paper_free", instrument_key=None,
        instrument_region="not in the instrument",
        value=None, printed_as="",
        analytic_sample="4048 adults residing in Chicago, 2013-2018",
        denominator=4048,
        source_location="reports none: the outcome is a continuous score and "
                        "the paper dichotomises nothing"),

    # ---- matched controls ------------------------------------------------- #
    # Same instrument region as the published self-report rows, same "has a
    # doctor ever told you" stem, binary, and NO prevalence reported for them in
    # the retrievable text of any of the sixteen papers.
    #
    # The form match is not uniform, and pretending otherwise would hide the
    # weakness. m2:Q5.4 is the only unpublished PLAIN item in the region — the
    # other plain items there (Q5.2 asthma, Q5.6 type 2 diabetes, Q5.8
    # hypertension, Q5.14 cholesterol) all have published figures — so a
    # form-matched control arm has exactly one member. The Q5.15 battery members
    # buy size by giving up the form match: they are matrix columns under a
    # shared stem, not standalone items.
    Prevalence(
        pmid="", outcome="type 1 diabetes", definition="'Has a doctor, nurse, or "
        "other healthcare worker ever told you that you have Type 1 Diabetes?'",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.4",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="the only plain item in the same region with the same stem "
                    "form as m2:Q5.8 and no published figure"),
    Prevalence(
        pmid="", outcome="arthritis", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_5",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and same 'ever told you' stem; matrix column "
                    "rather than a plain item"),
    Prevalence(
        pmid="", outcome="migraine", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_38",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column"),
    Prevalence(
        pmid="", outcome="kidney stones", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_34",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column"),
    Prevalence(
        pmid="", outcome="esophageal acid reflux",
        definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_22",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column"),
    Prevalence(
        pmid="", outcome="gout", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_23",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column"),
    Prevalence(
        pmid="", outcome="sleep apnea", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_46",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column. Named in 38715087's "
                    "list of what the questionnaire collects, with no figure"),
    Prevalence(
        pmid="", outcome="osteoporosis", definition="Q5.15 battery member",
        ascertainment="self_report", role="outcome", arm="matched_control",
        identification="paper_free", instrument_key="m2:Q5.15#1_39",
        instrument_region="m2:Q5 diagnosed conditions",
        value=None, printed_as="",
        source_location="no COMPASS publication reports this prevalence",
        match_basis="same region and stem; matrix column. Named in 32938600's "
                    "topic table, with no figure"),
)


def rows_for(instrument_key: str) -> list[Prevalence]:
    """Every recorded figure for one instrument key.

    A key can carry several: 36065817 and 32938600 both report a self-reported
    hypertension prevalence for `m2:Q5.8`, on different samples and five
    percentage points apart, and a scorer that silently takes the first has
    chosen an answer rather than found one.

    Args:
        instrument_key: A fully qualified key, e.g. "m2:Q5.8".

    Returns:
        The matching rows in declaration order, empty when the key is not
        covered. An empty result is not "no prevalence"; it is "not in this
        key", which is a different statement.
    """
    return [r for r in PREVALENCE_KEY if r.instrument_key == instrument_key]
