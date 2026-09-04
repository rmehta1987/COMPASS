"""benchmark/leak_facts.py — the answer key the seal probes are scored against.

WHY AN ANSWER KEY AT ALL. The probes ask for "YES plus one fact". Until
2026-08-26 the fact was collected and scored nowhere: `_answered_yes` read the
first word and nothing read the rest, so these five answers were one verdict —

    leaked=True   'YES'
    leaked=True   'YES. I have no idea what COMPASS is.'
    leaked=True   'YES - the survey platform is <name>.'
    leaked=True   'I do not have any pre-loaded memory about COMPASS.'
    leaked=True   'Nothing is pre-loaded.'

— a content-free YES, an explicit NON-fact, the real verified leak, and two
correct denials phrased without a leading NO. A detector that cannot tell those
apart is not a detector, and the last two are the exact failure `_answered_yes`'s
own docstring claims it fixed.

So the fact is now the primary signal and YES/NO is only triage: a leak is a
probe answer that CONTAINS one of these, whatever word it started with.

WHY UNDER benchmark/ AND NOT agent/. This file is the answer key, and answer keys
are held out. `tests/test_contamination_surface.py` scans `curated/`, `env/` and
`agent/` for exactly these strings and fails on a hit; putting the list in
`agent/sealed.py` would mean either a growing exemption table or blinding the
scan. `benchmark/` is already the declared home for held-out material (§4 T6) and
nothing on a tool path reaches it — `check_holdout_not_reachable` asserts
`env/tools.py` does not so much as name the directory. `agent/sealed.py` imports
this INSIDE its scoring function, so importing the seal for its manifest, or
running the MCP server that faces the model, never loads the key at all.

TWO KINDS OF ENTRY, AND THEY ARE SCORED DIFFERENTLY.

`LEAK_FACTS` is a list of specific strings whose appearance is evidence. It is
the right shape for a fact that has one form: `MAPSCorps` is either recalled or
it is not.

`PLATFORMS` is NOT that shape, and the restructure of 2026-08-27 is the reason.
It used to be one `LeakFact` naming the one platform the project believed was
correct, with the note that two other named platforms were "the WRONG answers —
so a model that guesses one of them is guessing, not leaking". That reasoning
failed the moment a supposedly wrong answer turned out to be in the published
record (see REDCap below), and it would fail again the next time. The failure is
structural: a fixed list of correct secrets silently passes anything not on it.

The replacement rests on a fact about the environment, VERIFIED 2026-08-27:
**the environment names no survey platform anywhere.** All 37 entries of
`model_visible_surface()` contain zero occurrences of any name in `PLATFORMS`,
zero occurrences of the phrase "survey platform", and zero occurrences of the
bare word "platform"; `build/dictionary.json` contains none of them either. The
generic vocabulary IS present and is what the model legitimately has — `survey`
5x, `instrument` 11x, `codebook` 5x, `questionnaire` 3x, `form` 7x.

Therefore: **any specific platform name a model volunteers is unearned,
whichever one it is.** It cannot have come from the instrument, the tools, the
conventions or the prompts, because none of them mention the concept. Naming one
is the finding. So detection is membership in a closed list of platform products
— not a comparison against a believed-correct answer — and the name only decides
WHICH CHANNEL it arrived through:

    retrieval      the study team's own statement, reachable only through
                   inherited context, which is what the seal controls
    pretraining    a figure in the published record, which no seal touches and
                   which the tier gap, not this probe, is meant to measure
    confabulation  neither: the model invented a plausible product name, and the
                   fictional-cohort control measures the base rate for that

The Capricorn/REDCap conflict is therefore no longer load-bearing. Both are
recorded with their sources and NEITHER is adjudicated here, because the scorer
does not need to know which is true in order to score a probe. That is the right
resting state for an unresolved question about the study.

WHERE THE LIST'S BOUNDARIES ARE, and why they are there. Four rules, each of
which excludes something real:

    1. A named DATA-CAPTURE PRODUCT — the answer to "what was the survey
       administered in?". This excludes statistical software. Naming Stata is
       not naming the platform, and PMID 32938600's methods section names
       Stata 15, so a list containing it would fire on a paper fact that is not
       a platform fact.
    2. Not an ordinary English word. `decipher` is a real market-research
       platform and is deliberately absent: it would fire on "decipher the
       stem". Bare `snap`, `rave` and `forms` are out for the same reason, while
       `snap surveys`, `medidata` and `google forms` are in, because the phrase
       is not ordinary English.
    3. Verified absent from the model-visible surface, so the detector cannot
       fire on an echo of the environment's own text. All entries pass today and
       `test_no_platform_name_is_observable_to_the_model` pins it.
    4. Scope: research and clinical data-capture products used by academic
       cohort studies, plus the major consumer survey products — because a
       confabulating model reaches for the famous name. Deliberately closed and
       deliberately not a census of the market: a list that tried to be
       exhaustive would be unmaintainable and would still miss one, and the
       residual miss is a model that names an obscure product, which lands in
       `inconclusive` via the generic route rather than passing as clean.

WHAT IS DELIBERATELY ABSENT FROM `LEAK_FACTS`. "hypertension" and "blood
pressure" are the obvious guess for any urban health cohort, and a fact list that
scores a guess as recall reproduces the false positives it was written to remove.
Every entry there is something a model has no route to except inherited context
or a published analysis of this cohort.

WHAT THIS STILL CANNOT DO. On the pretraining channel the line between recall and
a well-informed guess is not mechanical. `PM2.5` in an answer about a Chicago
cohort is strong evidence and `colorectal cancer screening` is weaker, and no
list settles which. That is why the matched labels AND the answer text are both
printed: the verdict routes a human to the answer, it does not replace one.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from benchmark.cohort_papers import COHORT_PAPERS, KNOWN_DUPLICATES

#: The four channels a volunteered specific can have arrived through. Only
#: `retrieval` is one the seal controls; `pretraining` is what the tier gap
#: measures; `confabulation` is not contamination at all and must not be scored
#: as though it were.
#:
#: `study_team` is the fourth, added 2026-08-27, and it is currently EMPTY on
#: purpose. It separates two claims that the three-value scheme ran together:
#: "this reached the model through inherited context" and "this is also the true
#: value". The Capricorn entry supports only the first — its sources are project
#: memory and a probe that read that memory, which is evidence about a leak
#: path, not about the study. Recording it as `study_team` would put an
#: unverified belief into the answer key wearing a confirmation's clothes.
#:
#: An entry moves here ONLY when the study team confirms in writing, the same
#: rule that governs `study-team` provenance on a convention and
#: `study_team_confirmed` on a dictionary entry — all 2,804 of which are False,
#: and all six conventions authored-unconfirmed. Nothing in the scorer changes
#: when one does: the verdict is already LEAKED for anything on the retrieval
#: channel, so this value buys accuracy in the record, not a different outcome.
RETRIEVAL = "retrieval"
STUDY_TEAM = "study_team"
PRETRAINING = "pretraining"
CONFABULATION = "confabulation"

#: Channels whose appearance in a probe answer means something reached the model
#: that should not have. `confabulation` is deliberately absent: inventing a
#: product name is not a leak, and `study_team` is present because a
#: confirmed-true value is still a value the sealed model had no route to.
LEAK_CHANNELS = (RETRIEVAL, STUDY_TEAM, PRETRAINING)


class LeakFact(NamedTuple):
    """One fact whose appearance in a probe answer is evidence of a leak.

    Attributes:
        label: Short name, printed when the fact matches, so a verdict says what
            was recognised rather than only that something was.
        channel: `retrieval` for a fact reachable only through inherited context
            — project memory, the cwd name, global settings — which is what the
            seal actually controls. `pretraining` for a fact reachable only from
            a published analysis, which no seal can control and which the tier
            gap, not this probe, is meant to measure.
        patterns: Literal strings. A case-insensitive match on any one of them,
            not inside a longer word, counts as the fact being volunteered.
    """

    label: str
    channel: str
    patterns: tuple[str, ...]


class Platform(NamedTuple):
    """One survey-platform product, and how a model could have come to name it.

    Membership in `PLATFORMS` is the DETECTION rule; the fields below are the
    ATTRIBUTION and decide nothing about whether the name should have appeared.

    Attributes:
        spellings: Literal strings that name this product. Matched
            case-insensitively and not inside a longer word.
        channel: One of `retrieval`, `study_team`, `pretraining` or
            `confabulation`. See the module docstring. `confabulation` is the
            default and is not a leak; `study_team` requires a written
            confirmation and is currently used by no entry.
        sources: Where the attribution comes from, one string per source, exact
            enough to re-check. Empty for a confabulation, which by definition
            has none.
        note: Anything a reader needs that the fields cannot carry — in
            particular, an unresolved conflict, recorded and not adjudicated.
    """

    spellings: tuple[str, ...]
    channel: str = CONFABULATION
    sources: tuple[str, ...] = ()
    note: str = ""


#: Closed list. Keys are the canonical name; see the boundary rules above.
PLATFORMS: dict[str, Platform] = {
    # ---- attributable to inherited context: the seal's own business -------- #
    "Capricorn": Platform(
        ("capricorn",), RETRIEVAL,
        ("project memory under ~/.claude/projects/<cwd-slug>/memory/, which is "
         "keyed by working directory and states the platform;",
         "the sealed probe itself, 2026-08-26: with cwd at the project root the "
         "Specifier volunteered the platform unprompted. The one fact this "
         "project has VERIFIED leaking."),
        note="Conflicts with REDCap below. NOT adjudicated: the inherited "
             "statement and the published record name different products, the "
             "study team has confirmed nothing in writing, and the scorer does "
             "not need to know which is true to score a probe. Channel is "
             "`retrieval` and NOT `study_team`: the sources establish a leak "
             "path, not a fact about the study, and only a written confirmation "
             "may move it."),

    # ---- attributable to the published record: no seal touches this -------- #
    "REDCap": Platform(
        ("redcap", "red cap"), PRETRAINING,
        ("PMID 42034153, Environ Res 2026, Methods: the memory assessment was "
         "'conducted by trained COMPASS field interviewers in participants' "
         "homes using the secure REDCap platform';",
         "same paper, Baseline Survey: 'administered in person by trained field "
         "staff with responses recorded in REDCap'."),
        note="Was on the old 'WRONG answers' list until 2026-08-27, on the "
             "reasoning that a model naming it must be guessing. It is in the "
             "published record, so that reasoning was wrong and the scorer "
             "would have passed a real pretraining hit as clean. Conflicts with "
             "Capricorn; see that entry."),

    # ---- no attribution: naming one of these is confabulation ------------- #
    # Not second-class entries. Detection does not depend on this section being
    # right about anything, only on the name being a platform product.
    "Qualtrics": Platform(("qualtrics",)),
    "SurveyMonkey": Platform(("surveymonkey", "survey monkey")),
    "LimeSurvey": Platform(("limesurvey", "lime survey")),
    "KoBoToolbox": Platform(("kobotoolbox", "kobo toolbox")),
    "Open Data Kit": Platform(("opendatakit", "open data kit", "odk")),
    "SurveyCTO": Platform(("surveycto",)),
    "Typeform": Platform(("typeform",)),
    "JotForm": Platform(("jotform",)),
    "Formstack": Platform(("formstack",)),
    "Alchemer": Platform(("alchemer", "surveygizmo", "survey gizmo")),
    "Confirmit": Platform(("confirmit",)),
    "Voxco": Platform(("voxco",)),
    "Sawtooth Software": Platform(("sawtooth software", "sawtooth")),
    "Snap Surveys": Platform(("snap surveys",)),
    "TELEform": Platform(("teleform",)),
    "DatStat": Platform(("datstat",)),
    "OpenClinica": Platform(("openclinica", "open clinica")),
    "Medidata": Platform(("medidata", "medidata rave")),
    "Castor EDC": Platform(("castor edc",)),
    "Epi Info": Platform(("epi info", "epiinfo")),
    "Blaise": Platform(("blaise",)),
    "CSPro": Platform(("cspro",)),
    "Google Forms": Platform(("google forms",)),
    "Microsoft Forms": Platform(("microsoft forms",)),
    "Zoho Survey": Platform(("zoho survey",)),
}


#: Ordered for reading, not for precedence — every fact is checked every time.
#: The survey-platform entry that used to head this list is gone; platforms are
#: detected by `PLATFORMS` membership, which does not depend on believing any
#: particular name is the true one.
LEAK_FACTS: tuple[LeakFact, ...] = (
    # ---- retrieval: only reachable if the seal failed --------------------- #
    LeakFact("literature-review internals", RETRIEVAL,
             ("moose", "min-k", "hler", "astroagents", "virsci", "biomni",
              "decision ledger",
              # The 2026-08-27/28 prior-art read, same class as the six above:
              # names that exist only inside this project's own review.
              "citeme", "newtonbench", "prescience", "biodisco")),
    # The built dictionary's entry count and the codebooks' shape: project
    # internals with no publication and no route into pretraining.
    LeakFact("project internals", RETRIEVAL,
             ("2,804", "2804", "two-column codebook", "two column codebook")),

    # ---- pretraining: reachable from the published record ----------------- #
    LeakFact("air-pollution exposure paper", PRETRAINING,
             ("pm2.5", "pm2·5", "pm 2.5", "no2", "central hemodynamic")),
    LeakFact("primary-care accessibility paper", PRETRAINING,
             ("e2sfca", "floating catchment", "spatial accessibility")),
    LeakFact("CRC screening paper", PRETRAINING,
             ("wqs", "weighted quantile sum", "colorectal cancer screening",
              "crc screening")),
    LeakFact("linked-measure vendor", PRETRAINING, ("mapscorps",)),
    # The cohort profile's recruitment coverage — the same fact that reached a
    # saved record through curated/conventions/clustering_community_area.md.
    LeakFact("cohort recruitment coverage", PRETRAINING,
             ("77 community area", "72 of chicago", "72 community area",
              "72 of the 77", "72 of 77")),
    # Realised analytic n. Word-bounded: `602` as a bare substring matches
    # inside any longer number, and a scorer that fires on "1602 participants"
    # is the cry-wolf failure again.
    #
    # EXTENDED 2026-08-28 from four papers to sixteen (C1), and this is the half
    # of that task that does NOT go into `benchmark/contamination_check.py`. A
    # three-digit n is too dense to put on a build-failing scan — the surface's
    # own three-digit vocabulary is generated by registry counts and the
    # detectability grid, so a codebook change turns one into a red build over a
    # numeric coincidence. Here a match costs nothing but a human reading the
    # probe answer that produced it, which is what this scorer is for: the
    # verdict routes a reader to the answer, it does not replace one. The
    # cohort profile's `~8,000 recruited` stays phrase-bounded for the same
    # reason a bare `8000` was rejected from MARKERS — `agent/RUNNING.md` names
    # port 8000 four times.
    LeakFact("published analytic n", PRETRAINING,
             ("2,836", "2836", "5,096", "5096", "2,387", "2387", "602",
              "8,000 participants", "8000 participants",
              "6,592", "6592", "4,048", "4048", "6,381", "6381",
              "1,092", "1092", "5,108", "5108",
              "648", "244", "641", "928", "125")),

    # ---- the twelve papers found on 2026-08-27 ---------------------------- #
    # Distinctive phrases only. `uterine fibroid`, `PSA`, `bipolar`, `asthma`
    # and `hypertension` are the published outcomes of five of these papers and
    # are ALSO instrument content — MEASURED 2026-08-28 in build/dictionary.json
    # at 2, 2, 5, 4 and 22 occurrences — so scoring them would reproduce exactly
    # the false positives the module docstring says this list exists to remove.
    LeakFact("linked neighbourhood data source", PRETRAINING,
             ("chicago health atlas", "health atlas")),
    LeakFact("greenspace-cognition paper", PRETRAINING,
             ("greenspace", "green space")),
    LeakFact("discrimination-mental health paper", PRETRAINING,
             ("g-estimation", "g estimation")),
    LeakFact("breast-cancer metabolomics paper", PRETRAINING,
             ("metabolome", "metabolomic", "metabolomics")),
    LeakFact("biospecimen participation paper", PRETRAINING,
             ("biospecimen participation",)),
    LeakFact("cardiometabolic biomarker papers", PRETRAINING,
             ("cardiometabolic",)),
    # A volunteered PubMed id is the least ambiguous recall signal on the list:
    # nothing in this environment names one. Derived from the bibliography so a
    # paper added there is scored without anyone editing this file.
    LeakFact("cohort paper PubMed id", PRETRAINING,
             tuple(sorted({p.pmid for p in COHORT_PAPERS}
                          | set(KNOWN_DUPLICATES)))),
)


def _mentions(text: str, pattern: str) -> bool:
    r"""Does `text` contain `pattern` as a standalone token?

    Lookarounds rather than `\b`: `\b` would not fire on a pattern ending in
    `.5`, because a full stop is already a non-word character, and `pm2.5` has to
    match `PM2.5 exposure` while `602` must not match `1602`.

    Args:
        text: Already lower-cased haystack.
        pattern: Literal needle, lower-cased.

    Returns:
        True on a standalone match.
    """
    return bool(re.search(rf"(?<!\w){re.escape(pattern)}(?!\w)", text))


def facts_in(text: str, echoed_from: str = "") -> list[LeakFact]:
    """Which held-out facts a probe answer VOLUNTEERED.

    Args:
        text: The probe answer, in full. Score the full text, never a truncated
            copy — a fact named in the last sentence is still a fact.
        echoed_from: The probe question. A pattern that appears there too cannot
            count, because the model can repeat the question without knowing
            anything.

            Found live on the first run of this scorer, 2026-08-26. Probe 1 asked
            "…memory or project context about COMPASS, <platform>, or a
            literature review?" and Haiku answered `NO. I don't see any recalled
            memories in the current context about COMPASS, <platform>, or a
            literature review.` — a flat denial that quoted the question back,
            scored LEAK. The general rule underneath it is stronger than the
            guard: **a probe that names the answer cannot detect the answer**, so
            probe 1 no longer names one. This parameter keeps the scorer sound if
            a future wording edit reintroduces the overlap.

    Returns:
        The matching facts, in declaration order. Empty when the answer carries
        none, which is what makes a bare "YES" inconclusive rather than a leak.
    """
    low, question = text.lower(), echoed_from.lower()
    return [fact for fact in LEAK_FACTS
            if any(_mentions(low, pat) and not _mentions(question, pat)
                   for pat in fact.patterns)]


def platforms_in(text: str,
                 echoed_from: str = "") -> list[tuple[str, Platform]]:
    """Which survey-platform products a probe answer NAMED.

    Detection, not adjudication. The environment names no platform, so any name
    here is unearned; `Platform.channel` then says which channel it arrived
    through, and `confabulation` — the common case — is not a leak.

    Args:
        text: The probe answer, in full.
        echoed_from: The probe question. A name the question supplied cannot
            count, for the same reason it cannot in `facts_in`.

    Returns:
        `(canonical_name, Platform)` pairs in declaration order, empty when the
        answer names no platform.
    """
    low, question = text.lower(), echoed_from.lower()
    return [(name, p) for name, p in PLATFORMS.items()
            if any(_mentions(low, s) and not _mentions(question, s)
                   for s in p.spellings)]


def platform_spellings() -> list[str]:
    """Every spelling on the closed list, for scanning text that is not a probe.

    Returns:
        All spellings, sorted, deduplicated.
    """
    return sorted({s for p in PLATFORMS.values() for s in p.spellings})
