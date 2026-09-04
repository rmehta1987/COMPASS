"""benchmark/contamination_check.py — one command, run it before every benchmark run.

    ./.venv/bin/python -m benchmark.contamination_check          # offline, free
    ./.venv/bin/python -m benchmark.contamination_check --live   # + seal probes (costs)

WHY A SEPARATE COMMAND AND NOT JUST TESTS. The tests check surfaces one at a
time and only when someone runs pytest. This assembles the ACTUAL bytes the model
receives — system prompt, user prompt, the JSON schema pasted into the
transduction call, and the return value of every tool in the registry — and scans
that single blob. A marker that never appears in any source file can still reach
the model, because tool output is generated, not stored.

WHY EVERY TOOL, WITH REPRESENTATIVE ARGUMENTS. Until 2026-08-26 this sampled 5 of
the 11 registry tools and reported "clean". `estimate_detectability` was one of
the six it never called, and its default `n_values` grid ended in a published
COMPASS analysis's realised analytic n — so the marker scan had a hole exactly
where a leak was sitting, and the hole was invisible because the surface count
and the hash both looked stable. Coverage is now checked: a tool present in
`build_registry(mode)` that `tool_samples()` does not sample FAILS this command.
Arguments are chosen to exercise a tool's real branches, because a tool sampled
with arguments that dodge its leaky default is not sampled.

It also emits `surface_hash`. Record it. If it changes and you did not change a
prompt, a convention or a docstring, something started reaching the model that
did not before.

WHAT IT CANNOT DO, AND WHY NO CHECK HERE WILL. Markers catch quotation. A
provenance declaration catches an author who knows the source is a paper. Neither
catches the case that actually happened on 2026-08-26:

    curated/conventions/clustering_community_area.md opened with "COMPASS
    recruited from 72 of Chicago's 77 community areas" — the cohort profile's
    recruitment coverage. `check_markers` passed it, because `72` and `77
    community areas` are not markers. `check_provenance` passed it, because the
    file declared `authored-unconfirmed` and the author believed that. It is
    served by get_design_convention, it was inside the hashed surface, and the
    live record run/.fe7cbe643d35ef50.json carries it in
    selection_rationale.prior_work with that tool call in its own log.

An author who declares the source honestly-but-wrongly defeats both checks by
construction, and no third check fixes it: a scan cannot know which sentences a
human read a paper to write. Enumerating the paper facts to grep for would mean
writing them into a scanned file, i.e. building the leak to detect it — and the
inventory is admittedly incomplete (§3: sixteen COMPASS records indexed, four
inventoried), so the enumeration would be wrong anyway.

So this is stated rather than automated: **the residual control is a human
re-reading every curated sentence against the paper record and being able to say,
per sentence, where it came from that is not a paper.** The marker list, the
provenance rule and the coverage check narrow what a reader has to hold in their
head. They do not replace the reader, and a check that looked like they did would
be worse than the honest gap.

ONE EXCEPTION, ADDED 2026-08-27, AND WHY IT IS NOT THE THING ARGUED AGAINST
ABOVE. `check_no_prevalence_figure_in_surface` does enumerate paper facts —
every prevalence in `benchmark/prevalence_key.py` — and greps the surface for
them. The objection above is to writing paper facts into a SCANNED file in order
to detect them. These are not written anywhere new: they are derived at check
time from a file that already exists on the held-out side, which
`tests/test_contamination_surface.py` deliberately does not scan and no tool path
reaches. The check is bounded to one quantity, the one input to
`estimate_detectability` that the model asserts and the environment cannot
supply, and it is a check ON the placement rule rather than a replacement for it.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent.prompt_contract as PC  # noqa: E402
import agent.query_rewrite as QR  # noqa: E402
import agent.specifier as SP  # noqa: E402
from agent.registry import Mode, build_registry  # noqa: E402
from agent.schema import NotSpecifiable, ProtocolSpecification  # noqa: E402
from agent.specifier import SYSTEM, _emit, user_prompt  # noqa: E402
from benchmark import resolver_eval as RE  # noqa: E402
from benchmark import retrieval_eval as RE_RETRIEVAL  # noqa: E402
from benchmark.cohort_papers import (  # noqa: E402
    COHORT_PAPERS,
    KNOWN_DUPLICATES,
)
from benchmark.input_leakage import (  # noqa: E402
    check_input_does_not_contain_the_answer,
)
from env import labels as LB  # noqa: E402
from env import tools as T  # noqa: E402
from generate import hybrid_ed as HY  # noqa: E402
from generate.funnel import load_constructs, run  # noqa: E402

#: Pool depths the hybrid renders, mirrored from `generate/hybrid_ed.py` so the
#: scan covers every depth that ships rather than one of them.
HYBRID_DEPTHS = HY.DEPTHS


def _pmid_tokens() -> list[str]:
    """Every PubMed id in the bibliography, including the recorded duplicate.

    DERIVED, not listed, for the reason `check_no_prevalence_figure_in_surface`
    derives its figures: a paper added to `benchmark/cohort_papers.py` is covered
    without anyone remembering to edit a list here, and the inventory has already
    gone from four to sixteen once. An eight-digit id is about as low a
    false-positive risk as a token gets — MEASURED 2026-08-28, the whole
    model-visible surface contains six distinct four-digit integers and no longer
    one.

    Returns:
        Sorted PubMed ids as strings.
    """
    return sorted({p.pmid for p in COHORT_PAPERS} | set(KNOWN_DUPLICATES))


def _published_n_tokens() -> list[str]:
    """Realised analytic n from the bibliography, in both written forms.

    Both forms, because a scan that only caught `n=2,836` would miss the same
    number inside a list literal — which is exactly how one survived here for a
    month.

    FOUR DIGITS AND UP ONLY, and this is the line C1 asks for. The environment
    legitimately emits small integers: `registry_coverage` returns per-registry
    counts (142, 2326, 336 today), `estimate_n` returns co-completion counts, and
    `DETECTABILITY_N_GRID` is a published grid of round numbers. MEASURED
    2026-08-28, the surface's three-digit vocabulary is
    {100, 123, 142, 150, 200, 256, 300, 336, 804, 922} and every one of those is
    generated rather than authored, so a three-digit paper n is a build failure
    waiting on a codebook change — a numeric coincidence failing a build is the
    cry-wolf failure this project has already paid for once. The short n
    (125, 244, 602, 641, 648, 928) are carried by the probe scorer instead, in
    `benchmark/leak_facts.py::LEAK_FACTS`, where a match prints the answer for a
    human to adjudicate rather than stopping a run.

    APPROXIMATE FIGURES ARE SKIPPED, and this rule was written by a failure.
    `CohortPaper.n` holds "the realised analytic sample as the paper reports it,
    OR A NOTE when the paper reports none"; the cohort profile's note is
    `~8,000 recruited`, a recruitment count and not an analytic n. Deriving a
    bare `8000` from it broke `test_no_source_file_names_a_published_analysis`
    on `agent/RUNNING.md`, which names port 8000 four times — vLLM's default,
    beside ports 8080, 11434 and 1234. Four legitimate occurrences misread as a
    paper's sample size is the cry-wolf failure arriving on its own. The figure
    is still scored, phrase-bounded, by `benchmark/leak_facts.py::LEAK_FACTS`
    as `8,000 participants`.

    Returns:
        Sorted analytic-n tokens, bare and comma-grouped.
    """
    out: set[str] = set()
    for paper in COHORT_PAPERS:
        for m in re.finditer(r"(~?)(\d[\d,]*)", paper.n):
            approx, bare = m.group(1), m.group(2).replace(",", "")
            if approx or len(bare) < 4:
                continue
            out |= {bare, f"{int(bare):,}"}
    return sorted(out)


# Traceable to the COMPASS cohort papers, to the earlier literature review, or to
# project internals the model has no business seeing.
#
# EXTENDED 2026-08-28 FROM FOUR PAPERS TO SIXTEEN (C1). The hand-written half
# below encoded the four-paper inventory; `benchmark/cohort_papers.py` has held
# sixteen since 2026-08-27, so twelve papers' exposures, methods and sample sizes
# were traceable and unscanned. The two derived halves close that and keep it
# closed as the bibliography grows.
#
# EVERY TOKEN ADDED HERE WAS AUDITED FIRST, against the model-visible surface,
# against `curated/`, `env/` and `agent/`, and against `build/dictionary.json`.
# THE DICTIONARY HALF OF THAT AUDIT NOW RUNS -- see
# `check_markers_are_not_instrument_content`. Until 2026-08-31 it did not: this
# file mentioned `build/dictionary.json` in three comments and READ IT NOWHERE,
# and the sentence below still said "verified against build/dictionary.json
# above" for a verification that did not exist. A guarantee stated in a comment
# and enforced nowhere is this codebase's signature failure, and this was an
# instance of it sitting inside the file that checks for the others.
# The audit is the reason four obvious candidates are ABSENT: `uterine fibroid`,
# `fibroid`, `bipolar` and `PSA` are the published designs of four of the twelve
# AND they are instrument content, so marking them would fail the build on a
# question the study asked.
# COUNTS CORRECTED 2026-08-31. This comment used to read 2 / 4 / 5 / 2. Those
# came from joining four text fields of which `searchable_text` is a measured
# superset, so every occurrence was counted about twice. Under `searchable_text`,
# whitespace-collapsed, case-insensitive, on build 6fcd02755bf3 the true counts
# are `uterine fibroid` 2, `fibroid` 2, `bipolar` 2, `PSA` 1.
# `asthma`, `hypertension`, `tobacco`, `marijuana` and `breast cancer` are out
# for the same measured reason. A marker that fires on the instrument is not a
# contamination control, it is a reason someone deletes the check.
MARKERS = [
    "2,836", "2836", "5,096", "5096", "2,387", "2387",                 # paper n
    # `602` WAS retained here, below the four-digit rule, on the recorded
    # ground that it had never fired. On 2026-09-02 it fired: arm D renders the
    # instrument as a 1,400-item numbered list and `602` is one of the
    # positions. That is the exact cry-wolf failure the four-digit rule exists
    # to prevent — a three-digit numeral stopping a build on a coincidence —
    # and the retention's own justification no longer holds. It is scored, as
    # the other short n are, by `benchmark/leak_facts.py::LEAK_FACTS`, where a
    # match prints the answer for a human instead of failing the build.
    "PM2.5", "PM2·5", "NO2", "NDVI", "WQS", "MAPSCorps", "E2SFCA",     # exposures/methods
    "floating catchment", "published COMPASS papers", "PMID",
    # The twelve found on 2026-08-27. Distinctive phrases only: each names an
    # external data source, a method or a construct that no COMPASS questionnaire
    # item uses -- enforced by check_markers_are_not_instrument_content, not
    # merely asserted here.
    "Health Atlas", "greenspace", "g-estimation", "metabolome",
    "central hemodynamic", "cardiometabolic", "biospecimen participation",
    "MOOSE", "Min-K", "HLER", "AstroAgents", "VirSci", "Biomni",       # review internals
    "benchmark paper", "Capricorn", "Decision Ledger",
    # The prior-art read of 2026-08-27/28, same class as the six above: names
    # that exist only in this project's own literature review.
    "CiteME", "NewtonBench", "PreScience", "BioDisco",
    *_pmid_tokens(),
    *_published_n_tokens(),
]

ALLOWED_SOURCES = {"study-team", "instrument-derived", "authored-unconfirmed"}
SOURCE_RE = re.compile(r"\*\*Source:\*\*\s*`?([a-z-]+)`?", re.I)

# An outcome that means the tool did its work. Anything else is a tool that
# bailed before touching the data it would normally return, which is the shape a
# "sampled" tool takes when its arguments were chosen for convenience.
SUCCESS_OUTCOMES = {"ok", "unique", "group", "construct"}

# Branches a single tool must be sampled across, because each one generates a
# different block of prose. resolve_variable is the model's most-called tool and
# every one of its five documented outcomes writes its own log text.
REQUIRED_OUTCOMES: dict[str, set[str]] = {
    "resolve_variable": {"unique", "group", "construct", "ambiguous", "not_found"},
    # browse_variables prints instrument wording straight into the surface, so
    # its refusal text is the one branch a sample could quietly skip while the
    # listing branches made coverage look complete.
    "browse_variables": {"ok", "not_found"},
}


class Sample(NamedTuple):
    """One recorded tool invocation and what it returned.

    Attributes:
        tool: Registry name of the tool that was called.
        key: Surface key, `tool:<name>(<args>)`, used for the hash and reports.
        value: The tool's return value, exactly as the model would receive it.
    """

    tool: str
    key: str
    value: Any


def _dumps(obj: Any) -> str:
    r"""Serialise a tool return value for scanning.

    `ensure_ascii=False` is load-bearing, not cosmetic: with the default the
    marker `PM2·5` serialises to `PM2\u00b75` and the scan cannot see it, so a
    paper's own exposure spelling would pass. `sort_keys` keeps the hash stable
    against dict-ordering changes that do not change what the model reads.

    Args:
        obj: Any JSON-serialisable tool return value.

    Returns:
        A UTF-8 JSON string with non-ASCII characters left intact.
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def tool_samples() -> dict[str, list[dict[str, Any]]]:
    """Argument sets every registry tool is sampled with, keyed by tool name.

    Representative, not convenient. Each entry is justified where it is written:
    the failure this table exists to prevent is a tool called with arguments that
    return early, so its real output — the part that could carry a paper's
    numbers — never reaches the scan.

    Topics and derivation ids are read from the environment rather than listed,
    so a newly added convention file or signed derivation is covered without
    anyone remembering to edit this table.

    Returns:
        Mapping of tool name to the list of keyword-argument dicts to call it
        with. Every tool in `build_registry` must appear as a key.
    """
    derivations: list[str] = sorted(
        p.stem for p in (ROOT / "curated" / "derivations").glob("*.json"))
    return {
        # All five documented outcomes. The construct and group branches print
        # member keys and stem text that appear nowhere else in the surface.
        "resolve_variable": [
            {"key": "m3:Q16.1_1"},        # unique, a battery sub-item
            {"key": "m2:Q5.8"},           # unique, the funnel's outcome anchor
            {"key": "m2:Q12.78"},         # unique, the CRC-screening anchor
            {"key": "group:m3:Q16.1"},    # group
            {"key": "m3:Q16.1"},          # construct
            {"key": "Q5.8"},              # ambiguous: bare qid, echoes candidates
            {"key": "linked:example_measure"},   # not_found: the empty registry
        ],
        # The largest generated text block in the environment and, until
        # 2026-08-26, entirely unscanned: the snippets are real question wording.
        # The default limit of 10 is kept — a smaller limit would shrink the very
        # text this sample exists to expose.
        "search_variables": [
            {"phrase": "high blood pressure"},   # the frame's outcome domain
            # The frame's exposure domain, and — since 2026-08-30 — the
            # single-term branch: one surviving term makes every hit score
            # 1.000, so the result carries its own banner saying the score
            # means nothing, text that appears in no other sample here.
            {"phrase": "neighborhood"},
            {"phrase": "zzzqqq"},                # zero hits: the empty-result log
            # The low_confidence branch. Added 2026-08-30 with the scored
            # rewrite: its banner, its per-hit below_threshold flags and its
            # "re-query, do not read this as absence" log exist in no other
            # sample, so the branch was unscanned the moment it was written.
            {"phrase": "green space"},
        ],
        # EVERY PAGE, not a sample of them. browse_variables is the only tool
        # here whose return is instrument text rather than authored prose, and
        # C25 requires its FULL return to be scannable — a browse tool sampled
        # with two rows is the "sampled only into a dead end" failure
        # check_tool_coverage exists to catch. Its argument space is closed and
        # small enough to enumerate exhaustively: three modules and the sections
        # the dictionary itself reports, 135 pages over build 6fcd02755bf3. They
        # are DERIVED for the reason the derivation ids above are: a section
        # that appears when the codebooks change is scanned without anyone
        # remembering to edit this table.
        "browse_variables": (
            [{"module": m} for m in T.BROWSE_MODULES]
            + [{"module": m, "section": s}
               for m in T.BROWSE_MODULES for s in T.browse_sections(m)]
            + [{"module": "4"},                      # not_found: no such module
               {"module": "1", "section": "999"}]),  # not_found: no such section
        # The only battery in the instrument with a signed derivation over it,
        # so it is the group the funnel actually drives at.
        "get_item_group": [{"group_id": "group:m3:Q16.1"}],
        "registry_coverage": [{}],
        # Every convention, plus the miss branch, which enumerates topic names.
        "get_design_convention": (
            [{"topic": t} for t in sorted(T.CONVENTION_FILES)]
            + [{"topic": "no_such_topic"}]),
        "list_derivations": [{}],
        "get_derivation": (
            [{"derivation_id": d} for d in derivations]
            + [{"derivation_id": "no_such_derivation"}]),
        # Both branches: the cross-module one carries the extra blocker text.
        "estimate_n": [
            {"keys": ["m3:Q16.1_1", "m2:Q5.8"]},
            {"keys": ["m2:Q5.8", "m2:Q12.78"]},
        ],
        # n_values is OMITTED from the first sample. Passing an explicit grid was
        # the exact mistake that hid the default's contents from the scan, and
        # the environment grid is now the ONLY grid, so this is what every real
        # call returns. The second sample exercises the refusal branch, whose log
        # text quotes the grid back and exists nowhere else in the surface.
        # Third sample added 2026-08-27 for the reason the second one exists.
        # Fixing the bound at BOUND_ALPHA/BOUND_POWER created a new branch whose
        # log text — the note that a caller's alpha and power shape only its own
        # curve — appears nowhere else in the surface, and no existing sample
        # passed either argument, so the branch was unscanned the moment it was
        # written. That is the estimate_detectability hole reopening in a
        # smaller shape.
        "estimate_detectability": [{"baseline_prevalence": 0.30},
                                   {"baseline_prevalence": 0.30,
                                    "n_values": [50, 100, 150]},
                                   {"baseline_prevalence": 0.30,
                                    "alpha": 0.5, "power": 0.5}],
        # All four contrast branches; the model may pass any of them.
        "get_contrast_convention": [
            {"key_or_kind": "likert"},
            {"key_or_kind": "derived scale"},
            {"key_or_kind": "binary"},
            {"key_or_kind": "continuous"},   # the fallthrough branch
        ],
        # A key set that actually trips the location regex at all three places,
        # so `per_place_working` echoes real keys instead of returning "no
        # location-bearing variable named"; plus a set with an unresolvable key,
        # which is the distinct origin_unknown state.
        "check_access": [
            {"keys": ["m1:Q2.4", "m1:Q85", "m2:Q25.5_2", "m2:Q27.4_2", "m2:Q5.8"]},
            {"keys": ["m2:Q5.8", "linked:example_measure"]},
        ],
    }


def _sample_registry(mode: Mode) -> list[Sample]:
    """Call every tool the registry exposes, with its declared argument sets.

    Args:
        mode: Registry mode to build. Has no default, for the same reason
            `build_registry` has none.

    Returns:
        One Sample per (tool, argument set). Tools with no declared arguments are
        skipped here and reported by `check_tool_coverage`, so a missing entry
        surfaces as a named failure rather than a traceback.
    """
    calls, _ = build_registry(mode)
    samples = tool_samples()
    out: list[Sample] = []
    for name in sorted(calls):
        for kwargs in samples.get(name, []):
            label = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            out.append(Sample(name, f"tool:{name}({label})", calls[name](**kwargs)))
    return out


#: What the second call's `{analysis}`, `{toollog}` and `{finding}` slots are
#: filled with here. They are runtime fills, not authored text: `analysis` is the
#: model's own call-1 prose, `finding` is the adjudication the environment
#: stamped, and `toollog` is `agent/specifier.py::_render_log` over the SAME tool
#: return values that `_sample_registry` already scans one by one. Scanning a
#: fabricated fill would add this module's own words to the surface and move the
#: hash for no reason; the fills are named here so nobody reads their absence as
#: an oversight. The one thing a fill could carry that a sample does not is
#: `_render_log`'s own framing, which is `name(args) -> outcome` and `returned:`
#: — VERIFIED 2026-08-28 by reading that function: no other authored prose.
SECOND_CALL_FILL = "<runtime fill; scanned where it is produced>"


def _second_call_surface() -> dict[str, str]:
    """The transduction call's prompts, captured as the backend receives them.

    WHY CAPTURED AND NOT LISTED. Until 2026-08-28 this module scanned `SYSTEM`,
    `user_prompt`, the protocol schema and the tool returns, and nothing else —
    so `TRANSDUCE`, `REPAIR`, and then `TRANSDUCE_REFUSAL` and the
    `NotSpecifiable` schema when the refusal path landed, all reached the model
    with no scan over them. A hand-listed set of template names would have gone
    stale the same way the last one did: the list grows whenever someone adds a
    literal to the emission loop, and nothing reminds them. Driving
    `agent/specifier.py::_emit` with a backend that records instead of answering
    collects whatever that loop actually sends, including text nobody thought to
    list — the emission system message is here for exactly that reason and
    appears in no C3 inventory.

    The cost is a dependency on a private function in another lane's module. That
    is deliberate: if `_emit` is renamed the import fails and this command stops
    with a name, whereas a stale list of templates goes quiet. `AGENTS.md`
    §Testing Patterns — prefer a check whose red state names a defect.

    Every emission is rejected so the loop runs to `MAX_TRANSDUCE_ATTEMPTS` and
    the repair turn is reached; the repair wrapper is only built on attempt two
    and later.

    Returns:
        Mapping of surface name to the exact text `_emit` put in a message,
        one entry per distinct (role, content) pair, plus the two schemas.
    """
    from agent.backends import Reply

    seen: list[tuple[str, str]] = []

    class _Recorder:
        """Records what `_emit` sends and refuses to satisfy it."""

        name = "surface-recorder"
        #: False on purpose. The CLI branch appends the schema to the prompt body
        #: instead of passing `guided_json`, and the schemas are added below by
        #: name; taking the in-process branch keeps one entry per message.
        drives_own_tool_loop = False

        def chat(self, messages: list[dict], **kw: Any) -> Reply:
            for m in messages:
                # `assistant` turns are the model's own previous draft echoed
                # back. Recording them would put THIS function's placeholder
                # reply into the scanned surface and call it environment text.
                if m.get("role") == "assistant":
                    continue
                pair = (str(m.get("role")), str(m.get("content")))
                if pair not in seen:
                    seen.append(pair)
            return Reply(content="{}")

    def _never(_: dict) -> Any:
        raise ValueError("recording the surface; no record is built here")

    # Read through the module, never from a `from ... import` binding. The
    # binding is a snapshot taken at import; `_emit` reads its own module global
    # at call time, so the two can disagree — which is not hypothetical: with
    # the templates bound locally, planting a marker in TRANSDUCE_REFUSAL and
    # rebuilding the surface produced ZERO hits, and the positive control for
    # this whole function passed for the wrong reason on the repair wrapper
    # alone. A scan that reads a copy is scanning something the model does not.
    bodies = {
        "protocol": SP.TRANSDUCE.format(analysis=SECOND_CALL_FILL,
                                        toollog=SECOND_CALL_FILL),
        "refusal": SP.TRANSDUCE_REFUSAL.format(analysis=SECOND_CALL_FILL,
                                               toollog=SECOND_CALL_FILL,
                                               finding=SECOND_CALL_FILL),
    }
    schemas = {
        "protocol": ProtocolSpecification.model_json_schema(),
        "refusal": NotSpecifiable.model_json_schema(),
    }
    out: dict[str, str] = {}
    for path, body in bodies.items():
        seen.clear()
        _emit(_Recorder(), schemas[path], body, None, _never)
        for i, (role, content) in enumerate(seen):
            out[f"transduce:{path}[{i}:{role}]"] = content
    out["transduce_refusal_schema"] = json.dumps(schemas["refusal"])
    # Asserted here rather than in a test alone: a capture that silently returned
    # nothing would shrink the surface and print `clean`, which is the shape of
    # the hole this function exists to close.
    missing = [n for n, t in (("TRANSDUCE", SP.TRANSDUCE),
                              ("TRANSDUCE_REFUSAL", SP.TRANSDUCE_REFUSAL),
                              ("REPAIR", SP.REPAIR))
               if not any(t.split("{")[0].strip() and t.split("{")[0].strip() in v
                          for v in out.values())]
    if missing:
        raise AssertionError(
            f"_second_call_surface captured nothing for {missing} — "
            f"agent/specifier.py::_emit no longer sends what this reads")
    return out


def _resolver_surface() -> dict[str, str]:
    """The prose resolver's prompts and schemas, as the model receives them.

    `AGENTS.md` §Contamination Practice: a prose resolver's prompt and schema
    join this surface. Both schemas are here because
    `benchmark/resolver_eval.py` puts `model_json_schema()` INTO the prompt, so
    the field descriptions in those model docstrings are prompt text under the
    same rule as `agent/schema.py`'s.

    Every row's shortlist prompt is rendered, not one: the pool is where the
    instrument's own wording enters the prompt, and a scan over one row would
    cover one pool. The critic prompt is rendered once with a clarification and
    once without, which is every literal on that call's path.

    Returns:
        Mapping of surface name to the text the resolver would read there.
    """
    fx = RE.load_fixture()
    out: dict[str, str] = {
        "resolver_shortlist_schema": json.dumps(RE.Shortlist.model_json_schema()),
        "resolver_verdict_schema": json.dumps(
            RE.CriticVerdict.model_json_schema()),
    }
    for row in fx.queries:
        out[f"resolver_shortlist_prompt:{row.id}"] = RE.shortlist_prompt(
            row, row.pool)
    row = next(r for r in fx.queries if r.narrowing is not None)
    samples = (RE.Shortlist(items=(RE.ResolvedItem(
        key=row.pool[0], wording=T._BY_KEY[row.pool[0]]["question_text"]),)),)
    agreed = RE.agreement(samples, RE.MIN_SAMPLES)
    # BOTH prompt arms. `with_family_rule` carries a block `unaided` does not,
    # and a scan over one arm is a scan over a prompt the other never sends.
    for arm in RE.RESOLVER_PROMPT_ARMS:
        if arm == "structured":
            # A different renderer, so a scan over the prose arms is a scan over
            # prompts this arm never sends. Both of its stages are rendered.
            out["resolver_shortlist_prompt:structured"] = (
                RE.structured_shortlist_contract(row, row.pool).render())
            out["resolver_critic_prompt:structured"] = (
                RE.structured_critic_contract(row, row.pool).render())
            out["resolver_critic_prompt_clarified:structured"] = (
                RE.structured_critic_contract(
                    row, row.pool,
                    row.narrowing.supply if row.narrowing else "").render())
            out["resolver_shortlist_index_schema"] = json.dumps(
                RE.VariableShortlist.model_json_schema())
            out["resolver_index_verdict_schema"] = json.dumps(
                RE.contract.VariableSelection.model_json_schema())
            continue
        out[f"resolver_critic_prompt:{arm}"] = RE.critic_prompt(
            row, samples, agreed, arm=arm)
        out[f"resolver_critic_prompt_clarified:{arm}"] = RE.critic_prompt(
            row, samples, agreed, row.narrowing.supply if row.narrowing else "",
            arm)
    return out


def _catalogue_surface() -> dict[str, str]:
    """Arm D's whole-instrument catalogue, as the selecting model receives it.

    The largest surface in this scan by an order of magnitude, and the one with
    the least prose: it is the instrument itself, folded to one line per
    selectable item. Instrument content is exempt from the marker list by
    `tests/test_contamination_surface.py::test_no_marker_is_instrument_content`
    — the renderer's own scaffolding is not, and that is what this puts in
    scope.

    Returns:
        Mapping of surface name to the text arm D would read there.
    """
    cat = LB.build_catalogue()
    cands = PC.candidates_from_keys([o.representative for o in cat.options])
    return {
        "arm_d_catalogue": LB.render_catalogue(cat),
        "arm_d_prompt": PC.catalogue_contract(cands).render(
            catalogue=LB.render_catalogue(cat)),
        "arm_d_selection_schema": json.dumps(
            PC.VariableSelection.model_json_schema()),
    }


def _hybrid_surface() -> dict[str, str]:
    """The hybrid E→D pool prompt, as the selecting model receives it.

    The POOL is per row and comes from an embedding ranking, which this scan
    cannot compute without `torch` — a dependency `pyproject.toml` does not
    declare and this command must not acquire. What varies between rows is which
    instrument wordings appear, and instrument content is already exempt from
    the marker list; what does NOT vary is the renderer's own scaffolding and the
    contract's guidance, which is what needs scanning. So a DETERMINISTIC pool —
    the first N targets in build order — is rendered here, and the scan covers
    the scaffolding exactly.

    Returns:
        Mapping of surface name to the text the hybrid selector would read.
    """
    targets = json.loads((ROOT / "targets.json").read_text())["targets"]
    out: dict[str, str] = {}
    for depth in HYBRID_DEPTHS:
        pool = targets[:depth]
        out[f"hybrid_pool_prompt:d{depth}"] = HY.prompt_for(
            pool, "a researcher's request, rendered for the scan")
    return out


def _rewrite_surface() -> dict[str, str]:
    """C16's query-rewrite prompt and schema, as the rewriting model receives them.

    In scope for the same reason the resolver's prompts are: a model reads this
    text, and `agent/query_rewrite.py::Phrasings`' docstring reaches it through
    `model_json_schema()` exactly as `agent/schema.py`'s docstrings do.

    Every fixture request is rendered, not one, because the request string is the
    only variable part of this prompt and a scan over one request is a scan over
    one of 221 prompts this stage sends.

    Returns:
        Mapping of surface name to the text the rewriter would read there.
    """
    schema = json.dumps(QR.Phrasings.model_json_schema(), indent=2)
    out: dict[str, str] = {"rewrite_phrasings_schema": schema}
    for i, row in enumerate(RE_RETRIEVAL.load_fixture().queries):
        out[f"rewrite_prompt:{i:03d}"] = QR.REWRITE_PROMPT.render(
            request=row.query, n=QR.N_PHRASINGS, schema=schema)
    return out


def model_visible_surface(mode: Mode = "benchmark") -> dict[str, str]:
    """Every byte the model receives, keyed by where it comes from.

    Args:
        mode: Registry mode whose tool set is sampled.

    Returns:
        Mapping of surface name to the text the model would read there.
    """
    _, schemas = build_registry(mode)
    C, _ = load_constructs()
    e = sorted([c for c in C.values() if c.module == "3"
                and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    o = sorted([c for c in C.values() if c.module == "2"
                and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, _ = run(e, o)

    surface = {
        "system_prompt": SYSTEM,
        "user_prompt": user_prompt(cands[0]),
        "transduce_schema": json.dumps(ProtocolSpecification.model_json_schema()),
        "tool_descriptions": json.dumps(schemas),
        # The SECOND call. Call 1's prompts were scanned from the beginning and
        # call 2's were not, which is the whole of C3.
        **_second_call_surface(),
        # The prose resolver. Its prompts carry instrument wording by design and
        # its schemas are prompt text; both are in scope for the same reason
        # call 2's were.
        **_resolver_surface(),
        # C16's rewrite stage. Its prompt carries NO instrument wording by
        # design, which is a claim this scan is what checks.
        **_rewrite_surface(),
        # Arm D. Its prompt carries the WHOLE instrument by design, which is
        # the opposite claim and needs the same scan.
        **_catalogue_surface(),
        # The hybrid's pool prompt: a different renderer, so a scan over arm D's
        # catalogue is not a scan over this.
        **_hybrid_surface(),
    }
    # Tool RETURN VALUES. Generated, not stored — a file grep cannot see these.
    # The whole return is scanned, not a chosen field: `get_design_convention`
    # used to contribute only its "text", leaving its `log` — which the model
    # reads in the same message — outside the scan.
    for s in _sample_registry(mode):
        surface[s.key] = _dumps(s.value)
    return surface


def check_tool_coverage(mode: Mode = "benchmark") -> list[str]:
    """Fail when a registry tool is unsampled or sampled only into a dead end.

    This is the structural half of the marker scan. The scan can only see what
    was called, so an uncalled tool makes "clean" mean less than it reads, and
    nothing in the old design made that visible — the surface count went down by
    six with no complaint from anything.

    Args:
        mode: Registry mode to check coverage against.

    Returns:
        One string per problem; empty when coverage is complete.
    """
    calls, _ = build_registry(mode)
    samples = _sample_registry(mode)
    bad: list[str] = []

    seen: dict[str, set[str]] = {}
    for s in samples:
        outcome = s.value.get("outcome", "ok") if isinstance(s.value, dict) else "ok"
        seen.setdefault(s.tool, set()).add(outcome)

    for name in sorted(calls):
        if name not in seen:
            bad.append(f"{name} is in build_registry({mode!r}) but tool_samples() "
                       f"does not sample it — its return value is not scanned")
            continue
        if not seen[name] & SUCCESS_OUTCOMES:
            bad.append(f"{name} is only sampled into {sorted(seen[name])}; no "
                       f"argument set makes it return real output")
        missing = REQUIRED_OUTCOMES.get(name, set()) - seen[name]
        if missing:
            bad.append(f"{name} is not sampled across {sorted(missing)}")
    return bad


def _instrument_text_by_module() -> dict[str, str]:
    r"""Every question wording in the built dictionary, keyed by module.

    ONLY `searchable_text`. MEASURED 2026-08-31 over build 6fcd02755bf3, it is a
    strict superset of the other three text fields: `question_text` sits inside
    it in 2,804 of 2,804 entries, and `stem_text` and `subitem_text` in 876 of
    876 each. Joining all four counts every occurrence twice — the first cut of
    this function did, and reported `hypertension` matching "22 times" when it
    matches 11 questions. A scan that inflates its own counts is the wrong shape
    in the file that polices counts.

    KEYED BY MODULE so the caller can tell PARTIAL blindness from health. A join
    that silently lost one module reads exactly like a clean scan, which is the
    same indistinguishability this whole check exists to end.

    WHITESPACE IS COLLAPSED, and that is not cosmetic. The codebooks break lines
    INSIDE phrases: `m2:Q9.117` carries "uterine\n  fibroids". Measured on the
    same build, `uterine fibroid` occurs 1 time raw and 2 times collapsed, so a
    raw scan misses half of them. A line break the typesetter chose must not
    evade a contamination control.

    Returns:
        Module id -> that module's question wording, whitespace-collapsed.

    Raises:
        FileNotFoundError: If the dictionary has not been built. Raising beats
            returning empty for the reason `env/tools.py::_load` raises: a scan
            over nothing reports `clean` and means nothing.
    """
    path = ROOT / "build" / "dictionary.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run `python build.py` first. A marker scan "
            f"over a dictionary that failed to load would report clean.")
    by_module: dict[str, list[str]] = {}
    for e in json.loads(path.read_text())["entries"]:
        if e.get("searchable_text"):
            by_module.setdefault(e["module"], []).append(e["searchable_text"])
    return {m: re.sub(r"\s+", " ", " ".join(v)) for m, v in by_module.items()}


#: The modules the instrument is built from, and a floor on what each must
#: contribute. Measured 2026-08-31 on build 6fcd02755bf3: module 1 is 10,172
#: chars, module 2 is 230,079, module 3 is 32,580. The floor is deliberately far
#: below each so a codebook edit does not cry wolf, while a module dropped from
#: the scan does. A guard that fires on normal operation gets disabled by
#: whoever it annoys.
EXPECTED_MODULES: dict[str, int] = {"1": 5_000, "2": 100_000, "3": 15_000}

#: Tokens deliberately ABSENT from `MARKERS` because they are instrument
#: content, with the reason recorded in the comment above MARKERS. Every token
#: that comment names is here: one recorded decision expiring unnoticed is the
#: drift this tuple exists to prevent, and `breast cancer` was named there and
#: missing here in the first cut of this check.
#:
#: They are also this check's PROOF THAT IT READ SOMETHING. "No marker appears
#: in the instrument" is exactly what a check that loads nothing reports, which
#: is the defect this function was written to end. If these stop being found,
#: the scan is blind and says so instead of saying `clean`.
INSTRUMENT_CONTENT_EXCLUSIONS = ("uterine fibroid", "fibroid", "bipolar", "PSA",
                                 "asthma", "hypertension", "tobacco",
                                 "marijuana", "breast cancer")


def check_markers_are_not_instrument_content() -> list[str]:
    """A marker may not fire on a question the study actually asked.

    The comment above `MARKERS` says every token was audited against
    `build/dictionary.json`. That audit was a human act performed once and
    recorded in prose; this runs it. A marker that matches instrument content is
    not a contamination control — it fails the build on a question the study
    asked, and it is the shape of guard that whoever it annoys deletes.

    Returns:
        One string per problem; empty when the audit holds.
    """
    by_module = _instrument_text_by_module()
    text = " ".join(by_module.values())
    problems = []

    # NO RIGHT-HAND BOUNDARY. `fibroid` must match `fibroids`: both instrument
    # occurrences are the plural, so a full-boundary rule reports clean on them.
    # The left boundary stays, so `PSA` cannot be earned inside a longer word.
    def occurrences(token: str, hay: str = text) -> int:
        return len(re.findall(r"(?<!\w)" + re.escape(token), hay, re.I))

    for m in sorted(set(MARKERS)):
        n = occurrences(m)
        if n:
            problems.append(
                f"MARKERS token {m!r} matches the instrument {n} time(s). It is "
                f"a question the study asked, not a trace of a published "
                f"analysis. Remove it from MARKERS and record why beside the "
                f"others, or the next build fails on the questionnaire.")

    # BLINDNESS, TOTAL AND PARTIAL. Stated separately from the loop above
    # because a silent pass and a blind pass read identically otherwise. The
    # per-module half exists because the first cut of this check probed only
    # tokens that live in modules 2 and 3, so a scan blinded to module 1 passed.
    for mod, floor in sorted(EXPECTED_MODULES.items()):
        got = len(by_module.get(mod, ""))
        if got < floor:
            problems.append(
                f"module {mod} contributed {got} chars to the marker audit, "
                f"below the {floor} floor. The scan is blind to part of the "
                f"instrument, and a partly blind audit reports `clean` exactly "
                f"as a correct one does.")
    blind = [t for t in INSTRUMENT_CONTENT_EXCLUSIONS if not occurrences(t)]
    if blind:
        problems.append(
            f"this check cannot see the instrument: {blind!r} are recorded as "
            f"instrument content and none of them was found. Either the "
            f"dictionary moved under the recorded audit — in which case the "
            f"reason those tokens are absent from MARKERS has expired and needs "
            f"re-deciding — or this scan is reading nothing and its 'clean' "
            f"means nothing, which is the defect it was written to end.")
    return problems


def check_markers(surface: dict[str, str]) -> list[str]:
    """Scan the assembled surface for anything traceable to a published analysis.

    Args:
        surface: Output of `model_visible_surface`.

    A NUMERIC marker matches a NUMBER, not a digit run inside a longer token.
    Every other marker keeps the substring rule, because `greenspace` must fire
    inside `greenspaces` and `PM2.5` inside a parenthesis.

    The boundaries are the same ones `check_markers_are_not_instrument_content`
    already uses on its own side of this file, and they were forced by
    measurement: arm D renders 1,400 numbered candidates, so `1092` — a
    published analytic n — matched the index `i1092`, and every numeric marker
    below 1,400 would collide with a position forever. What the rule gives up,
    stated rather than discovered later: a numeric marker glued to the RIGHT of
    a word character, as in `PMID12345678`, no longer fires. The forms that
    have actually leaked — `n=2,836`, a bare figure in prose, a list literal —
    all still do, and `tests/test_contamination_surface.py` plants each of them.

    Args:
        surface: Output of `model_visible_surface`.

    Returns:
        One string per (surface, marker) hit; empty when the surface is clean.
    """
    return [f"{where}  ->  {m!r}"
            for where, text in surface.items()
            for m in MARKERS if _marker_hit(m, text)]


#: A marker made only of digits and thousands separators. These are figures, and
#: a figure is a number rather than a substring; everything else is a name.
_NUMERIC_MARKER = re.compile(r"^[\d,]+$")


def _marker_hit(marker: str, text: str) -> bool:
    """Whether one marker occurs in one surface.

    Args:
        marker: The marker token.
        text: The surface text.

    Returns:
        True on an occurrence. Numeric markers need a number boundary on both
        sides; every other marker matches as a substring.
    """
    if not _NUMERIC_MARKER.match(marker):
        return marker in text
    return re.search(r"(?<!\w)" + re.escape(marker) + r"(?!\d)",
                     text) is not None


def check_no_platform_name_in_surface(surface: dict[str, str]) -> list[str]:
    """No survey-platform product may be observable to the model. Any of them.

    The user's instruction is that the platform must not be observable at all
    and that the environment refer only to a generic survey tool. VERIFIED
    2026-08-27 that this already held — zero occurrences of any name in
    `PLATFORMS`, of the phrase "survey platform", or of the bare word "platform"
    across all 37 surfaces — and this turns that from a fact about today into a
    ratchet.

    It is also what makes the seal scorer sound. `agent/sealed.py::score` now
    treats ANY platform name a probe volunteers as unearned, on the argument
    that the environment supplies none. If a name ever entered the surface, that
    argument would silently become false and the scorer would be reporting
    echoes as findings.

    The generic vocabulary is NOT scanned and must not be: `survey` (5x),
    `instrument` (11x), `codebook` (5x), `questionnaire` (3x) and `form` (7x)
    are all in the surface legitimately. Generic is the whole point — a named
    product is the thing that cannot be there.

    Args:
        surface: Output of `model_visible_surface`.

    Returns:
        One string per (surface, name) hit; empty when clean.
    """
    from benchmark.leak_facts import platform_spellings
    return [f"{where}  ->  survey platform {name!r}"
            for where, text in surface.items()
            for name in platform_spellings()
            if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text.lower())]


def check_provenance() -> list[str]:
    """Every convention must declare where it came from.

    NOT a defence against paraphrase, and it was described as one here until
    2026-08-26. It catches an author who knows the source is a paper and writes
    that down. `clustering_community_area.md` declared `authored-unconfirmed`,
    passed this check every time it ran, and opened with a sentence lifted from
    the cohort profile — because the author believed the declaration. This check
    establishes only that a source was named, and `study-team` may be named only
    after the study team confirms in writing.

    Returns:
        One string per document with a missing or disallowed source.
    """
    bad = []
    for p in sorted((ROOT / "curated" / "conventions").glob("*.md")):
        m = SOURCE_RE.search(p.read_text())
        if not m:
            bad.append(f"{p.relative_to(ROOT)}: no **Source:** declared")
        elif m.group(1).lower() not in ALLOWED_SOURCES:
            bad.append(f"{p.relative_to(ROOT)}: source {m.group(1)!r} "
                       f"not in {sorted(ALLOWED_SOURCES)}")
    for p in sorted((ROOT / "curated" / "derivations").glob("*.json")):
        d = json.loads(p.read_text())
        if not d.get("construct_validity_basis"):
            bad.append(f"{p.relative_to(ROOT)}: no construct_validity_basis")
        if d.get("fitted_to_outcome"):
            bad.append(f"{p.relative_to(ROOT)}: fitted_to_outcome is true")
    return bad


def check_seal_config() -> list[str]:
    """Assert the sealed worktree denies what it claims to deny.

    Returns:
        One string per seal setting that does not hold; empty when sealed.
    """
    from agent.sealed import DENY_TOOLS, SEALED_SETTINGS, SealedWorktree
    bad = []
    with SealedWorktree() as w:
        m = w.manifest()
        if m["claude_md_found"]:
            bad.append(f"CLAUDE.md reachable: {m['claude_md_found']}")
        if str(ROOT) in str(w.cwd):
            bad.append(f"sealed cwd is inside the project: {w.cwd}")
        for t in ("Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch"):
            if t not in DENY_TOOLS:
                bad.append(f"{t} is not denied")
        if SEALED_SETTINGS.get("enabledPlugins") != {}:
            bad.append("plugins not disabled in sealed settings")
    return bad


def check_holdout_not_reachable() -> list[str]:
    """benchmark/ must not be reachable from any tool path.

    Returns:
        One string per reachable held-out path; empty when unreachable.
    """
    bad = []
    src = (ROOT / "env" / "tools.py").read_text()
    for forbidden in ("benchmark", "references"):
        if forbidden in src:
            bad.append(f"env/tools.py references {forbidden!r} — neither the "
                       f"held-out registry nor the external-paper directory may "
                       f"sit on a tool path")
    if (ROOT / "curated" / "known_analyses.json").exists():
        bad.append("curated/known_analyses.json exists — move it to benchmark/; "
                   "curated/ is globbed by the tool layer")
    # The answer keys, by name. A copy of one under curated/, env/ or agent/ is
    # not a near miss: curated/ is globbed by the tool layer, and agent/ ships
    # docstrings into the transduction prompt.
    # `cohort_papers.py` and `input_leakage.py` joined the list on 2026-08-28.
    # The first was already the bibliography and was simply not named here; the
    # second reads two keys at once and is therefore the worst of the set to
    # find on a tool path.
    # `scorability.py` joined on 2026-08-28: it derives exposure and outcome
    # terms from the bibliography's design lines, so a copy of it under curated/
    # would put a published pairing on a globbed tool path.
    for key in ("leak_facts.py", "prevalence_key.py", "unearned_assertions.py",
                "cohort_papers.py", "input_leakage.py", "scorability.py"):
        for d in ("curated", "env", "agent"):
            if (ROOT / d / key).exists():
                bad.append(f"{d}/{key} exists — an answer key belongs under "
                           f"benchmark/, which no tool path reaches")
    return bad


def check_no_prevalence_figure_in_surface(
        surface: dict[str, str]) -> list[str]:
    """No figure from the held-out prevalence key may reach the model.

    This is the scan for the leak that placing `benchmark/prevalence_key.py`
    could create. `baseline_prevalence` is the one input to
    `estimate_detectability` the model asserts and the environment cannot
    supply, and the key records what the cohort's own papers report it to be —
    so a figure from it appearing anywhere in the surface would hand the model
    the answer to a quantity the benchmark scores.

    The tokens are DERIVED from the key rather than listed, so a figure added
    there is covered without anyone remembering to edit a list.

    WHAT IS DELIBERATELY NOT SCANNED, and why. Only the one-decimal percent form
    (`38.0%`, and bare `38.0`) and the three-decimal proportion (`0.380`) are
    searched. The integer-percent form is not: `82%` and `5%` both occur in the
    transduce schema in unrelated sentences about auditor detection rates, and a
    scan that fires on those is the cry-wolf failure this project has already
    paid for once. Placement is the control — `benchmark/` sits on no tool path
    — and this scan is the check on placement, not a substitute for it.

    Args:
        surface: Output of `model_visible_surface`.

    Returns:
        One string per (surface, figure) hit; empty when clean.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY
    tokens: set[str] = set()
    for row in PREVALENCE_KEY:
        if row.value is None:
            continue
        tokens |= {f"{row.value * 100:.1f}%", f"{row.value * 100:.1f}",
                   f"{row.value:.3f}"}
    # Boundaries on both sides: a bare `.find` would match `0.10` inside the
    # variable key `m2:Q20.10`, which is instrument content and not a figure.
    #
    # `Q` joins the left boundary for the same reason and on a much larger
    # measurement. `m2:Q4.7#1` is a real construct key: the `.` guard saves
    # `Q20.10` because the digits sit after the dot, and saves nothing at all
    # when the whole `<section>.<question>` pair IS the figure. MEASURED
    # 2026-08-31 over build 6fcd02755bf3 by running every derived token against
    # every key, `searchable_text` and `stem_text` in the built dictionary:
    # ELEVEN of the figures collide with a question id, in hundreds of places,
    # and every single collision is `Q`-prefixed — adding `Q` to this class
    # removes all of them and nothing else. It was latent before
    # `browse_variables` and would have fired the first time `search_variables`
    # returned a hit from one of those batteries; the browse listings print the
    # keys wholesale, so it fired immediately.
    #
    # This is the cry-wolf failure the paragraph above already names, and the
    # cost of leaving it would have been the whole check going red on
    # instrument content. What it gives up is a leaked figure written as `Q4.7`,
    # which is a question id and not how a prevalence is ever written.
    # `tests/test_contamination_surface.py` pins both halves: the question-id
    # class does not fire, and a real figure in a surface still does.
    return [f"{where}  ->  published prevalence {tok!r}"
            for where, text in surface.items()
            for tok in sorted(tokens)
            if re.search(rf"(?<![\d.Q]){re.escape(tok)}(?![\d])", text)]


def main() -> int:
    """Assemble the model-visible surface, scan it, and report.

    Returns:
        0 when every section is clean, 1 otherwise, for use as an exit status.
    """
    live = "--live" in sys.argv
    surface = model_visible_surface()
    blob = "\n".join(f"{k}\n{v}" for k, v in sorted(surface.items()))
    surface_hash = hashlib.sha256(blob.encode()).hexdigest()[:16]

    sections = {
        # First, because a marker verdict over a partial surface is worth less
        # than it reads, and this is the section that says whether it is partial.
        "every registry tool sampled": check_tool_coverage(),
        "markers in model-visible surface": check_markers(surface),
        # The INSTRUMENT side of the marker audit. check_markers asks whether a
        # marker reached the model; this asks whether a marker was ever a fair
        # thing to scan for. Both are needed: a marker that matches the
        # questionnaire makes the section above fire on the study's own work.
        "markers are not instrument content":
            check_markers_are_not_instrument_content(),
        "published prevalence figures in surface":
            check_no_prevalence_figure_in_surface(surface),
        # The INPUT side, added 2026-08-28 (C2). Every section above scans what
        # the environment says to the model; this one asks whether the question
        # already contains its own answer. A benchmark can be broken before the
        # model is invoked and nothing downstream repairs it — the tool
        # authority gate, the refusal gate and the marker scan all pass a model
        # that read the answer out of its own prompt.
        "input does not contain the answer":
            check_input_does_not_contain_the_answer(),
        "survey platform named in surface":
            check_no_platform_name_in_surface(surface),
        "convention provenance": check_provenance(),
        "seal configuration": check_seal_config(),
        "held-out registry unreachable": check_holdout_not_reachable(),
    }

    print("=" * 74)
    print("CONTAMINATION CHECK")
    print("=" * 74)
    print(f"  surface_hash   {surface_hash}   ({len(blob):,} chars the model can see)")
    print(f"  surfaces       {len(surface)} "
          f"({sum(1 for k in surface if k.startswith('tool:'))} are tool return values)")
    print()
    failed = 0
    for name, problems in sections.items():
        print(f"  {'FAIL' if problems else 'ok  '}  {name}")
        for p in problems:
            print(f"          {p}")
        failed += len(problems)

    if live:
        from agent.sealed import CLEAN, SealedWorktree
        print("\n  live seal probes (Haiku 4.5):")
        with SealedWorktree() as w:
            r = w.verify(model="claude-haiku-4-5")
            for n, p in r["probes"].items():
                tag = {"clean": "ok  ", "leaked": "LEAK",
                       "inconclusive": "????"}[p["verdict"]]
                print(f"    {tag}  {n}")
                if p["facts"]:
                    # Not "held-out facts" any more: a confabulated platform
                    # name is volunteered and unearned but is nobody's held-out
                    # fact, and it now arrives here with an `inconclusive`
                    # verdict. Labelling it a leak would misreport it.
                    print(f"          volunteered: {', '.join(p['facts'])}")
                # EVERY answer is printed, not only the failures. A verdict of
                # `inconclusive` is a request for a human to read the answer, and
                # a verdict of `clean` is worth no more than the answer behind
                # it — the previous version printed only leaks, so the two probes
                # it was mis-scoring as clean were invisible.
                print(f"          {p['answer'][:400]}".replace("\n", " "))
            # An inconclusive probe counts as a problem: `clean` is a
            # precondition for a benchmark run, not a score, and a run that could
            # not tell whether the seal held has not established that it held.
            failed += sum(1 for p in r["probes"].values()
                          if p["verdict"] != CLEAN)
    else:
        print("\n  live seal probes SKIPPED — pass --live before a benchmark run.")

    print()
    if failed:
        print(f"  {failed} problem(s). Do not run a benchmark until these are clear.")
    else:
        print("  clean. Record surface_hash with the run.")
        print("\n  NOT CHECKED, and not checkable here: a curated sentence a")
        print("  human wrote after reading a paper. On 2026-08-26 the clustering")
        print("  convention opened with the cohort profile's recruitment")
        print("  coverage; the marker scan passed it (not a marker) and the")
        print("  provenance check passed it (declared authored-unconfirmed), and")
        print("  it reached a saved record. The control is a human re-reading")
        print("  every curated sentence against the paper record. Nothing above")
        print("  substitutes for that, and no check added here would.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
