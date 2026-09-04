"""Regression fixture for `env/tools.py::search_variables`' scoring and floor.

Fully hermetic: no model call, no network, no live run. Everything here is a
re-derivation of the numbers written into `search_variables`' docstring, so the
docstring's calibration table cannot drift away from the code silently — which
is how three documents in this project went stale.

WHAT THIS FIXTURE EXISTS TO PIN. On 2026-08-27 a live run made six distinct
attempts to find the participant's age. Every one came back n=10 with a
mother's- or sibling's-birth-year item on top, and nothing in the return value
let the model tell a good hit from a bad one. The six phrases are pinned below
verbatim from `run/m3q16.1_to_m2q5.8.07c23aff60ad3c7f.tool_log.jsonl`.

The docstring's own sentence — "every number here is re-derived by this file" —
was itself unenforced when it was written: five of its twenty numbers were
asserted nowhere. `test_every_numbered_docstring_row_is_pinned_here` now closes
the loop by parsing the table out of the docstring and demanding an exact match
against the constants below, in both directions.
"""

import re

import pytest

from agent.registry import SCHEMAS
from env.tools import SEARCH_SCORE_FLOOR, search_variables

# The instrument DOES hold the target: two modules print "What is your birthday?"
# as a Month/Day/Year triple. So the fixture's expected answer is not "empty" —
# every failure below is a ranking or vocabulary failure, not an absence.
ACCEPTABLE_AGE_KEYS = frozenset({
    "m1:Q2.15_1", "m1:Q2.15_2", "m1:Q2.15_3",
    "m3:Q1.7_1", "m3:Q1.7_2", "m3:Q1.7_3",
})

# Verbatim from the live tool log named in the module docstring.
AGE_QUERIES = (
    "age years born",
    "participant age how old you",
    "date born when were you born",
    "what year born 1900 1950 2000",
    "m1 age demographics years",
    "currently are you how many currently years old",
)

# The one query lexical scoring gets confidently wrong. Pinned as a KNOWN
# LIMITATION rather than fitted around: for this phrase the mother's-birth-year
# item covers 100% of the query's content terms and IS the honest best lexical
# match. No floor rejects it while still admitting 'blood pressure medication'
# (measured 1.000 below). The remedy is the agent-side screening stage over
# these scored candidates — outside env/, outside this tool, and outside this
# test, which is what keeps this fixture hermetic.
KNOWN_LIMITATION = "what year born 1900 1950 2000"

# (phrase, top-hit score) measured 2026-08-30. Known-good: the top hit is a
# defensible candidate for the phrase. These calibrate the floor from below.
CONTROL_GOOD = (
    ("what is your birthday", 1.000),
    ("yearly household income", 1.000),
    ("blood pressure medication", 1.000),
    ("phone number", 1.000),
    ("marital status", 1.000),
    ("high blood pressure", 1.000),
    ("how many years lived at your current address", 1.000),
    ("sex male female gender", 0.740),
    ("blood pressure medication treatment", 0.692),
    ("depression sad hopeless", 0.623),
    ("physical activity exercise", 0.574),
    ("income money household", 0.569),      # lowest known-good
)

# Known-bad: the top hit is a vocabulary accident. 'green space' matches an item
# about a phone number on the word "spaces"; 'social cohesion' matches one about
# a social security number. These calibrate the floor from above.
CONTROL_BAD = (
    ("green space", 0.477),                 # highest known-bad
    ("social cohesion", 0.463),
)

# The floor's measured cost, pinned so it stays stated rather than forgotten:
# these top hits are defensible and still land below it. Below-floor results
# keep returning their hits, so the cost is a label, not a lost candidate.
CONTROL_CONSERVATIVE = (
    ("body mass index weight height", 0.203),
    ("stress worried anxious", 0.333),
)

CONTROL_EMPTY = "zzzqqq xyzzyx plughq"

# The six age queries' top-hit scores, re-measured 2026-08-30 after the variable
# key was taken out of the index. Pinned because the docstring prints them and
# `test_every_numbered_docstring_row_is_pinned_here` refuses any printed number
# that no constant here re-derives: four of these six sat in that table with
# nothing asserting them, inside the docstring whose own sentence claimed
# otherwise.
AGE_SCORES = (
    ("currently are you how many currently years old", 0.704),
    ("age years born", 0.676),
    ("participant age how old you", 0.498),
    ("date born when were you born", 0.465),
    ("m1 age demographics years", 0.322),
    ("what year born 1900 1950 2000", 1.000),
)

#: Ratchets on the age-ranking failure this fixture records, measured
#: 2026-08-30. They may only IMPROVE, and the tests below fail only when they
#: get WORSE. The earlier form asserted the opposite — that no age query may put
#: an acceptable item first — so the day ranking got good enough to do it, a red
#: test would have announced the goal of acceptance (b) as a regression, and
#: whoever it annoyed would have deleted it.
#: How many of the six reach an acceptable birthday item anywhere in the page.
AGE_QUERIES_REACHING_AN_ACCEPTABLE_ITEM = 1
#: Best (lowest) position an acceptable item takes over the six. 1 would mean
#: the ranking failure had closed.
BEST_ACCEPTABLE_POSITION = 9


def _top(phrase: str) -> tuple[dict, dict | None]:
    r = search_variables(phrase=phrase)
    return r, (r["hits"][0] if r["hits"] else None)


# --------------------------------------------------------------------------- #
# the score itself
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("phrase", [p for p, _ in CONTROL_GOOD + CONTROL_BAD
                                    + CONTROL_CONSERVATIVE] + list(AGE_QUERIES))
def test_every_hit_carries_a_bounded_score_and_its_decomposition(phrase):
    """Acceptance (a): a per-hit score, and enough to see WHY it is that score.

    Raw BM25 is unbounded and query-dependent, so it cannot be thresholded
    across queries. The normalised score can be, and the decomposition is what
    makes a miss readable rather than a number to squint at.
    """
    r = search_variables(phrase=phrase)
    for h in r["hits"]:
        assert 0.0 <= h["score"] <= 1.0, h
        assert set(h["matched_terms"]) | set(h["missed_terms"]) == set(r["query_terms"])
        assert not set(h["matched_terms"]) & set(h["missed_terms"])
        assert isinstance(h["bm25"], float)          # raw rank reported, not hidden
        # On the value RETURNED. See test_below_threshold_is_flagged_on_the
        # _score_returned_not_the_unrounded_one for why that is not incidental.
        assert h["below_threshold"] is (h["score"] < SEARCH_SCORE_FLOOR)
        # The definition in the docstring, checked against the code: 1.0 means
        # the wording contains every term searched, and nothing else does.
        assert (h["score"] == 1.0) is (h["missed_terms"] == [])


# Queries where sqlite's BM25 order and the score order DISAGREE inside the
# returned page. Chosen by measurement: on most phrases BM25 already happens to
# be score-monotone, so a test over those cannot fail when the re-rank is
# deleted, which is exactly what happened to the first draft of this test.
REORDERED = ("currently are you how many currently years old",
             "blood pressure medication",
             "sex male female gender")


@pytest.mark.parametrize("phrase", REORDERED)
def test_hits_are_re_ranked_by_score_not_left_in_bm25_order(phrase):
    r = search_variables(phrase=phrase)
    scores = [h["score"] for h in r["hits"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == max(scores)


def test_the_re_rank_changes_which_hit_leads():
    """Pinned so deleting the re-rank cannot pass as a no-op.

    Left in BM25 order this query's page leads with m2:Q7.2 at 0.522 —
    re-measured 2026-08-30, and now BELOW the floor as well; re-ranked it leads
    with 0.704. It is one of the six the live run actually issued.
    """
    top = _top("currently are you how many currently years old")[1]
    assert top["score"] == pytest.approx(0.704, abs=0.001)


# --------------------------------------------------------------------------- #
# the floor
# --------------------------------------------------------------------------- #

def test_the_floor_sits_in_the_measured_gap_between_good_and_bad():
    """The floor is a measurement, not a constant somebody liked.

    If this goes red, the separating interval moved and the constant has to be
    re-derived from the new measurement — not nudged until the test passes.
    """
    best_bad = max(s for _, s in CONTROL_BAD)
    worst_good = min(s for _, s in CONTROL_GOOD)
    assert best_bad < SEARCH_SCORE_FLOOR < worst_good, (
        f"floor {SEARCH_SCORE_FLOOR} is outside the measured gap "
        f"({best_bad}, {worst_good})")


def test_the_floor_is_the_midpoint_the_docstring_says_it_is():
    """The constant said 0.52 and called itself the midpoint of (0.477, 0.569).

    The midpoint is 0.523. "Sits in the gap" was true and tested; "is the
    midpoint" was neither, and a false number in a docstring is the cheapest
    version of this codebase's signature failure. Pick one: move the constant or
    delete the word. This asserts the word.
    """
    best_bad = max(s for _, s in CONTROL_BAD)
    worst_good = min(s for _, s in CONTROL_GOOD)
    assert SEARCH_SCORE_FLOOR == pytest.approx((best_bad + worst_good) / 2,
                                               abs=0.0005), (
        f"floor {SEARCH_SCORE_FLOOR} is not the midpoint of "
        f"({best_bad}, {worst_good}); either move it or stop calling it one")


def test_every_numbered_docstring_row_is_pinned_here():
    """`search_variables`' docstring claims this file re-derives every number.

    It did not: 'physical activity exercise' appeared in no test at all, and
    four of the six age scores were printed and asserted nowhere. A claim
    broader than its test is the defect this project keeps finding, so the claim
    is now structural — the table is parsed out of the docstring and compared
    both ways against the constants above.
    """
    doc = search_variables.__doc__
    assert doc is not None
    printed = {(m.group(1), float(m.group(2))) for m in re.finditer(
        r"^\s+'(.+?)'\s+([01]\.\d{3})\s*$", doc, re.MULTILINE)}
    pinned = set(CONTROL_GOOD) | set(CONTROL_BAD) | set(
        CONTROL_CONSERVATIVE) | set(AGE_SCORES)
    assert printed == pinned, (
        f"docstring rows no test pins: {sorted(printed - pinned)}; "
        f"pinned rows the docstring no longer prints: {sorted(pinned - printed)}")
    # The one row in the table carrying no number still has to mean something.
    assert f"'{CONTROL_EMPTY}'" in doc


def test_below_threshold_is_flagged_on_the_score_returned_not_the_unrounded_one():
    """Latent, and it would have been reported as an invariant violation.

    The top hit for 'income money household' scores 0.5688707… and is returned
    as 0.569. With the floor at 0.569 the unrounded comparison flags it
    below_threshold while returning `score == score_floor` — self-contradictory,
    and red against the bounded-score invariant, which asserts on the rounded
    value. Flag on what you return.
    """
    import env.tools

    original = env.tools.SEARCH_SCORE_FLOOR
    try:
        env.tools.SEARCH_SCORE_FLOOR = 0.569
        top = _top("income money household")[1]
        assert top is not None
        assert top["score"] == 0.569
        assert top["below_threshold"] is False, (
            "flagged below a floor equal to the score returned")
        assert top["below_threshold"] is (top["score"] < 0.569)
    finally:
        env.tools.SEARCH_SCORE_FLOOR = original


@pytest.mark.parametrize(("phrase", "expected"), CONTROL_GOOD)
def test_known_good_control_queries_score_at_or_above_the_floor(phrase, expected):
    r, top = _top(phrase)
    assert top is not None
    assert top["score"] == pytest.approx(expected, abs=0.001)
    assert r["outcome"] == "ok"
    assert top["below_threshold"] is False


@pytest.mark.parametrize(("phrase", "expected"), CONTROL_BAD)
def test_known_bad_control_queries_are_flagged_low_confidence(phrase, expected):
    """Below the floor the caller cannot mistake the result for a confident find.

    The hits are still RETURNED — a tool that hides a weak hit is a tool that
    cannot be second-guessed — but the outcome word and every hit's flag say
    what they are.
    """
    r, top = _top(phrase)
    assert top is not None
    assert top["score"] == pytest.approx(expected, abs=0.001)
    assert r["outcome"] == "low_confidence"
    assert all(h["below_threshold"] for h in r["hits"])
    assert "LOW-CONFIDENCE CANDIDATES" in r["log"]


def test_a_below_floor_hit_is_described_as_a_candidate_not_as_an_absence():
    """The log used to call a below-floor page a NON-ANSWER. It is not one.

    This module's own position, asserted by
    `test_the_floors_measured_cost_is_a_label_not_a_lost_candidate`, is that the
    floor costs a label and never a candidate — and on the known-limitation
    query the ONLY defensible item on the page is below the floor. Telling the
    model that such a page "found nothing" instructs it to discard the one item
    the duplicate collapse worked to surface.
    """
    log = search_variables(phrase="green space")["log"]
    assert "LOW-CONFIDENCE CANDIDATES" in log
    assert "screen" in log.lower()
    assert "NON-ANSWER" not in log
    assert "found nothing" not in log
    assert "is NOT a find" not in log
    # the guarantee that had to survive the reframing
    assert "cannot tell you whether the instrument holds the construct" in log


@pytest.mark.parametrize(("phrase", "expected"), CONTROL_CONSERVATIVE)
def test_the_floors_measured_cost_is_a_label_not_a_lost_candidate(phrase, expected):
    """These are the queries the floor is wrong about, and it still shows them."""
    r, top = _top(phrase)
    assert top is not None
    assert top["score"] == pytest.approx(expected, abs=0.001)
    assert r["outcome"] == "low_confidence"
    assert r["n"] > 0, "a below-floor result must still return its candidates"


def test_nonsense_returns_an_explicit_nothing():
    r = search_variables(phrase=CONTROL_EMPTY)
    assert r["outcome"] == "no_match"
    assert r["n"] == 0
    assert r["hits"] == []
    assert r["terms_matched_by_no_hit"] == ["zzzqqq", "xyzzyx", "plughq"]


# --------------------------------------------------------------------------- #
# the six age queries — the regression fixture proper
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("phrase", AGE_QUERIES)
def test_each_age_query_reports_what_its_top_hit_missed(phrase):
    """Acceptance (b), to the extent lexical scoring can honestly reach it.

    The property asserted is the one the tool can actually guarantee: whatever
    comes back, the caller is told which of its own search terms the top hit
    does NOT contain. That is what was absent in the live run — the model
    re-queried six times because every answer looked the same.
    """
    r, top = _top(phrase)
    assert top is not None
    assert "missed_terms" in top
    assert set(top["missed_terms"]) <= set(r["query_terms"])


@pytest.mark.parametrize(("phrase", "expected"), AGE_SCORES)
def test_each_age_query_scores_what_the_docstring_says_it_scores(phrase, expected):
    """The six numbers the docstring prints, re-derived.

    Four of them were printed and asserted nowhere until 2026-08-30, inside a
    docstring whose own sentence said this file re-derived all of them.
    """
    top = _top(phrase)[1]
    assert top is not None
    assert top["score"] == pytest.approx(expected, abs=0.001)


@pytest.mark.parametrize("phrase", [p for p in AGE_QUERIES if p != KNOWN_LIMITATION])
def test_no_age_query_returns_a_confident_wrong_answer(phrase):
    """Never a confident, unqualified WRONG answer — for five of the six.

    Three ways to pass, one way to fail. Either the top hit is an acceptable
    birthday item (a right answer), or it is below the floor, or its own
    decomposition names a search term it does not contain. Red means a
    not-acceptable item came back at or above the floor with nothing missing —
    a confident wrong answer, which is the defect.

    The predecessor of this test also asserted `top["key"] not in
    ACCEPTABLE_AGE_KEYS`, which made ranking SUCCESS read as a regression. The
    ranking failure is still recorded — as a ratchet, in the two tests below —
    but a passing build is no longer required to keep committing it.
    """
    top = _top(phrase)[1]
    assert top is not None
    if top["key"] in ACCEPTABLE_AGE_KEYS:
        return                                    # acceptance (b) reached here
    assert top["below_threshold"] or top["missed_terms"], (
        f"{phrase!r} returned a top hit at score {top['score']} with nothing "
        f"flagged: that is a confident wrong answer")


def _acceptable_positions(phrase: str) -> list[int]:
    """1-based positions in the returned page that reach an acceptable item.

    A position counts if the acceptable key is the hit itself or was collapsed
    under it: the collapse is what put one inside the page at all, and a
    screening stage reads `collapsed_keys` too.

    Args:
        phrase: The search phrase to run.

    Returns:
        The positions, ascending; empty if the page reaches none.
    """
    r = search_variables(phrase=phrase)
    return [i for i, h in enumerate(r["hits"], 1)
            if ({h["key"]} | set(h["collapsed_keys"])) & ACCEPTABLE_AGE_KEYS]


def test_the_age_ranking_failure_is_ratcheted_not_asserted_as_correct():
    """The recorded size of the failure, in a form improvement cannot redden.

    Red here means FEWER of the six age queries reach an acceptable birthday
    item than on 2026-08-30 — a recall regression, which is a defect. More is
    better, and prints rather than fails.
    """
    reaching = [q for q in AGE_QUERIES if _acceptable_positions(q)]
    n = len(reaching)
    assert n >= AGE_QUERIES_REACHING_AN_ACCEPTABLE_ITEM, (
        f"only {n} of the six age queries now reach an acceptable item "
        f"({reaching}); it was {AGE_QUERIES_REACHING_AN_ACCEPTABLE_ITEM}. "
        f"Recall regressed — the duplicate collapse is the first thing to check.")
    if n > AGE_QUERIES_REACHING_AN_ACCEPTABLE_ITEM:
        print(f"\nAGE_QUERIES_REACHING_AN_ACCEPTABLE_ITEM can be raised to {n}")


def test_the_best_position_an_acceptable_item_reaches_is_ratcheted():
    """Position 9, measured 2026-08-30, and only allowed to get smaller.

    Position 1 would mean the ranking failure had closed; this test would pass
    and say so. Red means an acceptable item fell further down the page or off
    it — the collapse regressing, which is what put it inside the page.
    """
    best = min((pos for q in AGE_QUERIES for pos in _acceptable_positions(q)),
               default=None)
    assert best is not None, (
        "no age query reaches an acceptable item anywhere in its page")
    assert best <= BEST_ACCEPTABLE_POSITION, (
        f"the best acceptable position fell from {BEST_ACCEPTABLE_POSITION} to "
        f"{best}: the ranking regressed")
    if best < BEST_ACCEPTABLE_POSITION:
        print(f"\nBEST_ACCEPTABLE_POSITION can be lowered to {best}")


def test_the_known_limitation_is_pinned_and_not_papered_over():
    """KNOWN LIMITATION. Lexical scoring gets this one confidently wrong.

    'what year born 1900 1950 2000' scores a birth-year item about a relative at
    1.000 with nothing missed, because that item genuinely contains every
    content term the query has. No defensible lexical floor rejects it while
    still admitting 'blood pressure medication', also 1.000. THE REMEDY IS THE
    AGENT-SIDE SCREENING STAGE over these scored candidates, which lives outside
    env/ and is not built here — a passing test that hid this would be worse
    than a red one.

    What the rebuild did buy, and what this pins: collapsing near-duplicate
    roster repeats moves the acceptable item from position 32 under the old
    ordering into the returned page, flagged below the floor, where a screening
    stage can see it at all.
    """
    r = search_variables(phrase=KNOWN_LIMITATION)
    top = r["hits"][0]
    assert top["score"] == 1.0
    assert top["missed_terms"] == []
    # The limitation, stated as the property that is actually true: a 1.000 with
    # nothing missed is not evidence of a right answer. Asserting `top["key"]
    # not in ACCEPTABLE_AGE_KEYS` would demand the wrong answer stay wrong.
    assert top["below_threshold"] is False
    reachable = {h["key"] for h in r["hits"]} | {
        k for h in r["hits"] for k in h["collapsed_keys"]}
    assert reachable & ACCEPTABLE_AGE_KEYS, (
        "the acceptable item is no longer reachable in the returned page; the "
        "duplicate collapse that put it there has regressed")
    below = [h for h in r["hits"]
             if h["key"] in ACCEPTABLE_AGE_KEYS and h["below_threshold"]]
    assert below, "the acceptable item is no longer in the page as a flagged hit"
    # The reason the prompt may not call a below-floor page an absence: on this
    # query the one defensible item on the page IS below the floor.
    assert below[0]["score"] < SEARCH_SCORE_FLOOR


def test_the_positive_control_finds_the_birthday_items_first():
    """Acceptance (c): instrument vocabulary still finds what it should.

    Without this, every assertion above could be satisfied by a tool that
    returns nothing for everything.
    """
    r, top = _top("what is your birthday")
    assert r["outcome"] == "ok"
    assert top["key"] in ACCEPTABLE_AGE_KEYS
    assert top["score"] == 1.0
    assert top["below_threshold"] is False
    assert top["missed_terms"] == []


# --------------------------------------------------------------------------- #
# acceptance (d): a miss the caller can act on
# --------------------------------------------------------------------------- #

def test_the_silently_dropped_tokens_are_named():
    """The rewrite drops numerals and 1-2 character words. It used to do it silently.

    That silent drop is a defect in itself: one live query searched three years
    and was never told they had not been searched.
    """
    r = search_variables(phrase=KNOWN_LIMITATION)
    assert r["discarded_tokens"] == ["1900", "1950", "2000"]
    assert "DROPPED" in r["log"]
    for tok in ("1900", "1950", "2000"):
        assert tok in r["log"]
    assert r["query_terms"] == ["what", "year", "born"]


def test_a_phrase_with_nothing_tokenisable_says_no_search_ran():
    r = search_variables(phrase="   ...   ")
    assert r["outcome"] == "no_terms"
    assert r["n"] == 0
    assert "no search ran" in r["log"]


def test_a_sub_three_character_phrase_still_searches():
    """Searching a two-character phrase beats searching nothing at all.

    The three-character rule exists to stop 'is'/'of' dominating an OR; applied
    to a phrase that is ONLY short tokens it would silently search the empty
    query and return an empty result that reads like an absence finding.
    """
    r = search_variables(phrase="x")
    assert r["outcome"] != "no_terms"
    assert r["query_terms"] == ["x"]
    assert r["discarded_tokens"] == []


def test_an_fts_keyword_in_the_phrase_is_searched_not_executed():
    """Unquoted, 'AND' made the rewrite emit `"a" OR AND OR "b"` — a syntax error.

    The caller then got outcome 'error' for writing an ordinary English word.
    """
    r = search_variables(phrase="blood AND pressure")
    assert r["outcome"] != "error"
    assert r["effective_query"] == '"blood" OR "and" OR "pressure"'


def test_the_effective_query_that_actually_ran_is_shown():
    r = search_variables(phrase="green space")
    assert r["effective_query"] == '"green" OR "space"'
    assert r["effective_query"] in r["log"]


def test_terms_no_returned_hit_matched_are_named():
    r = search_variables(phrase="social cohesion")
    assert r["terms_matched_by_no_hit"] == ["cohesion"]
    assert "cohesion" in r["log"]


def test_the_log_says_what_a_low_or_empty_result_means_and_what_to_do():
    low = search_variables(phrase="green space")["log"]
    empty = search_variables(phrase=CONTROL_EMPTY)["log"]
    for log in (low, empty):
        assert "Re-query" in log
        assert "blocker" in log
    assert "resolve_variable() first" in low


def test_the_log_never_claims_the_instrument_lacks_a_construct():
    """Could not detect X is never X is absent, and this tool cannot say it.

    It has one corpus, one tokeniser and no notion of meaning. A log that let
    the model read an empty result as an absence finding would manufacture
    exactly the unearned assertion this project exists to catch.
    """
    for phrase in ("green space", CONTROL_EMPTY, "social cohesion"):
        log = search_variables(phrase=phrase)["log"]
        assert "no standing to make that claim" in log or "cannot tell you" in log
        assert "is absent from the instrument" not in log.replace(
            "It is NOT a finding that the construct is absent from the instrument", "")


def test_the_log_hardcodes_no_item_key_as_a_hint():
    """A hint naming a specific item is an answer key on a tool path.

    It would also be a fixture fit: the tool would 'work' for the one query
    somebody tuned it on and nowhere else.
    """
    for phrase in (*AGE_QUERIES, "what is your birthday", CONTROL_EMPTY):
        r = search_variables(phrase=phrase)
        keys_in_log = set(re.findall(r"m[123]:Q[\w.#_]+", r["log"]))
        assert not keys_in_log, keys_in_log


# --------------------------------------------------------------------------- #
# the score measures wording, and nothing else
# --------------------------------------------------------------------------- #

# Key-shaped phrases. `m1`/`m3` are module prefixes every key in that module
# carries, and a live run typed one of them into a search.
KEY_SHAPED = ("m1", "m3")


@pytest.mark.parametrize("phrase", KEY_SHAPED)
def test_a_variable_key_is_not_searchable_text(phrase):
    """The key column is UNINDEXED, so a term cannot be earned by the key.

    Until 2026-08-30 it was indexed and `search_variables(phrase='m1')` returned
    outcome ok, 142 items matched, every hit scored 1.000 — on the key prefix,
    with the word appearing in no wording anywhere. The schema description the
    model reads says the score is the share of its terms' information the
    WORDING covers, and the log says 1.0 means the item contains every term
    searched. Both were false on that path.
    """
    r = search_variables(phrase=phrase)
    assert r["outcome"] == "no_match"
    assert r["n_matched_items"] == 0
    assert r["hits"] == []


# Terms whose posting lists are checked against an independent index below.
# 'm1'/'m3' are the key prefixes; the rest are ordinary wording, present so a
# mutation that empties every posting list cannot pass this by returning nothing.
POSTING_TERMS = ("m1", "m3", "age", "born", "space", "green", "birthday", "q2")


def test_a_terms_postings_come_from_the_wording_and_only_the_wording():
    """df, and therefore idf, and therefore every score, rest on `_postings`.

    The main query and `_postings` have to agree on what is indexed; a
    divergence is the failure `_postings`' own docstring warns about, and with
    the key column indexed BOTH of them were wrong in the same direction, which
    is exactly the shape a same-index consistency check cannot see. So this
    rebuilds an index over `searchable_text` alone and demands an exact posting
    list match, term by term.
    """
    import sqlite3

    import env.tools as tools

    entries = tools._load()["entries"]
    ref = sqlite3.connect(":memory:")
    ref.execute("CREATE VIRTUAL TABLE w USING fts5(txt, tokenize='porter')")
    ref.executemany("INSERT INTO w(rowid, txt) VALUES (?,?)",
                    [(i, e["searchable_text"]) for i, e in enumerate(entries)])
    for term in POSTING_TERMS:
        want = {entries[r[0]]["key"] for r in ref.execute(
            "SELECT rowid FROM w WHERE w MATCH ?", (f'"{term}"',))}
        got = tools._postings(tools._fts(), term)
        assert got == want, (
            f"{term!r}: {len(got)} postings from the live index, {len(want)} "
            f"from an index over wording alone — the two disagree, so the idf "
            f"denominators do not describe the page they score")


# --------------------------------------------------------------------------- #
# a one-term query carries no confidence information
# --------------------------------------------------------------------------- #

# 'space' and 'x' are the reproduction: 'green space' is correctly flagged
# low_confidence at 0.477 on a phone-number item, and dropping the term no hit
# matched — which is what the log and the schema description both instructed —
# returns the SAME item at 1.000, outcome ok. 'neighborhood' is the phrase the
# contamination scan samples.
SINGLE_TERM_QUERIES = ("space", "x", "neighborhood", "birthday")


@pytest.mark.parametrize("phrase", SINGLE_TERM_QUERIES)
def test_a_single_term_query_is_never_presented_as_a_confident_find(phrase):
    """The floor is structurally unable to fire on one term.

    Every hit that matches the sole term covers the whole denominator and scores
    1.000, so `below_threshold` and `low_confidence` cannot happen. That made a
    correctly-flagged non-answer reachable, in one obeyed instruction, as an
    unflagged score-1.000 find.
    """
    r = search_variables(phrase=phrase)
    assert len(r["query_terms"]) == 1
    assert r["score_discriminates"] is False
    assert r["outcome"] != "ok"
    assert "SINGLE-TERM QUERY" in r["log"]
    assert "carry NO confidence information" in r["log"]


def test_dropping_the_unmatched_term_does_not_turn_a_flagged_miss_into_a_find():
    """The exact walk the tool's own advice used to invite.

    'green space' -> low_confidence, top hit 0.477, terms_matched_by_no_hit
    ['green']. Re-query without 'green', as instructed, and the same item came
    back outcome ok at 1.000. The item is the same one both times; only the
    label used to change.
    """
    wide = search_variables(phrase="green space")
    assert wide["outcome"] == "low_confidence"
    assert wide["terms_matched_by_no_hit"] == ["green"]
    narrow = search_variables(phrase="space")
    assert narrow["hits"][0]["key"] == wide["hits"][0]["key"]
    assert narrow["hits"][0]["score"] == 1.0
    assert narrow["outcome"] != "ok", (
        "narrowing to the one matched term turned a flagged miss into a "
        "confident find, which is what the log told the model to do")


def test_a_multi_term_query_still_gets_a_discriminating_score():
    """The guard must not swallow every query, only the degenerate one."""
    for phrase, _ in CONTROL_GOOD:
        r = search_variables(phrase=phrase)
        assert r["score_discriminates"] is True, phrase
        assert r["outcome"] == "ok", phrase


# --------------------------------------------------------------------------- #
# the mirror: a word the instrument does not use depresses a CORRECT answer
# --------------------------------------------------------------------------- #

# Words a researcher writes and this instrument never prints. Each is checked to
# have df=0 before it is used, so the test measures the property rather than
# assuming a corpus: a term the dictionary cannot satisfy carries the maximum
# idf, log((N+1)/1), and therefore the largest possible share of the denominator.
VOCABULARY_GAP_TERMS = ("physician", "history", "frequency", "limitation",
                        "malignancy", "duration", "functional")


def test_a_word_the_instrument_never_prints_depresses_a_correct_top_hit():
    """The mirror of the single-term guard above, and it had no test.

    That guard stops a query from MANUFACTURING confidence. This one records the
    opposite motion, which is the one C16's population is exposed to: a
    researcher's request carries words the instrument does not use, every such
    word is unsatisfiable and therefore weighs the most, and the score of a hit
    that covers every satisfiable term falls below the floor while remaining the
    same, correct hit. Measured 2026-09-02 over the committed fixture: 9 of the
    34 rows whose gold item is already at RANK 1 come back `low_confidence`.

    This is honest reporting, not a defect — `search_variables` says terms the
    dictionary lacks stay in the denominator, and dropping them is the failure it
    was rebuilt to stop. What it forbids is downstream: a rewrite stage may not
    read this label as "rephrase again", because on this population the label is
    not about the answer. `agent/query_rewrite.py::rewrite` therefore makes one
    call and branches on nothing.
    """
    from env.tools import _fts, _postings

    con = _fts()
    gaps = [t for t in VOCABULARY_GAP_TERMS if not _postings(con, t)]
    assert len(gaps) >= 3, (
        f"only {len(gaps)} of the gap terms are still absent from the "
        f"instrument; pick words it does not print, or this measures nothing")

    for phrase, _ in CONTROL_GOOD[:3]:
        first = search_variables(phrase=phrase)
        top, best = first["hits"][0]["key"], first["hits"][0]["score"]
        assert first["outcome"] == "ok"

        scores = [best]
        crossed = False
        for i in range(1, len(gaps) + 1):
            r = search_variables(phrase=f"{phrase} {' '.join(gaps[:i])}")
            hit = r["hits"][0]
            assert hit["key"] == top, (
                f"{phrase!r} + {gaps[:i]}: the top hit changed, so this row "
                f"measures ranking rather than the label")
            assert hit["score"] < scores[-1], (
                f"{phrase!r} + {gaps[:i]}: an unsatisfiable term did not "
                f"depress the score, so it is not in the denominator")
            scores.append(hit["score"])
            if hit["below_threshold"]:
                assert r["outcome"] == "low_confidence"
                crossed = True

        assert crossed, (
            f"{phrase!r}: adding {len(gaps)} words the instrument never prints "
            f"never pushed its own correct top hit below the floor. Either the "
            f"floor moved or idf stopped weighting absence; both change what a "
            f"rewrite stage may read the label as meaning")


# --------------------------------------------------------------------------- #
# limit
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("limit", [1, 2, 3, 5, 10, 25])
def test_limit_caps_the_returned_page(limit):
    """Advertised in the schema and enforced by no test until 2026-08-30.

    Mutating the cap to a no-op left 64 of the 65 tests in this file green.
    """
    for phrase in (KNOWN_LIMITATION, "blood pressure medication", "green space"):
        r = search_variables(phrase=phrase, limit=limit)
        assert len(r["hits"]) <= limit, (phrase, limit)
        assert r["n"] == len(r["hits"])


def test_limit_truncates_the_page_without_changing_which_hit_leads():
    """A cap that reordered would be a cap that changed the answer."""
    full = search_variables(phrase=KNOWN_LIMITATION, limit=10)
    one = search_variables(phrase=KNOWN_LIMITATION, limit=1)
    assert len(full["hits"]) == 10
    assert len(one["hits"]) == 1
    assert one["hits"][0]["key"] == full["hits"][0]["key"]
    assert one["hits"][0]["score"] == full["hits"][0]["score"]


def test_a_collapsed_duplicate_does_not_consume_a_limit_slot():
    """The interaction the cap and the collapse have with each other.

    The collapse exists to stop one roster battery spending the whole page; if a
    folded sibling still ate a slot it would not. Past the cap a new wording is
    deliberately NOT registered as a representative, so nothing is folded under
    a row the caller cannot see.
    """
    r = search_variables(phrase=KNOWN_LIMITATION, limit=3)
    assert len(r["hits"]) == 3
    assert sum(h["collapsed_n"] for h in r["hits"]), (
        "no duplicate was folded into the three rows shown")
    reachable = {h["key"] for h in r["hits"]} | {
        k for h in r["hits"] for k in h["collapsed_keys"]}
    assert len(reachable) > 3, (
        "three rows reach only three keys; a folded sibling consumed a slot")
    for h in r["hits"]:
        assert len(h["collapsed_keys"]) <= h["collapsed_n"]


# --------------------------------------------------------------------------- #
# duplicate collapse
# --------------------------------------------------------------------------- #

def test_roster_repeats_are_collapsed_under_one_representative():
    """Ten near-identical roster rows spend the whole budget on one question.

    Measured 2026-08-30: one roster battery contributed 19 duplicates to a
    single query. Collapsing them is a recall improvement, not a fixture fit.
    """
    r = search_variables(phrase=KNOWN_LIMITATION)
    collapsed = {h["key"]: h["collapsed_n"] for h in r["hits"] if h["collapsed_n"]}
    assert collapsed, "no near-duplicates were collapsed; the collapse regressed"
    texts = [h["excerpt"] for h in r["hits"]]
    assert len(set(texts)) == len(texts), "the returned page still repeats a wording"
    for h in r["hits"]:
        assert len(h["collapsed_keys"]) <= 4
        assert len(h["collapsed_keys"]) <= h["collapsed_n"]
    assert "collapsed" in r["log"]


def test_collapse_does_not_hide_the_keys_it_folded_away():
    r = search_variables(phrase=KNOWN_LIMITATION)
    folded = [h for h in r["hits"] if h["collapsed_n"]]
    assert folded
    for h in folded:
        assert h["collapsed_keys"], "a fold with no keys echoed is a silent drop"


# --------------------------------------------------------------------------- #
# the description the model actually reads
# --------------------------------------------------------------------------- #

def test_the_registry_description_describes_what_the_tool_returns():
    """The prompt text and the return value have to agree.

    A description promising a score the tool does not return is this codebase's
    signature failure in its cheapest form.
    """
    desc = SCHEMAS["search_variables"]["description"]
    r = search_variables(phrase="green space")
    assert "score" in desc
    assert "below_threshold" in desc and "below_threshold" in r["hits"][0]
    for word in ("low_confidence", "no_match"):
        assert word in desc
    assert "score_discriminates" in desc and "score_discriminates" in r
    assert search_variables(phrase=CONTROL_EMPTY)["outcome"] == "no_match"


def test_the_registry_description_calls_a_weak_hit_a_candidate_not_an_absence():
    """This description IS prompt text: the model reads it on every call.

    It said a below_threshold hit or a low_confidence outcome "means this
    WORDING found nothing". The only defensible item on the known-limitation
    page is a below_threshold hit at 0.325, so the prompt was instructing the
    model to read the right answer as nothing — while this module's own position
    is that the floor costs a label, never a candidate.
    """
    desc = SCHEMAS["search_variables"]["description"]
    assert "found nothing" not in desc
    assert "LOW-CONFIDENCE CANDIDATE" in desc
    assert "screen it" in desc
    # the guarantee that had to survive the reframing
    assert "lacks the construct" in desc
    # and the one-term hole, named where the model will read it
    assert "score_discriminates=false" in desc
