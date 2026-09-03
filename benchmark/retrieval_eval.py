"""Recall@k of the shipped `search_variables`, measured over a committed fixture.

WHY THIS EXISTS. C22 (`CHANGELOG.md`, 2026-08-31) was a deletion task whose
acceptance was "line count DOWN, recall@10 not down". No recall evaluator existed,
so half that gate was unenforceable and the deletion would have been landed on an
argument instead of a measurement. This module is the missing half. It does not
change retrieval and it must not: it CALLS `env.tools.search_variables` and scores
what comes back.

WHAT IT REUSES, rather than rebuilding. The retrieval engine is sqlite3 FTS5 inside
`env/tools.py`; the corpus is `build/dictionary.json`; the fixture schema is checked
by pydantic, the project's only runtime dependency. Nothing here re-implements
search, ranking, tokenisation or roster normalisation — `normalise` calls the same
regex `search_variables` collapses with, because a second definition of "same
wording" is how a scorer and the thing it scores silently disagree.

THAT REUSE IS ALSO THE HOLE, and `collapse_cardinality` is what plugs it. Borrowing
the definition of correctness from the file under test means a C22 rewrite that
BROADENS the collapse broadens this scorer's notion of a correct hit in the same
commit, minting recall out of wrong items. Measured 2026-08-31 against the shipped
code, substituting a normalisation that strips the roster index and then truncates
to 25 characters: @1 34 -> 52, @5 93 -> 131, @10 120 -> 155, gold excluded 18 -> 12.
Every ratchet in `tests/test_retrieval_eval.py` reads GREEN on that, because a floor
that may only go up cannot see a definition that got looser. `collapse_cardinality`
is measured over the whole dictionary rather than the fixture and moves the moment
the normalisation does, in a named direction; see its docstring for why one count
is a complete detector rather than a heuristic one.

THE GOLD RULE is the fixture's, verbatim: a hit is correct when its
roster-normalised `searchable_text` equals the target's. NOT key equality. This
dictionary carries ~1,520 roster repeats — the same question printed once per roster
row — and `search_variables` collapses them under one representative, so key
equality would score a correct retrieval as a miss whenever the collapse elected a
sibling key. "Verbatim" is checked, not asserted: `GOLD_RULE` holds the sentence
`_score_row` actually implements and `RecallReport` refuses a fixture stating a
different one, because the scope block PRINTS the fixture's sentence and would
otherwise publish a rule the scorer does not apply.

THE NUMBER IS AN UPPER BOUND. The fixture's `KNOWN_BIAS` records that its queries
were written by a model that had seen each gold item's wording. What is enforced,
exactly: every `RecallReport` CARRIES that text verbatim and cannot be constructed
without it, and every rendering LEADS with it, above the first recall figure. What
is NOT enforced, because Python cannot: `evaluate().recall_at(10)` returns a bare
float like any other, and nothing stops a caller quoting it alone. An earlier
version of this docstring claimed "a number cannot be lifted out of this module
without it", which was false in one line of code.

Run it: `python -m benchmark.retrieval_eval` from the repository root.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from env import tools

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "benchmark" / "fixtures" / "retrieval_queries.json"

#: The cut-offs reported by default. 1, 5 and 10 are the row C22 quotes; 10 is the
#: one its acceptance gate names.
DEFAULT_KS: tuple[int, ...] = (1, 5, 10)

#: Printed above every recall figure. A test pins that it precedes the first one.
BIAS_BANNER = "KNOWN BIAS — read every figure below as an UPPER BOUND"

#: The ONE rule `_score_row` implements, in the fixture's own words. The module
#: docstring called the gold rule "the fixture's, verbatim" and the scope block
#: prints the fixture's sentence, but the comparison is hard-coded here: edit the
#: fixture's `gold_rule` to anything else and every report would print a rule the
#: scorer does not apply, with the prose stating a guarantee nothing enforced.
#: `RecallReport` refuses that fixture instead. Changing this string is a change
#: to `_score_row`, not to a caption.
GOLD_RULE = ("a hit is correct when its roster-normalised searchable_text "
             "equals the target's")

SearchFn = Callable[[str, int], dict]


class QueryRow(BaseModel):
    """One fixture row: a query and the item it was written to retrieve.

    Attributes:
        key: The gold variable key.
        text: The gold item's wording, as recorded when the fixture was generated.
        query: The phrase to search.
    """

    key: str
    text: str
    query: str


class QueryFixture(BaseModel):
    """The committed query fixture.

    `gold_rule` and `KNOWN_BIAS` are `min_length=1` rather than plain strings
    because both are load-bearing: the first defines what counts as correct and the
    second is the only thing standing between this module's numbers and their being
    quoted as ground truth. A fixture that lost either would otherwise score
    silently.

    Attributes:
        schema_: Fixture schema identifier, read from the `schema` key.
        generated: The date the fixture was generated.
        generator: What generated it.
        sample: How the sample was drawn.
        gold_rule: What counts as a correct hit.
        known_bias: The bias a reader must carry into every figure.
        queries: The query rows, in fixture order.
    """

    schema_: str = Field(alias="schema")
    generated: str
    generator: str
    sample: str
    gold_rule: str = Field(min_length=1)
    known_bias: str = Field(alias="KNOWN_BIAS", min_length=1)
    queries: tuple[QueryRow, ...] = Field(min_length=1)


@dataclass(frozen=True)
class QueryOutcome:
    """What one query did, in enough detail to diagnose why it missed.

    Attributes:
        key: The gold variable key from the fixture.
        query: The phrase searched.
        rank: 1-based position of the first hit whose wording equals the gold
            item's, or `None` when no candidate did.
        n_candidates: Hits the search returned, after roster collapse.
        n_matched_items: Items the engine matched before collapse, as reported by
            the search itself; `-1` when the search reports no such field.
        outcome: The search's own `outcome` field.
    """

    key: str
    query: str
    rank: int | None
    n_candidates: int
    n_matched_items: int
    outcome: str

    def hit_at(self, k: int) -> bool:
        """Whether the gold item was retrieved within the first `k` candidates.

        Args:
            k: The cut-off.

        Returns:
            True when the gold wording ranked at or above `k`.
        """
        return self.rank is not None and self.rank <= k


@dataclass(frozen=True)
class RecallReport:
    """Recall of the gold item over one fixture, for one search callable.

    Attributes:
        fixture_path: The fixture that was scored.
        dictionary_version: `version_hash` of the dictionary searched.
        known_bias: The fixture's `KNOWN_BIAS`, verbatim.
        gold_rule: The fixture's `gold_rule`, verbatim.
        generator: The fixture's `generator`, verbatim.
        sample: The fixture's `sample`, verbatim.
        ks: The cut-offs measured.
        results: One outcome per fixture row, in fixture order.
        candidate_limit: The `limit` every search was called with.
        search_name: `__name__` of the search callable that was scored.
        collapse_cardinality: Distinct wordings the dictionary collapsed to under
            the gold rule when this report was built. Carried, not merely
            computed: two recall figures produced under different values of it
            are not on the same scale, and nothing else in the report says so.
        dictionary_entries: Entries in the dictionary searched, the denominator
            of `collapse_cardinality`.

    Raises:
        ValueError: If `known_bias` is empty. The bias notice is the reason this
            module's numbers are safe to publish; a report that could be built
            without one would be quoted without one.
        ValueError: If `gold_rule` is not `GOLD_RULE`. The scope block prints
            this sentence as the definition behind every figure; printing one
            the scorer does not implement is worse than printing none.
    """

    fixture_path: str
    dictionary_version: str
    known_bias: str
    gold_rule: str
    generator: str
    sample: str
    ks: tuple[int, ...]
    results: tuple[QueryOutcome, ...]
    candidate_limit: int
    search_name: str
    collapse_cardinality: int
    dictionary_entries: int

    def __post_init__(self) -> None:
        """Refuse a report that carries no bias notice or the wrong gold rule.

        Raises:
            ValueError: If `known_bias` is empty or whitespace.
            ValueError: If `gold_rule` is not the rule this module implements.
        """
        if not self.known_bias.strip():
            raise ValueError(
                "RecallReport built with no known_bias. The fixture's KNOWN_BIAS "
                "is what stops these numbers being read as ground truth; a report "
                "without it must not exist.")
        # Whitespace-collapsed: the sentence lives in JSON and a rewrap is not a
        # change of rule. Anything else is.
        if " ".join(self.gold_rule.split()) != GOLD_RULE:
            raise ValueError(
                f"The fixture states a gold rule this module does not implement.\n"
                f"  fixture says:  {self.gold_rule}\n"
                f"  scorer does:   {GOLD_RULE}\n"
                f"`_score_row` compares roster-normalised wording and nothing "
                f"else, whatever the fixture says; the scope block prints the "
                f"fixture's sentence as the definition behind every figure, so a "
                f"report built from this fixture would publish a rule that was "
                f"never applied. Change `_score_row` and `GOLD_RULE` together, or "
                f"restore the fixture's sentence.")

    @property
    def n_queries(self) -> int:
        """The denominator of every recall figure: fixture rows scored."""
        return len(self.results)

    @property
    def distinct_gold_items(self) -> int:
        """How many distinct gold keys the fixture rows point at."""
        return len({r.key for r in self.results})

    def hits_at(self, k: int) -> int:
        """How many rows retrieved the gold wording within `k`.

        Args:
            k: The cut-off.

        Returns:
            The numerator of recall@k.
        """
        return sum(1 for r in self.results if r.hit_at(k))

    def recall_at(self, k: int) -> float:
        """Recall@k as a fraction of fixture rows.

        Args:
            k: The cut-off.

        Returns:
            `hits_at(k) / n_queries`, or 0.0 for an empty fixture.
        """
        return self.hits_at(k) / self.n_queries if self.n_queries else 0.0

    def misses(self, k: int) -> tuple[QueryOutcome, ...]:
        """The rows that did NOT retrieve the gold wording within `k`.

        C22 deletes code from `search_variables`; a deletion has to be diagnosed,
        not only scored, so the misses are addressable rather than aggregated away.

        Args:
            k: The cut-off.

        Returns:
            The failing rows, in fixture order.
        """
        return tuple(r for r in self.results if not r.hit_at(k))

    @property
    def gold_excluded(self) -> int:
        """Rows whose gold wording appeared NOWHERE in the candidate set.

        Reported beside recall, always. A target filter measured +5 recall on
        2026-08-30 by taking its input from the gold item's own label; supplied
        from the query alone it was net negative and deleted the right answer on
        9.8% of queries. Recall alone cannot see that; this can.
        """
        return sum(1 for r in self.results if r.rank is None)

    @property
    def gold_excluded_rate(self) -> float:
        """`gold_excluded` as a fraction of fixture rows."""
        return self.gold_excluded / self.n_queries if self.n_queries else 0.0

    @property
    def scope(self) -> str:
        """The glob, the filter and the definitions behind every figure here.

        An unstated denominator is not a number: two figures in an earlier handoff
        were called irreproducible by a critic and were in fact exact, under a
        scope nobody had written down.
        """
        return "\n".join([
            f"fixture         {self.fixture_path}",
            f"rows            {self.n_queries} query rows over "
            f"{self.distinct_gold_items} distinct gold items",
            f"generator       {self.generator}",
            f"sample          {self.sample}",
            "filter          none — every fixture row is scored, no row, item or "
            "outcome is dropped",
            f"search          {self.search_name}(query, limit="
            f"{self.candidate_limit}) over build/dictionary.json "
            f"{self.dictionary_version}",
            f"gold rule       {self.gold_rule}",
            # The gold rule's resolution belongs beside the gold rule: the
            # sentence alone does not say how many questions the rule can still
            # tell apart, and a recall figure scored under a looser answer is
            # not comparable to one scored under a tighter one.
            f"collapse        {self.dictionary_entries} entries -> "
            f"{self.collapse_cardinality} distinct wordings under that rule",
            # Labelled `def` rather than reusing the figures' own labels: a
            # definition line beginning "recall@k" is indistinguishable from the
            # figure line beginning "recall@1" to anything that reads this report
            # by prefix, the test for the denominators included.
            f"def recall@k    rows whose gold wording appears among the first k "
            f"candidates, over {self.n_queries} rows",
            f"def excluded    rows whose gold wording appears at NO rank in the "
            f"candidate set, over {self.n_queries} rows",
        ])


def normalise(text: str) -> str:
    """Reduce one searchable text to its wording, the gold rule's unit of equality.

    Delegates to `env.tools`' own roster regex. That coupling is deliberate:
    `search_variables` collapses roster repeats under exactly this normalisation,
    and a scorer holding a second copy of the definition would keep scoring the old
    rule after the tool changed it. It is a seam, not a second definition — it
    exists so a test can state what the normalisation must do to a string it wrote
    itself, which is the one expectation a delegating scorer cannot supply.

    Args:
        text: A raw `searchable_text`.

    Returns:
        The text with any leading roster index stripped.
    """
    return tools._ROSTER_INDEX.sub("", text).strip()


def collapse_cardinality() -> int:
    """Distinct wordings the whole dictionary collapses to under the gold rule.

    THE GOLD RULE'S RESOLUTION, as one number, and the guard on the coupling in
    `normalise`. The rule counts a hit correct when its normalised wording equals
    the target's, so this count is exactly how many different questions the rule
    can still tell apart.

    It is a complete detector for a normalisation change that inflates recall, not
    a heuristic one: minting a hit that was previously a miss requires two wordings
    that used to differ to compare equal, and any such merge lowers this count.
    Symmetrically, losing a true hit requires a split, which raises it. The residual
    it cannot see is a change that merges and splits the same number of pairs at
    once; `tests/test_retrieval_eval.py` covers that with an expectation written by
    hand rather than derived from `env.tools`.

    Measured over the dictionary, never over the fixture: the fixture's 56 wordings
    would move only when the drift happened to touch them.

    Returns:
        `len({normalise(searchable_text) for every entry})`.
    """
    return len({normalise(e["searchable_text"]) for e in tools._load()["entries"]})


def _entry(key: str) -> dict:
    """The dictionary entry for one key, or a diagnosis of why there is none.

    Args:
        key: A fully qualified variable key.

    Returns:
        The entry.

    Raises:
        KeyError: If the key is not in the built dictionary.
    """
    tools._load()
    entry = tools._BY_KEY.get(key)
    if entry is None:
        raise KeyError(
            f"{key!r} is not in build/dictionary.json "
            f"({tools.dictionary_version()}). A fixture row pointing at a key the "
            f"dictionary no longer holds is a stale fixture, not a miss, and "
            f"scoring it as a miss would report a rebuild as a regression.")
    return entry


def normalised_text(key: str) -> str:
    """Roster-normalised searchable text of one variable — the fixture's gold rule.

    Args:
        key: A fully qualified variable key.

    Returns:
        The item's `searchable_text` with any leading roster index stripped.

    Raises:
        KeyError: If the key is not in the built dictionary.
    """
    return normalise(str(_entry(key)["searchable_text"]))


def fixture_drift(fx: QueryFixture) -> tuple[str, ...]:
    """Fixture rows whose recorded wording is no longer the dictionary's.

    The DELETED key is already diagnosed, by `_entry`. This is the reworded one,
    which is worse because it is silent: `QueryRow.text` records the wording each
    query was written against, and nothing in the scoring path reads it. Let a
    rebuild reword or renumber an item and the row keeps scoring — either the
    gold item is unreachable and the recall ratchet goes red blaming C22's
    deletions, or it is reachable and the row scores GREEN against a question
    nobody asked. Both report the wrong defect.

    Compared exactly, against the raw `searchable_text` rather than the
    normalised wording: MEASURED 2026-08-31 over build 6fcd02755bf3, all 224
    committed rows record the raw text character for character, roster index
    included, and 12 of them would disagree with the roster-normalised form. A
    whitespace change in `searchable_text` is a change to what the engine
    indexes, so it is drift too.

    Args:
        fx: The fixture to check.

    Returns:
        One human-readable line per drifted gold ITEM, not per row — a fixture
        carries several queries per item and repeating one reword four times
        buries the second drifted item under the first. Empty when the fixture
        and the dictionary still describe the same questions.

    Raises:
        KeyError: If a row points at a key the dictionary no longer holds.
    """
    drifted: dict[str, str] = {}
    rows: dict[str, int] = {}
    for row in fx.queries:
        current = str(_entry(row.key)["searchable_text"])
        if row.text != current:
            rows[row.key] = rows.get(row.key, 0) + 1
            drifted[row.key] = (f"{row.key}: fixture recorded {row.text!r}, "
                                f"dictionary now holds {current!r}")
    return tuple(f"{line}  [{rows[key]} quer"
                 f"{'y' if rows[key] == 1 else 'ies'}]"
                 for key, line in drifted.items())


def candidate_limit() -> int:
    """The `limit` to search with so the candidate set is never truncated.

    Derived from the dictionary rather than pinned to a constant: a fixed number
    smaller than the instrument would turn "ranked below the cut-off" into
    "excluded from the candidate set", which are different defects with different
    fixes.

    Returns:
        The number of entries in the built dictionary.
    """
    return len(tools._load()["entries"])


def load_fixture(path: Path = FIXTURE) -> QueryFixture:
    """Read and validate the committed query fixture.

    Args:
        path: The fixture file.

    Returns:
        The parsed fixture.

    Raises:
        FileNotFoundError: If the fixture is missing.
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; it is committed, so this is a "
                                f"checkout problem, not a regeneration cue.")
    return QueryFixture.model_validate(json.loads(path.read_text()))


#: What the scope line says when the caller passed rows rather than a file. The
#: scope block existed because an unstated denominator is not a number, and it
#: was naming the committed 224-row fixture for every subset and every
#: hand-built row set an experiment scored. Better to name no file than the
#: wrong one. The committed fixture's name is deliberately absent from this
#: string, including as the negative half of a "not X": a reader scanning the
#: scope block for a filename finds it either way.
UNNAMED_FIXTURE = "<rows supplied by the caller in memory; no file was read>"


def _fixture_label(path: Path) -> str:
    """The fixture path as the scope block should print it.

    Args:
        path: The fixture file that was read.

    Returns:
        The path relative to the repository root, or absolute when it lies
        outside.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def evaluate(search: SearchFn | None = None,
             ks: Sequence[int] = DEFAULT_KS,
             fixture: QueryFixture | None = None,
             fixture_path: Path | None = None) -> RecallReport:
    """Score a search callable over the fixture.

    Deterministic by construction: rows are scored in fixture order, the search is
    called once per row with a fixed limit, and nothing is sampled or shuffled.

    Any candidate-set experiment — a facet, a target filter, a rerank — passes its
    own callable here and gets `gold_excluded` reported whether it wanted it or not.

    Args:
        search: `(query, limit) -> result dict` with a `hits` list of dicts
            carrying `key`. Defaults to `env.tools.search_variables` as shipped.
        ks: Cut-offs to measure.
        fixture: A pre-loaded fixture; loaded from `fixture_path` when omitted.
        fixture_path: The file to read when `fixture` is omitted, and the name
            the scope block prints. Defaults to `FIXTURE`; a caller passing
            `fixture` may pass this too to name where those rows came from.

    Returns:
        The report, carrying one `QueryOutcome` per fixture row.

    Raises:
        ValueError: If the fixture's recorded wordings have drifted from the
            dictionary. Refused rather than scored, for the same reason
            `_entry` refuses a vanished key: a number produced against a
            question the fixture was not written for is worse than no number.
    """
    if fixture is not None:
        fx = fixture
        label = _fixture_label(fixture_path) if fixture_path else UNNAMED_FIXTURE
    else:
        path = fixture_path if fixture_path is not None else FIXTURE
        fx = load_fixture(path)
        label = _fixture_label(path)
    drift = fixture_drift(fx)
    if drift:
        raise ValueError(
            f"FIXTURE DRIFT: {len(drift)} gold item(s) across "
            f"{len(fx.queries)} rows record a "
            f"wording the rebuilt dictionary "
            f"({tools.dictionary_version()}) no longer holds. This is NOT a "
            f"retrieval regression and nothing C22 deleted caused it: each of "
            f"these queries was written to retrieve the text on the left, and "
            f"scoring it against the text on the right measures a question "
            f"nobody asked. Regenerate the fixture against this build and "
            f"re-measure every ratchet in tests/test_retrieval_eval.py.\n  "
            + "\n  ".join(drift))
    fn: SearchFn = search if search is not None else tools.search_variables
    limit = candidate_limit()

    # A 224-query sweep would otherwise land 224 entries in the shared tool log and
    # appear in a live run's audit trail as calls the Specifier made. Measuring is
    # not running; the log is trimmed back to what it held on entry.
    log_depth = len(tools.LOG.calls)
    try:
        results = tuple(_score_row(fn, row, limit) for row in fx.queries)
    finally:
        del tools.LOG.calls[log_depth:]

    return RecallReport(
        fixture_path=label,
        dictionary_version=tools.dictionary_version(),
        known_bias=fx.known_bias,
        gold_rule=fx.gold_rule,
        generator=fx.generator,
        sample=fx.sample,
        ks=tuple(ks),
        results=results,
        candidate_limit=limit,
        search_name=getattr(fn, "__name__", repr(fn)),
        collapse_cardinality=collapse_cardinality(),
        dictionary_entries=len(tools._load()["entries"]),
    )


def _score_row(search: SearchFn, row: QueryRow, limit: int) -> QueryOutcome:
    """Run one query and locate the gold wording in its candidate list.

    Args:
        search: The search callable under evaluation.
        row: The fixture row.
        limit: The limit to search with.

    Returns:
        The row's outcome.
    """
    gold = normalised_text(row.key)
    result = search(row.query, limit)
    hits = result.get("hits", [])
    rank: int | None = None
    for i, hit in enumerate(hits, start=1):
        if normalised_text(str(hit["key"])) == gold:
            rank = i
            break
    return QueryOutcome(
        key=row.key,
        query=row.query,
        rank=rank,
        n_candidates=len(hits),
        # -1, not 0: a custom search that does not report the pre-collapse count is
        # unknown here, and unknown printed as 0 reads as "matched nothing".
        n_matched_items=int(result.get("n_matched_items", -1)),
        outcome=str(result.get("outcome", "unknown")),
    )


def format_report(report: RecallReport) -> str:
    """Render a report a human can read, bias notice first.

    Args:
        report: The report to render.

    Returns:
        The full text, ending with the per-query misses at the largest cut-off.

    Raises:
        ValueError: If the report carries no cut-offs to render.
    """
    if not report.ks:
        raise ValueError("A report with no ks renders no recall figure at all.")
    widest = max(report.ks)
    lines = [
        "retrieval recall — env.tools.search_variables over the committed fixture",
        "",
        report.scope,
        "",
        # The banner sits ABOVE the first figure, not in a footnote: a number read
        # before its caveat is a number quoted without it.
        f"{BIAS_BANNER}",
        f"    {report.known_bias}",
        "",
    ]
    for k in sorted(report.ks):
        lines.append(f"recall@{k:<4} {report.hits_at(k):>4}/{report.n_queries}  "
                     f"{100 * report.recall_at(k):5.1f}%")
    lines += [
        f"gold excluded {report.gold_excluded:>3}/{report.n_queries}  "
        f"{100 * report.gold_excluded_rate:5.1f}%   "
        f"(gold wording at no rank in the candidate set)",
        "",
        f"misses at @{widest} — {len(report.misses(widest))} row(s), "
        f"'rank -' means excluded from the candidate set entirely:",
    ]
    for miss in report.misses(widest):
        rank = "-" if miss.rank is None else str(miss.rank)
        lines.append(f"    rank {rank:>5}  {miss.outcome:<14} {miss.key:<16} "
                     f"{miss.query}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_report(evaluate()))
