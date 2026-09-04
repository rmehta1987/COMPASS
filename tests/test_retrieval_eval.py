from __future__ import annotations

import pytest

from benchmark import retrieval_eval as ev
from env import tools

# The as-shipped measurement, re-derived 2026-08-31 by `python -m
# benchmark.retrieval_eval` over benchmark/fixtures/retrieval_queries.json: 224
# rows, no filter, gold = roster-normalised searchable_text equality. It
# reproduces the lexical row C22 was accepted against exactly (15.2% / 41.5% /
# 53.6%); see `CHANGELOG.md`, 2026-08-31.
#
# A RATCHET, deliberately, not a pin. C22 deletes code from search_variables and
# its acceptance is "recall@10 not down"; a test pinning equality would go red on
# a deletion that IMPROVED retrieval, and a guard that fires on correct work gets
# deleted by whoever it annoys. These may only go UP. The test prints the new
# value when one can be raised.
#
# IT STAYS ONE-SIDED, and COLLAPSE_CARDINALITY below is why it can. A large
# unexplained INCREASE has exactly two causes: retrieval genuinely improved,
# which is C22's goal and must not go red, or the definition of a correct hit
# got looser. The second cause is now observable at its source and in the
# direction it moved, so an upper bound on recall would add no detection and
# would fire on the outcome the task is trying to produce. Inflating recall by
# loosening the rule REQUIRES merging two wordings that used to differ, and
# every such merge lowers COLLAPSE_CARDINALITY: the increase is caught before
# it reaches this ratchet, by a check that names the cause instead of the
# symptom.
RECALL_FLOOR = {1: 34, 5: 93, 10: 120}

#: Rows whose gold wording the shipped engine surfaces at no rank at all, same
#: scope. Recorded so a later filter experiment cannot raise it unnoticed; it may
#: only go DOWN.
GOLD_EXCLUDED_CEILING = 18

FIXTURE_ROWS = 224

#: Rows whose gold item the shipped engine ranks FIRST and which still come back
#: `low_confidence`. MEASURED 2026-09-02 over the build below: 9 of 34, every one
#: of them below the floor with a correct top hit, because the researcher's words
#: carry terms this instrument never prints and an unsatisfiable term takes the
#: largest possible share of the score's denominator.
#:
#: A CEILING: it may only go DOWN. It is here because C16's rewrite stage asked
#: whether it could stop rephrasing when the label says `ok`, and this number is
#: the answer — on a quarter of the rows where retrieval already did its job
#: perfectly, the label says otherwise. The mechanism is pinned in
#: `tests/test_search_scoring.py::
#: test_a_word_the_instrument_never_prints_depresses_a_correct_top_hit`.
RANK1_LOW_CONFIDENCE_CEILING = 9

# The build every number in this file was measured over, printed by `python
# build.py`. Pinned so a rebuilt dictionary reports itself as a rebuild rather
# than surfacing as a recall regression blamed on C22's deletions.
# Re-derived 2026-09-02 against d7a70c5014c5, which differs from
# 6fcd02755bf3 only by BUILD_RULES_VERSION and the two identifier
# columns. Every number above was re-measured and NONE moved:
# recall 34/93/120, gold excluded 18, collapse cardinality 1863,
# fixture drift 0. The columns touch no text the index reads.
DICTIONARY_BUILD = "3dc8415eccfe"

# MEASURED 2026-08-31 over that build: the dictionary's 2,804 entries hold 1,863
# distinct wordings once the roster index is stripped. This is the gold rule's
# resolution, and it is the ONLY guard on the scorer's borrowed definition of
# correctness — see `ev.collapse_cardinality`. RECALL_FLOOR below is one-sided
# and cannot see a rule that got looser; this can, in both directions.
DICTIONARY_ENTRIES = 2804
COLLAPSE_CARDINALITY = 1863


@pytest.fixture(scope="module")
def report() -> ev.RecallReport:
    return ev.evaluate()


@pytest.fixture(scope="module")
def rendered(report: ev.RecallReport) -> str:
    return ev.format_report(report)


# --------------------------------------------------------------------------- #
# what "correct" means, pinned before anything counts how often it happened
# --------------------------------------------------------------------------- #

def test_the_dictionary_under_test_is_the_one_the_numbers_were_measured_over():
    assert tools.dictionary_version() == DICTIONARY_BUILD, (
        f"The dictionary was REBUILT: {tools.dictionary_version()}, not "
        f"{DICTIONARY_BUILD}. Every number in this file — RECALL_FLOOR, "
        f"GOLD_EXCLUDED_CEILING, COLLAPSE_CARDINALITY, FIXTURE_ROWS — was "
        f"measured over the old build and none of them is evidence about the "
        f"new one. This is not a retrieval regression and not C22's doing: "
        f"re-measure them and regenerate the fixture, whose recorded wordings "
        f"are pinned to the old build too.")


def test_the_collapse_normalisation_has_not_been_redefined():
    """The gold rule's resolution, pinned so a looser rule cannot mint recall.

    THE HOLE THIS CLOSES, reproduced 2026-08-31 against the shipped code by
    substituting a normalisation that strips the roster index and then truncates
    to 25 characters — a stand-in for a "simplified" collapse key in the C22
    rewrite: @1 34 -> 52, @5 93 -> 131, @10 120 -> 155, gold excluded 18 -> 12.
    Both ratchets below stayed GREEN (155 >= 120, 12 <= 18) while wrong items
    were being counted as gold. This count went 1,863 -> 451.
    """
    entries = len(tools._load()["entries"])
    got = ev.collapse_cardinality()
    # Only the direction that actually happened is printed. A message offering
    # the reader both readings of one number makes them do the comparison the
    # test just did, and the wrong half reads as a contradiction.
    direction = (
        f"FEWER wordings ({got} < {COLLAPSE_CARDINALITY}) — the rule got "
        f"LOOSER. Items that were different questions now score as the same "
        f"one, so recall rises on WRONG hits while the one-sided floor below "
        f"stays green and offers to be raised to the inflated figure."
        if got < COLLAPSE_CARDINALITY else
        f"MORE wordings ({got} > {COLLAPSE_CARDINALITY}) — the rule got "
        f"TIGHTER. True hits are now scored as misses, and the floor below "
        f"will fail next and name C22's deletions for a scoring change."
        if got > COLLAPSE_CARDINALITY else
        f"The wording count is unchanged but the dictionary now holds "
        f"{entries} entries, not {DICTIONARY_ENTRIES}.")
    assert (entries, got) == (DICTIONARY_ENTRIES, COLLAPSE_CARDINALITY), (
        f"THE COLLAPSE NORMALISATION CHANGED. {entries} dictionary entries now "
        f"hold {got} distinct wordings under the gold rule; when every recall "
        f"figure in this file was measured it was {DICTIONARY_ENTRIES} entries "
        f"-> {COLLAPSE_CARDINALITY} wordings. `ev.normalise` delegates to "
        f"`env.tools._ROSTER_INDEX`, the same normalisation `search_variables` "
        f"collapses with, so a C22 edit to the collapse changes what this "
        f"scorer counts as a CORRECT HIT. This is that change; it is not a "
        f"retrieval regression and not a fixture problem.\n"
        f"  {direction}\n"
        f"The old and new recall figures are not on the same scale. Re-measure "
        f"RECALL_FLOOR and GOLD_EXCLUDED_CEILING under the new rule before "
        f"comparing them to anything.")


#: (raw searchable text, what the gold rule must leave of it, what a failure
#: means). Written HERE, by hand, NOT derived from `env.tools` — that is the
#: whole point. `ev.normalise` borrows its definition from the file C22
#: rewrites, so every other check in this file moves with the thing it checks.
#: The cardinality pin above catches any merge or split; these name WHICH
#: broadening happened, in the message, so the red is not argued away as a
#: fixture number that moved.
NORMALISATION_CASES = [
    ("3 - What is your age?", "What is your age?",
     "a leading roster index is no longer stripped — the collapse this scorer "
     "and search_variables share has stopped collapsing roster repeats"),
    ("  12 -   Blood pressure ", "Blood pressure",
     "the roster index plus surrounding whitespace is no longer stripped"),
    ("What is your age?", "What is your age?",
     "text carrying no roster index was altered anyway"),
    ("What Is Your AGE?", "What Is Your AGE?",
     "the collapse now CASEFOLDS: two wordings that differ in case are being "
     "scored as the same question"),
    ("Do you smoke, ever?", "Do you smoke, ever?",
     "the collapse now STRIPS PUNCTUATION: wordings that differ only in "
     "punctuation are being scored as the same question"),
    ("Section 3 - a heading", "Section 3 - a heading",
     "an index that is not at the START of the text is now being stripped"),
    ("In the last 12 months, how often did you have trouble paying for the "
     "things you needed, such as food, rent or medicine?",
     "In the last 12 months, how often did you have trouble paying for the "
     "things you needed, such as food, rent or medicine?",
     "the collapse now TRUNCATES: long wordings sharing a prefix are being "
     "scored as the same question"),
]


@pytest.mark.parametrize(("raw", "expected", "defect"), NORMALISATION_CASES)
def test_the_collapse_strips_a_roster_index_and_does_nothing_else(raw, expected,
                                                                  defect):
    assert ev.normalise(raw) == expected, (
        f"THE COLLAPSE NORMALISATION CHANGED: {defect}. Given {raw!r} the gold "
        f"rule must yield {expected!r} and yielded {ev.normalise(raw)!r}. That "
        f"redefines a correct hit for every recall figure in this file.")


def test_two_wordings_that_differ_only_in_case_stay_two_questions():
    """The case above stated as the property it protects, not as a string."""
    assert ev.normalise("Have you ever smoked?") != \
        ev.normalise("have you ever smoked?"), (
        "THE COLLAPSE NORMALISATION CHANGED: it now casefolds, so two distinct "
        "dictionary wordings score as one gold item and recall counts a hit on "
        "the wrong one.")


# --------------------------------------------------------------------------- #
# the C22 gate itself
# --------------------------------------------------------------------------- #

def test_recall_is_a_ratchet_that_c22_cannot_lower(report):
    assert report.n_queries == FIXTURE_ROWS
    for k, floor in sorted(RECALL_FLOOR.items()):
        got = report.hits_at(k)
        assert got >= floor, (
            f"recall@{k} fell to {got}/{report.n_queries} from the {floor} "
            f"measured before C22's deletions. C22's acceptance is 'recall@10 not "
            f"down'; this is that gate. Scope: {report.scope}")
        if got > floor:
            print(f"RECALL_FLOOR[{k}] can be raised {floor} -> {got}")


def test_gold_exclusion_is_a_ratchet_that_only_goes_down(report):
    assert report.gold_excluded <= GOLD_EXCLUDED_CEILING, (
        f"{report.gold_excluded}/{report.n_queries} rows now have the gold item "
        f"at no rank at all, up from {GOLD_EXCLUDED_CEILING}. Recall can hold "
        f"steady while this rises; that is the 2026-08-30 target-filter failure.")


# --------------------------------------------------------------------------- #
# the gold rule: wording equality, not key equality
# --------------------------------------------------------------------------- #

def _a_gold_key_with_a_roster_sibling() -> tuple[str, str]:
    """A fixture gold key and another key whose wording differs only by roster.

    Grouped with `env.tools`' own regex, NOT with `ev.normalised_text`. Deriving
    the pair from the function under test made this test pass with the roster
    strip deleted — the mutation moved both sides of the comparison together, so
    the check could not fail. Found by mutation on 2026-08-31, not by reading.
    The pair is required to differ in RAW text, so the strip is what makes them
    equal and nothing else can.
    """
    fx = ev.load_fixture()
    raw = {e["key"]: e["searchable_text"] for e in tools._load()["entries"]}
    by_wording: dict[str, list[str]] = {}
    for key, text in raw.items():
        stripped = tools._ROSTER_INDEX.sub("", text).strip()
        by_wording.setdefault(stripped, []).append(key)
    for row in fx.queries:
        siblings = by_wording[tools._ROSTER_INDEX.sub("", raw[row.key]).strip()]
        other = next((k for k in siblings
                      if k != row.key and raw[k] != raw[row.key]), None)
        if other is not None:
            return row.key, other
    pytest.skip("no fixture gold item has a roster sibling in this dictionary")


def test_a_collapsed_roster_sibling_counts_as_a_hit():
    """The fixture's gold_rule is wording equality, NOT key equality.

    MEASURED 2026-08-31: on the fixture as committed the two rules agree on all
    224 rows, so the fixture alone cannot tell them apart and cannot enforce the
    rule. This exercises it by construction instead: a search returning the
    SIBLING key must still score a hit. If it did not, every query whose collapse
    elected a different roster row would be scored a miss the day the collapse
    changed its representative.
    """
    gold_key, sibling = _a_gold_key_with_a_roster_sibling()
    assert sibling != gold_key
    assert ev.normalised_text(sibling) == ev.normalised_text(gold_key)

    fx = ev.load_fixture()
    row = next(q for q in fx.queries if q.key == gold_key)
    one_row = fx.model_copy(update={"queries": (row,)})

    def sibling_only(query: str, limit: int) -> dict:
        return {"hits": [{"key": sibling}], "outcome": "ok",
                "n_matched_items": 1}

    report = ev.evaluate(search=sibling_only, fixture=one_row)
    assert report.results[0].rank == 1, (
        "The evaluator scored a same-wording sibling as a miss, which is key "
        "equality, not the fixture's gold rule.")
    assert report.gold_excluded == 0


def test_a_different_wording_is_not_a_hit():
    """The rule is wording EQUALITY; a merely similar item must not count."""
    fx = ev.load_fixture()
    row = fx.queries[0]
    other = next(e["key"] for e in tools._load()["entries"]
                 if ev.normalised_text(e["key"]) != ev.normalised_text(row.key))
    one_row = fx.model_copy(update={"queries": (row,)})

    def wrong_item_only(query: str, limit: int) -> dict:
        return {"hits": [{"key": other}], "outcome": "ok", "n_matched_items": 1}

    report = ev.evaluate(search=wrong_item_only, fixture=one_row)
    assert report.results[0].rank is None
    assert report.gold_excluded == 1


def test_the_printed_gold_rule_is_the_rule_the_scorer_applies(report):
    """The fixture's sentence is printed in every report; pin it to behaviour.

    The module docstring calls the gold rule "the fixture's, verbatim" and the
    scope block prints the fixture's `gold_rule`, but `_score_row` hard-codes
    wording equality whatever that sentence says. Nothing compared the two.
    """
    assert " ".join(report.gold_rule.split()) == ev.GOLD_RULE
    assert report.gold_rule in ev.format_report(report)


def test_a_fixture_stating_a_rule_the_scorer_does_not_apply_is_refused(report):
    """Edit the sentence, and the report that would print it cannot be built."""
    with pytest.raises(ValueError, match="does not implement"):
        ev.RecallReport(
            fixture_path=report.fixture_path,
            dictionary_version=report.dictionary_version,
            known_bias=report.known_bias,
            gold_rule="a hit is correct when its key equals the target's",
            generator=report.generator,
            sample=report.sample,
            ks=report.ks,
            results=report.results,
            candidate_limit=report.candidate_limit,
            search_name=report.search_name,
            collapse_cardinality=report.collapse_cardinality,
            dictionary_entries=report.dictionary_entries)


def test_rewrapping_the_rules_whitespace_is_not_a_change_of_rule(report):
    """A guard that fires on a JSON rewrap gets disabled by whoever it annoys."""
    rewrapped = report.gold_rule.replace(" ", "\n  ", 1)
    assert rewrapped != report.gold_rule
    assert ev.RecallReport(**{**vars(report), "gold_rule": rewrapped})


def test_a_fixture_that_lost_its_gold_rule_is_refused():
    """The parallel of the KNOWN_BIAS refusal, seeded the way that one was.

    `min_length=1` on `gold_rule` had no test; the field beside it did.
    """
    raw = ev.load_fixture().model_dump(by_alias=True)
    raw["gold_rule"] = ""
    with pytest.raises(ValueError, match="gold_rule"):
        ev.QueryFixture.model_validate(raw)


def test_normalised_text_strips_only_the_roster_index():
    """`normalised_text` is the tool's own definition, not a second copy."""
    key = next(k for k, e in tools._BY_KEY.items()
               if tools._ROSTER_INDEX.match(e["searchable_text"]))
    raw = tools._BY_KEY[key]["searchable_text"]
    assert ev.normalised_text(key) == tools._ROSTER_INDEX.sub("", raw).strip()
    assert ev.normalised_text(key) != raw


def test_a_key_outside_the_dictionary_raises_rather_than_scoring_a_miss():
    with pytest.raises(KeyError, match="stale fixture"):
        ev.normalised_text("m9:Q0.0_does_not_exist")


# --------------------------------------------------------------------------- #
# fixture drift: a REWORDED key, not only a deleted one
# --------------------------------------------------------------------------- #

def test_every_fixture_row_records_the_wording_the_dictionary_still_holds():
    """`QueryRow.text` is read nowhere in the scoring path; this reads it.

    MEASURED 2026-08-31 over build 6fcd02755bf3: all 224 rows record the raw
    `searchable_text` character for character, so this check is free today and
    goes red the day a rebuild rewords one.
    """
    fx = ev.load_fixture()
    assert len(fx.queries) == FIXTURE_ROWS
    assert ev.fixture_drift(fx) == (), (
        "The committed fixture and the built dictionary no longer describe the "
        "same questions.")


def test_a_reworded_gold_item_is_refused_rather_than_scored():
    """The silent half of drift: the row still scores, against the wrong item.

    A deleted key already raised. A REWORDED one did not: the query was written
    for the old wording, so either the gold item is now unreachable and the
    recall ratchet goes red naming C22's deletions, or it is reachable and the
    row scores green against a question nobody asked.
    """
    fx = ev.load_fixture()
    row = fx.queries[0]
    stale = fx.model_copy(update={
        "queries": (row.model_copy(update={"text": row.text + " (2019 wording)"}),)})
    with pytest.raises(ValueError, match="FIXTURE DRIFT") as exc:
        ev.evaluate(fixture=stale)
    assert "not a retrieval regression" in str(exc.value).lower()
    assert row.key in str(exc.value)


# --------------------------------------------------------------------------- #
# KNOWN_BIAS must reach whoever reads the number
# --------------------------------------------------------------------------- #

def test_the_report_object_carries_the_fixtures_known_bias_verbatim(report):
    assert report.known_bias == ev.load_fixture().known_bias
    assert "UPPER BOUND" in report.known_bias.upper()


def test_the_banner_precedes_the_first_recall_figure(rendered, report):
    banner_at = rendered.index(ev.BIAS_BANNER)
    bias_at = rendered.index(report.known_bias)
    first_figure_at = rendered.index("recall@1")
    assert banner_at < bias_at < first_figure_at, (
        "A recall number rendered above its bias notice is a number that gets "
        "quoted without one.")


def test_a_report_without_a_bias_notice_cannot_be_constructed(report):
    with pytest.raises(ValueError, match="known_bias"):
        ev.RecallReport(
            fixture_path=report.fixture_path,
            dictionary_version=report.dictionary_version,
            known_bias="   ",
            gold_rule=report.gold_rule,
            generator=report.generator,
            sample=report.sample,
            ks=report.ks,
            results=report.results,
            candidate_limit=report.candidate_limit,
            search_name=report.search_name,
            collapse_cardinality=report.collapse_cardinality,
            dictionary_entries=report.dictionary_entries)


def test_a_fixture_that_lost_its_bias_field_is_refused():
    raw = ev.load_fixture().model_dump(by_alias=True)
    raw["KNOWN_BIAS"] = ""
    with pytest.raises(ValueError, match="KNOWN_BIAS"):
        ev.QueryFixture.model_validate(raw)


# --------------------------------------------------------------------------- #
# an unstated denominator is not a number
# --------------------------------------------------------------------------- #

def test_every_recall_line_states_its_denominator(rendered, report):
    for k in report.ks:
        assert f"recall@{k}" in rendered
    for line in rendered.splitlines():
        if line.startswith(("recall@", "gold excluded")):
            assert f"/{FIXTURE_ROWS}" in line, f"no denominator on: {line!r}"


def test_the_rendering_states_the_gold_rules_resolution(rendered, report):
    """The gold rule's sentence does not say how many questions it tells apart.

    Two recall figures scored under different collapses are not on the same
    scale, and nothing else in the report says which collapse produced this one.
    """
    assert report.collapse_cardinality == ev.collapse_cardinality()
    assert (f"{report.dictionary_entries} entries -> "
            f"{report.collapse_cardinality} distinct wordings") in rendered, (
        "The report renders its gold rule without its resolution, so the "
        "number can be compared to one scored under a different rule.")


def test_the_scope_names_the_fixture_that_was_actually_scored(report):
    """A subset scored 40 rows and the scope line named the committed 224.

    This module's own scope block exists because "an unstated denominator is not
    a number". A MISstated one is worse: an experiment renders a report naming
    `benchmark/fixtures/retrieval_queries.json` and the reader reproduces it
    against 224 rows that were never searched.
    """
    fx = ev.load_fixture()
    subset = ev.evaluate(fixture=fx.model_copy(update={"queries": fx.queries[:8]}))
    assert subset.n_queries == 8
    assert "retrieval_queries.json" not in subset.fixture_path, (
        "A caller-supplied 8-row fixture rendered a scope line naming the "
        "committed 224-row file.")
    assert subset.fixture_path == ev.UNNAMED_FIXTURE
    assert ev.UNNAMED_FIXTURE in ev.format_report(subset)

    # A caller that DOES know where its rows came from can say so.
    named = ev.evaluate(fixture=fx, fixture_path=ev.FIXTURE)
    assert named.fixture_path == report.fixture_path == \
        "benchmark/fixtures/retrieval_queries.json"


def test_the_scope_names_the_glob_the_filter_and_the_definition(rendered, report):
    for required in ("retrieval_queries.json", "filter", "gold rule",
                     report.gold_rule, report.dictionary_version,
                     f"limit={report.candidate_limit}"):
        assert required in rendered, f"scope does not state {required!r}"


# --------------------------------------------------------------------------- #
# gold exclusion, reported beside recall whether an experiment wants it or not
# --------------------------------------------------------------------------- #

def test_gold_excluded_is_rendered_beside_recall(rendered, report):
    line = next(x for x in rendered.splitlines() if x.startswith("gold excluded"))
    assert f"{report.gold_excluded}/{report.n_queries}" in line


def test_a_filter_that_drops_the_gold_item_is_caught_by_gold_excluded():
    """The 2026-08-30 trap, made impossible to report without.

    A target filter measured +5 recall by reading the gold item's own label, and
    supplied from the query alone it deleted the right answer on 9.8% of queries.
    An experiment that plugs its own search in here gets that rate whether it
    asked for it or not.
    """
    fx = ev.load_fixture()
    subset = fx.model_copy(update={"queries": fx.queries[:40]})

    def strict_and_search(query: str, limit: int) -> dict:
        """Keep only hits whose wording covers every term searched."""
        out = tools.search_variables(query, limit)
        terms = out["query_terms"]
        out["hits"] = [h for h in out["hits"]
                       if len(h["matched_terms"]) == len(terms)]
        return out

    base = ev.evaluate(fixture=subset)
    filtered = ev.evaluate(search=strict_and_search, fixture=subset)

    assert filtered.gold_excluded > base.gold_excluded, (
        "A strictly narrower candidate set did not raise gold_excluded, so this "
        "metric is not measuring exclusion.")
    assert filtered.search_name == "strict_and_search"
    assert "gold excluded" in ev.format_report(filtered)


# --------------------------------------------------------------------------- #
# the assumptions recall@k rests on
# --------------------------------------------------------------------------- #

def test_the_candidate_limit_cannot_truncate_the_dictionary():
    assert ev.candidate_limit() == len(tools._load()["entries"])


def test_slicing_a_deep_search_equals_searching_at_that_limit():
    """recall@k slices one deep call; that is only valid if the prefix is stable."""
    fx = ev.load_fixture()
    for row in fx.queries[:40]:
        deep = tools.search_variables(row.query, ev.candidate_limit())["hits"]
        for k in (1, 5, 10):
            shallow = tools.search_variables(row.query, k)["hits"]
            assert [h["key"] for h in deep[:k]] == [h["key"] for h in shallow], (
                f"limit={k} returns a different prefix than the deep call for "
                f"{row.query!r}; recall@k computed by slicing would be wrong.")


def test_the_same_input_gives_the_same_number_every_run():
    fx = ev.load_fixture()
    subset = fx.model_copy(update={"queries": fx.queries[:60]})
    first = ev.evaluate(fixture=subset)
    second = ev.evaluate(fixture=subset)
    assert first.results == second.results
    assert ev.format_report(first) == ev.format_report(second)


def test_evaluating_does_not_leave_its_searches_in_the_run_tool_log():
    """224 measurement searches must not appear in a run's audit trail."""
    tools.search_variables("marital status")
    before = list(tools.LOG.calls)
    fx = ev.load_fixture()
    ev.evaluate(fixture=fx.model_copy(update={"queries": fx.queries[:5]}))
    assert tools.LOG.calls == before


# --------------------------------------------------------------------------- #
# per-query detail: C22's deletions have to be diagnosed, not only scored
# --------------------------------------------------------------------------- #

def test_misses_name_the_query_that_missed(report):
    misses = report.misses(10)
    assert len(misses) == report.n_queries - report.hits_at(10)
    assert all(m.rank is None or m.rank > 10 for m in misses)
    assert all(m.query and m.key for m in misses)
    assert {m.rank for m in misses} != {None}


def test_every_fixture_row_is_scored_and_none_is_filtered_out(report):
    fx = ev.load_fixture()
    assert [(r.key, r.query) for r in report.results] == \
           [(q.key, q.query) for q in fx.queries]


def test_the_rendered_misses_list_is_addressable(rendered, report):
    for miss in report.misses(10)[:5]:
        assert miss.query in rendered
    assert f"misses at @10 — {len(report.misses(10))} row(s)" in rendered


# --------------------------------------------------------------------------- #
# the confidence label on rows retrieval already answered
# --------------------------------------------------------------------------- #

def test_the_confidence_label_is_not_a_stopping_signal_on_a_rank_one_row(report):
    """A rewrite stage cannot rephrase until the label says `ok`.

    Anti-vacuity first: the denominator is the rows the engine already ranks
    first, and if that set shrank below the recall floor this measures something
    else. Then the ceiling, one-sided — a rise means MORE correct answers are
    being labelled low-confidence, which widens the trap; a fall is the label
    getting more honest and must not go red.
    """
    rank1 = [o for o in report.results if o.rank == 1]
    assert len(rank1) >= RECALL_FLOOR[1], (
        f"only {len(rank1)} rows rank their gold item first; the recall floor "
        f"says at least {RECALL_FLOOR[1]}, so this row set is not the one the "
        f"ceiling was measured over")
    flagged = [o for o in rank1 if o.outcome != "ok"]
    assert len(flagged) <= RANK1_LOW_CONFIDENCE_CEILING, (
        f"{len(flagged)} of {len(rank1)} rank-1 rows are labelled "
        f"{sorted({o.outcome for o in flagged})}, up from "
        f"{RANK1_LOW_CONFIDENCE_CEILING}: "
        + ", ".join(f"{o.key} {o.query!r}" for o in flagged[:4]))
    if len(flagged) < RANK1_LOW_CONFIDENCE_CEILING:
        print(f"\nRANK1_LOW_CONFIDENCE_CEILING can be lowered to {len(flagged)}")
