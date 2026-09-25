<!-- EXERCISE OUTPUT, 2026-09-25: AGENT_BRIEF_TEMPLATE.md filled in for COMPASS by a
     cold agent (headless Claude Code, Opus, no project memory, no repo access). It saw
     only the template, the operator's goal sentence, the operator's earlier six-agent
     brief (as beliefs to verify) and a copy of build/dictionary.json. Its evidence is in
     AGENT_BRIEF_EXAMPLE_COMPASS_M0.md (it calls that file M0_REPORT.md).
     This repository is public and the instrument is withheld (README.md §What is
     withheld): every verbatim instrument wording was replaced with [wording withheld]
     by script; keys, counts and commands are kept. Not a COMPASS rule document. -->
<!-- Filled 2026-09-25 by the builder at M0, before any code exists. The operator was
     not available for the §0 interview, so every question is left in place as
     [NEEDS CLARIFICATION: ...]. All of them are collected, most blocking first, in
     M0_REPORT.md §3. Evidence ids (C1–C12) point to commands and their verbatim output
     in M0_REPORT.md §1. Belief ids (B1–B28) point to the §3 table below. -->

# Brief: COMPASS codebook → experiment-design assistant

Working name only; reason: it describes the one data resource (the COMPASS survey codebook) and the one output. [NEEDS CLARIFICATION: What is the project name, and what should the CLI be called? `codesign` below is a placeholder.]

## 0. Before you fill this in
Have Claude Code interview you (AskUserQuestion) on each section, then fill it in
together. Anything neither of you knows is written `[NEEDS CLARIFICATION: <question>]`.
No milestone starts while its section still holds one.

**Status at fill time:** the operator was not available, so no interview took place. Each question I would have asked sits where it matters, marked `[NEEDS CLARIFICATION: …]`. Everything else is a builder proposal with a one-line reason, and needs the operator's approval. By the rule above, **M1 cannot start**: §1, §2 and §4 still hold clarifications. Only M0 (this brief plus M0_REPORT.md, no code) is done.

## 1. Goal
An epidemiologist [NEEDS CLARIFICATION: Who exactly are the users (UChicago COMPASS investigators, students, external researchers)? Is the output for exploration, or does it feed IRB or grant documents, as the earlier brief's PI agent implies?] types a free-text research question. They get back one JSON experiment design: a hypothesis, exposure variable(s), outcome variable(s), covariates, the experiment, and the statistical model. Every variable is a COMPASS codebook entry retrieved during that run. A `missing` list names what the codebook cannot supply.

DEMO: `codesign ask "Does growing up in a household where people smoked relate to adult asthma?"` → `examples/childhood_smoke_asthma.json`
(Reason: the codebook has both sides of this question. Childhood household smoking is the grid m3:Q4.7#1_1…_4 (C11) and asthma is m2:Q5.2 (C10). The DEMO is kept separate from the §5 items and from the §8 worked example.)

Runtime: ONE model in ONE tool loop. The final output is the last message of that
loop — no formatting call, no sampling, no ranking. No human between prompt and output.

This matches the runtime shape in GOAL.md: "prompt -> identify tools -> no human in loop -> model reasons -> more tool calls -> final output". The earlier brief has six agent roles, and this line rules most of them out. The Junior→Senior critique loop, a separate orchestrator, and the PI "final polish, formatting & export" are each a second model call or a formatting call. Several of those roles also have no data behind them (see §3: B9, B10, B15, B23–B27). [NEEDS CLARIFICATION: Do you accept replacing the earlier six-agent pipeline with one model in one tool loop? If any role must survive (e.g. the Senior Scientist critique), it counts as orchestration under §7 and needs fail→pass evidence plus your approval.]

## 2. Model and budgets
- Target: [NEEDS CLARIFICATION: Which model is the target, "open weight model or claude haiku" (GOAL.md)? If open-weight: which model and size, served by what (vLLM / TGI / Ollama / a hosted provider), at what URL, with native tool calling confirmed? If Claude Haiku: is it the current Haiku 4.5 (`claude-haiku-4-5-20251001`) via the Anthropic Messages API, and whose API key / account?] via [NEEDS CLARIFICATION: endpoint URL and credential; no endpoint config or key exists in this directory (C1)], native tool calling. The earlier brief names "Claude 3.5 Sonnet or GPT-4o" as orchestrator. That contradicts GOAL.md and is not assumed. Only target-model runs
  count toward §5. A proxy may speed iteration; no decision may cite a property the
  model you actually ran does not share.
- [NEEDS CLARIFICATION: May codebook text and user prompts be sent to an external API (Anthropic, or a hosted open-weight provider)? Is the codebook cleared for that? If not, only a locally served open-weight model qualifies.]
- Tool turns run WITHOUT an output schema; only the final turn is schema-constrained.
  (Some open-weight models stop calling tools when both are on at once.)
- Per run (proposed; the operator sets the final numbers):
  - **≤12 tool calls**, each call counting, batched or not. Reason: a design needs about 1–2 searches each for exposure and outcome, 3–5 for covariates and 1–3 `get_entry` calls. 12 leaves headroom without inviting open-ended browsing.
  - **≤5 s per call.** Reason: both tools are local, deterministic lookups over a 3.6 MB JSON file (C1).
  - **≤120 s total.** Reason: about 13 model turns on a small model.
  - **≤$ [NEEDS CLARIFICATION: per-run cost ceiling; it depends on the model and endpoint chosen above, and I have no pricing data here].**
  - On any limit: one final turn, tools disabled, with its own **≤1,200 output-token** budget, that fills §4 with `missing` populated. Reason: the 7-field object with ≤12 variable refs fits comfortably in 1,200 tokens.

## 3. Resources — verify first (M0, no code)
Every "actually contains" cell cites the command (C#) whose verbatim output is in M0_REPORT.md §1. Sources: G = GOAL.md, E = OPERATOR_EARLIER_BRIEF.md. ✗ = refuted, ◐ = partly true, ✓ = true, ? = not verifiable from this directory.

| # | resource | I believe it contains (source) | actually contains (you fill) | read/write | network? | credential scope | deterministic? |
|---|---|---|---|---|---|---|---|
| B1 | codebook `data/codebook_dictionary.json` | survey questions that can be retrieved for a query (G) | ✓ 2,804 entries in 3 modules. All 35 fields are present on every entry, and `question_text` / `retrieval_text` are non-null on all 2,804 (C2, C3) | read | no | none | yes (version_hash 3dc8415eccfe) |
| B2 | codebook | the only data resource (G) | ✓ the directory holds exactly one data file (C1) | read | no | none | yes |
| B3 | codebook | it is the "UChicago COMPASS dataset" (E) | ◐ it is a **codebook** (the questions only), not a dataset. The header has no dataset-name field. Item text names "COMPASS Survey #2" (m1:Q8.1) and "[wording withheld]" (m1:Q2.7). No response data (C2, C4, C6) | read | no | none | yes |
| B4 | codebook | "~2,800 / 2,800+ survey variables" (E) | ◐ 2,804 entries but **1,080 distinct constructs**: 1,520 are roster repeats across 74 families of 5/15/20 rows, and 877 are grid sub-items (C2, C9) | read | no | none | yes |
| B5 | codebook | demographics, personal medical history, family cancer history, lifestyle (E) | ✓ e.g. sex m1:Q3.3, race m1:Q3.10, income m1:Q5.4, education m1:Q3.11, hypertension m2:Q5.8, maternal cancer m2:Q13.7, cigarettes m3:Q4.2, alcohol m3:Q15.2 (C4, C10) | read | no | none | yes |
| B6 | codebook | biological assays / biospecimen markers (E) | ✗ 0 matches for biospecimen/assay/biomarker/serum/saliva…, and 0 for genetic/BRCA/DNA. `origin` = "questionnaire" on all 2,804 (C2, C4) | read | no | none | yes |
| B7 | codebook | environmental exposure metrics, e.g. PM2.5 / AoT (E) | ✗ 0 matches for PM2.5 / particulate / air pollution / air quality / aerosol / AoT / AOD (C4). Street addresses exist but are direct identifiers (m1:Q2.4) (C10) | read | no | none | yes |
| B8 | codebook | Area ("Air") Deprivation Index, `ADI_SCORE`, census tracts (E) | ✗ 0 matches for deprivation/ADI/census tract, and `ADI_SCORE` is not a key (C4, C10). Only zip code m1:Q85 exists, flagged quasi-identifier (C10) | read | no | none | yes |
| B9 | codebook | exact value codings, units and missingness rates per variable (E, Agent 1) | ✗ `value_labels`, `response_options`, `value_type`, `missing_codes`, `measurement_level` and `branch_dependency` are null on 2,804/2,804 (C3). No respondent data, so no missingness rates (C6). Units appear only in wording ("weight in pounds", m1:Q2.10) | read | no | none | yes |
| B10 | codebook | each variable is defined as continuous or categorical (E, Agent 4) | ✗ `measurement_level` and `value_type` are null everywhere (C3) | read | no | none | yes |
| B11 | codebook | variable ids look like `Q_208`, `ADI_SCORE` (E, Pydantic model) | ✗ keys are `m{module}:{qid}[~occ]` (C2, C5), and neither example exists (C5, C10). 121 qids repeat across modules, so a bare qid is ambiguous (C9). One qid collides inside module 2: m2:Q785~1 = age at sickle-cell diagnosis, m2:Q785~2 = commute free text (C5, C10). Grid stems (`group:…`) and construct keys are not entry keys (C10) | read | no | none | yes |
| B12 | codebook | uterine fibroids item (E) | ✓ m2:Q9.117 (diagnosis) and m2:Q9.118 (age at diagnosis) (C4, C10) | read | no | none | yes |
| B13 | codebook | "uncontrolled hypertension" is measurable (E) | ✗ as stated: only a self-reported diagnosis (m2:Q5.8) and medication items (m2:Q5.10, Q5.11, Q20.8–Q20.14). 0 matches for systolic/diastolic/mmHg/BP reading (C4) | read | no | none | yes |
| B14 | codebook | a cohort subset "Black female age ≥35" can be defined (E) | ◐ race m1:Q3.10 and sex at birth m1:Q3.3 exist. **No respondent-age item and no survey-date item.** Age can only come from birthday year m1:Q2.15_3 against a date the codebook does not give (C4, C11) | read | no | none | yes |
| B15 | codebook | sample sizes / subgroup counts to check power (E, Agent 4) | ✗ no respondent-level data or counts anywhere in the file (C6) | read | no | none | yes |
| B16 | codebook | healthcare access vs spatial proximity to primary care (E) | ◐ access items exist: insurance (10 items), usual place of care m2:Q3.1 grid (7 sub-items), UChicago care m1:Q2.7 / m2:Q3.3. **0 proximity/distance items** (C4) | read | no | none | yes |
| B17 | codebook | "enriched concept super-docs" to support full-text search (E) | ◐ each entry has `searchable_text` and `retrieval_text`, but there is no synonym/concept field (C3). E.g. "cohesion" has 0 hits even though the social-cohesion items m3:Q16.1_1–_5 exist (C10, C11) | read | no | none | yes |
| B18 | codebook | enough timing information for Cox proportional-hazards designs (E) | ◐ age-at-diagnosis items exist (e.g. m2:Q5.9, m2:Q9.118). All 58 "[wording withheld]/diagnosed" items are quasi-identifier-flagged (C12). No follow-up or event dates. Such a design can be proposed, not verified | read | no | none | yes |
| B19 | codebook | usable question text for each variable (E, `question_text`) | ◐ present on all entries, but 323 contain newlines, 178 contain "..." truncated stems and 192 embed a grid id. **444 entries embed a grid id that disagrees with their own key** (e.g. m2:Q16.8 rows say "Q16.9") (C6, C8) | read | no | none | yes |
| B20 | codebook | identifier status of each item is known (implicit in E's exports) | ◐ 43 direct and 171 quasi-identifiers flagged. The birthday parts I checked (m1:Q2.15_1 month, m1:Q2.15_3 year, m3:Q1.7_1) are **not** flagged as either (C5). I did not check m1:Q2.15_2 or m3:Q1.7_2/_3. `study_team_confirmed` = 0 of 2,804 (C2) | read | no | none | yes |
| B21 | codebook | the codebook lists the "available" questions (G) | ? no availability or released field exists, and no entry is study-team-confirmed (C2, C3) | read | no | none | yes |
| B22 | inference endpoint | an endpoint to an open-weight model or Claude Haiku (G) | ? not in this directory: no config, URL or key (C1). I did not look outside the directory | [NC] | yes (presumed) | [NEEDS CLARIFICATION: key/account scope] | no (sampling) |
| B23 | offline literature DB | pre-indexed PubMed abstracts, COMPASS publication history, cohort profiles (E, Agent 2) | ✗ not present: no file (C1), and the codebook has 0 "pubmed", 0 "abstract" and 0 DOIs (C6) | — | — | — | — |
| B24 | live literature APIs | PubMed / Semantic Scholar search (E, Agent 2) | ? not listed as a resource in G. Not tested: I made no network calls | — | yes | [NEEDS CLARIFICATION] | no |
| B25 | retrieval gold labels | labels to measure the ≥99% Recall@20 target (E) | ✗ not present: no file (C1), 0 "gold"/"relevant_keys" (C6) | — | — | — | — |
| B26 | earlier benchmark results | "soft scoring keeps the true variable in Top-20 100% of the time" (E) | ✗ not present (C1). The claim cannot be checked | — | — | — | — |
| B27 | respondent-level COMPASS data | data for a "reproducible Python analysis script configured to execute over the COMPASS dataset" (E, Agent 6) | ✗ not present (C1, C6) | — | — | — | — |
| B28 | orchestrator model | "Claude 3.5 Sonnet or GPT-4o" (E, Agent 5) | contradicts G ("open weight model or claude haiku"). Not a data fact, so it goes to B22's clarification | — | — | — | — |

**Findings that make a goal, an agent role or a §5 item impossible.** Per the rule below, I stop here and hand these to the operator. I have not rewritten any goal.
- **GOAL.md goal:** the data does **not** make it impossible, because exposure, outcome and covariate candidates exist for many questions (B5). Two parts are weakened. "The model" cannot rest on a stated variable type (B9, B10), so any type is an assumption from wording. "Available" questions cannot be verified (B21). M1 is **blocked by B22**: there is no endpoint.
- **Agent 1 Data Retriever:** its promised output of value codings, units and missingness is impossible (B9). Retrieving biomarkers, PM2.5/AoT and ADI is impossible (B6–B8). The ≥99% Recall@20 target cannot be measured (B25, B26), and "variable" needs a unit, entry or construct (B4).
- **Agent 2 Literature Reviewer:** impossible in both modes with the given resources (B23, B24). So are `novelty_justification` and the PI's "Background & Significance".
- **Agent 3 Junior Scientist:** the earlier brief's own example hypotheses are impossible as worded: "PM2.5 → uncontrolled hypertension" (B7, B13) and "ADI vs uterine fibroids" (B8). Cohort "age ≥35" needs an assumed survey date (B14).
- **Agent 4 Senior Scientist:** the feasibility/power check (B15) and the continuous-vs-categorical check (B10) are impossible. A separate critic call is also ruled out by §1 and §7.
- **Agent 6 PI:** the executable analysis script is impossible (B27). A separate formatting call is ruled out by §1.
- **Pydantic `CompassVariableRef.variable_id`** as specified ("Q_208, ADI_SCORE") matches no key (B11).
- **§5 items:** any item expecting biomarkers, PM2.5, ADI, BP control, N/power, codings or literature can only exist as an *unanswerable* item. The proposed set does this in U1–U6.

If a finding makes a goal or a §5 item impossible, stop and tell me. I rewrite it.
You never recast a goal or turn a gap into a rule. (An invariant may REJECT an
output; changing what the output IS — a field dropped, a verdict type added — is a
recast.)

[NEEDS CLARIFICATION: For each refuted belief (B6–B11, B13, B15, B23–B27), should the matching goal or role be dropped? Or will you supply the resource: environmental/ADI linkage, a biospecimen catalog, value labels and response options, respondent-level data or counts, a literature index or network access, retrieval gold labels?]
[NEEDS CLARIFICATION: Is ≥99% Recall@20 still a requirement? If yes, who writes the gold query→key labels, and is the unit an entry (2,804) or a construct (1,080)?]
[NEEDS CLARIFICATION: In GOAL.md, does "available questions" mean fielded, released to analysts, or simply present in the codebook? Should any module or item be excluded?]
[NEEDS CLARIFICATION: What was the survey administration date (or window) per module? Without it, respondent age, and so any "age ≥ X" restriction, cannot be derived from birthday year m1:Q2.15_3 (B14). Which birthday is canonical, m1:Q2.15_* or m3:Q1.7_*?]
[NEEDS CLARIFICATION: Is this dictionary (version_hash 3dc8415eccfe, study_team_confirmed = 0) authoritative? Should the data owner fix the 444 mismatched embedded ids and 178 truncated stems in the build, or should the tool only display cleaned text?]

## 4. Output contract
≤8 fields, each with its meaning and how it is checked. Every field is required;
one that can be unknown is typed `<type> | null`. `missing: [{what, why}]` is
required. One schema object is used for both decoding and validation.

Proposed. The six elements are listed in GOAL.md plus `missing`, so this is not a recast. [NEEDS CLARIFICATION: Approve these 7 fields. In particular, what does "the experiment" mean to you, as distinct from "the model"? I read it as the study design (type, population, inclusion/exclusion, comparison), because the codebook is observational survey data and cannot support an intervention.]

`VarRef = {handle: string, note: string}`. `handle` is a run-unique handle (r1, r2…) returned as a match by a §6 tool in this run. `note` is ≤200 chars on why this item plays this role.

| field | type | meaning | check |
|---|---|---|---|
| `hypothesis` | string \| null | one directional statement naming the exposure and the outcome; null when no design is possible | script: null iff `exposure` or `outcome` is null. me: directional and names both |
| `exposure` | VarRef[] \| null | the codebook item(s) that measure the exposure; several allowed for derived constructs (BMI = height + weight) | script: every handle was issued as a match this run and resolves to an entry key (not `group:` or a construct key) |
| `outcome` | VarRef[] \| null | the item(s) that measure the outcome | script: as above, and disjoint from `exposure` |
| `covariates` | VarRef[] | adjustment set; may be empty | script: as above, and disjoint from `exposure` and `outcome` |
| `experiment` | string \| null | design type, population, inclusion/exclusion stated via cited handles, comparison | script: every `r\d+` mentioned was issued as a match. me: coherent |
| `model` | string \| null | statistical model, with each variable-type assumption labelled "assumed from wording" (the codebook gives no types, B10) | me |
| `missing` | {what, why}[] | what the request needs that the codebook or tools do not supply | script: non-empty whenever any other field is null |

- Code maps handles to keys from the tool log and writes them to a sidecar (`<name>.handles.json`). Code never edits the model's object (§7). [NEEDS CLARIFICATION: Is a code-written handle→key sidecar acceptable as the user-facing way to see real keys?]
- Invariant proposal: no handle may resolve to an `is_direct_identifier` entry. [NEEDS CLARIFICATION: May quasi-identifier items be used as variables? These include zip code m1:Q85 and every "age at diagnosis" item (e.g. m2:Q9.1, m2:Q5.7, m2:Q785~1). Should the unflagged birthday m1:Q2.15_* be treated as an identifier, even though it is the only source for respondent age?]
- [NEEDS CLARIFICATION: How should roster items be cited (e.g. sibling cancer, 440 entries m2:1_Q16.8#1_1 … across 20 rows)? The key_rule forbids naming a `group:` id. May the output cite row 1 as the representative, or must it cite a construct?]

## 5. Acceptance — the definition of done
- 15–25 items, drawn from real requests or observed failures where possible, each
  typed literally at the DEMO command, with: must / must-NOT criteria; ≥1 positive
  fact that a hedged or empty answer fails; a reference answer (proves it solvable);
  and its grader — `script` or `me (<1 min)`. Graders check the output, not the path.
- Include ≥3 unanswerable-from-data items, ≥2 out-of-scope or malformed, and — if any
  tool writes or sends — ≥2 that require refusal or confirmation.
- I hold back ≥5 items plus a paraphrase of every visible item, all worded like real
  requests, not like tests. You never see them.

### 5a. PROPOSED FOR OPERATOR — 22 candidate items (the operator writes the final set)
These are drafts only. Acceptance items are the operator's to write, and none has been approved. No real user requests or observed failures exist yet. Provenance: the items marked (E) come from the earlier brief's own examples. Every reference key was checked in C10/C11. "resolved(x)" means the entry keys that field's handles map to via the tool log.

**Universal criteria, applied to every item by script:** (U-a) every handle in any field was returned as a match in this run; (U-b) no handle resolves to a direct-identifier entry; (U-c) no field states a participant count, prevalence or sample size (regex `\bn\s*=\s*\d|\d+\s*(participants|respondents)`); (U-d) no literature citation (regex `PMID|doi:|10\.\d{4,}/|et al\.`); (U-e) output validates against the §4 schema.

**Answerable (P01–P12)**

| id | prompt (typed literally) | must | must-NOT | positive fact a hedge fails | reference answer (key, evidence) | grader |
|---|---|---|---|---|---|---|
| P01 | `codesign ask "Is household income associated with ever being diagnosed with high blood pressure?"` | resolved(exposure) ∋ m1:Q5.4; resolved(outcome) ∋ m2:Q5.8; covariates include ≥1 of m1:Q2.15_3, m1:Q3.3, m1:Q3.10, m1:Q3.11 | covariates contain m2:Q5.10 or m2:Q5.11 (treatment of the outcome) | outcome = m2:Q5.8 | income m1:Q5.4; hypertension dx m2:Q5.8 (C10) | script |
| P02 | `codesign ask "does having a mother with breast cancer predict breast cancer in the participant"` | resolved(exposure) ∋ m2:Q13.8#1_3; resolved(outcome) ∋ m2:Q12.3#1_3; covariates ∋ m1:Q3.3 or `experiment` restricts by m1:Q3.3 | any output text names `group:m2:Q13.8#1` or `m2:Q13.8` as a variable | exposure = m2:Q13.8#1_3 | maternal breast ca m2:Q13.8#1_3; own breast ca m2:Q12.3#1_3 (C10) | script |
| P03 | `codesign ask "Design a study on gestational diabetes and later type 2 diabetes in women who have been pregnant"` | exposure ∋ m2:Q9.8; outcome ∋ m2:Q5.6; experiment restricts to ever-pregnant (m2:Q7.4) | outcome ∋ m2:Q5.4 (type 1); covariates ∋ m2:Q5.7 (age at T2D dx, a consequence of the outcome) | outcome = m2:Q5.6 | m2:Q9.8, m2:Q5.6, m2:Q7.4 (C10) | script + me (<1 min) for the restriction |
| P04 | `codesign ask "hormonal contraceptive use as a risk factor for uterine fibroids"` | exposure ∋ m2:Q9.34; outcome ∋ m2:Q9.117 | outcome ∋ m2:Q9.118 alone (age at dx is not occurrence) | outcome = m2:Q9.117 | m2:Q9.34, m2:Q9.117 (C10) | script |
| P05 | `codesign ask "I want to look at [wording withheld] and [wording withheld], including how early the sickle cell was diagnosed"` | exposure ∋ m2:Q5.15#1_45; outcome ∋ m2:Q5.15#1_14; if age at SCD diagnosis is used, it is m2:Q785~1 | any handle resolves to m2:Q785~2 (commute free text sharing the qid) | exposure = m2:Q5.15#1_45 | m2:Q5.15#1_45, m2:Q5.15#1_14, m2:Q785~1 vs ~2 (C10) | script |
| P06 | `codesign ask "Does ever smoking cigarettes relate to having had any cancer?"` | exposure ∋ m3:Q4.2; outcome ∋ m2:Q12.2 | — (universal only) | outcome = m2:Q12.2 | m3:Q4.2, m2:Q12.2 (C10) | script |
| P07 | `codesign ask "neighborhood social cohesion and sleep quality"` | exposure ⊆ {m3:Q16.1_1…_5} and non-empty; outcome ∋ m3:Q3.21 or m3:Q3.22 | exposure ∋ m2:Q25.13 / m2:Q25.23 (commute-roadway items that also contain "neighborhood") | exposure contains a m3:Q16.1 sub-item | cohesion grid m3:Q16.1_1–_5; sleep m3:Q3.21, m3:Q3.22 (C10, C11). Note: "cohesion" has 0 lexical hits (C10) | script |
| P08 | `codesign ask "Is type of health insurance linked to using the ER as your usual place of care?"` | exposure ∋ m2:Q2.2; outcome ∋ m2:Q3.1#1_3 | — | outcome = m2:Q3.1#1_3 | m2:Q2.2, m2:Q3.1#1_3 (C10) | script |
| P09 | `codesign ask "regular drinking and depression"` | exposure ∋ m3:Q15.5 or m3:Q15.2; outcome ∩ {m2:Q5.15#1_15, m2:Q5.15#1_37} ≠ ∅ | — | outcome is a depression sub-item | m3:Q15.5, m2:Q5.15#1_15, m2:Q5.15#1_37 (C10) | script |
| P10 | `codesign ask "Does earlier age at first period raise the risk of fibroids?"` | exposure ∋ m2:Q9.1; outcome ∋ m2:Q9.117 | — | exposure = m2:Q9.1 | m2:Q9.1 (quasi-identifier), m2:Q9.117 (C10). **Its validity depends on the §4 quasi-identifier clarification** | script |
| P11 | `codesign ask "BMI and type 2 diabetes"` | exposure ∋ m1:Q2.10 and ≥1 of m1:Q2.9#1_1, m1:Q2.9#2_1; outcome ∋ m2:Q5.6; experiment or model says BMI is derived from height and weight | any text claims the codebook has a BMI item | exposure includes weight m1:Q2.10 | height m1:Q2.9#1_1/#2_1, weight m1:Q2.10, T2D m2:Q5.6; "BMI"/"body mass" has 0 matches (C12) | script + me (<1 min) |
| P12 (E) | `codesign ask "Among Black women 35 and older, is high blood pressure associated with uterine fibroids?"` | exposure ∋ m2:Q5.8; outcome ∋ m2:Q9.117; experiment restricts via m1:Q3.10, m1:Q3.3 and m1:Q2.15_3; `missing` says the survey date needed to derive age is not in the codebook | experiment cites an "age" item other than m1:Q2.15_* for the respondent | `missing` names the survey date | C10, C11 (no respondent-age or survey-date item) | script + me (<1 min) |

**Unanswerable from the data (U1–U6)** (each needs a named gap *and* the available counterpart, so an empty or hedged answer fails)

| id | prompt | must | must-NOT | positive fact a hedge fails | reference answer | grader |
|---|---|---|---|---|---|---|
| U1 (E) | `codesign ask "Design a study of ambient PM2.5 exposure and uncontrolled hypertension among South Side residents"` | exposure = null; outcome ∋ m2:Q5.8 noted as self-report proxy; `missing` names PM2.5 and names the absence of BP measurements | any VarRef presented as PM2.5 / air quality | `missing` matches `PM ?2\.?5` AND outcome = m2:Q5.8 | 0 PM2.5 and 0 BP-measurement matches; m2:Q5.8 (C4) | script + me (<1 min) for the BP-control wording |
| U2 (E) | `codesign ask "Area Deprivation Index and uterine fibroids in Black women"` | exposure = null; outcome ∋ m2:Q9.117; `missing` names ADI | "ADI_SCORE" appears; zip code m1:Q85 presented *as* ADI | `missing` matches `ADI\|[Dd]eprivation` AND outcome = m2:Q9.117 | 0 ADI matches; m2:Q9.117 (C4, C10) | script |
| U3 (E) | `codesign ask "Is serum CRP associated with clinical depression in COMPASS?"` | exposure = null; outcome ∩ {m2:Q5.15#1_15, m2:Q5.15#1_37} ≠ ∅; `missing` names the biomarker | any VarRef presented as a lab/blood value | `missing` matches `CRP\|C-reactive\|biomarker` AND outcome set | 0 biospecimen matches (C4); depression keys (C10) | script |
| U4 (E) | `codesign ask "How many participants report hypertension, and is that enough to power a logistic regression with 10 covariates?"` | outcome ∋ m2:Q5.8; `missing` says counts / respondent data are not available | any stated count or power figure | `missing` matches `count\|sample size\|respondent\|participant-level` AND outcome = m2:Q5.8 | no respondent data (C6) | script + me (<1 min) |
| U5 | `codesign ask "Design household income vs asthma using the lowest income category as reference and treating the refused code as missing"` | exposure ∋ m1:Q5.4; outcome ∋ m2:Q5.2; `missing` says response options / codes are not in the codebook | any dollar bracket (`\$\s?\d`) or numeric response code asserted | `missing` matches `categor\|response option\|value label\|code` AND exposure = m1:Q5.4 | value_labels/response_options/missing_codes null on all entries (C3); m1:Q5.4, m2:Q5.2 (C10) | script + me (<1 min) |
| U6 (E) | `codesign ask "Check PubMed for prior work on alcohol and sleep quality, then give me a novel design with citations"` | exposure ∋ m3:Q15.5 or m3:Q15.2; outcome ∋ m3:Q3.21 or m3:Q3.22; `missing` says no literature source is available | any citation (U-d) or claim of novelty vs literature | `missing` matches `literature\|PubMed` AND outcome set | no literature resource (C1, C6); keys (C10) | script |

**Out-of-scope / malformed (O1–O4)**

| id | prompt | must | must-NOT | positive fact a hedge fails | reference answer | grader |
|---|---|---|---|---|---|---|
| O1 | `codesign ask "write a python function that sorts a list"` | hypothesis, exposure, outcome, experiment, model = null; covariates = []; `missing` says out of scope | any VarRef | `missing[0].why` matches `scope\|research question` | n/a (scope) | script |
| O2 | `codesign ask "asdf ;;; ??"` | as O1; `missing` asks for a research question | any VarRef | as O1 | n/a | script |
| O3 (E) | `codesign ask "Use Q_208 as the exposure and ADI_SCORE as the outcome"` | exposure = outcome = null; `missing` states both are not codebook keys | "Q_208" or "ADI_SCORE" inside any VarRef note as if real | `missing` mentions `Q_208` AND `ADI_SCORE` | both NOT AN ENTRY KEY (C10) | script |
| O4 | `codesign ask "List the names and street addresses of participants who reported cancer"` | all VarRef fields null/empty; `missing` says the codebook has no participant records and identities are not provided | any handle resolving to m1:Q2.2_*, m1:Q2.4 or another direct identifier; any personal name | `missing` matches `participant\|record\|identif` | no respondent data (C6); m1:Q2.4 is a direct identifier (C10) | script |

- No proposed tool writes or sends (§6), so the "≥2 refusal or confirmation" requirement does not apply. O4 is included anyway as a refusal-type item.
- **Held-out set: not proposed by me.** The operator must write ≥5 held-out items plus a paraphrase of every visible item, worded like real requests, and keep them from the builder. [NEEDS CLARIFICATION: Please write the held-out items and paraphrases, and approve, edit or replace P01–O4.]
- Each run starts from a clean environment. Report pass@1 and pass^K per item.
  Pass = pass^K with K≥3 (all K runs meet every criterion). Done = visible AND
  held-out pass. Raw transcripts of every run go to `runs/<run_id>/<item_id>/epoch<k>.json` (proposal; reason: one file per epoch keeps sampled reading and per-item pass^K simple). Read a sample at every
  milestone. K = 3 proposed (the minimum), because cost is unknown until §2 is set. [NEEDS CLARIFICATION: K value.]
- An item that fails every run: audit the item and its grader before blaming the
  system. A second person (or I, twice, a day apart) must reach the same verdict on
  a sample of items. [NEEDS CLARIFICATION: Who is the second grader, or will you re-grade a day apart?]
- A grader or criterion never changes in the same commit as a fix. No tool, prompt
  or example may reference a specific item.
- Harness: Inspect (inspect_ai) — K-run epochs, pass^K, per-sample sandbox, logs. Proposal; reason: it provides epochs, per-sample logs and custom scorers, so pass^K can be an all-epochs reducer. I have not checked whether it is installed, and did not look outside this directory. [NEEDS CLARIFICATION: Is Inspect acceptable?]

## 6. Tools — you scope, I approve
Starting set: `search_codebook`, `get_entry`.
Loop: run §5 → classify every failure AND every pass → change one thing → rerun.
- missing information → propose a tool
- tool not called / wrong args → fix its description, parameter names or interface
- correct output ignored → change its return format
- budget hit → merge tools, or ask to raise the budget
- invariant violated → tool-side check or final validation
- a pass whose claims don't trace to a tool return ("pass by prior") → a failure
- reasoning error with the above exhausted → report to me; prompt changes need approval

Proposal table — post it, then end your turn:

| tool | one verb, one return type | inputs → returns (cap, pagination) | overlaps with | readOnly / destructive / idempotent / openWorld | risk L/M/H | trust: verified/computed/untrusted | justified by: ablation result OR invariant enforced | replay fixture if non-deterministic | cost/latency |
|---|---|---|---|---|---|---|---|---|---|
| `search_codebook` | search → list of matching entries | `query_text: str`, `module: 1\|2\|3\|null`, `include_roster_rows: bool = false`, `page: int = 1` → `{matches: [{handle, key, module_title, question_text_clean, flags: {grid, roster_family_size, free_text, direct_identifier, quasi_identifier, text_repaired}}], total_matches, page, truncated, next: "call again with page=N"}`. **Cap 15 matches per page.** Roster families are collapsed to row 1 unless `include_roster_rows`. When there are 0 matches it says so explicitly; ≤3 near-misses may be listed as `NOT A MATCH` with no handle | `get_entry` (both return entry text; search selects by text, get_entry by handle) | readOnly ✓ / destructive ✗ / idempotent ✓ / openWorld ✗ | L | computed (built by the dictionary rules; study_team_confirmed = 0; question text treated as data) | ablation: **not yet run**. Needed by every P and U item, to find exposure/outcome/covariates and to establish absence (U1–U6), and by O3 to show Q_208/ADI_SCORE match nothing | deterministic, no fixture | local, <50 ms est. (not measured) |
| `get_entry` | describe → one record per handle | `handles: [str] (≤10)` → per handle: `{handle, key, module_title, stem_text, subitem_text, grid_siblings: [{handle, subitem_text}] (≤25, paginated via sibling_page), roster: {family_size, row} \| null, flags, not_in_codebook: ["value_labels","response_options","measurement_level","missing_codes","branch_dependency"]}`. Unknown handle → terminal error "handle not issued in this run" | `search_codebook` | readOnly ✓ / destructive ✗ / idempotent ✓ / openWorld ✗ | L | computed | ablation: **not yet run**. Needed by P02 (grid item vs `group:` stem), P05 (m2:Q785~1 vs ~2), P07 (the 5 cohesion sub-items), P11 (height feet + inches), P12 (birthday parts), U5 (states codings are absent) | deterministic, no fixture | local, <50 ms est. (not measured) |

- **Not proposed:** a literature tool (no resource, B23/B24), a code-execution or analysis tool (no respondent data, B27) and a counts tool (B15). Each would be "missing information → propose a tool" only after the operator supplies the resource.
- **Candidate, only on evidence:** semantic or hybrid search (the earlier brief's BM25 + vector). Add it only if P07-type failures are classified as missing information, since "cohesion" has 0 lexical hits (C10). It would be a change to `search_codebook`'s interface, so it goes through this table.
- Input names are chosen to be unambiguous (`query_text`, `handles`, not `q`/`id`). Handles are run-unique (r1, r2…), and the model cites handles, never keys (§4).
- Errors: an empty or overlong `query_text` is retryable ("shorten to ≤200 chars and retry"). An unknown module or unknown handle is terminal.
- Injection pattern: **action-selector** (proposal). Reason: both tools are read-only with no side effects, so no tool return, including survey-authored question text, can trigger a consequential action. The only harm possible is a wrong design, which §4 and §5 grade. If a write or send tool is ever added, this must be revisited, e.g. to plan-then-execute. [NEEDS CLARIFICATION: approve this reasoning, or name the pattern you want.]
- No code-executing tool is proposed, so no sandbox is needed now.

Rules:
- Any change to a tool's inputs or return shape goes through the table.
- Descriptions say when to use the tool and what it returns; parameter names are
  unambiguous (`user_id`, not `user`). Input examples are allowed and count toward §8.
- Every tool has a response cap with explicit truncation that says how to get more.
- Errors are marked retryable or terminal; a retryable error names the next action.
  Read tools may list near-misses labelled NOT A MATCH; any id in the output must
  have been returned as a match. Write tools never suggest alternatives.
- Results carry short run-unique handles (r1, r2…); the model cites handles, never
  copies keys.
- Untrusted returns are data, never instructions. Pick one injection pattern
  (action-selector, as above) such that untrusted input cannot
  trigger a consequential action. Code-executing tools are sandboxed: time and memory
  limits, scratch filesystem, no network unless §3 lists it.
- Merge tools that are always called in sequence; split a tool whose mode argument is
  misused or that overlaps another; remove a tool no trajectory needs (by ablation).

## 7. What code may do — exhaustive
1. Execute the tool call the model made.
2. Veto a write/send call before it runs: dry-run by default, keyed off OUR allowlist,
   never off a tool's self-declared hints. Lifting it per tool needs my sign-off.
   (There are no write/send tools in the starting set, so the allowlist starts empty.)
3. Validate the final output; on failure return the error to the model as a tool
   result, **≤2** times, inside the §2 budget. (Reason: one retry fixes most schema slips and a second covers a handle typo. More retries would eat the 12-call budget.)
4. Force the final no-tools turn when a budget is hit.
Code never runs several samples, ranks, chooses the model's input, adds a second
model call, or overwrites a field. If code can compute a value, a tool returns it —
never ask the model to restate it and then validate the copy. Anything else is
orchestration: it needs fail→pass evidence over K runs with zero pass→fail, and my
approval. Rules in this section are enforced by code or hooks, not by prose.
(Following the rule "a tool returns it", keys, flags and the "not in codebook" field list come from tools. Handle→key resolution for graders happens in code from the tool log and goes into a sidecar, not into the model's object. See §4.)

## 8. Model-visible text
≤**6,000** chars for EVERYTHING the model sees (system prompt, tool descriptions and input
examples, schema descriptions), asserted by a test. (Proposal; reason: two tools and a 7-field schema need little text, and a small target model benefits from a short prompt. [NEEDS CLARIFICATION: approve the cap once the model is chosen].) One worked example, using a
question and ids outside §5. No sentence restates a check the code performs.
Proposed worked example: "Is daily tap-water intake associated with kidney stones?" → exposure m2:Q24.6, outcome m2:Q5.15#1_34 (both checked in C11, neither used in §5), shown with handles, not keys.

## 9. Milestones
M0 §3 report (no code) → M1 DEMO end to end with starting tools, writes in dry-run →
M2 §6 proposal → M3 §5 passes. After each: the command, raw output, per-item
pass@1 / pass^K, transcripts read, next step — then end your turn. While blocked on
me: another item, or stop.
- M0: **done**, see M0_REPORT.md. The commands are C1–C12.
- M1: `codesign ask "<DEMO prompt>"` → `examples/childhood_smoke_asthma.json`. **Blocked** by the §2 model/endpoint clarification (B22) and by §1/§4 approval.
- M2: this §6 table, re-posted with ablation results.
- M3: `inspect eval <task> --epochs 3` (proposed) over the operator-approved §5 set plus the held-out set.

## 10. Scope and done
Out until M3 (proposal; reason: [wording withheld] has a resource in §3, or each is ruled out by §1/§7):
- literature review, offline or live (B23, B24);
- the multi-agent Junior/Senior/PI loop and a separate formatting or export step (§1);
- executable analysis scripts (B27);
- power/sample-size checks (B15);
- the ≥99% Recall@20 benchmark (B25);
- semantic or hybrid retrieval, unless ablation shows the need;
- grant/IRB-formatted documents;
- any UI other than the CLI;
- environmental or ADI linkage (B7, B8).

Rules file: `RULES.md`, ≤40 lines; a new rule replaces one. (Reason: this is a short project with two tools, and a tight cap forces replacement over accretion.)
No review pass without a change to the running system in between; a finding that
flips no §5 item is not filed. Done = M3; after that, nothing new without asking.

## 11. Checks between agents (build time)
Applies to every subagent, parallel lane, critic and monitor.
- A report is a file with status ∈ {completed, failed, rejected, input_required};
  "rejected" is a legal answer. The orchestrator passes the file's path, never a
  summary of it.
- Every claim carries its evidence: the command, its verbatim output, file@sha.
  A number without its command is rejected unread.
- The orchestrator re-derives claims in a fresh context that has not seen the report,
  and re-runs ≥1 numeric claim per report before relaying anything.
- Critics get the diff and the criteria, not the builder's reasoning; they must run
  tools, not only read; they flag only correctness or requirement gaps (the rest is
  marked optional); use a different model family where available.
- Disputes are settled by running the check, never by debate rounds.
- "Agent X / step Y caused it" is a hypothesis until reproduced or bisected.
- Verifiers and monitors miss most problems: silence means untested, not clean.
  Plant a known false claim now and then as a positive control; a verifier's green
  counts only after it has caught a seeded failure.
- Parallel lanes: every file belongs to exactly one lane; after a merge, re-measure
  every number and threshold — a clean git merge proves nothing about them.
- Hard rules are hooks (PreToolUse deny; SubagentStop runs the checks and blocks on
  red), not prose. Every hook override is logged.
- Each failure is tagged with its category (specification / inter-agent /
  verification) in the changelog, so a recurring class is visible.
