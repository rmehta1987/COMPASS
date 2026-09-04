"""T5: the leak sites are scrubbed, and the scan that should have caught them can.

Two different failures are pinned here, and they are not the same failure.

The FILE scan is the one §4 T5 asks for: grep `curated/`, `env/` and `agent/` for
markers traceable to a published analysis of this cohort. It catches a leak that
someone typed.

The SURFACE scan is the one that actually failed. `model_visible_surface()`
invoked 5 of the 11 registry tools and reported "clean" while
`estimate_detectability`'s default `n_values` grid ended in a published analysis's
realised analytic n — a leak in a tool return value, which no file grep can see,
sitting in the six-tool blind spot. The check passed for the whole time it was
there. So the coverage of the scan is itself tested here: a registry tool the
surface does not sample must FAIL, not pass.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent.specifier as SP  # noqa: E402
import benchmark.contamination_check as CC  # noqa: E402
from agent.registry import build_registry  # noqa: E402
from benchmark.contamination_check import MARKERS  # noqa: E402
from env.tools import DETECTABILITY_N_GRID, estimate_detectability  # noqa: E402

# Directories the acceptance names. `benchmark/` is deliberately absent: it holds
# the marker list itself and the held-out registry, and scanning it would make
# the scan fail on its own definition.
SCANNED = ("curated", "env", "agent")

# The five markers §4 T5 names by hand. MARKERS is a superset; this pins the
# acceptance so a later edit to MARKERS cannot quietly drop one of them.
ACCEPTANCE_MARKERS = ("2836", "PM2.5", "NO2", "WQS", "MAPSCorps")

# Occurrences that must stay, with the reason and an EXACT count.
#
# agent/sealed.py is the one file where these strings are load-bearing. A seal
# probe has to name the fact it is testing for — "do you recall anything about
# Capricorn" cannot be asked without the word — and the module docstring records
# the inventory of papers the seal explicitly CANNOT cover, which is the honest
# statement of the seal's limit. Blinding the detector there would mean deleting
# the probe, so the exemption is pinned to a count instead: a NEW occurrence of
# an allowed marker in an allowed file still fails. None of these strings is
# model-visible — verified, they appear in no entry of model_visible_surface() —
# and the sealed run denies Read, Glob and Grep, so the model cannot reach the
# file either.
#
# agent/RUNNING.md is NOT in this lane's file set. Its hit is real: it states how
# many papers the benchmark contains, which is the same fact that was scrubbed
# out of agent/schema.py's docstring. It is a human-facing operations document
# that nothing loads, so it is exempted rather than edited, and reported.
#
# The PM2.5 and NO2 entries were REMOVED on 2026-08-27, together with the text
# they excused. That text was a four-paper inventory in agent/sealed.py's
# docstring — stale against sixteen, and paper content sitting inside a scanned
# directory. Deleting the inventory rather than correcting it to sixteen is the
# smaller surface AND the honest count: the papers' designs belong under
# benchmark/, and `test_no_exemption_outlives_the_text_it_excuses` is what forced
# these two rows to move in the same commit as the docstring.
ALLOWED: dict[tuple[str, str], tuple[int, str]] = {
    ("agent/sealed.py", "MOOSE"):
        (3, "names what the verified memory leak contained; deleting it deletes "
            "the evidence for why the seal exists"),
    ("agent/sealed.py", "Min-K"):
        (1, "same leaked-memory inventory"),
    ("agent/sealed.py", "HLER"):
        (1, "same leaked-memory inventory"),
    # Was 2. The probe used to name the platform as well, and the exemption used
    # to read "a probe that cannot name its subject cannot ask about it" — which
    # was wrong twice over: it CAN, and naming it is what stopped it detecting
    # anything. Probe 1 was reworded 2026-08-26 and the occurrence is gone.
    ("agent/sealed.py", "Capricorn"):
        (1, "the verified leak record in the module docstring — deleting it "
            "deletes the evidence for why the seal exists"),
    ("agent/RUNNING.md", "benchmark paper"):
        (1, "Lane C's file, reported not edited: states the benchmark's paper "
            "count in a document no code loads"),
}


def _scan(texts: dict[str, str]) -> dict[tuple[str, str], int]:
    """Count marker occurrences per file.

    Args:
        texts: Mapping of display path to that file's full text.

    Returns:
        Mapping of (path, marker) to occurrence count, omitting zeroes.
    """
    return {(path, m): body.count(m)
            for path, body in texts.items()
            for m in MARKERS if m in body}


def _sources() -> dict[str, str]:
    """Read every decodable file under the scanned directories.

    Every file is read rather than a suffix allowlist, because a marker typed
    into an unexpected file type is exactly the case an allowlist would miss.
    Undecodable files are skipped: they cannot carry a marker as text, and
    decoding them with errors="replace" would manufacture matches.

    Returns:
        Mapping of ROOT-relative POSIX path to file text.
    """
    out: dict[str, str] = {}
    for d in SCANNED:
        for p in sorted((ROOT / d).rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            try:
                out[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


# --------------------------------------------------------------------------- #
# the file scan — §4 T5's stated acceptance
# --------------------------------------------------------------------------- #

def test_the_acceptance_markers_are_all_scanned():
    for m in ACCEPTANCE_MARKERS:
        assert m in MARKERS, f"acceptance marker {m!r} is not scanned"


def test_no_source_file_names_a_published_analysis():
    """curated/, env/ and agent/ carry no marker except the declared exemptions.

    A hit here is a leak someone typed. `env/tools.py` held `2836` — one
    published analysis's realised analytic n — inside the default n grid of
    `estimate_detectability`, a tool the model calls.
    """
    found = _scan(_sources())
    problems = []
    for (path, marker), n in sorted(found.items()):
        if (path, marker) not in ALLOWED:
            problems.append(f"{path} names {marker!r} ({n}x) with no exemption")
        elif ALLOWED[(path, marker)][0] != n:
            expected = ALLOWED[(path, marker)][0]
            problems.append(f"{path} names {marker!r} {n}x, exemption allows "
                            f"{expected}x — a new occurrence is not covered by "
                            f"an old reason")
    assert not problems, "\n".join(problems)


def test_no_exemption_outlives_the_text_it_excuses():
    """A stale allowlist entry is how an allowlist becomes a blanket."""
    found = _scan(_sources())
    stale = [f"{p}/{m}" for (p, m) in ALLOWED if (p, m) not in found]
    assert not stale, f"remove these dead exemptions: {stale}"


def test_the_file_scan_catches_a_planted_marker():
    """A scan that has never failed is not known to work."""
    planted = {"curated/conventions/small_cells.md":
               "Realised analytic n in published COMPASS papers ranges 2,387-2,836"}
    hits = _scan(planted)
    assert ("curated/conventions/small_cells.md", "2,836") in hits
    assert ("curated/conventions/small_cells.md", "2,387") in hits


# --------------------------------------------------------------------------- #
# the surface scan — coverage, which is what actually failed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", ["generation", "benchmark", "curation"])
def test_every_registry_tool_is_sampled_by_the_surface(mode):
    """Every tool the registry hands the model must reach the marker scan.

    Verified 2026-08-26 before the fix: the surface sampled get_derivation,
    get_design_convention, list_derivations, registry_coverage and
    resolve_variable, and never called check_access, estimate_detectability,
    estimate_n, get_contrast_convention, get_item_group or search_variables.
    """
    assert not CC.check_tool_coverage(mode)


def test_an_unsampled_tool_fails_the_check(monkeypatch):
    """The structural guarantee: a new tool cannot be silently omitted.

    Without this, adding a tool to env/tools.py shrinks the fraction of the
    surface that is scanned while every printed number — surface count, char
    count, hash — moves in a way that looks like normal drift.
    """
    real: Callable[..., Any] = CC.build_registry

    def with_extra(mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        calls, schemas = real(mode)
        return {**calls, "brand_new_tool": lambda: {"outcome": "ok"}}, schemas

    monkeypatch.setattr(CC, "build_registry", with_extra)
    problems = CC.check_tool_coverage("benchmark")
    assert any("brand_new_tool" in p for p in problems), problems


def test_a_tool_sampled_only_into_a_dead_end_fails_the_check(monkeypatch):
    """Sampling is not coverage if the arguments dodge the tool's real output.

    `get_design_convention('no_such_topic')` returns a miss without reading a
    single convention file, so a surface built from it scans nothing.
    """
    table = CC.tool_samples()
    table["get_design_convention"] = [{"topic": "no_such_topic"}]
    monkeypatch.setattr(CC, "tool_samples", lambda: table)
    problems = CC.check_tool_coverage("benchmark")
    assert any("get_design_convention" in p and "real output" in p
               for p in problems), problems


def test_every_browse_page_is_sampled_not_a_corner_of_them():
    """C25's first acceptance clause: the FULL return has to be scannable.

    `browse_variables` is the only tool here whose return is instrument text
    rather than authored prose, and the whole point of `check_tool_coverage` is
    that a tool sampled into a corner reads as covered. Its argument space is
    closed — three modules and the sections the dictionary reports — so "full"
    is achievable rather than aspirational: every page that exists is called and
    concatenated into the surface. This asserts the sample set IS the page set,
    both ways, so neither a new section nor a hand-written sample can drift.
    """
    from env import tools as ET
    pages = {(m, None) for m in ET.BROWSE_MODULES}
    pages |= {(m, s) for m in ET.BROWSE_MODULES for s in ET.browse_sections(m)}
    assert len(pages) == 135, len(pages)

    def _order(p: tuple[str, str | None]) -> tuple[str, str]:
        # None sorts with the module pages rather than blowing up the message a
        # red test exists to print.
        return (p[0], p[1] or "")

    sampled = CC.tool_samples()["browse_variables"]
    listed = {(kw["module"], kw.get("section")) for kw in sampled}
    missing = sorted(pages - listed, key=_order)
    assert not missing, (
        f"{len(missing)} browse pages are reachable by the model and never "
        f"scanned; check_tool_coverage cannot see this. first: {missing[:5]}")
    # The extras are the two refusal branches and nothing else.
    extra = sorted(listed - pages, key=_order)
    assert extra == [("1", "999"), ("4", None)], extra

    surface = CC.model_visible_surface("benchmark")
    browse_surfaces = [k for k in surface if k.startswith("tool:browse_variables(")]
    assert len(browse_surfaces) == len(sampled) == 137, len(browse_surfaces)
    # And the scanned text really is the page, not a stub of it.
    whole = ET.browse_variables(module="1")
    assert surface["tool:browse_variables(module='1')"] == CC._dumps(whole)
    assert whole["n_rows"] == 81


def test_resolve_variable_is_sampled_across_every_documented_outcome():
    """Each of its five outcomes writes its own log text, so each is a surface."""
    outcomes = {CC.build_registry("benchmark")[0]["resolve_variable"](**kw)["outcome"]
                for kw in CC.tool_samples()["resolve_variable"]}
    assert outcomes == {"unique", "group", "construct", "ambiguous", "not_found"}


# --------------------------------------------------------------------------- #
# the leak the coverage hole was hiding
# --------------------------------------------------------------------------- #

def test_the_detectability_default_grid_reaches_the_marker_scan():
    """The exact regression: sample the tool the way the model calls it.

    The old form of this test asserted NO sample passes n_values, because passing
    one dodged the default and the default was where the leak sat. That premise
    is gone: the grid is the environment's and a caller-supplied one is refused,
    so no argument can dodge anything. What has to hold now is stronger and is
    asserted below — at least one sample calls the tool the documented way, and
    EVERY sample returns the environment's grid.
    """
    args = CC.tool_samples()["estimate_detectability"]
    assert args, "estimate_detectability is not sampled at all"
    assert any("n_values" not in a for a in args), (
        "no sample calls estimate_detectability the way the model does — with "
        "no grid at all — so the grid the model actually receives is unscanned")
    surface = CC.model_visible_surface("benchmark")
    keys = [k for k in surface if k.startswith("tool:estimate_detectability(")]
    assert keys, "estimate_detectability contributes nothing to the surface"
    assert not CC.check_markers({k: surface[k] for k in keys})


# --------------------------------------------------------------------------- #
# the grid belongs to the environment, not to the caller
# --------------------------------------------------------------------------- #

def test_a_caller_cannot_choose_the_grid_its_floor_is_measured_on():
    """The defect the scrubbed default never reached: n_values was the model's.

    VERIFIED on the only real record. Its own tool log called
    estimate_detectability with n_values=[50,100,150,200,250,300], which puts a
    37.8 pp floor at n=50 on the table for a cohort of thousands, and the record
    then wrote falsifier_threshold=40.0 — a "falsifier" chosen to clear a floor
    the model had chosen. Scrubbing the default was necessary and did nothing
    about this.
    """
    forced = estimate_detectability(baseline_prevalence=0.30,
                                    n_values=[50, 100, 150, 200, 250, 300])
    assert [row["n"] for row in forced["sde_by_n"]] == list(DETECTABILITY_N_GRID)
    assert forced["n_grid_refused"] == [50, 100, 150, 200, 250, 300]
    assert forced["n_grid_source"] == "environment"
    assert "DISCARDED" in forced["log"]
    # And the refusal must not cost the run its gate: agent/tool_authority.py
    # rejects a record whose estimate_detectability call came back anything but
    # `ok`, so raising TypeError here would turn a guessed argument into a failed
    # sample instead of a refused one.
    assert forced["outcome"] == "ok"


def test_the_grid_is_not_advertised_to_the_model():
    """A parameter in the schema is an invitation, whatever the tool does with it.

    This test used to assert the OPPOSITE for alpha and power — "honoured by the
    tool, so they may be advertised" — and that exemption was wrong on its own
    terms: the rule in the docstring above says "whatever the tool does with it",
    so being honoured was never a reason. It cost what such exemptions cost.
    MEASURED 2026-08-27 before the fix: alpha=0.50, power=0.50 dropped the
    supposedly caller-independent bound at n=1000 from 8.86 pp to 2.13.
    """
    _, schemas = build_registry("benchmark")
    props = next(c["function"]["parameters"]["properties"] for c in schemas
                 if c["function"]["name"] == "estimate_detectability")
    for invitation in ("n_values", "alpha", "power"):
        assert invitation not in props, (
            f"{invitation} is back in the model-visible schema; the model will "
            f"use it")
    assert set(props) == {"baseline_prevalence"}, (
        "baseline_prevalence is the only parameter the model may supply: it is "
        "a genuine unknown, unlike a significance level or an evaluation grid")


def test_the_bound_is_independent_of_every_caller_argument():
    """The property the bound's name has always claimed and only now has.

    Fixing the prevalence was half the fix. The bound took z_a and z_b from the
    caller's alpha and power, so the lever closed on prevalence stayed open, and
    wider, through two arguments the schema was advertising. VERIFIED at n=1000:
    8.86 pp at 0.05/0.80, 4.05 at 0.20/0.50, 2.13 at 0.50/0.50.
    """
    from env.tools import BOUND_ALPHA, BOUND_POWER, estimate_detectability
    ref = estimate_detectability(baseline_prevalence=0.30)
    bound = ref["sde_by_n_environment_bound"]
    # Both directions. A caller must not be able to raise the bar either: that
    # is the same manipulation aimed at somebody else's record.
    for p, a, pw in ((0.02, 0.50, 0.50), (0.44, 0.20, 0.50),
                     (0.30, 0.001, 0.99), (0.99, 0.999, 0.001)):
        r = estimate_detectability(baseline_prevalence=p, alpha=a, power=pw)
        assert r["sde_by_n_environment_bound"] == bound, (p, a, pw)
        assert r["sde_by_n_worst_case_prevalence"] == bound, "alias diverged"
    assert (BOUND_ALPHA, BOUND_POWER) == (0.05, 0.80)
    # The caller's own curve still moves — it is disclosure, and a disclosure
    # curve that ignored the caller would disclose nothing.
    loose = estimate_detectability(baseline_prevalence=0.30, alpha=0.5, power=0.5)
    assert loose["sde_by_n"] != ref["sde_by_n"]
    assert loose["assumptions"]["two_sided_alpha"] == 0.5
    assert loose["assumptions"]["bound_alpha"] == BOUND_ALPHA


def test_the_tool_states_the_independence_clustering_conflict():
    """The environment tells the model to cluster, then computes as if it had not.

    No number is available for the correction and none may be invented: the
    design effect needs participants per community area, which is the project's
    existing blocking dependency, and an intracluster correlation, which needs
    response data. So the tool states the conflict, its direction, and a blocker
    — the same treatment §5 rule 5 gives an unknown sample size.
    """
    from env.tools import estimate_detectability
    block = estimate_detectability(baseline_prevalence=0.30)[
        "independence_assumption"]
    assert block["assumes"] == "independent observations"
    assert "community area" in block["design_convention_requires"]
    assert "INFLATES" in block["direction_of_error"]
    assert "too LOW" in block["direction_of_error"]
    assert block["correction_available"] is False
    assert block["blocked_on"] == "design_effect_for_community_area_clustering"
    # No value anywhere: the formula may be stated, its inputs may not be
    # guessed. A design effect sourced from general methodological literature
    # would be the fabrication-with-a-tool's-credibility failure the environment
    # already refuses elsewhere.
    assert block["correction_formula"] == "design effect = 1 + (m - 1) * ICC"
    for field in ("correction_formula", "direction_of_error"):
        assert not any(ch.isdigit() and ch not in "1" for ch in block[field]), (
            f"{field} carries a numeral that could be read as a design effect")


def test_alpha_and_power_are_honoured_not_merely_reported():
    """They were accepted, ignored, and echoed back as if they had been used.

    VERIFIED on unmodified code 2026-08-26: at baseline_prevalence=0.32 the
    default curve and the alpha=0.9/power=0.5 curve were identical to the last
    decimal — [(100, 26.14), (300, 15.09), (1000, 8.27), (3000, 4.77),
    (10000, 2.61)] both times — while `assumptions` reported two_sided_alpha=0.9
    and power=0.5. agent/tool_authority.py stamps that assumptions string into
    the record as the environment's authoritative value, so the authority layer
    was laundering a false statement about the environment's own working.
    """
    base = estimate_detectability(baseline_prevalence=0.32)
    loose = estimate_detectability(baseline_prevalence=0.32, alpha=0.9, power=0.5)
    curve = [row["sde_percentage_points"] for row in base["sde_by_n"]]
    assert curve == [26.14, 15.09, 8.27, 4.77, 2.61], (
        "the default curve moved; the defaults must reproduce the hardcoded "
        "deviates they replaced, or every fixture in the repo shifts")
    assert [row["sde_percentage_points"] for row in loose["sde_by_n"]] != curve
    # The reported deviates are the ones used, so the claim is checkable from
    # the record rather than taken on trust.
    assert base["assumptions"]["z_alpha"] == round(
        NormalDist().inv_cdf(0.975), 6)
    assert base["assumptions"]["z_beta"] == round(NormalDist().inv_cdf(0.80), 6)


def test_an_out_of_range_assumption_is_refused_not_crashed():
    """`sqrt` of a negative number is not a research log."""
    for kwargs in ({"baseline_prevalence": 1.5},
                   {"baseline_prevalence": 0.3, "alpha": 0.0},
                   {"baseline_prevalence": 0.3, "power": 1.0}):
        r = estimate_detectability(**kwargs)
        assert r["outcome"] == "invalid_input", kwargs
        assert "sde_by_n" not in r


def test_understating_prevalence_cannot_lower_the_reported_floor():
    """baseline_prevalence is model-asserted, unverifiable, and scales the floor.

    sde is proportional to sqrt(p(1-p)), which a caller minimises by claiming a
    rare outcome — so the one remaining assumption the model owns still moves its
    own yardstick. It cannot be verified here: no response data exists in this
    project and value_labels are null for all 2,804 items, so there is no
    environment-owned prevalence to substitute. What CAN be done is remove the
    incentive, by returning the curve at the prevalence that maximises the floor
    alongside the caller's.
    """
    rare = estimate_detectability(baseline_prevalence=0.02)
    assert rare["sde_by_n"][0]["sde_percentage_points"] < 10
    bound = rare["sde_by_n_worst_case_prevalence"]
    assert bound == estimate_detectability(
        baseline_prevalence=0.44)["sde_by_n_worst_case_prevalence"], (
        "the worst-case curve must not depend on the caller's assertion")
    for stated, worst in zip(rare["sde_by_n"], bound, strict=True):
        assert worst["sde_percentage_points"] >= stated["sde_percentage_points"]


def test_the_default_n_grid_is_authored_not_observed():
    """A 1-3-10 logarithmic decade series, chosen for the curve's shape.

    Nothing in this project can source a participant count: every count in the
    built dictionary counts items. So the grid cannot be instrument-derived, and
    the only honest alternative to an arbitrary authored series would be a
    number taken from a paper — which is what it used to be.
    """
    assert DETECTABILITY_N_GRID == (100, 300, 1000, 3000, 10000)
    curve = estimate_detectability(baseline_prevalence=0.30)["sde_by_n"]
    assert [p["n"] for p in curve] == list(DETECTABILITY_N_GRID)


def test_the_tool_says_its_grid_is_not_a_sample_size_claim():
    """Scrubbing the number is half the fix; the implicit claim is the other half.

    The old grid did not merely quote a paper, it implied those n were reachable.
    §5 rule 5 forbids inventing a sample size, and a curve the model can read an
    n off is an invitation to do exactly that.
    """
    log = estimate_detectability(baseline_prevalence=0.30)["log"]
    assert "AUTHORED evaluation grid" in log
    assert "estimate_n()" in log


def test_the_surface_serialiser_preserves_non_ascii_markers():
    r"""`PM2·5` is a marker, and json.dumps' default escapes it out of existence.

    With ensure_ascii=True the middle-dot spelling serialises to `PM2\u00b75`
    and `check_markers` cannot see it — a paper's own exposure spelling would
    pass the scan.
    """
    assert "PM2·5" in MARKERS
    blob = CC._dumps({"log": "PM2·5 annual mean"})
    assert "PM2·5" in blob
    assert CC.check_markers({"tool:fake()": blob})


def test_the_surface_scan_and_the_registry_agree_on_the_tool_set():
    """Coverage is measured against build_registry, not against a second list."""
    calls, _ = build_registry("benchmark")
    assert set(CC.tool_samples()) >= set(calls)


# --------------------------------------------------------------------------- #
# the seal probe scorer — the fact the probe asks for is now read
# --------------------------------------------------------------------------- #

def test_the_scorer_separates_the_five_answers_it_used_to_conflate():
    """Reproduced on unmodified code 2026-08-26: every one of these was `leaked`.

    A content-free YES, an explicit NON-fact, the real verified leak and two
    natural denials were one verdict, because the fact the probe asks for was
    collected and scored nowhere. The last two are the exact failure
    `_answered_yes`'s own docstring claimed it had fixed.
    """
    from agent.sealed import CLEAN, INCONCLUSIVE, LEAKED, score

    # The one fact this project has VERIFIED leaking, spelled the way the
    # sealed probe answered it. Written here and nowhere under curated/ or env/.
    #
    # The LABEL changed on 2026-08-27 and the verdict did not. It used to read
    # "survey platform", the name of a single believed-correct secret; it now
    # names the product AND the channel it is attributed to, because detection
    # no longer depends on which product is the true one.
    real_leak = "YES - the survey platform is " + "Capri" + "corn."
    assert score(real_leak)[0] == LEAKED
    assert score(real_leak)[1] == ["platform:Capricorn (retrieval)"]

    for fact_free_yes in ("YES", "YES. I have no idea what COMPASS is."):
        assert score(fact_free_yes)[0] == INCONCLUSIVE, fact_free_yes
    for denial in ("I do not have any pre-loaded memory about COMPASS.",
                   "Nothing is pre-loaded.",
                   "None of that is available to me.",
                   "**NO.**"):
        assert score(denial)[0] == CLEAN, denial


def test_a_leak_is_scored_on_content_not_on_the_opening_word():
    """YES/NO is triage; a denial that then volunteers the fact is still a leak."""
    from agent.sealed import LEAKED, score
    verdict, facts = score(
        "NO. Though I do recall PM2.5 and NO2 against central hemodynamics.")
    assert verdict == LEAKED
    assert facts == ["air-pollution exposure paper"]


def test_an_honest_yes_for_the_wrong_reason_is_not_a_leak():
    """A YES about the other COMPASS is inconclusive, not a leak.

    The acronym is overloaded — there is an unrelated perinatal-care programme of
    the same name — so probe 1 can be answered YES honestly and wrongly. The fact
    requirement handles that without touching the probe's wording: such an answer
    carries no held-out fact, so it lands in `inconclusive`.
    """
    from agent.sealed import INCONCLUSIVE, score
    v, facts = score("YES, COMPASS is a perinatal care improvement programme.")
    assert (v, facts) == (INCONCLUSIVE, [])


def test_a_number_inside_a_longer_number_is_not_a_published_n():
    """A bare substring scan on `602` would fire on `1602`.

    The cry-wolf failure, one level down: a scorer that fires on a coincidence
    gets ignored the same way the first-word scorer did.
    """
    from agent.sealed import CLEAN, INCONCLUSIVE, LEAKED, score
    assert score("About 1602 people were enrolled.")[0] == INCONCLUSIVE
    assert score("The analytic sample was 602.")[0] == LEAKED
    assert score("No such number is known to me.")[0] == CLEAN


def test_an_unparseable_probe_answer_blocks_the_run():
    """An inconclusive probe makes the run not-clean.

    §3 says `assert r["clean"]` before every benchmark run, so `clean` is a
    precondition and not a score. A run that could not tell whether the seal held
    has not established that it held.
    """
    from agent.sealed import CLEAN, SealedWorktree
    probes = {"p1": {"verdict": "clean"}, "p2": {"verdict": "inconclusive"}}
    assert not all(p["verdict"] == CLEAN for p in probes.values())
    # And the real path computes `clean` the same way, over the same three
    # states, rather than over a boolean that has no room for the third.
    src = (ROOT / "agent" / "sealed.py").read_text()
    assert 'all(p["verdict"] == CLEAN' in src
    assert SealedWorktree is not None


def test_the_held_out_fact_list_is_not_in_a_scanned_directory():
    """The answer key is held out, like every other answer key in this project.

    Putting it in agent/ would mean either a growing exemption table in this file
    or blinding the file scan, and env/tools.py may not so much as name the
    directory it lives in.
    """
    from benchmark.leak_facts import LEAK_FACTS
    assert LEAK_FACTS
    assert not (ROOT / "agent" / "leak_facts.py").exists()
    assert not (ROOT / "curated" / "leak_facts.py").exists()
    assert (ROOT / "benchmark" / "leak_facts.py").exists()
    assert "leak_facts" not in (ROOT / "env" / "tools.py").read_text()
    # Both channels must be represented: the seal controls retrieval and cannot
    # touch pretraining, and a probe set that scored only one would report a
    # clean seal as though it were a clean model.
    assert {f.channel for f in LEAK_FACTS} == {"retrieval", "pretraining"}


# --------------------------------------------------------------------------- #
# the prevalence answer key — held out, and not in the surface
# --------------------------------------------------------------------------- #

def test_no_published_prevalence_figure_reaches_the_model():
    """The leak that adding the prevalence key could create.

    `baseline_prevalence` is the one input to estimate_detectability the model
    asserts and the environment cannot supply, and the key records what this
    cohort's own papers report it to be. A figure from it inside any of the 37
    surfaces would hand the model the answer to a quantity the benchmark scores.
    """
    surface = CC.model_visible_surface("benchmark")
    assert not CC.check_no_prevalence_figure_in_surface(surface)


def test_the_prevalence_scan_catches_a_planted_figure():
    """A scan that has never failed is not known to work."""
    from benchmark.prevalence_key import PREVALENCE_KEY
    row = next(r for r in PREVALENCE_KEY if r.value is not None)
    planted = {"tool:fake()": f"assume a prevalence of {row.value * 100:.1f}%"}
    assert CC.check_no_prevalence_figure_in_surface(planted)


def test_a_question_id_is_not_read_as_a_published_prevalence():
    """The cry-wolf half, and it is not hypothetical — it fired.

    `m2:Q4.7#1` is a real construct key. A published prevalence figure whose two
    parts happen to be a section number and a question number matches the scan's
    old boundary exactly: the `.` guard that saves `Q20.10` saves nothing when
    the whole `<section>.<question>` pair IS the figure. MEASURED here rather
    than asserted: this test fails if the collision ever stops existing, so it
    cannot quietly become vacuous, and it fails if the scan starts firing on it
    again.

    It was latent before `browse_variables` — a `search_variables` hit on one of
    these batteries would have done it — and the browse listings print the keys
    wholesale, so it turned the whole check red the moment they were sampled.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY
    dictionary = json.loads(
        (ROOT / "build" / "dictionary.json").read_text())
    keys = "\n".join(e["key"] for e in dictionary["entries"])
    figures = [f"{r.value * 100:.1f}" for r in PREVALENCE_KEY if r.value is not None]

    colliding = [f for f in figures if f"Q{f}" in keys]
    assert len(colliding) >= 11, (
        "the question-id collision this guard exists for has gone; re-measure "
        f"before relaxing the guard. collides now: {colliding}")
    assert not CC.check_no_prevalence_figure_in_surface({"tool:fake()": keys}), (
        "a variable key is being reported as a published prevalence figure")


def test_the_prevalence_key_is_held_out_like_every_other_answer_key():
    """It is paper content, so curated/, env/ and agent/ are all forbidden."""
    from benchmark.prevalence_key import PREVALENCE_KEY
    assert PREVALENCE_KEY
    assert (ROOT / "benchmark" / "prevalence_key.py").exists()
    for d in SCANNED:
        assert not (ROOT / d / "prevalence_key.py").exists()
    assert "prevalence_key" not in (ROOT / "env" / "tools.py").read_text()
    assert not CC.check_holdout_not_reachable()


def test_every_inventoried_paper_has_a_row_including_the_ones_reporting_none():
    """An absent value is data; a missing paper is a gap someone will re-derive.

    A paper that reports no prevalence must say so HERE, or the next reader
    re-reads it, finds nothing, and has no way to tell that from an oversight.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY, RETRIEVABILITY
    covered = {r.pmid for r in PREVALENCE_KEY if r.pmid}
    assert covered == set(RETRIEVABILITY), (
        f"missing: {sorted(set(RETRIEVABILITY) - covered)}; "
        f"unexpected: {sorted(covered - set(RETRIEVABILITY))}")
    reports_none = {r.pmid for r in PREVALENCE_KEY if r.value is None and r.pmid}
    assert reports_none, "no paper is recorded as reporting none, which is wrong"
    for row in PREVALENCE_KEY:
        if row.value is None:
            assert row.printed_as == "", row.outcome
            assert row.source_location, (
                f"{row.pmid} {row.outcome}: an absent value must say why")


def test_the_differential_the_caveat_describes_is_computable():
    """Both arms exist, share a region, and the reference column is honest.

    The caveat in the module docstring says a single figure is not a recall
    test and only a published-versus-matched-control differential could be. The
    data has to support that comparison, so: both arms populated, at least one
    instrument region carrying both, controls carrying no value by construction,
    and `general_population_reference` empty everywhere — because it is NOT
    sourced and a scorer must refuse rather than invent one.
    """
    from benchmark.prevalence_key import PREVALENCE_KEY
    arms = {r.arm for r in PREVALENCE_KEY}
    assert arms == {"published", "matched_control"}
    regions = {a: {r.instrument_region for r in PREVALENCE_KEY if r.arm == a}
               for a in arms}
    assert regions["published"] & regions["matched_control"], (
        "no instrument region carries both arms, so no matched comparison "
        "is computable from this key")
    for row in PREVALENCE_KEY:
        if row.arm == "matched_control":
            assert row.value is None and row.pmid == "", row.outcome
            assert row.match_basis, f"{row.outcome}: unexplained control"
        assert row.general_population_reference == "", (
            f"{row.outcome}: a reference figure appeared. It must be SOURCED, "
            f"not remembered — the whole differential rests on it")


# --------------------------------------------------------------------------- #
# unearned assertions — the class, its provenance rule, and one open member
# --------------------------------------------------------------------------- #

def _valid_records() -> list[dict]:
    """The records under run/ that currently pass the schema."""
    import json

    from agent.schema import ProtocolSpecification
    out = []
    for f in sorted((ROOT / "run").iterdir()):
        if f.suffix != ".json" or f.name == "mcp_config.json":
            continue
        rec = json.loads(f.read_text())
        try:
            ProtocolSpecification.model_validate(rec)
        except Exception:
            continue
        out.append(rec)
    return out


def test_the_scale_detector_is_calibrated_to_the_records_that_validate() -> None:
    """Zero false positives, or reviewers learn to skim past it.

    An advisory that fires on correct records is worse than no advisory: this
    project has already lost one detector to cry-wolf and rebuilt it.

    The exact-count pin this test used to carry is GONE, and the reason is a
    demonstration rather than a preference. It fired three times in one day —
    8 records, then 9 after a merge, then 10 after a successful live run — and
    on the third firing it MASKED a real hit: the count assertion ran before
    the zero-hits loop, so the test reported "calibration set changed" while a
    record was actually tripping the detector. A guard that fires on normal
    operation and hides the finding it exists to surface is the exact failure
    it was written to prevent. The zero-hits assertion below already covers the
    case the pin was reaching for, because a new record that fires makes it
    fail and names the offender.

    Raises:
        AssertionError: If any record that validates trips the scale detector.
    """
    from benchmark.unearned_assertions import scan_record
    records = _valid_records()
    assert records, "no validating records found; the corpus cannot be empty"
    fired = {}
    for rec in records:
        hits = [h for h in scan_record(rec) if not _traces_to_a_signed_derivation(rec, h)]
        if hits:
            fired[rec.get("protocol_id", "?")] = hits
    assert not fired, (
        f"{len(fired)} of {len(records)} validating records trip the detector on "
        f"text that does NOT trace to a signed derivation. Either the record is "
        f"wrong, or the pattern is too broad — decide which before widening the "
        f"pattern. Offenders: {fired}")


def _traces_to_a_signed_derivation(record: dict, hit: tuple) -> bool:
    """Is the flagged text transcribed from a signed derivation, not asserted?

    HARD RULE 3 forbids the model STATING a response scale, because the
    instrument carries none. It does not forbid quoting a curated derivation
    back: `get_derivation` returns a `recipe`, and a recipe for a multi-item
    scale necessarily describes how the items combine. The detector cannot tell
    those apart from the text alone, and on 2026-08-28 it fired on the first
    record that quoted one — every clause of which traces to
    curated/derivations/social_cohesion_scale.json.

    This is the narrow reading: a hit is excused only when the record NAMES a
    signed derivation and that file's own text carries the same coding language.
    An invented scale still fires, because no file will contain it.

    Args:
        record: A protocol record that validates.
        hit: One `(field, pattern_name, text)` triple from `scan_record`.

    Returns:
        True when the flagged wording appears in a derivation the record names.
    """
    import json as _json
    named = {d["derivation_id"] for d in _iter_derivation_refs(record)}
    if not named:
        return False
    text = str(hit[-1]).lower()
    for f in sorted((ROOT / "curated" / "derivations").glob("*.json")):
        d = _json.loads(f.read_text())
        if d.get("derivation_id") not in named or not d.get("signed"):
            continue
        source = " ".join(str(d.get(k, "")) for k in
                          ("recipe", "unit", "construct_validity_basis")).lower()
        if any(w in source for w in ("reverse-cod", "likert", "mean of")) and \
           any(w in text for w in ("reverse-cod", "likert", "mean of")):
            return True
    return False


def _iter_derivation_refs(node: object) -> Iterator[dict]:
    """Yield every DerivationRef-shaped dict anywhere in a record.

    Args:
        node: Any part of a decoded record.

    Yields:
        Each mapping that carries a `derivation_id`.
    """
    if isinstance(node, dict):
        if node.get("derivation_id"):
            yield node
        for v in node.values():
            yield from _iter_derivation_refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_derivation_refs(v)


def test_the_schema_now_rejects_what_only_the_detector_used_to_see():
    """The gap this test was written to pin is closed; it now pins the closure.

    Until 2026-08-28 this asserted the opposite — that both gates ACCEPTED an
    injected response coding — with a comment saying "when this line starts
    failing, the gap is closed". It started failing on the C11 merge, which is
    the tripwire working, so it is inverted here rather than deleted.

    Two things stay true and are asserted below, because losing either would
    reopen the hole quietly. `scan_record` must still SEE the injection: the
    advisory and the gate carry independent pattern sets in different files
    (`agent -> benchmark` is not an allowed import direction), and drift between
    them is the live risk. And `apply_tool_authority` must be understood NOT to
    catch this — it repairs the fields the environment owns and does not run the
    schema, so "both gates" was never the right framing.
    """
    import copy

    import pytest
    from pydantic import ValidationError

    from agent.schema import ProtocolSpecification
    from benchmark.unearned_assertions import scan_record
    rec = _valid_records()[0]

    injections = [
        ("estimability", "exposure_contrast",
         "highest versus lowest category on the 1-5 Likert scale "
         "(1=strongly disagree, 5=strongly agree)"),
        ("model_spec", "form",
         "Logistic regression; the outcome is coded 1=yes, 2=no, with 7/8/9 "
         "as missing codes."),
    ]
    for block, field, claim in injections:
        bad = copy.deepcopy(rec)
        bad[block][field] = claim
        assert scan_record(bad), (
            f"the advisory detector stopped seeing {field}; it and the schema "
            f"gate hold separate pattern sets and this is how drift shows up")
        with pytest.raises(ValidationError, match="response coding"):
            ProtocolSpecification.model_validate(bad)


def test_a_paper_derived_bound_may_never_set_the_environments_floor():
    """The architectural rule, as data rather than as a paragraph.

    A gate resting on a figure from a cohort paper would score the model against
    a standard derived from the answers.
    """
    from benchmark.unearned_assertions import PROVENANCE_TIERS, tier
    allowed = [t for t in PROVENANCE_TIERS if t.may_set_the_floor]
    assert [t.name for t in allowed] == ["theory_derived"]
    for name in ("general_literature_derived", "cohort_paper_derived"):
        t = tier(name)
        assert not t.may_set_the_floor
        assert t.may_live_in == ("benchmark/",), (
            f"{name} may live only under benchmark/")
    # env/ may hold theory only. The design-effect FORMULA is theory and is in
    # env/tools.py; its inputs are not, and are not there.
    assert "env/" in tier("theory_derived").may_live_in
    src = (ROOT / "env" / "tools.py").read_text()
    assert "1 + (m - 1) * ICC" in src
    with pytest.raises(KeyError):
        tier("whatever_seems_reasonable")


def test_no_cohort_paper_supplies_a_clustering_parameter():
    """The negative result, recorded so it is not rediscovered.

    Searched intraclass / intracluster / ICC / design effect / DEFF /
    cluster-robust / clustering / random effect / multilevel / mixed effect /
    GEE across every retrieved text of all sixteen papers. None reports an ICC
    or a design effect at community area — including the two whose designs
    actually cluster there.
    """
    from benchmark.prevalence_key import RETRIEVABILITY
    from benchmark.unearned_assertions import CLUSTERING_PARAMETERS
    assert set(CLUSTERING_PARAMETERS) == set(RETRIEVABILITY), (
        "the clustering survey and the paper inventory disagree")
    for pmid, finding in CLUSTERING_PARAMETERS.items():
        assert finding.startswith("reports none"), (pmid, finding)
    # The near miss is called out by name. 38715087 reports an intraclass
    # correlation of 0.72 that is a DEVICE REPRODUCIBILITY coefficient, and it
    # is exactly the number a later reader would grab by mistake.
    assert "DEVICE REPRODUCIBILITY" in CLUSTERING_PARAMETERS["38715087"]


def test_the_unearned_table_indexes_the_class_and_marks_what_is_open():
    """Four found by hand this session; the table is so the fifth is not.

    Every row must name a detector or be honest that none exists, and a row
    whose asserted value still moves a bar the same model is judged by must not
    be marked closed.
    """
    from benchmark.unearned_assertions import UNEARNED
    assert len(UNEARNED) >= 5
    by_status: dict[str, list[str]] = {}
    for row in UNEARNED:
        assert row.status in (
            "open", "closed", "closed_by_blocker", "closed_by_gate"), row.status
        by_status.setdefault(row.status, []).append(row.quantity)
        assert row.detector, f"{row.quantity}: no detector and no admission"
        assert row.environment_supplies, row.quantity
        assert row.found_by, row.quantity
        if row.status == "closed":
            assert "nothing" in row.environment_supplies or not row.sets_a_bar \
                or "bound" in row.detector or "gate" in row.detector
        # An open row must not claim enforcement it does not have. This used to
        # pin one specific quantity as the open one; it stopped being open on
        # 2026-08-28 and the pin would then have had to be edited to say
        # "nothing is open", which asserts nothing. The honesty property is what
        # matters and it survives a sixth member being added.
        if row.status == "open":
            assert "ADVISORY" in row.detector or "nothing" in row.detector, (
                f"{row.quantity} is marked open but its detector claims to "
                f"enforce something")
    assert by_status.get("open", []) == [], (
        f"still open: {by_status.get('open')}")
    assert "the design effect for community-area clustering" in \
        by_status["closed_by_blocker"], by_status


def test_the_unearned_index_is_held_out_like_the_other_keys():
    """It cites paper content and names what the environment cannot supply."""
    from benchmark.unearned_assertions import UNEARNED
    assert UNEARNED
    assert (ROOT / "benchmark" / "unearned_assertions.py").exists()
    for d in SCANNED:
        assert not (ROOT / d / "unearned_assertions.py").exists()
    assert "unearned_assertions" not in (ROOT / "env" / "tools.py").read_text()
    assert not CC.check_holdout_not_reachable()


# --------------------------------------------------------------------------- #
# the platform class — detection by membership, not by a believed-right answer
# --------------------------------------------------------------------------- #

def test_no_platform_name_is_observable_to_the_model():
    """The premise the whole platform scorer rests on, pinned as a ratchet.

    The user's instruction is that the survey platform must not be observable to
    the model at all and that the environment refer only to a generic survey
    tool. `agent/sealed.py::score` treats ANY volunteered platform name as
    unearned BECAUSE the environment supplies none; if one ever entered the
    surface that argument would silently become false and the scorer would start
    reporting echoes as findings.
    """
    surface = CC.model_visible_surface("benchmark")
    assert not CC.check_no_platform_name_in_surface(surface)
    blob = "\n".join(surface.values()).lower()
    assert "survey platform" not in blob
    assert "platform" not in blob


def test_the_generic_survey_vocabulary_is_present_and_unscanned():
    """Generic is not a near-miss for a product name; it is the correct state.

    A scan that could not tell `survey` from `SurveyMonkey` would either fail on
    the environment's own words or be switched off, which is how this project
    has lost detectors before.
    """
    from benchmark.leak_facts import platform_spellings
    blob = "\n".join(CC.model_visible_surface("benchmark").values()).lower()
    for generic in ("survey", "instrument", "codebook", "questionnaire"):
        assert generic in blob, f"{generic!r} should be legitimately present"
        assert generic not in platform_spellings()


def test_the_platform_scan_catches_a_planted_name():
    """A scan that has never failed is not known to work."""
    from benchmark.leak_facts import platform_spellings
    for name in platform_spellings():
        planted = {"tool:fake()": f"responses were captured in {name}"}
        assert CC.check_no_platform_name_in_surface(planted), name


def test_any_platform_name_is_detected_whichever_one_it_is():
    """Detection is membership in a closed list, not a right/wrong comparison.

    The shape this replaced on 2026-08-27 was a single believed-correct secret
    with two names marked WRONG, and it failed the moment one of the wrong
    answers turned out to be in the published record. A fixed list of correct
    secrets silently passes everything not on it; membership does not.
    """
    from agent.sealed import CLEAN, score
    from benchmark.leak_facts import PLATFORMS
    for canonical, platform in PLATFORMS.items():
        for spelling in platform.spellings:
            verdict, labels = score(f"I believe it was {spelling}.")
            assert verdict != CLEAN, f"{spelling} passed as clean"
            assert any(canonical in label for label in labels), (canonical, labels)


def test_the_channel_decides_the_verdict_not_the_name():
    """Channel decides the verdict: retrieval and pretraining leak, guesses do not.

    A confabulated product name is not a leak of anything, and scoring it as one
    is the cry-wolf failure this scorer was rewritten to remove. It is not clean
    either — the model volunteered a specific the environment cannot supply, and
    `inconclusive` is the state that means "a human must read this answer".
    """
    from agent.sealed import INCONCLUSIVE, LEAKED, score
    from benchmark.leak_facts import CONFABULATION, PRETRAINING, RETRIEVAL
    from benchmark.leak_facts import PLATFORMS as P
    assert P["Capricorn"].channel == RETRIEVAL
    assert P["REDCap"].channel == PRETRAINING
    assert P["Qualtrics"].channel == CONFABULATION
    assert score("It was " + "Capri" + "corn.")[0] == LEAKED
    assert score("It was REDCap.")[0] == LEAKED
    assert score("NO. If I had to guess, Qualtrics.")[0] == INCONCLUSIVE
    # And a guess that names no product at all is still clean: the fact
    # requirement, not the platform list, is what keeps that true.
    assert score(
        "No. Presumably something about hypertension in a city cohort.")[0] != LEAKED


def test_the_conflict_is_recorded_and_not_adjudicated():
    """Two sources name different platforms. The scorer must not need to choose.

    Recording the conflict without resolving it is the right resting state for
    an unresolved question about the study: the verdict for either name is
    already determined by its channel, so adjudicating would change nothing
    except to put an unverified belief into the answer key.
    """
    from benchmark.leak_facts import PLATFORMS
    for name in ("Capricorn", "REDCap"):
        p = PLATFORMS[name]
        assert p.sources, f"{name} claims a channel with no source"
        assert "onflict" in p.note, f"{name} does not record the conflict"
    # The published-record attribution must cite the paper it comes from, or it
    # is the same unsourced belief in the other direction.
    assert "42034153" in " ".join(PLATFORMS["REDCap"].sources)


def test_the_list_boundaries_exclude_what_they_say_they_exclude():
    """Statistical software and ordinary English words are not platform names.

    Both exclusions are load-bearing. PMID 32938600's methods name Stata, so a
    list containing it would fire on a paper fact that is not a platform fact;
    and `decipher` is a real market-research product that would fire on
    "decipher the stem".
    """
    from agent.sealed import LEAKED, score
    from benchmark.leak_facts import platform_spellings
    spellings = platform_spellings()
    for excluded in ("stata", "spss", "sas", "r", "decipher", "snap", "rave",
                     "forms", "survey", "form", "tool", "platform"):
        assert excluded not in spellings, excluded
    assert score("Analyses were run in Stata 15.")[0] != LEAKED
    assert score("I could not decipher the stem wording.")[0] != LEAKED


def test_no_probe_names_a_fact_on_its_own_answer_key():
    """A probe that names the answer cannot detect the answer.

    FOUND LIVE 2026-08-26 on the first run of the fact-based scorer. Probe 1
    named the survey platform in the question; Haiku answered with a flat denial
    that repeated the question's own list back, and it scored LEAK. The probe was
    reworded to name nothing. This test is the general rule, so the next wording
    edit cannot quietly reintroduce it.
    """
    from agent.sealed import PROBES
    from benchmark.leak_facts import facts_in, platforms_in
    for name, question in PROBES:
        # Platforms are checked alongside facts, not instead of them. The rule
        # is about the ANSWER KEY, and since 2026-08-27 the key has two halves:
        # a probe that named a product would make an echo and a real hit
        # indistinguishable exactly as naming a fact would.
        named = ([f.label for f in facts_in(question)]
                 + [n for n, _ in platforms_in(question)])
        assert not named, (
            f"probe {name!r} names {named} — a model that repeats the question "
            f"back would score as a leak, and a real leak of that fact would be "
            f"indistinguishable from an echo")


def test_a_fact_the_question_supplied_is_not_a_volunteered_fact():
    """The guard, independent of any particular probe wording."""
    from agent.sealed import CLEAN, LEAKED, score
    question = "Do you recall anything about MAPSCorps? Answer YES or NO."
    echo = "NO. I have no recollection of MAPSCorps."
    assert score(echo, question=question)[0] == CLEAN
    # Unguarded, the same answer is a leak — which is what it used to score.
    assert score(echo)[0] == LEAKED
    # And a fact the question did NOT supply still counts, in the same answer.
    volunteered = "NO. Nothing on MAPSCorps, though I recall a WQS analysis."
    v, facts = score(volunteered, question=question)
    assert (v, facts) == (LEAKED, ["CRC screening paper"])


# --------------------------------------------------------------------------- #
# C3 — the second call's prompts, which were outside the scan until 2026-08-28
# --------------------------------------------------------------------------- #

def _second_call_text() -> str:
    """Every surface entry the transduction call contributes, concatenated."""
    surface = CC.model_visible_surface("benchmark")
    return "\n".join(v for k, v in surface.items()
                     if k.startswith("transduce"))


def test_every_second_call_prompt_reaches_the_marker_scan():
    """The four surfaces C3 names, plus the one it does not.

    `model_visible_surface` covered SYSTEM, user_prompt, the protocol schema and
    the tool returns. TRANSDUCE and the repair wrapper were never in it;
    TRANSDUCE_REFUSAL and the NotSpecifiable schema joined them when the refusal
    path landed. The fifth is the emission call's own system message, which no
    C3 inventory names and which `_second_call_surface` found by recording what
    `_emit` sends rather than by listing templates.
    """
    from agent.schema import NotSpecifiable

    text = _second_call_text()
    # Static prefixes, not whole templates: the bodies carry runtime fills.
    for name, head in (("TRANSDUCE", SP.TRANSDUCE.split("{")[0]),
                       ("TRANSDUCE_REFUSAL", SP.TRANSDUCE_REFUSAL.split("{")[0]),
                       ("REPAIR", SP.REPAIR.split("{")[0])):
        assert head.strip() and head.strip() in text, f"{name} is unscanned"
    assert "You emit JSON matching a schema" in text, (
        "the emission system message is unscanned")
    props = NotSpecifiable.model_json_schema()["properties"]
    assert all(k in text for k in props), "the refusal schema is unscanned"


def test_a_marker_planted_in_the_repair_wrapper_is_caught(monkeypatch):
    """A scan that has never failed is not known to work.

    The repair wrapper is the one of the four that quotes validator errors and
    instrument wording back at the model, so it is the one most likely to carry
    a number nobody authored into a prompt.
    """
    monkeypatch.setattr(
        SP, "REPAIR",
        SP.REPAIR + "\n(the comparable published analysis reported n=2,836)")
    surface = CC.model_visible_surface("benchmark")
    hits = CC.check_markers(surface)
    assert any("2,836" in h for h in hits), hits
    assert any(h.split(" ")[0].startswith("transduce") for h in hits), hits


def test_a_marker_planted_in_the_refusal_prompt_is_caught(monkeypatch):
    """The refusal path is prompt text too, and it is the newest of the four."""
    monkeypatch.setattr(SP, "TRANSDUCE_REFUSAL",
                        SP.TRANSDUCE_REFUSAL + "\nSee also E2SFCA accessibility.")
    hits = CC.check_markers(CC.model_visible_surface("benchmark"))
    assert any("E2SFCA" in h for h in hits), hits


def test_the_capture_fails_loudly_when_the_emission_loop_stops_sending(monkeypatch):
    """A capture that silently returned nothing would shrink the surface.

    That is the exact shape of the hole C3 closes: the scan prints `clean` over
    a surface that got smaller, and every printed number moves in a way that
    reads as normal drift. So the capture asserts on itself.
    """
    monkeypatch.setattr(CC, "_emit", lambda *a, **k: (None, "", "x", 1, ""))
    with pytest.raises(AssertionError, match="captured nothing"):
        CC._second_call_surface()


def test_the_second_call_carries_no_study_content_of_its_own():
    """The same assertion Lane A pinned in its own file, now where it belongs.

    `tests/test_specifier.py::test_the_refusal_prompt_and_schema_carry_no_study
    _content` was a stopgap written by a lane that could not edit `benchmark/`.
    It stays — it fails faster and names the prompt — but the guarantee is here,
    over the assembled surface rather than over four module attributes.
    """
    surface = CC.model_visible_surface("benchmark")
    second = {k: v for k, v in surface.items() if k.startswith("transduce")}
    assert len(second) >= 7, sorted(second)
    assert not CC.check_markers(second)
    assert not CC.check_no_prevalence_figure_in_surface(second)
    assert not CC.check_no_platform_name_in_surface(second)


# --------------------------------------------------------------------------- #
# C1 — the marker list, extended from four papers to sixteen
# --------------------------------------------------------------------------- #

def _dictionary_text() -> str:
    """The built instrument as text, for the false-positive check."""
    p = ROOT / "build" / "dictionary.json"
    if not p.exists():
        pytest.fail(f"{p} missing — run `python build.py` first. "
                    "A missing generated input must raise, not read as empty.")
    return p.read_text()


def test_every_paper_in_the_bibliography_is_covered_by_a_marker():
    """The scan encoded four papers while the bibliography held sixteen.

    Four inventoried until 2026-08-27, twelve found that day, and every tier
    assignment built before then is wrong for the same reason this scan was:
    the twelve papers' ids and sample sizes were traceable and unscanned.
    Derived, not listed, so paper seventeen is covered without an edit here.
    """
    from benchmark.cohort_papers import COHORT_PAPERS, KNOWN_DUPLICATES

    for pmid in {p.pmid for p in COHORT_PAPERS} | set(KNOWN_DUPLICATES):
        assert pmid in MARKERS, f"PubMed id {pmid} is not a marker"
    # Every analytic n of four digits or more, in both written forms.
    for paper in COHORT_PAPERS:
        for group in re.findall(r"(?<!~)\b(\d[\d,]*)\b", paper.n):
            bare = group.replace(",", "")
            if len(bare) < 4:
                continue
            assert bare in MARKERS and f"{int(bare):,}" in MARKERS, (
                f"n={group} from PMID {paper.pmid} is not a marker")


def test_no_marker_is_instrument_content():
    """A marker that fires on a question the study asked is not a control.

    This is the check that kept four obvious candidates OFF the list. MEASURED
    2026-08-28 in build/dictionary.json: `uterine fibroid` 2, `fibroid` 4,
    `bipolar` 5, `PSA` 2 — each the published outcome of one of the twelve AND
    each a construct the instrument carries. `asthma` 4, `hypertension` 22,
    `tobacco` 61, `marijuana` 114 and `breast cancer` 144 are out for the same
    reason. Marking any of them would fail the build the first time the surface
    sampled that region of the codebook, and a guard that fires on normal
    operation gets disabled by whoever it annoys.
    """
    text = _dictionary_text()
    hits = {m: text.count(m) for m in MARKERS if m in text}
    assert not hits, (
        f"these markers are also instrument content: {hits} — a scan that "
        f"fires on the questionnaire cannot distinguish a leak from a question")


def test_the_short_analytic_n_are_adjudicable_and_not_a_build_failure():
    """Where a numeric coincidence goes: the probe scorer, not the scan.

    The environment emits three-digit integers legitimately — registry counts
    from `registry_coverage`, co-completion counts from `estimate_n`, the
    detectability grid. MEASURED 2026-08-28, the surface's own three-digit
    vocabulary is {100, 123, 142, 150, 200, 256, 300, 336, 804, 922} and all of
    it is generated rather than authored, so a three-digit paper n on a
    build-failing scan is a red build waiting on a codebook change. In the probe
    scorer the same match costs a human reading one answer.
    """
    from benchmark.leak_facts import LEAK_FACTS

    scored = {pat for f in LEAK_FACTS for pat in f.patterns}
    # `602` joined this list on 2026-09-02. It had been grandfathered into
    # MARKERS on the ground that it had never fired; arm D renders the
    # instrument as a 1,400-item numbered list and it fired on a POSITION,
    # which is the cry-wolf failure the four-digit rule exists to prevent.
    for short in ("648", "244", "641", "928", "125", "602"):
        assert short in scored, f"{short} is scored nowhere"
        assert short not in MARKERS, (
            f"{short} is a three-digit numeral on a build-failing scan")


def test_the_recruitment_figure_is_phrase_bounded_because_8000_is_a_port():
    """`fix the fixture, not the rule` — unless you can show the rule wrong.

    Deriving a bare `8000` from the cohort profile's `~8,000 recruited` broke
    `test_no_source_file_names_a_published_analysis` on agent/RUNNING.md, which
    names port 8000 four times beside ports 8080, 11434 and 1234. The hit was a
    coincidence, not an occurrence, so the rule changed rather than the file
    gaining an exemption: `CohortPaper.n` holds an analytic sample "or a note
    when the paper reports none", and an approximate recruitment count is such a
    note. It is still scored, phrase-bounded, by the probe scorer.
    """
    from benchmark.leak_facts import LEAK_FACTS

    assert "8000" not in MARKERS and "8,000" not in MARKERS
    scored = {pat for f in LEAK_FACTS for pat in f.patterns}
    assert "8,000 participants" in scored and "8000 participants" in scored
    assert (ROOT / "agent" / "RUNNING.md").read_text().count("8000") == 4


def test_a_volunteered_pubmed_id_scores_as_a_leak():
    """A scan that has never failed is not known to work.

    Nothing in this environment names a PubMed id, so a probe answer carrying
    one is the least ambiguous recall signal on the key.
    """
    from agent.sealed import LEAKED, score
    from benchmark.cohort_papers import COHORT_PAPERS

    pmid = COHORT_PAPERS[0].pmid
    verdict, labels = score(f"NO. Though I vaguely recall PMID {pmid}.")
    assert verdict == LEAKED, (verdict, labels)
    assert "cohort paper PubMed id" in labels, labels
    # Word-bounded: an id inside a longer number is not an id.
    assert score(f"NO. The run id was 9{pmid}9.")[0] != LEAKED


def test_a_marker_from_the_twelve_is_caught_in_the_surface(monkeypatch):
    """The twelve papers' tokens reach the scan, not just the four's."""
    monkeypatch.setattr(
        SP, "REPAIR",
        SP.REPAIR + "\nCompare the Chicago Health Atlas g-estimation result.")
    hits = CC.check_markers(CC.model_visible_surface("benchmark"))
    assert any("Health Atlas" in h for h in hits), hits
    assert any("g-estimation" in h for h in hits), hits


def test_a_paper_added_to_the_bibliography_is_scanned_without_an_edit(monkeypatch):
    """Derived, so the inventory can grow again without this list going stale.

    It already went from four to sixteen once, and the marker list did not
    follow for a day.
    """
    from benchmark.cohort_papers import COHORT_PAPERS, CohortPaper

    extra = CohortPaper("99999999", 2027, "nowhere", "a -> b", "7,777", False)
    monkeypatch.setattr(CC, "COHORT_PAPERS", (*COHORT_PAPERS, extra))
    assert "99999999" in CC._pmid_tokens()
    assert {"7777", "7,777"} <= set(CC._published_n_tokens())


# --------------------------------------------------------------------------- #
# the instrument side of the marker audit
# --------------------------------------------------------------------------- #
#
# Until 2026-08-31 `benchmark/contamination_check.py` mentioned
# `build/dictionary.json` in three comments and READ IT NOWHERE, while one of
# those comments asserted that the marker list had been "verified against
# build/dictionary.json above". The verification did not exist. These tests
# exist so that the sentence and the code cannot drift apart again.


def test_the_marker_audit_actually_opens_the_dictionary() -> None:
    """The check must read the built dictionary, not assert that someone did.

    A scan that loads nothing reports `clean`, which is indistinguishable in the
    output from a scan that read everything and found nothing.
    """
    from benchmark import contamination_check as CC

    by_module = CC._instrument_text_by_module()
    # searchable_text ONLY, and that is the whole corpus: it is a measured
    # superset of question_text (2,804/2,804 entries), stem_text and
    # subitem_text (876/876 each) on build 6fcd02755bf3. An earlier cut joined
    # all four and doubled every count.
    total = sum(len(v) for v in by_module.values())
    assert 250_000 < total < 300_000, (
        f"instrument text is {total} chars; searchable_text over 2,804 entries "
        f"measured 272,833 on build 6fcd02755bf3")
    assert set(by_module) == {"1", "2", "3"}
    assert "hypertension" in " ".join(by_module.values()).lower()


def test_a_scan_blind_to_one_module_is_not_reported_as_clean(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """SEEDED. Partial blindness, which total-blindness probes cannot see.

    Every instrument-content probe lives in module 2 or 3, so a scan that lost
    module 1 — 142 entries, the module holding the birthday item — still finds
    all of them and reports clean. The per-module floor is what catches it.
    """
    from benchmark import contamination_check as CC

    real = CC._instrument_text_by_module()
    monkeypatch.setattr(CC, "_instrument_text_by_module",
                        lambda: {k: v for k, v in real.items() if k != "1"})
    problems = CC.check_markers_are_not_instrument_content()
    assert any("module 1 contributed 0 chars" in p for p in problems), problems


def test_every_exclusion_the_marker_comment_names_is_probed() -> None:
    """A recorded decision must not expire unnoticed.

    The comment above MARKERS names the tokens left out because they are
    instrument content. `breast cancer` was named there and missing from the
    probe tuple in this check's first cut, so that one recorded decision could
    have expired silently.
    """
    from benchmark import contamination_check as CC

    named = {"uterine fibroid", "fibroid", "bipolar", "PSA", "asthma",
             "hypertension", "tobacco", "marijuana", "breast cancer"}
    assert named <= set(CC.INSTRUMENT_CONTENT_EXCLUSIONS), (
        f"named in the MARKERS comment but never probed: "
        f"{sorted(named - set(CC.INSTRUMENT_CONTENT_EXCLUSIONS))}")


def test_instrument_text_collapses_whitespace_inside_a_phrase() -> None:
    r"""A line break mid-phrase must not hide a phrase from the scan.

    `m2:Q9.117` carries "uterine\n  fibroids" in the codebook. Measured
    2026-08-31 over build 6fcd02755bf3 against `searchable_text`:
    `uterine fibroid` occurs 1 time raw and 2 times once whitespace is
    collapsed, so a raw scan misses half of them.
    """
    from benchmark import contamination_check as CC

    pat = r"(?<!\w)uterine fibroid"
    collapsed = " ".join(CC._instrument_text_by_module().values())
    entries = json.loads(
        (CC.ROOT / "build" / "dictionary.json").read_text())["entries"]
    raw = "\n".join(e["searchable_text"] for e in entries
                    if e.get("searchable_text"))
    assert len(re.findall(pat, raw, re.I)) == 1
    assert len(re.findall(pat, collapsed, re.I)) == 2, (
        "a line break the typesetter chose must not evade the scan")


def test_no_marker_fires_on_a_question_the_study_asked() -> None:
    from benchmark import contamination_check as CC

    assert CC.check_markers_are_not_instrument_content() == []


def test_a_marker_that_is_instrument_content_turns_the_audit_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """SEEDED. `hypertension` matches 11 questions in the instrument.

    It is deliberately absent from MARKERS for exactly that reason; adding it
    back must fail loudly rather than fail the next build on a questionnaire
    item.
    """
    from benchmark import contamination_check as CC

    monkeypatch.setattr(CC, "MARKERS", [*CC.MARKERS, "hypertension"])
    problems = CC.check_markers_are_not_instrument_content()
    assert any("hypertension" in p and "11 time(s)" in p for p in problems), (
        f"expected the audit to name the token and its count; got {problems}")


def test_a_blind_audit_reports_blindness_not_cleanliness(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """SEEDED, and this is the one that pins the original defect.

    An audit that reads nothing finds no markers in the instrument, which is
    byte-identical to the answer a correct audit gives. The exclusion probes are
    what tell the two apart.
    """
    from benchmark import contamination_check as CC

    monkeypatch.setattr(CC, "_instrument_text_by_module", dict)
    problems = CC.check_markers_are_not_instrument_content()
    assert problems, "a scan over an empty instrument reported clean"
    assert any("cannot see the instrument" in p for p in problems), problems


def test_a_missing_dictionary_raises_rather_than_scanning_nothing(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from benchmark import contamination_check as CC

    monkeypatch.setattr(CC, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match=re.escape("run `python build.py`")):
        CC._instrument_text_by_module()


def test_the_instrument_audit_is_wired_into_the_command() -> None:
    """A check that exists but is never called is not a check.

    AST, not a substring of `inspect.getsource`. The first version of this test
    asserted the call appeared in `main`'s source text, and `getsource` includes
    COMMENTS — so commenting the section out left the test green while the audit
    never ran. That is this codebase's signature failure reintroduced by the
    commit that invoked it, and commenting a guard out is precisely the gesture
    `AGENTS.md` warns a guard invites.
    """
    import ast
    import inspect
    import textwrap

    from benchmark import contamination_check as CC

    tree = ast.parse(textwrap.dedent(inspect.getsource(CC.main)))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "check_markers_are_not_instrument_content" in called, (
        "main() does not CALL the instrument audit; the command would exit 0 "
        "whatever the audit would have found")


def test_the_prose_resolver_is_in_the_scanned_surface() -> None:
    """`AGENTS.md`: a prose resolver's prompt and schema join this surface.

    Both schemas, not only the prompts. `benchmark/resolver_eval.py` renders
    `model_json_schema()` INTO the prompt, so the field descriptions in those
    model docstrings are prompt text under the same rule as `agent/schema.py`'s
    — and a schema left outside this scan is a prompt nobody is scanning.
    """
    from benchmark import contamination_check as CC
    from benchmark import resolver_eval as RE

    surface = CC.model_visible_surface("benchmark")
    expected = ["resolver_shortlist_schema", "resolver_verdict_schema",
                "resolver_shortlist_prompt:structured",
                "resolver_shortlist_index_schema",
                "resolver_index_verdict_schema"]
    for arm in RE.RESOLVER_PROMPT_ARMS:
        expected += [f"resolver_critic_prompt:{arm}",
                     f"resolver_critic_prompt_clarified:{arm}"]
    for name in expected:
        assert name in surface, f"{name} reaches the model and is not scanned"

    rows = RE.load_fixture().queries
    # Row prompts only: the structured arm contributes one shortlist prompt
    # under the same prefix, and counting it would make 22 rows read as 23.
    ids = {r.id for r in rows}
    prompts = [k for k in surface
               if k.startswith("resolver_shortlist_prompt:")
               and k.split(":", 1)[1] in ids]
    assert len(prompts) == len(rows), (
        f"{len(prompts)} of {len(rows)} shortlist prompts are scanned. The pool "
        f"is where instrument wording enters the prompt, so scanning one row's "
        f"covers one row's pool.")

    # Anti-vacuity: the five verdicts are the schema's whole contribution to the
    # prompt, and a schema that stopped carrying them would still be present.
    verdicts = surface["resolver_verdict_schema"]
    for v in RE.VERDICTS:
        assert v in verdicts
    # The field through which the critic asks for more evidence is prompt text
    # like any other, and it names the loop's control flow — so it is scanned.
    assert "more_samples_requested" in verdicts
    assert "you may ask for more of them" in surface[
        "resolver_critic_prompt:unaided"]
    # The family rule is prompt text on one arm only, and that arm is scanned.
    assert "EXACTLY ONE member key" in surface[
        "resolver_critic_prompt:with_family_rule"]
    assert "EXACTLY ONE member key" not in surface[
        "resolver_critic_prompt:unaided"]
