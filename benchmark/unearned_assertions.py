"""benchmark/unearned_assertions.py — quantities the environment cannot supply.

THE CLASS. This session found the same defect four times in four costumes, and
the shape is always: the model asserts a number the environment has no way to
give it, the number then sets a bar the model is judged by, and nothing detects
it. Each instance was found by hand, one at a time, by someone auditing a
different thing. This file is the index, so the fifth is found by reading a table
instead of by luck.

The test for membership is not "is it uncertain" but "could any tool, any file,
or any convention in this environment produce it?". If the answer is no, then a
model that states it has stated something unearned, and the only two honest
outcomes are a labelled assumption or a blocker.

WHAT AN UNEARNED ASSERTION IS NOT. It is not necessarily wrong. `0.35` may well
be close to the truth. The objection is not to the value but to its STANDING: an
assertion with no route into the environment cannot be checked here, so it may
not silently become a measurement, and it may above all not set a threshold the
same model is then scored against.

THE PROVENANCE RULE, which is the thing that will be got wrong later.

    A BOUND TAKEN FROM A PAPER MAY NEVER SET THE ENVIRONMENT'S FLOOR.

If the environment's gate depended on a figure from a cohort paper, the benchmark
would be scoring the model against a standard derived from the answers, and every
number it produced would be unfalsifiable in the same way the tier gap is
unfalsifiable when the exclusion list is wrong. This is not a style preference;
it is the difference between a benchmark and a circular argument.

So bounds are sorted into three tiers by where they come from, and the tier
decides where the bound may live. `PROVENANCE_TIERS` below carries them as data
so a later scorer can check placement rather than trusting a reviewer to
remember.

WHAT THIS FILE DOES NOT DO. It does not gate anything. `scan_record` is
ADVISORY — it reports, it does not reject — because it is a regex over prose and
the correct response to a regex over prose is a human reading the hit. It is
calibrated to zero false positives across the eight records that currently
validate, and a test pins that; if it ever starts firing on a legitimate record,
loosen the pattern rather than teaching a reviewer to ignore the output, which is
how this project has lost detectors before.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple


class ProvenanceTier(NamedTuple):
    """Where a bound came from, and therefore where it is allowed to live.

    Attributes:
        name: Tier id.
        may_live_in: Directories a bound of this tier may be written into.
        may_set_the_floor: Whether the environment's gate may compare against it.
        reason: Why the placement rule is what it is.
        examples: Concrete instances, so the tier is recognisable in the wild.
    """

    name: str
    may_live_in: tuple[str, ...]
    may_set_the_floor: bool
    reason: str
    examples: tuple[str, ...]


#: Ordered from least to most restricted.
PROVENANCE_TIERS: tuple[ProvenanceTier, ...] = (
    ProvenanceTier(
        "theory_derived", ("env/", "curated/", "agent/", "benchmark/"), True,
        "Contains no study content, so it cannot leak one and cannot make the "
        "gate circular. It is a mathematical fact, checkable by anyone, and it "
        "is the only tier the environment's floor may rest on.",
        ("prevalence is maximised at one half, which is why "
         "WORST_CASE_PREVALENCE is 0.5",
         "the design effect FORMULA 1 + (m - 1) * ICC — the formula is theory, "
         "its inputs are not, and stating the formula while refusing the inputs "
         "is the honest half of that distinction",
         "alpha and power are conventions, not unknowns, which is why the "
         "environment may simply fix them")),
    ProvenanceTier(
        "general_literature_derived", ("benchmark/",), False,
        "External and non-COMPASS, so it carries no cohort-contamination risk — "
        "but it is a new provenance surface, and a figure remembered rather "
        "than sourced would silently become the thing a whole test rests on. It "
        "may CHECK the environment's bound; it may not BE it.",
        ("a general-population prevalence for an outcome, which the prevalence "
         "key's differential needs and does not have",
         "published ranges for neighborhood-level intracluster correlations")),
    ProvenanceTier(
        "cohort_paper_derived", ("benchmark/",), False,
        "The answers. A gate resting on one would score the model against a "
        "standard derived from what it is being asked to rediscover. Permitted "
        "use is exactly one: establishing whether the environment's own bound "
        "is adequate — for instance, showing that a floor assuming independence "
        "is not merely imprecise but materially wrong.",
        ("every figure in benchmark/prevalence_key.py",
         "any clustering parameter a cohort paper reported, of which there are "
         "none — see CLUSTERING_PARAMETERS")),
)


class Unearned(NamedTuple):
    """One quantity the environment cannot supply, and its current status.

    Attributes:
        quantity: What the model asserts.
        environment_supplies: What, if anything, the environment can give
            instead. "nothing" is the common and important case.
        asserted_where: Where the assertion lands.
        sets_a_bar: Whether the asserted value moves a threshold the same model
            is judged by. This is what turns an assumption into a defect.
        status: `closed`, `open`, or `closed_by_blocker` when the honest
            resolution is to refuse rather than to compute.
        detector: What catches it today, or "" when nothing does.
        bound_tier: Which `PROVENANCE_TIERS` entry a bound would fall into.
        found_by: How the instance came to light — recorded because four of
            five were found by someone auditing something else, which is the
            argument for this table existing.
    """

    quantity: str
    environment_supplies: str
    asserted_where: str
    sets_a_bar: bool
    status: str
    detector: str
    bound_tier: str
    found_by: str


#: The class, as of 2026-08-27. Add a row when one is found; do not delete a
#: closed row, because the pattern is the point and a table of open items only
#: would hide how this keeps happening.
UNEARNED: tuple[Unearned, ...] = (
    Unearned(
        "baseline_prevalence", "nothing: no tool returns a prevalence, "
        "build/dictionary.json counts items and not participants, and "
        "value_labels are null for every entry",
        "estimate_detectability argument, then estimability.assumptions",
        True, "closed",
        "the falsifier gate compares against the environment's bound, so the "
        "asserted value no longer moves the bar; it is carried as a labelled "
        "unverified assumption and scored against benchmark/prevalence_key.py",
        "cohort_paper_derived",
        "an audit of what the environment supplies, after 10 recorded runs "
        "chose six different values for one outcome"),
    Unearned(
        "alpha and power", "the conventions themselves — these are NOT unknowns, "
        "which is what makes them the easiest of the class to close",
        "estimate_detectability arguments, then estimability.assumptions",
        True, "closed",
        "the bound is computed at BOUND_ALPHA/BOUND_POWER whatever the caller "
        "passes, and both are gone from the model-visible schema",
        "theory_derived",
        "reading the bound's code after it was described as caller-independent "
        "in the tool's own log, which it was not"),
    Unearned(
        "the survey platform's name", "nothing: verified zero occurrences of any "
        "platform name, of 'survey platform', or of the bare word 'platform' "
        "across all 37 model-visible surfaces",
        "a seal probe answer",
        False, "closed",
        "benchmark/leak_facts.py PLATFORMS membership, plus "
        "check_no_platform_name_in_surface as a ratchet on the premise",
        "cohort_paper_derived",
        "a user instruction that the platform not be observable, which turned "
        "out to describe the environment as it already was"),
    Unearned(
        "the design effect for community-area clustering",
        "nothing, and this one cannot be closed by computing: participants per "
        "community area are unknown for the same reason analytic n is, and the "
        "intracluster correlation needs response data",
        "implicitly, in every falsifier threshold: the floor assumes "
        "independence while the clustering convention requires cluster-robust "
        "standard errors, and clustering inflates the true floor",
        True, "closed_by_blocker",
        "estimate_detectability returns independence_assumption, stating the "
        "conflict, its direction and the blocker; NO number is supplied",
        "general_literature_derived",
        "asking what else the environment is silent about after the prevalence "
        "and platform cases"),
    Unearned(
        "a variable's response scale, coding or missing codes",
        "nothing, and the absence is total: all 2,804 dictionary entries have "
        "value_labels, response_options, value_type, missing_codes, "
        "measurement_level and branch_dependency null",
        "six gated fields of the record, not all free text",
        False, "closed_by_gate",
        "ProtocolSpecification rejects it as of 2026-08-28 over "
        "CODING_GATED_FIELDS, using its own CODING_ASSERTION_PATTERNS; every "
        "kept pattern requires a numeral, because prose about the ABSENCE of "
        "codes names none. scan_record below stays ADVISORY and keeps a "
        "separate, looser set: it is what a human reads, and the two sets "
        "drifting is the live risk, since agent -> benchmark is not an allowed "
        "import direction. Measured 0 false positives over all 23 records on "
        "disk, but 22 of the 23 specify one exposure-outcome pair, so that is "
        "weaker evidence than the count suggests. NOT gated: quoted_wording, "
        "because m2:Q19.86_1's own instrument text reads '0 = Mild pain; "
        "10 = Extreme pain' and _wording_is_verbatim requires it verbatim - "
        "gating it would set two validators against each other",
        "theory_derived",
        "generalising from the platform case: a stated scale is structurally "
        "the same event as a named platform"),
)


#: Which of the sixteen inventoried papers report a clustering parameter. NONE
#: do, and that negative result is recorded here so it is not rediscovered.
#:
#: Retrievability is as in benchmark/prevalence_key.py: twelve read in full via
#: PMC, four in abstract only. Searched for intraclass / intracluster / ICC /
#: design effect / DEFF / cluster-robust / clustering / random effect /
#: multilevel / mixed effect / GEE across every retrieved text.
CLUSTERING_PARAMETERS: dict[str, str] = {
    "32938600": "reports none. NAMES the concept — 'as two locations within the "
                "same census block do not each contribute completely "
                "independent information (this is known as the intra-cluster "
                "correlation)' — while describing two-stage sampling, with NO "
                "value, and at census block/tract rather than community area.",
    "36065817": "reports none. The two term hits are not what they look like: "
                "'multilevel' appears in the title of a linked commentary "
                "(PMID 36065816) carried in the PMC metadata, and 'GEE' is the "
                "surname Gee G in a reference list.",
    "37252073": "reports none. Clusters at the right level — 'robust standard "
                "errors to account for clustering at the community level' — "
                "and reports no ICC and no design effect. One of the two "
                "papers whose design actually clusters at community area.",
    "38715087": "reports none. NEAR MISS, and the most dangerous entry here: it "
                "reports an intraclass correlation of 0.72, which is a DEVICE "
                "REPRODUCIBILITY coefficient for arterial compliance from blind "
                "duplicate measurements in a cited validation study. It is a "
                "different quantity from a clustering ICC and must never be "
                "substituted for one.",
    "38397711": "reports none, and says so explicitly: 'a multilevel model was "
                "not utilized to analyze the contextual neighborhood variables "
                "because the available data had no hierarchical or clustered "
                "structure.'",
    "32542493": "reports none (abstract only).",
    "33088675": "reports none. No clustering term appears anywhere in the text.",
    "36702470": "reports none (abstract only; PMC record is metadata-only).",
    "36823587": "reports none (abstract only).",
    "37879000": "reports none (abstract only; no PMC full text).",
    "37884074": "reports none. Uses 'random effects of residential zip codes for "
                "intercept' — wrong level, and no variance component printed "
                "from which an ICC could be computed.",
    "38961645": "reports none (abstract only; PMC record is metadata-only).",
    "39217205": "reports none. 'A random intercept for the residential zip code' "
                "and a cluster COUNT of 130 unique zip codes — wrong level for "
                "community area, and a count is not an ICC.",
    "39238838": "reports none. The single 'multilevel' hit is a reference-list "
                "title (Naess et al. 2007).",
    "41883377": "reports none. Cluster-robust standard errors with random "
                "intercepts at 3-digit zip code, no ICC and no design effect.",
    "42034153": "reports none. No clustering term appears anywhere in the text.",
}

#: Patterns for a response-scale, coding or missing-code assertion. Each is
#: deliberately narrow, because the calibration constraint is zero false
#: positives on records that are otherwise correct — `mean Likert score, 5-item
#: scale` is a legitimate derivation unit and must not fire, while `1-5 Likert
#: scale (1=strongly disagree)` must.
SCALE_PATTERNS: dict[str, str] = {
    "value_label_enumeration": r"\b\d+\s*=\s*[A-Za-z]",
    "coding_claim": r"\bcod(?:ed|ing|es)\b",
    # `\u2013` rather than a literal en dash: ruff flags the ambiguous glyph,
    # and a model writing "1\u20135" must still be caught.
    "scale_range": r"\b\d+\s*(?:-|\u2013|\bto\b)\s*\d+\s*(?:point|likert|scale)\b",
    "n_point_scale": (r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine"
                      r"|ten)[- ]point\b"),
    "scored_range": r"\bscor(?:ed|ing)\s+\d+\s*(?:-|\u2013|\bto\b)\s*\d+",
    "missing_code": (r"\bmissing\s+cod|(?<![\w-])-\d{2,4}\b|\b9{3,4}\s*=|"
                     r"\b7\s*/\s*8\s*/\s*9\b|"
                     r"\b\d{2,4}\b[^.]{0,30}\b(?:refus|don'?t know|not applicable)"),
    "response_option_list": r"\bresponse\s+(?:option|categor|code|scale)",
}

#: Record paths this detector does not read. `provenance.tool_calls` is a
#: transcript of what the environment returned, not a claim the model made, and
#: scanning it would report the environment to itself.
SCAN_EXEMPT_PREFIXES: tuple[str, ...] = ("provenance.tool_calls",)


def _walk(obj: Any, path: str = "") -> list[tuple[str, str]]:
    """Every string in a record, with its dotted path.

    Args:
        obj: A decoded record, or any part of one.
        path: Dotted path accumulated so far.

    Returns:
        `(path, text)` pairs for every string leaf.
    """
    if isinstance(obj, dict):
        return [pair for k, v in obj.items()
                for pair in _walk(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [pair for i, v in enumerate(obj) for pair in _walk(v, f"{path}[{i}]")]
    return [(path, obj)] if isinstance(obj, str) else []


def scan_record(record: dict[str, Any]) -> list[tuple[str, str, str]]:
    """ADVISORY. Where a record appears to state a response scale or coding.

    Not a gate, and deliberately not wired into one. HARD RULE 3 of the system
    prompt says a model may not state a variable's response scale, coding or
    missing codes, and `resolve_variable`'s log repeats it; VERIFIED 2026-08-27
    that nothing enforces either. This reports; a human reads the hits.

    Calibrated against the eight records under `run/` that currently validate:
    zero hits. If it starts firing on a legitimate record, narrow the pattern.
    An advisory that reviewers learn to skim past is worse than none.

    Args:
        record: A decoded protocol record.

    Returns:
        `(path, pattern_name, text)` triples, one per hit, in record order.
    """
    return [(path, name, text)
            for path, text in _walk(record)
            if not path.startswith(SCAN_EXEMPT_PREFIXES)
            for name, pattern in SCALE_PATTERNS.items()
            if re.search(pattern, text, re.I)]


def tier(name: str) -> ProvenanceTier:
    """Look up a provenance tier by name.

    Args:
        name: One of the `PROVENANCE_TIERS` names.

    Returns:
        The tier.

    Raises:
        KeyError: If no tier has that name, rather than returning a permissive
            default — a bound whose tier nobody can name has not been placed.
    """
    for t in PROVENANCE_TIERS:
        if t.name == name:
            return t
    raise KeyError(f"no provenance tier {name!r}; "
                   f"known: {[t.name for t in PROVENANCE_TIERS]}")
