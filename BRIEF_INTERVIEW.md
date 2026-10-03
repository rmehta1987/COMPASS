# COMPASS brief §0 interview: operator answers (verbatim choices), 2026-10-02
Target document: `BRIEF.md` (binding; derived from `AGENT_BRIEF_EXAMPLE_COMPASS.md`). It overrides DESIGN.md and AGENTS.md.

## Decided before the interview (this session)
- The brief overrides DESIGN.md and AGENTS.md: "lets say we make brief supercede the design and agents by modifying design and agents to follow the brief". This resolves §1 NC "one model in one tool loop": YES.
- Rediscovery benchmark (DESIGN §6): "Drop it".
- Literature: live Semantic Scholar (B24 supplied). The tool returns "Titles + year + ID only". No abstracts, so methods are not copied ("we don't want to copy an existing method").
- §2 external API NC: "the codebook is available to the public so it doesn't matter if the web sees it". README §What is withheld still says "Not cleared for public release" and must be reconciled.
- How to proceed: "Run the §0 interview".

## Batch 1: §0/§1/§2
- Name: "Keep COMPASS, CLI `compass`"
- Users: "COMPASS investigators, exploring"
- Target model: "Haiku 4.5 is the target" (claude-haiku-4-5)
- Endpoint: "Headless claude CLI"

## Batch 2: §2/§3
- Budget: "≤16 calls, ≤180 s"
- Cost: "No ceiling, log cost"
- Refuted beliefs (B6–B11, B13, B15, B25–B27): "Drop them; test as gaps" (kept as unanswerable items U1–U5)
- Recall@20: "Keep ≥99% Recall@20" (hard requirement; unit and gold labels in batch 3)

## Batch 3: §3
- Recall@20 unit: "Construct (1,080)"
- Gold labels: "Reuse existing fixtures" (benchmark/fixtures/retrieval_queries.json, training machine). CAVEAT told to operator: the fixture queries saw the gold wording (KNOWN_BIAS), so ≥99% on them is an upper bound.
- "Available questions": "All except direct identifiers" (43 excluded)
- Dictionary: "Fix in the build first" (444 mismatched embedded ids, 178 truncated stems; moves build hash 3dc8415eccfe, operator-authorised by this choice)

## Batch 4: §3/§4
- "experiment": "Study design" (type, population, inclusion/exclusion via cited handles, comparison)
- Survey date / age restriction: "Report it as missing"
- Quasi-identifiers: "Yes, flagged" (direct identifiers stay banned)
- Handle→key sidecar: "Yes, sidecar"

## Batch 5: §4/§5
- Rosters: "Row 1 as representative" (after a worked example of m2:{row}_Q16.8#1_{col})
- Birthday: "Module 1, quasi-identifier" (m1:Q2.15_* canonical, flagged)
- K: "K = 5"
- Second grader: "You, a day apart" (after an explanation of what is human-graded)

## Batch 6: §5/§6/§8
- Harness: "Plain pytest + JSON logs" (no Inspect; runs/<run_id>/<item>/epoch<k>.json + pass^K table)
- prior_work (8th field): "[{handle, relation}]", relation ∈ {same_question, related, differs_by_population, differs_by_exposure_or_outcome}; handles → S2 paperId in sidecar
- Injection pattern: "Approve action-selector"
- Model-visible cap: "7,000 chars"

## Batch 7: §5 / README
- U6: "Accept the rewrite". U6 becomes answerable: prior_work must be non-empty with handles issued by the literature tool this run. U-d (regex `PMID|doi:|10\.\d{4,}/|et al\.`) still applies to every free-text field, so citations exist only as tool-issued handles.
- P01–O4: "Approve as drafts; I'll edit"
- Held-out items: "Private repo/branch I control" (builders never see them)
- README: "Public, but don't republish here". Sending wording to APIs is fine; the repo still does not republish the instrument files; add one clarifying README line.

## Status
All 23 brief NCs answered (3 of the 26 matches are template placeholders). Next: write the brief as binding.

## Change after the interview (operator, 2026-10-02)
- "i think for the literature review we should add the abstract, the variables are usually not included in the title". This REPLACES "Titles + year + ID only". The literature tool returns title, year, abstract and a handle. Copy controls that remain: U-c (no counts/prevalence/sample size), U-d (citations only as tool handles), and the prior_work relation. Default cap: 5 papers per page with pagination (builder default, operator may change).
