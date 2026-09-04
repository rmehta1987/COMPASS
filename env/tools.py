"""env/tools.py — the deterministic tool layer the Specifier calls.

INVARIANT: nothing in env/ imports a model or touches the network. A test greps
this whole package for import forms. If a component needs a model call it is not
environment, and it belongs on the other side of the line.

Every tool either fills a field of the protocol record with a looked-up fact, or
is a documented discovery tool that may never write a key into a protocol. A
field whose only filler would be a simulator gets nullability instead of a
simulator — which is why there is no `profile_synthetic` here: zero variables in
this instrument carry response coding, so there is nothing to parameterise a
synthetic cohort from, and any number one returned would be fabrication wearing a
tool's credibility.

Tool output convention: return a research log — prose the model can reason over —
not a dataclass. Carry `[unverified]` inline so a project reading cannot be
laundered into a study claim. Include negative instructions, because the failure
mode is doing the wrong thing, not omitting the right one.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CURATED = ROOT / "curated"

_DICT: dict | None = None
_BY_KEY: dict[str, dict] = {}
_BY_GROUP: dict[str, list[dict]] = {}
_BY_CONSTRUCT: dict[str, list[dict]] = {}
_BY_MODULE: dict[str, list[dict]] = {}
_BY_SECTION: dict[str, dict[str, list[dict]]] = {}
_FTS: sqlite3.Connection | None = None


# --------------------------------------------------------------------------- #
# call logging — at the function boundary, never by parsing model output
# --------------------------------------------------------------------------- #

@dataclass
class ToolCall:
    """One tool invocation, recorded where it happened.

    Attributes:
        name: Registry name of the tool.
        args: The keyword arguments it was called with. Recorded even when the
            tool discards one — a refused `n_values` is evidence that a caller
            tried to choose its own grid, and evidence is not noise.
        outcome: The `outcome` field of the return value, or `error` if it raised.
        ms: Wall-clock duration of the call.
    """

    name: str
    args: dict
    outcome: str
    ms: float


@dataclass
class ToolLog:
    """The calls made during one run, in call order.

    Attributes:
        calls: Every recorded invocation.
    """

    calls: list[ToolCall] = field(default_factory=list)

    def record(self, name: str, args: dict, outcome: str, ms: float) -> None:
        """Append one call.

        Args:
            name: Registry name of the tool.
            args: Keyword arguments it was called with.
            outcome: Its `outcome` field, or `error`.
            ms: Wall-clock duration of the call.
        """
        self.calls.append(ToolCall(name, args, outcome, ms))

    @property
    def names(self) -> list[str]:
        """Tool names in call order, with repeats."""
        return [c.name for c in self.calls]

    def distinct(self) -> set[str]:
        """The set of tools called at least once."""
        return set(self.names)


LOG = ToolLog()


def _logged(fn: Callable) -> Callable:
    """Record every call to a tool at the function boundary.

    At the boundary, never by parsing model output: a log reconstructed from what
    the model says it did is the model's recollection, not the log.

    Args:
        fn: The tool function to wrap.

    Returns:
        The wrapped function, with `__name__` and `__doc__` preserved because the
        registry and the MCP server both read them.
    """
    def wrapper(*a: object, **kw: object) -> object:
        t0 = time.perf_counter()
        try:
            out = fn(*a, **kw)
            outcome = out.get("outcome", "ok") if isinstance(out, dict) else "ok"
            return out
        finally:
            LOG.record(fn.__name__, {**kw}, locals().get("outcome", "error"),
                       (time.perf_counter() - t0) * 1000)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def _load() -> dict:
    global _DICT, _BY_KEY, _BY_GROUP, _BY_CONSTRUCT, _BY_MODULE, _BY_SECTION, _FTS
    if _DICT is not None:
        return _DICT
    p = BUILD / "dictionary.json"
    if not p.exists():
        raise RuntimeError(
            f"{p} is missing. Run `python build.py`. A missing generated input "
            "must raise loudly with the command to fix it — never read as empty, "
            "which once made every variable resolve as unknown-provenance and the "
            "access gate refer everything: correct-looking behaviour, wrong reason.")
    _DICT = json.loads(p.read_text())
    for e in _DICT["entries"]:
        _BY_KEY[e["key"]] = e
        if e["group_key"]:
            _BY_GROUP.setdefault(e["group_key"], []).append(e)
        _BY_CONSTRUCT.setdefault(e["construct_key"], []).append(e)
        _BY_MODULE.setdefault(e["module"], []).append(e)
        _BY_SECTION.setdefault(e["module"], {}).setdefault(
            _section_of(e["construct_key"]), []).append(e)

    _FTS = sqlite3.connect(":memory:")
    # `key` is UNINDEXED because an indexed key column made the variable key
    # itself searchable: `search_variables(phrase='m1')` matched 142 items on
    # their key prefix and scored every one of them 1.0, while the tool's own
    # log and schema description promise the score measures WORDING coverage.
    # UNINDEXED also keeps the main query and `_postings` on the same index by
    # construction, rather than by two `MATCH`es that have to be edited together.
    _FTS.execute(
        "CREATE VIRTUAL TABLE v USING fts5(key UNINDEXED, txt, tokenize='porter')")
    _FTS.executemany("INSERT INTO v(key, txt) VALUES (?,?)",
                     [(e["key"], e["searchable_text"]) for e in _DICT["entries"]])
    _FTS.commit()
    return _DICT


def dictionary_version() -> str:
    return _load()["version_hash"]


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #

@_logged
def resolve_variable(key: str) -> dict:
    """Resolve a fully qualified variable key.

    Four outcomes, and `ambiguous` is a failure: unique | ambiguous | group |
    not_found. A bare qid is not a variable name — 121 qids are not globally
    unique, 120 collide across modules, and one appears twice inside module 2.
    """
    _load()
    if key in _BY_KEY:
        e = _BY_KEY[key]
        return {
            "outcome": "unique", "key": e["key"], "module": e["module"],
            "quoted_wording": e["question_text"],
            "stem_text": e["stem_text"], "subitem_text": e["subitem_text"],
            "origin": e["origin"], "study_team_confirmed": e["study_team_confirmed"],
            "is_free_text": e["is_free_text"], "is_grid_subitem": e["is_grid_subitem"],
            "group_key": e["group_key"],
            "value_labels": None,
            "log": (f"{key} resolves uniquely in module {e['module']}. Use this "
                    f"wording verbatim in quoted_wording. Response coding, value "
                    f"labels and missing codes are NULL for every variable in this "
                    f"instrument because the codebooks have two columns — do not "
                    f"infer them, and do not state a variable's scale."),
        }
    if key in _BY_GROUP:
        n = len(_BY_GROUP[key])
        return {"outcome": "group", "key": key,
                "log": (f"{key} is a GROUP id covering {n} sub-items, not a variable. "
                        f"A protocol may never name a stem: naming one generates a "
                        f"reference resolution cannot find. Call get_item_group('{key}') "
                        f"and either name a sub-item or declare a derivation over the "
                        f"battery.")}
    if key in _BY_CONSTRUCT:
        # The funnel hands the Specifier a CONSTRUCT key, which is not a
        # variable name. Found live: the model's first call was the construct
        # key, and the generic not_found reply sent it looking through the
        # empty clinical/lab/linked registries before it recovered by guessing
        # sub-item keys. Naming the next call costs nothing and saves the turns.
        rows = _BY_CONSTRUCT[key]
        members = sorted(r["key"] for r in rows)
        grp = rows[0]["group_key"]
        nxt = (f"get_item_group({grp!r})" if grp
               else f"resolve_variable({members[0]!r})")
        return {"outcome": "construct", "key": key, "member_keys": members,
                "group_key": grp,
                "log": (f"{key} is a CONSTRUCT key covering {len(members)} "
                        f"variable(s), not a variable name — it is the id the "
                        f"enumeration uses, and a protocol may not name it. "
                        f"Next call: {nxt}. Members: {members[:8]}"
                        f"{' …' if len(members) > 8 else ''}. If this is a "
                        f"multi-item battery, name a signed derivation rather "
                        f"than a member.")}

    if re.fullmatch(r"Q\d+(\.\d+)?(_\d+)?", key):
        matches = [k for k in _BY_KEY if k.split(":", 1)[1].split("~")[0] == key]
        return {"outcome": "ambiguous", "key": key, "candidates": sorted(matches),
                "log": (f"'{key}' is a bare question id, not a variable name, and "
                        f"resolves to {len(matches)} variables: {sorted(matches)}. "
                        f"Ambiguous is a FAILURE. Re-issue with a module-qualified key.")}
    return {"outcome": "not_found", "key": key,
            "log": (f"{key} is not in any registry. If it names a clinical, lab, "
                    f"linked or EHR measure, those registries are declared but EMPTY "
                    f"in v1 — see registry_coverage(). Do not substitute a survey "
                    f"item that sounds similar: a key that resolves while naming the "
                    f"wrong construct is the failure mode with no automated detector.")}


@_logged
def get_item_group(group_id: str) -> dict:
    """Resolve a grid battery to its sub-items."""
    _load()
    if group_id not in _BY_GROUP:
        return {"outcome": "not_found", "log": f"{group_id} is not a group id."}
    rows = sorted(_BY_GROUP[group_id], key=lambda e: e["subitem_index"] or 0)
    return {
        "outcome": "ok", "group_id": group_id,
        "stem_text": rows[0]["stem_text"],
        "items": [{"key": r["key"], "subitem_text": r["subitem_text"],
                   "ordinal": r["subitem_index"]} for r in rows],
        "log": (f"{group_id} has {len(rows)} sub-items sharing one stem. Sub-item "
                f"text is only interpretable WITH the stem. To use this battery as "
                f"an exposure or outcome you must name a derivation from "
                f"list_derivations() — inline recipes are forbidden, and the "
                f"record is REJECTED if it names a derivation with no signed "
                f"file, or one whose component_keys or unit differ from that "
                f"file. Call get_derivation() and copy them."),
    }


# --------------------------------------------------------------------------- #
# scored lexical retrieval
# --------------------------------------------------------------------------- #

#: Floor on the normalised score below. At or above it a hit is a candidate;
#: below it the hit carries `below_threshold` and, when the BEST hit is below,
#: the whole result's outcome is `low_confidence` rather than `ok`. 0.523 is the
#: midpoint of the separating interval re-measured 2026-08-30 over the control
#: set recorded in `search_variables`' docstring — highest known-bad top hit
#: 0.477, lowest known-good top hit 0.569 — not a guessed constant, and not
#: tuned to make any single query pass. It read 0.52 and called itself the
#: midpoint until 2026-08-30; the midpoint of (0.477, 0.569) is 0.523, and
#: `tests/test_search_scoring.py` now re-derives the word rather than leaving
#: the claim unenforced beside a number that contradicts it.
SEARCH_SCORE_FLOOR = 0.523

#: How many collapsed sibling keys are echoed per hit. The full count is always
#: reported; the list is truncated because one roster battery contributed 19
#: duplicates in a measured query and echoing them all spends the caller's
#: context on the thing the collapse exists to suppress.
SEARCH_COLLAPSE_KEYS_SHOWN = 4

#: A roster repeat is the same question printed once per roster row, so its
#: searchable text differs from its siblings' only by a leading "<n> - ".
#: Returning ten of them spends the whole result budget on one question:
#: measured 2026-08-30, collapsing them moved the item a live run was actually
#: looking for from position 32 to position 9 for one of its queries.
_ROSTER_INDEX = re.compile(r"^\s*\d+\s*-\s*")

_CONTENT_TOKEN = re.compile(r"[A-Za-z]{3,}")
_ANY_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _fts() -> sqlite3.Connection:
    """Return the loaded full-text index.

    Raising beats returning `None` here for the same reason `_load` raises on a
    missing dictionary: a search that silently returns nothing reads exactly
    like a search that found nothing.

    Returns:
        The in-memory FTS5 connection built by `_load`.

    Raises:
        RuntimeError: If `_load` ran without building the index.
    """
    _load()
    con = _FTS
    if con is None:
        raise RuntimeError("FTS index missing after _load(); this is a bug in _load.")
    return con


def _dedupe(tokens: Iterable[str]) -> list[str]:
    """Drop repeats while keeping first-seen order.

    Args:
        tokens: Tokens in the order they were written.

    Returns:
        The tokens with later repeats removed.
    """
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _query_terms(phrase: str) -> tuple[list[str], list[str]]:
    """Split a phrase into the terms actually searched and the tokens dropped.

    The rewrite keeps alphabetic runs of three or more characters, which means
    numerals and one- or two-character words never reach the index. That rule is
    kept — a bare year is nearly always the caller illustrating rather than
    searching — but until 2026-08-30 the drop was SILENT: a live run searched
    'what year born 1900 1950 2000' and nothing in the return value said the
    three years had been discarded. The dropped tokens are returned so the log
    can name them.

    Args:
        phrase: The caller's raw search phrase.

    Returns:
        `(terms, discarded)`, both deduplicated and lowercased. If no token
        survives the three-character rule, every token becomes a term and
        `discarded` is empty: searching a two-character phrase beats searching
        nothing at all.
    """
    terms = _dedupe(t.lower() for t in _CONTENT_TOKEN.findall(phrase))
    every = _dedupe(t.lower() for t in _ANY_TOKEN.findall(phrase))
    if not terms:
        return every, []
    kept = set(terms)
    return terms, [t for t in every if t not in kept]


def _postings(con: sqlite3.Connection, term: str) -> set[str]:
    """Return the keys of every item whose searchable text contains `term`.

    The membership test runs through FTS5 rather than through a Python stemmer
    on purpose: the score has to agree with the ranking, and re-implementing
    porter stemming beside sqlite's is how the two silently diverge.

    Args:
        con: The FTS5 connection from `_fts`.
        term: A single already-lowercased alphanumeric term.

    Returns:
        The set of matching variable keys, empty if the term is in no item.
    """
    rows = con.execute("SELECT key FROM v WHERE v MATCH ?", (f'"{term}"',))
    return {str(r[0]) for r in rows}


def _idf(df: int, n_items: int) -> float:
    """Smoothed inverse document frequency of a term over the dictionary.

    Args:
        df: How many items contain the term.
        n_items: Total items in the dictionary.

    Returns:
        `log((n_items + 1) / (df + 1))`, so a term in every item weighs ~0 and a
        term in no item weighs the most — a query word nothing can satisfy is
        the most informative thing about the query, not the least.
    """
    return math.log((n_items + 1) / (df + 1))


@_logged
def search_variables(phrase: str, limit: int = 10) -> dict:
    """DISCOVERY ONLY. Scored lexical search over the dictionary.

    This tool may NEVER write a key into a protocol. Take a candidate from here,
    then call resolve_variable() and use that wording. Lexical, not embedding:
    an embedding index would require loading a model, which breaks the env/
    no-model invariant, and 2,804 two-column rows are small enough that lexical
    search is exhaustive rather than approximate.

    WORDING ONLY. The index covers question wording and nothing else: the
    variable key is stored `UNINDEXED`, so a term can never be earned by the key
    it is printed under. It was indexed until 2026-08-30, and the consequence
    was not cosmetic — `phrase='m1'`, a query a live run actually issued, matched
    142 items on their key prefix and scored every one of them 1.000 while the
    log promised the score measured wording coverage.

    SCORE. `score` is the fraction of the query's idf-weighted information that a
    hit's question wording covers:

        score = sum(idf(t) for t in matched) / sum(idf(t) for t in searched)

    with `idf` as in `_idf`. It is in [0, 1] by construction, it is 1.0 exactly
    when the wording contains every term searched, and unlike raw BM25 it means
    the same thing across two different queries — which is what a threshold
    needs. Raw BM25 is reported per hit as `bm25` rather than hidden, so the
    ordering can be audited; hits are ordered by score, then by BM25.

    Terms the whole dictionary lacks stay in the denominator. Dropping them
    would score a hit 1.0 for covering the only word that was ever findable,
    which is the failure this tool was rebuilt to stop.

    ONE TERM IS NOT A SCORE. If only ONE term survives tokenisation, every hit
    that matches covers the whole denominator and scores 1.000, so the floor
    cannot fire; such a result reports `score_discriminates=false` and outcome
    `low_confidence` however high its scores look. The measured walk that made
    that necessary is recorded at `score_discriminates` in the body.

    FLOOR. `SEARCH_SCORE_FLOOR`, calibrated 2026-08-30 against the control set
    below, top-hit score first. `tests/test_search_scoring.py` re-derives EVERY
    row of this table and fails if any phrase carrying a number here is not
    pinned there, so the table cannot drift from the code:

        known-good, top hit is a defensible candidate
            'what is your birthday'                         1.000
            'yearly household income'                       1.000
            'blood pressure medication'                     1.000
            'phone number'                                  1.000
            'marital status'                                1.000
            'high blood pressure'                           1.000
            'how many years lived at your current address'  1.000
            'sex male female gender'                        0.740
            'blood pressure medication treatment'           0.692
            'depression sad hopeless'                       0.623
            'physical activity exercise'                    0.574
            'income money household'                        0.569
        known-bad, top hit is a vocabulary accident
            'green space'                                   0.477
            'social cohesion'                               0.463
        below the floor and defensible anyway — the floor's measured cost
            'stress worried anxious'                        0.333
            'body mass index weight height'                 0.203
        the six age queries one live run actually issued
            'currently are you how many currently years old' 0.704
            'age years born'                                0.676
            'participant age how old you'                   0.498
            'date born when were you born'                  0.465
            'm1 age demographics years'                     0.322
            'what year born 1900 1950 2000'                 1.000
        matches nothing at all
            'zzzqqq xyzzyx plughq'                          no hits

    The gap this floor is the midpoint of is derived at `SEARCH_SCORE_FLOOR`. It
    is deliberately conservative on the low side: the two rows under "measured
    cost" have defensible top hits and still land below it — a measured
    false-non-answer rate, stated rather than tuned away. That costs a LABEL,
    never a candidate: a below-floor result still RETURNS its hits, because a
    tool that hides a weak hit cannot be second-guessed, and because on one age
    query the only defensible item on the page scores 0.325 and sits below the
    floor. Below the floor means SCREEN THIS, not "nothing here".

    KNOWN LIMITATION, stated because a scorer that hid it would be worse than a
    red test. For 'what year born 1900 1950 2000' the top hit covers 100% of the
    query's content terms and is the honest best lexical match while being the
    wrong item. No defensible lexical floor rejects it and still admits
    'blood pressure medication'. Lexical scoring cannot close that gap; an
    agent-side screening stage over these scored candidates, outside env/ and
    outside this tool, is where it closes. `tests/test_search_scoring.py` pins it
    as a known limitation rather than asserting a property this tool cannot hold.

    Args:
        phrase: Words likely to appear in the question wording.
        limit: Maximum hits to return after near-duplicate collapse. Hits are
            capped at this many; collapsed near-duplicates do not consume a slot.

    Returns:
        A research log. `outcome` is `ok` (more than one term searched AND the
        best hit at or above the floor), `low_confidence` (hits found, but
        either every hit is below the floor or only one term was searched so the
        score cannot discriminate), `no_match` (the wording matched nothing),
        `no_terms` (nothing tokenisable) or `error`, alongside `hits` and the
        query-level fields the return statements below name.
    """
    d = _load()
    con = _fts()
    terms, discarded = _query_terms(phrase)
    dropped = (
        f"DROPPED from the query and never searched: {discarded} — the rewrite "
        f"keeps only alphabetic runs of 3+ characters, so numerals and 1-2 "
        f"character words do not reach the index. " if discarded else "")
    # A one-term query scores every hit that matches it 1.000, because the sole
    # term is the whole denominator — so `below_threshold` and `low_confidence`
    # are structurally unable to fire. 'green space' was correctly flagged at
    # 0.477 while 'space' returned outcome ok at 1.000 on the same phone-number
    # item, and this tool's own re-query advice is what led from one to the other.
    score_discriminates = len(terms) > 1
    base = {"query_terms": terms, "discarded_tokens": discarded,
            "score_floor": SEARCH_SCORE_FLOOR,
            "score_discriminates": score_discriminates}
    if not terms:
        return {**base, "outcome": "no_terms", "n": 0, "hits": [],
                "effective_query": "", "terms_matched_by_no_hit": [],
                "n_matched_items": 0,
                "log": (f"{phrase!r} contains nothing this tool can tokenise, so "
                        f"no search ran. Re-query with words a questionnaire "
                        f"would print.")}

    effective = " OR ".join(f'"{t}"' for t in terms)
    base["effective_query"] = effective
    # Every term is quoted, so a caller word that is an FTS5 keyword — 'AND',
    # 'NEAR' — is a string literal now rather than syntax. That closed the one
    # route a caller could reach this handler by; it stays as a guard on sqlite
    # itself, which is why nothing below reports it as the caller's mistake.
    try:
        rows = con.execute(
            "SELECT key, snippet(v,1,'','','…',12), rank FROM v "
            "WHERE v MATCH ? ORDER BY rank", (effective,)).fetchall()
    except sqlite3.OperationalError as exc:
        return {**base, "outcome": "error", "n": 0, "hits": [],
                "terms_matched_by_no_hit": terms, "n_matched_items": 0,
                "log": f"search rejected: {exc}"}

    n_items = len(d["entries"])
    postings = {t: _postings(con, t) for t in terms}
    idf = {t: _idf(len(postings[t]), n_items) for t in terms}
    total = sum(idf.values())
    scored: list[tuple[float, int, str, str, float, list[str]]] = []
    for order, (key, excerpt, bm25) in enumerate(rows):
        matched = [t for t in terms if key in postings[t]]
        score = (sum(idf[t] for t in matched) / total) if total else 0.0
        # -score first so the sort is score-descending, `order` second so ties
        # keep sqlite's BM25 ordering rather than an arbitrary one.
        scored.append((-score, order, key, excerpt, float(bm25), matched))
    scored.sort()

    hits: list[dict] = []
    representative: dict[str, dict] = {}
    n_collapsed = 0
    for neg, _, key, excerpt, bm25, matched in scored:
        norm = _ROSTER_INDEX.sub("", _BY_KEY[key]["searchable_text"]).strip()
        rep = representative.get(norm)
        if rep is not None:
            rep["collapsed_n"] += 1
            n_collapsed += 1
            if len(rep["collapsed_keys"]) < SEARCH_COLLAPSE_KEYS_SHOWN:
                rep["collapsed_keys"].append(key)
            continue
        if len(hits) >= limit:
            # Deliberately not registered as a representative: past the limit a
            # new wording is not shown, so nothing may be collapsed under it.
            continue
        # Flag on the value RETURNED, not the unrounded one. A hit 0.0004 below
        # the floor would otherwise come back score==score_floor with
        # below_threshold=true — self-contradictory, and red against the
        # bounded-score invariant, which asserts on the rounded value.
        shown = round(-neg, 3)
        hit = {"key": key, "excerpt": excerpt, "score": shown,
               "bm25": round(bm25, 3), "matched_terms": matched,
               "missed_terms": [t for t in terms if t not in matched],
               "below_threshold": shown < SEARCH_SCORE_FLOOR,
               "collapsed_n": 0, "collapsed_keys": []}
        representative[norm] = hit
        hits.append(hit)

    unmatched = [t for t in terms
                 if not any(t in h["matched_terms"] for h in hits)]
    unmatched_note = (
        f"Matched by NO returned hit: {unmatched}. " if unmatched
        else "Every term searched was matched by at least one returned hit. ")
    collapse_note = (
        f"{n_collapsed} near-duplicate item(s) — the same wording under a "
        f"different roster index — were collapsed into the hits shown; see each "
        f"hit's collapsed_n and collapsed_keys. " if n_collapsed else "")

    if not hits:
        return {**base, "outcome": "no_match", "n": 0, "hits": [],
                "terms_matched_by_no_hit": terms, "n_matched_items": 0,
                "log": (f"No item's wording matched any of {terms}. Effective "
                        f"query: {effective}. {dropped}This is an empty LEXICAL "
                        f"result about this wording. It is NOT a finding that "
                        f"the construct is absent from the instrument, and this "
                        f"tool has no standing to make that claim. Re-query with "
                        f"the words a questionnaire would print. If several "
                        f"distinct wordings all come back empty, record that as "
                        f"a blocker rather than naming a key you did not verify.")}

    if not score_discriminates:
        outcome = "low_confidence"
        banner = (
            " — SINGLE-TERM QUERY: every hit matching the one term searched "
            "scores 1.000 by construction, so these scores carry NO confidence "
            "information and the floor cannot fire. Widen the phrase")
    elif hits[0]["below_threshold"]:
        outcome = "low_confidence"
        banner = (
            " — every hit is below the floor: these are LOW-CONFIDENCE "
            "CANDIDATES to screen with resolve_variable(), not confident finds")
    else:
        outcome = "ok"
        banner = ""
    # This log paid ~1,100 characters PER CALL for text that was byte-identical
    # on every call — what `score` and `bm25` are, what the floor and
    # `score_discriminates=false` mean, that a key from here is a candidate.
    # `agent/registry.py::_TOOLS["search_variables"]` says all of it once per
    # prompt, so it was deleted here 2026-08-31 sentence by sentence, each
    # checked as carried there first; `bm25` was the one that was not, and moved.
    # `weak` is conditional because an `ok` page has no below-floor hit for
    # "a result about THIS WORDING" to be about. Mean log over the 224-query
    # fixture: 2,071 -> 892 chars.
    weak = (
        "This is a LOW-CONFIDENCE result about THIS WORDING: this tool cannot "
        "tell you whether the instrument holds the construct, and the hits are "
        "still candidates worth screening. Re-query in the words a "
        "questionnaire would print, SWAPPING the terms reported as matched by "
        "no hit for other wording rather than deleting them — cutting a query "
        "down to one term makes every hit score 1.000 and hides the miss "
        "instead of fixing it. If two or three distinct wordings all come back "
        "low-confidence, STOP RE-QUERYING and call browse_variables to read the "
        "instrument's own wording instead: this tool matches WORDS, so a "
        "construct the questionnaire words differently is invisible to it "
        "however you rephrase. Record a blocker only after browsing has failed "
        "too. " if outcome == "low_confidence" else "")
    return {**base, "outcome": outcome, "n": len(hits), "hits": hits,
            "terms_matched_by_no_hit": unmatched, "n_matched_items": len(rows),
            "log": (
                f"{len(hits)} scored candidate(s) for {phrase!r}{banner}. Terms "
                f"searched: {terms}. Effective query: {effective}. {dropped}"
                f"{len(rows)} item(s) matched at least one term before collapse. "
                f"{collapse_note}{unmatched_note}{weak}"
                f"A score near 1.0 means the WORDS overlap and nothing more — it "
                f"is not evidence that the item measures what you asked about. "
                f"These are CANDIDATES. Do not write any of these keys into a "
                f"protocol without calling resolve_variable() first.")}


# --------------------------------------------------------------------------- #
# browsing — listing the key space instead of searching it
# --------------------------------------------------------------------------- #

#: The three survey modules the built dictionary covers. A closed set, and it is
#: closed on purpose: `browse_variables` is the one tool whose WHOLE return space
#: has to be enumerable, because `contamination_check.py` scans tool return
#: values by sampling them and a tool with an open argument space can only ever
#: be sampled into a corner. Module and section are both drawn from the
#: dictionary itself, so `tool_samples()` can call every page that exists.
#: (`contamination_check.py` is named without its directory on purpose: that
#: directory's name is a forbidden substring in this file and the check that
#: enforces it is a plain grep.)
BROWSE_MODULES = ("1", "2", "3")

#: Largest one browse page may be, measured as the length of the JSON list of
#: rows the caller receives (`listing_chars` in the return value, which excludes
#: the surrounding envelope and the log).
#:
#: DERIVED, not chosen. Two bounds fix it and `tests/test_browse.py` re-derives
#: both against the built dictionary, so it cannot drift into a number nobody
#: can defend:
#:   lower — module 1's complete item-level listing must fit, MEASURED 2026-08-31
#:     at 10,534 characters over build 6fcd02755bf3. That is the module holding
#:     the item a live run spent ~94 brute-force resolve_variable calls locating
#:     after its searches errored, and a browse tool that pages module 1 is a
#:     browse tool that does not fix the thing it was built for.
#:   upper — the constant has to be a true bound on every page this tool can
#:     return, and construct level is the last rung: there is nothing coarser to
#:     fall back to, so a section over budget would be returned anyway and the
#:     name would be a lie. The largest is module 2 section 9 at 20,065
#:     characters, MEASURED the same day.
#: 21,000 is the smallest whole thousand above the second, which is the binding
#: one. It is a PAGE bound, not a total, and most pages are far smaller.
BROWSE_PAGE_BUDGET = 21_000

#: A construct key is `m<module>:Q<section>[.<n>]` for all 1,080 of them —
#: asserted in `tests/test_browse.py`, not assumed — so the leading question
#: number is the questionnaire's own section and needs no separate metadata.
#: The dictionary carries no section field; this is the section, read off the key.
_SECTION_RX = re.compile(r"^m[123]:Q(\d+)")


def _section_of(construct_key: str) -> str:
    """Return the questionnaire section a construct key belongs to.

    Args:
        construct_key: A construct key such as `m2:Q5.8`.

    Returns:
        The section number as a string, or `"?"` for a key that does not carry
        one. `"?"` is a bucket rather than an exception: a key shape the build
        starts emitting should show up as an odd-looking section in a listing,
        not take the whole environment down at import time.
    """
    m = _SECTION_RX.match(construct_key)
    return m.group(1) if m else "?"


def _norm_wording(text: str) -> str:
    """Strip a roster row index off a wording so repeats collapse to one line.

    The same normalisation `search_variables` uses for its near-duplicate
    collapse, and for the same measured reason: one roster battery prints the
    same question once per row, and listing all of them spends the page on the
    duplication rather than on the instrument.

    Args:
        text: Raw `searchable_text`, `stem_text` or `question_text`.

    Returns:
        The wording with any leading `"<n> - "` removed and ends trimmed.
    """
    return _ROSTER_INDEX.sub("", text).strip()


def _chars(rows: list[dict]) -> int:
    """Length of the JSON a caller would receive for these rows.

    `ensure_ascii=False` for the reason `contamination_check._dumps` uses it: the
    instrument contains non-ASCII punctuation, and escaping it measures a string
    nobody is ever sent.

    Args:
        rows: The listing rows.

    Returns:
        Character count of the serialised list.
    """
    return len(json.dumps(rows, ensure_ascii=False))


def _item_rows(entries: list[dict]) -> list[dict]:
    """One row per distinct wording, with a representative key.

    Args:
        entries: Dictionary entries to list.

    Returns:
        Rows carrying `key`, `text` and `n_keys_sharing_wording`, ordered by key.
        Every entry's normalised wording appears in exactly one row.
    """
    by_text: dict[str, list[str]] = {}
    for e in entries:
        by_text.setdefault(_norm_wording(e["searchable_text"]), []).append(e["key"])
    rows = [{"key": sorted(keys)[0], "text": text,
             "n_keys_sharing_wording": len(keys)}
            for text, keys in by_text.items()]
    rows.sort(key=lambda r: str(r["key"]))
    return rows


def _construct_rows(entries: list[dict]) -> list[dict]:
    """One row per construct, labelled by its shared stem.

    Args:
        entries: Dictionary entries to list.

    Returns:
        Rows carrying `construct_key`, `stem` and `n_variables`, ordered by key.
        Every entry's construct appears in exactly one row.
    """
    agg: dict[str, tuple[str, int]] = {}
    for e in entries:
        label = _norm_wording(e["stem_text"] or e["question_text"])
        prev = agg.get(e["construct_key"])
        agg[e["construct_key"]] = (label if prev is None else prev[0],
                                   1 if prev is None else prev[1] + 1)
    return [{"construct_key": k, "stem": v[0], "n_variables": v[1]}
            for k, v in sorted(agg.items())]


def _index_rows(module: str) -> list[dict]:
    """One row per section of a module, with a signpost into it.

    Args:
        module: `"1"`, `"2"` or `"3"`.

    Returns:
        Rows carrying `section`, `n_constructs`, `n_variables` and the first
        construct's key and stem, in questionnaire order.
    """
    rows: list[dict] = []
    for s in browse_sections(module):
        entries = _BY_SECTION[module][s]
        cons = _construct_rows(entries)
        rows.append({"section": s, "n_constructs": len(cons),
                     "n_variables": len(entries),
                     "first_construct_key": cons[0]["construct_key"],
                     "first_stem": cons[0]["stem"]})
    return rows


def browse_sections(module: str) -> list[str]:
    """Every section number a module has, in questionnaire order.

    Public because `contamination_check.py` derives its browse samples from it
    rather than listing them, the way `tool_samples` already derives
    convention topics and derivation ids: a section that appears when the
    codebooks change is then scanned without anyone remembering to edit a table.

    Args:
        module: `"1"`, `"2"` or `"3"`.

    Returns:
        Section numbers as strings, numerically ordered, empty for an unknown
        module.
    """
    _load()
    return sorted(_BY_SECTION.get(module, {}),
                  key=lambda s: int(s) if s.isdigit() else 10**9)


def _browse_arg(value: object, prefix: str) -> str:
    """Normalise a browse argument the way a caller is likely to write it.

    59 of 419 live tool calls died on an argument's NAME alone, so a browse tool
    that also rejected `module='m1'` or `section='Q5'` would be spending the
    caller's turns on punctuation. The prefix is optional on the way in and never
    present on the way out.

    Args:
        value: The caller's raw argument.
        prefix: The single letter a caller may prepend (`m` or `q`).

    Returns:
        The argument lowercased, trimmed and with the prefix removed.
    """
    return str(value).strip().lower().removeprefix(prefix)


@_logged
def browse_variables(module: str, section: str | None = None) -> dict:
    """List what a module contains, instead of searching it for a phrase.

    WHY THIS EXISTS. `search_variables` answers "which wordings match these
    words", and it cannot answer "what is in here" — a construct the caller has
    no vocabulary for is invisible to it, and the recorded consequence was a run
    whose searches errored and which then walked the key space by hand with ~94
    resolve_variable calls. This tool hands the key space over instead.

    EXHAUSTIVE AT ITS LEVEL, which is what makes it different from search. A page
    lists EVERY row at the `level` it reports: every distinct wording of the
    slice at `item`, every construct at `construct`, every section at
    `section_index`. Nothing is ranked, scored, cut off or held back, so an
    absence on an `item` page is a real absence from that slice — unlike a search
    miss, which is a result about one wording. `tests/test_browse.py` checks that
    for every page this tool can return.

    THE LEVEL IS THE ENVIRONMENT'S CHOICE, not the caller's. A slice is listed
    wording by wording when that fits `BROWSE_PAGE_BUDGET`; when it does not, a
    module falls back to its section index and a section falls back to its
    constructs. Module 1 fits whole. Module 2 does not: its 1,464 distinct
    wordings run to roughly 200,000 characters, an order of magnitude over the
    page bound, so it returns sections and then constructs. There is no argument
    for overriding this, because a caller who could ask for the unpaged listing
    would eventually get it.

    A KEY FROM HERE IS A CANDIDATE, never a protocol entry. Call
    resolve_variable() on it first, exactly as with search_variables.

    Args:
        module: `"1"`, `"2"` or `"3"`. A leading `m` is accepted and stripped.
        section: A section number from this module's index, or None for the
            module's own page. A leading `Q` is accepted and stripped.

    Returns:
        A research log. `outcome` is `ok` or `not_found`; `level` is `item`,
        `construct` or `section_index`; `rows` is the listing, `n_rows` its
        length and `listing_chars` the size of `rows` alone as JSON.
    """
    _load()
    mod = _browse_arg(module, "m")
    if mod not in BROWSE_MODULES:
        return {"outcome": "not_found", "module": mod, "section": None,
                "level": "none", "n_rows": 0, "rows": [], "listing_chars": 0,
                "log": (f"{module!r} is not a module of this instrument. The "
                        f"modules are {list(BROWSE_MODULES)}, written as the bare "
                        f"number. Variable keys are prefixed 'm1:', 'm2:', 'm3:'.")}

    if section is None:
        entries = _BY_MODULE[mod]
        rows = _item_rows(entries)
        level = "item"
        if _chars(rows) > BROWSE_PAGE_BUDGET:
            # Straight to the section index, skipping the construct rung: a
            # module-level construct listing measures 92,066 characters for
            # module 2 and 31,141 for module 3, so the rung is over budget for
            # every module that ever reaches it and would only ever add a level
            # the caller has to learn about.
            rows, level = _index_rows(mod), "section_index"
        sect: str | None = None
    else:
        sect = _browse_arg(section, "q")
        if sect not in _BY_SECTION[mod]:
            return {"outcome": "not_found", "module": mod, "section": sect,
                    "level": "none", "n_rows": 0, "rows": [], "listing_chars": 0,
                    "log": (f"module {mod} has no section {sect!r}. Its sections "
                            f"are {browse_sections(mod)}. Call "
                            f"browse_variables(module={mod!r}) for the index with "
                            f"counts and a signpost for each one.")}
        entries = _BY_SECTION[mod][sect]
        rows = _item_rows(entries)
        level = "item"
        if _chars(rows) > BROWSE_PAGE_BUDGET:
            rows, level = _construct_rows(entries), "construct"

    where = f"module {mod}" if sect is None else f"module {mod} section {sect}"
    if level == "item":
        body = (f"Every distinct question wording in {where}, {len(rows)} of "
                f"them, with one key per wording. n_keys_sharing_wording>1 is a "
                f"roster repeat — the same question asked once per person "
                f"listed — and the other keys are found with resolve_variable() "
                f"on the construct.")
    elif level == "construct":
        body = (f"{where} is too large to list wording by wording, so this is "
                f"its {len(rows)} CONSTRUCTS, each with the stem its variables "
                f"share. A construct key is not a variable name: "
                f"resolve_variable() on one returns its member keys.")
    else:
        body = (f"{where} is too large to list wording by wording, so this is "
                f"its {len(rows)} SECTIONS with counts and the first stem in "
                f"each as a signpost. Call "
                f"browse_variables(module={mod!r}, section='<section>') to open "
                f"one. The signpost is the first stem in questionnaire order, "
                f"not a summary of the section.")
    return {
        "outcome": "ok", "module": mod, "section": sect, "level": level,
        "n_rows": len(rows), "rows": rows, "listing_chars": _chars(rows),
        # The 375-char constant tail this log used to carry — what search cannot
        # tell you, the NULL response coding, and "a key from here is a
        # CANDIDATE" — was identical on all 135 pages this tool can return, so
        # it cost 50,625 characters of model-visible surface to say once. It is
        # said once, in agent/registry.py::_TOOLS["browse_variables"]. What is
        # left names THIS page: the level it is complete at, and the slice.
        "log": (f"{body} COMPLETE at level={level}: nothing here is ranked, "
                f"scored or cut off, so a wording absent from this page is "
                f"absent from {where}.")}


@_logged
def registry_coverage() -> dict:
    """Which registries exist, and which are declared-but-empty."""
    _load()
    return {"outcome": "ok",
            "registries": {
                "m1": {"coverage": "populated", "n": 142},
                "m2": {"coverage": "populated", "n": 2326},
                "m3": {"coverage": "populated", "n": 336},
                "clinical": {"coverage": "none", "blocked_on": "study_team_confirmation"},
                "lab": {"coverage": "none", "blocked_on": "study_team_confirmation"},
                "linked": {"coverage": "none", "blocked_on": "area_measure_inventory"},
                "ehr": {"coverage": "none", "blocked_on": "study_team_confirmation"},
            },
            "log": ("The survey registries are populated from the three codebooks. "
                    "The other four are DECLARED AND EMPTY, so naming e.g. "
                    "linked:pm25_annual fails resolution loudly with a named blocker "
                    "rather than being unrepresentable. If the design you were given "
                    "needs one of those, say so in the protocol and set the blocker — "
                    "do not substitute a survey item.")}


# --------------------------------------------------------------------------- #
# conventions and derivations
# --------------------------------------------------------------------------- #

CONVENTION_FILES = {
    "clustering:community_area": "clustering_community_area.md",
    "adjustment_set:area_exposure": "adjustment_set_area_exposure.md",
    "mediator_exclusion": "mediator_exclusion.md",
    "skip_logic_missingness": "skip_logic_missingness.md",
    "small_cells": "small_cells.md",
    "place_level_vs_person_level_claims": "place_vs_person_claims.md",
}


@_logged
def get_design_convention(topic: str) -> dict:
    """Return the canonical text for a design topic.

    Closed domain plus hard constraints plus tools returning canonical text is
    what produced the best result in the one comparable system, and this is the
    highest-leverage artifact in the environment.
    """
    fn = CONVENTION_FILES.get(topic)
    if not fn:
        return {"outcome": "not_found", "available": sorted(CONVENTION_FILES),
                "log": f"No convention for {topic!r}. Available: {sorted(CONVENTION_FILES)}"}
    text = (CURATED / "conventions" / fn).read_text()
    return {"outcome": "ok", "topic": topic, "text": text,
            "log": "Authored, dated, and UNCONFIRMED by the study team. Follow it, "
                   "and if your design departs from it say why in the justification."}


@_logged
def list_derivations() -> dict:
    d = sorted(p.stem for p in (CURATED / "derivations").glob("*.json"))
    return {"outcome": "ok", "derivations": d,
            "log": (f"{len(d)} signed derivations exist. A combined variable must "
                    f"name one of these; inline recipes are forbidden, and the "
                    f"record is REJECTED if the named signed file does not exist "
                    f"or if the reference's component_keys or unit differ from "
                    f"it. If the "
                    f"derivation you need is absent, say so and set status draft — "
                    f"never invent a recipe mid-protocol, and never score a recipe "
                    f"by how strongly it associates with the outcome.")}


@_logged
def get_derivation(derivation_id: str) -> dict:
    p = CURATED / "derivations" / f"{derivation_id}.json"
    if not p.exists():
        return {"outcome": "not_found",
                "log": f"No signed derivation {derivation_id!r} in curated/derivations/."}
    return {"outcome": "ok", **json.loads(p.read_text())}


# --------------------------------------------------------------------------- #
# estimability — degraded, and honest about it
# --------------------------------------------------------------------------- #

@_logged
def estimate_n(keys: list[str]) -> dict:
    """Analytic n for a set of variables. DEGRADED: returns unknown for any
    cross-module set, because module co-completion counts do not exist.

    This is not a placeholder to be improved by guessing. When the counts arrive
    from the study team, n_source switches to computed_from_counts, n enters the
    ordering, and the parked set is re-run. Nothing else changes.
    """
    _load()
    modules = sorted({k.split(":")[0] for k in keys if k.split(":")[0].startswith("m")})
    if len(modules) <= 1:
        return {"outcome": "ok", "analytic_n": None, "n_source": "unknown",
                "modules_required": modules,
                "log": ("Single-module set. Per-item non-missing counts have not been "
                        "supplied either, so analytic_n stays null. Set "
                        "n_source='unknown' and blocked_on "
                        "['per_item_non_missing_counts'].")}
    return {"outcome": "ok", "analytic_n": None, "n_source": "unknown",
            "modules_required": modules,
            "blocked_on": "module_co_completion_counts",
            "log": (f"Cross-module set spanning {modules}. Module co-completion counts "
                    f"do not exist, so analytic_n is NULL and n_source is 'unknown'. "
                    f"Set blocked_on ['module_co_completion_counts']. Do NOT derive an "
                    f"n from cohort size — a fabricated n is worse than an admitted "
                    f"gap, and this protocol cannot reach ready_for_review.")}


# AUTHORED evaluation grid, and nothing else. A 1-3-10 logarithmic decade
# series: the smallest detectable effect falls as 1/sqrt(n), so equal-RATIO
# spacing is what makes the curve's shape readable, and three decades bracket any
# analytic n this instrument could plausibly yield instead of approximating one.
#
# It is deliberately a series with no empirical referent. The previous default
# ended in a realised analytic n lifted from a published analysis of this very
# cohort, so a tool the model calls handed back one of the numbers the model is
# supposed to reason without — and the scan that should have caught it never
# called this tool. There is no instrument-derived alternative to reach for:
# every count in build/dictionary.json counts ITEMS, not participants, and
# borrowing one of those as an n would be a category error dressed as provenance.
#
# A candidate n at which to EVALUATE a formula is not an asserted analytic n. The
# log line below has to say so, because a grid of round numbers cannot.
#
# THE GRID IS THE ENVIRONMENT'S, NOT THE CALLER'S. Scrubbing this constant was
# only half a fix while `n_values` stayed a caller argument in the schema: the
# one real record called estimate_detectability with n_values=[50,...,300], took
# the 37.8 pp floor at n=50 for a cohort of thousands, and wrote a 40 pp
# "falsifier" just above it. A floor a caller chooses is not a floor. The
# parameter is gone from agent/registry.py's schema; the sink below exists only
# so a caller that guesses the argument anyway gets a refusal in the log instead
# of a TypeError that would fail the whole gate.
DETECTABILITY_N_GRID: tuple[int, ...] = (100, 300, 1000, 3000, 10000)

# p(1-p) is maximised at one half, so this is the prevalence at which the
# smallest detectable effect is LARGEST. baseline_prevalence is asserted by the
# caller and unverifiable here — no response data exists in this project, and
# value_labels are null for every item — so a caller that understates it shrinks
# its own floor. Reporting the curve at this prevalence alongside removes the
# incentive: the bound holds whatever the true prevalence turns out to be.
#
# 2026-08-27: reporting it alongside was only half the fix, because the gate was
# still comparing against the asserted curve. MEASURED over run/*.tool_log.jsonl
# — 10 saved runs, one estimate_detectability call each, every one of them for
# the same hypertension outcome: the caller chose 0.35 five times and 0.25, 0.28,
# 0.30, 0.32 and 0.40 once each. sde is proportional to sqrt(p(1-p)), so that
# spread is a 13.1% swing in the floor the caller is then judged against, and
# nothing in the environment supplies a prevalence it could have used instead. So
# the comparator is now the curve below and the asserted value is demoted to a
# labelled assumption on the record. The log says which curve is judged, because
# a tool whose text describes the previous contract is indistinguishable to the
# caller from one that still implements it.
WORST_CASE_PREVALENCE: float = 0.5

# 2026-08-27, SECOND HALF OF THE SAME DEFECT. Fixing the prevalence was not
# enough, because the bound took z_a and z_b from the CALLER's alpha and power
# and used them for both curves. MEASURED on the code as it stood, floor at
# n=1000: the supposedly caller-independent bound fell from 8.86 pp at
# alpha=0.05/power=0.80 to 4.05 at 0.20/0.50 and to 2.13 at 0.50/0.50 — a 76%
# reduction, six times what the prevalence lever ever bought, through arguments
# the schema was advertising. The tool's own log meanwhile said the bound "does
# not depend on anything you assert", which was false.
#
# alpha and power are the easiest of these to close, because they are NOT
# unknowns. There is no true significance level to be ignorant of; they are
# conventions, so the environment can simply fix them, exactly as it fixed the n
# grid. The caller's values still shape `sde_by_n` — that is its disclosed
# reasoning and it is not the bar — and they are recorded in `assumptions` so the
# disclosure stays auditable.
BOUND_ALPHA: float = 0.05
BOUND_POWER: float = 0.80


def _sde_curve(p: float, z_a: float, z_b: float) -> list[dict]:
    """Smallest detectable difference in proportions, at each n on the grid.

    Args:
        p: Assumed outcome prevalence in the reference arm, strictly 0-1.
        z_a: Normal deviate for the two-sided significance level.
        z_b: Normal deviate for the target power.

    Returns:
        One `{n, sde_percentage_points}` row per n in DETECTABILITY_N_GRID.
    """
    return [{"n": n,
             "sde_percentage_points": round(
                 (z_a + z_b) * math.sqrt(2 * p * (1 - p) / (n / 2)) * 100, 2)}
            for n in DETECTABILITY_N_GRID]


@_logged
def estimate_detectability(baseline_prevalence: float, alpha: float = 0.05,
                           power: float = 0.80,
                           n_values: list[int] | None = None) -> dict:
    """Smallest detectable effect as a CURVE across candidate n, not a scalar.

    Computable from formulas alone; needs no data. This is what lets the field
    stay honest while n is unknown.

    Args:
        baseline_prevalence: Assumed outcome prevalence, strictly between 0 and
            1. Caller's input, not a measured quantity of this cohort, and not
            the value the falsifier gate compares against — it shapes `sde_by_n`,
            which is disclosure, while `sde_by_n_worst_case_prevalence` is the
            bound the record is judged on.
        alpha: Two-sided significance level, strictly between 0 and 1. HONOURED
            for `sde_by_n` — the caller's deviate is computed from it — and
            IGNORED for the bound, which uses BOUND_ALPHA. Not advertised in the
            model-visible schema; see agent/registry.py for why. It used to be
            accepted, ignored entirely, and then echoed back in `assumptions` as
            though it had been used, which was a different bug in the same field.
        power: Target power, strictly between 0 and 1. Same treatment as alpha.
        n_values: REFUSED. The grid is DETECTABILITY_N_GRID and is owned by the
            environment; a value here is recorded and discarded, never used.

    Returns:
        A research log carrying the curve, the worst-case bound, the assumption
        set it was computed under, and an explicit statement that the grid is not
        an n claim. `outcome` is `invalid_input` when a parameter is out of
        range, rather than a bare traceback from `sqrt` of a negative number.
    """
    for name, v in (("baseline_prevalence", baseline_prevalence),
                    ("alpha", alpha), ("power", power)):
        if not 0 < v < 1:
            return {"outcome": "invalid_input", "parameter": name, "value": v,
                    "log": (f"{name}={v!r} is not strictly between 0 and 1, so no "
                            f"curve was computed. Nothing here is a measured "
                            f"quantity of this cohort; supply a stated assumption "
                            f"in range and label it as an assumption.")}

    # The CALLER's deviates, for the caller's own curve only.
    z_a: float = NormalDist().inv_cdf(1 - alpha / 2)
    z_b: float = NormalDist().inv_cdf(power)
    # The ENVIRONMENT's, for the bound. Not derived from anything the caller
    # passed, which is the whole property the bound is supposed to have and did
    # not have until 2026-08-27.
    zb_a: float = NormalDist().inv_cdf(1 - BOUND_ALPHA / 2)
    zb_b: float = NormalDist().inv_cdf(BOUND_POWER)
    bound = _sde_curve(WORST_CASE_PREVALENCE, zb_a, zb_b)
    out: dict = {
        "outcome": "ok",
        "sde_by_n": _sde_curve(baseline_prevalence, z_a, z_b),
        # The name is historical and narrower than the guarantee: this curve is
        # now fixed in prevalence AND in alpha and power. Kept as the key the
        # falsifier gate already binds to; `sde_by_n_environment_bound` below is
        # the same list under an accurate name, and the alias should be dropped
        # once the gate is switched over.
        "sde_by_n_worst_case_prevalence": bound,
        "sde_by_n_environment_bound": bound,
        "assumptions": {"two_sided_alpha": alpha, "power": power,
                        "z_alpha": round(z_a, 6), "z_beta": round(z_b, 6),
                        "baseline_prevalence": baseline_prevalence,
                        "worst_case_prevalence": WORST_CASE_PREVALENCE,
                        "bound_alpha": BOUND_ALPHA, "bound_power": BOUND_POWER,
                        "allocation": "1:1",
                        "test": "two-proportion normal approximation"},
        "n_grid_source": "environment",
        "bound_parameter_source": "environment",
        # Item 2, 2026-08-27. The formula below assumes independent
        # observations. The design convention this environment serves instructs
        # the model to cluster. Both statements are true, they disagree, and the
        # disagreement has a direction — so the tool states it rather than
        # letting the floor quietly under-report itself.
        "independence_assumption": {
            "assumes": "independent observations",
            "design_convention_requires": "cluster-robust standard errors at "
                                          "the community area",
            "direction_of_error": "clustering INFLATES the true smallest "
                                  "detectable effect, so this floor is too LOW "
                                  "and errs toward accepting a falsifier the "
                                  "study could not actually falsify",
            "correction_formula": "design effect = 1 + (m - 1) * ICC",
            "correction_available": False,
            "blocked_on": "design_effect_for_community_area_clustering",
        },
        "log": ("Report the value at your stated n, or the whole curve where n is "
                "unknown. TWO CURVES ARE RETURNED AND THEY ARE NOT "
                "INTERCHANGEABLE. sde_by_n is computed at the "
                "baseline_prevalence YOU supplied; it is your disclosed "
                "reasoning and it is not the bar. sde_by_n_environment_bound "
                "(also returned under its older name "
                "sde_by_n_worst_case_prevalence) is computed at the prevalence "
                "that maximises the floor AND at the environment's fixed "
                "significance level and power, so it is derived from nothing you "
                "pass, and IT IS THE CURVE THE RECORD IS JUDGED AGAINST: a "
                "falsifier threshold below that curve at the n you name cannot "
                "be falsified by this study and the record is rejected. "
                "[unverified] baseline_prevalence is an assumption you supplied "
                "and nothing here can check it — no response data exists in this "
                "project — so it is never treated as a measured quantity of this "
                "cohort, it does not set the bar, and the record carries it as a "
                "labelled unverified assumption. alpha and power are conventions, "
                "not unknowns: whatever you pass shapes your own curve and is "
                "recorded in assumptions, but the bound uses the environment's "
                "fixed values, so loosening them cannot lower the bar. "
                "INDEPENDENCE: every number here assumes independent "
                "observations, while the clustering convention requires "
                "cluster-robust standard errors at the community area. Those "
                "disagree. Clustering inflates the true smallest detectable "
                "effect, so this floor is too LOW, and the correction "
                "1 + (m - 1) * ICC cannot be computed here — participants per "
                "community area are unknown for the same reason analytic n is, "
                "and the intracluster correlation would need response data. "
                "Carry blocked_on "
                "['design_effect_for_community_area_clustering'] on any record "
                "whose model clusters, do not substitute a design effect from "
                "anywhere else, and treat clearing this floor as necessary and "
                "not sufficient. The n grid is an AUTHORED evaluation "
                "grid fixed by the environment, not a set of sample sizes this "
                "study is known to reach and not yours to choose: analytic n is "
                "unknown until estimate_n() can return one, so do not copy an n "
                "off this curve into analytic_n. NO point on this grid is a "
                "claim about this study's sample size — not the largest as a "
                "cohort size, and not the smallest as a lower bound on the n "
                "this study realises."),
    }
    if (alpha, power) != (BOUND_ALPHA, BOUND_POWER):
        out["bound_parameters_unaffected_by"] = {"alpha": alpha, "power": power}
        out["log"] += (f" You passed alpha={alpha}, power={power} rather than the "
                       f"conventional {BOUND_ALPHA}/{BOUND_POWER}. That is "
                       f"recorded and it shapes sde_by_n, your own curve. It does "
                       f"NOT touch the bound, which is fixed at "
                       f"{BOUND_ALPHA}/{BOUND_POWER}: a significance level is a "
                       f"convention, not something this study could be ignorant "
                       f"of, so choosing one cannot move the bar in either "
                       f"direction.")
    if n_values is not None:
        out["n_grid_refused"] = list(n_values)
        out["log"] += (f" Your n_values={list(n_values)} was DISCARDED. The grid "
                       f"a detectable effect is measured on is the environment's "
                       f"and is fixed at {list(DETECTABILITY_N_GRID)}; choosing "
                       f"the n makes the floor an assumption rather than a "
                       f"measurement.")
    return out


@_logged
def get_contrast_convention(key_or_kind: str) -> dict:
    """A stated design contrast, from a convention — not from data."""
    kind = key_or_kind.lower()
    if "likert" in kind or "agree" in kind:
        c = "highest versus lowest Likert category"
    elif "scale" in kind or "derivation" in kind:
        c = "highest versus lowest quintile of the derived scale"
    elif "binary" in kind or "ever" in kind:
        c = "yes versus no"
    else:
        c = "per one standard-deviation increase"
    return {"outcome": "ok", "exposure_contrast": c,
            "log": (f"Stated contrast: '{c}'. This is a DESIGN choice from a "
                    f"convention document, not an empirical property — no data has "
                    f"been examined and no distribution is known.")}


@_logged
def check_access(keys: list[str]) -> dict:
    """Location-reconstruction risk. Returns its working, not just a verdict.

    Precision is grouped by the PLACE being located, the finest precision taken
    per place, then summed across places — because residence-tract plus
    residence-ZIP narrows to one area, while residence-tract plus workplace-ZIP
    narrows to an area AND a building, and additive scoring calls those equal.

    AN EXCLUSION IS INDISTINGUISHABLE FROM AN ADJUSTMENT HERE: a flat key list
    comes in and every location-bearing key in it is charged. Excluded variables
    consume no budget because the CALLER DOES NOT PASS THEM, and
    `agent/tool_authority.py` binds that by not requiring `excluded_variables`
    keys in this call. Until 2026-08-31 this docstring claimed the exclusion was
    checked HERE, with a `measures` parameter as the alibi — AST-parsed, it was
    read ZERO times in the body. `tests/test_env_tools.py::
    test_no_tool_accepts_a_parameter_it_ignores` fails on any such argument now.

    Args:
        keys: Every key the protocol names in a position that uses it.

    Returns:
        A research log carrying `decision`, `reconstruction_load`, `budget`, the
        location-bearing and unknown-origin keys, and the per-place working.
    """
    _load()
    LOCATION_RX = re.compile(
        r"street address|zip|postal|what city|neighborhood you live|"
        r"employer|school address|census|community area", re.I)
    per_place: dict[str, list[str]] = {}
    unknown_origin = []
    for k in keys:
        e = _BY_KEY.get(k)
        if e is None:
            unknown_origin.append(k)
            continue
        if LOCATION_RX.search(e["question_text"]):
            place = "workplace" if re.search(r"employer|work", e["question_text"], re.I) \
                else "school" if re.search(r"school", e["question_text"], re.I) else "residence"
            per_place.setdefault(place, []).append(k)
    load = len(per_place)
    budget = 3  # named config value, never a literal in a caller
    decision = "pass" if load <= budget and not unknown_origin else "refer"
    return {"outcome": "ok", "decision": decision, "reconstruction_load": load,
            "budget": budget, "location_bearing_keys": sorted(
                k for ks in per_place.values() for k in ks),
            "origin_unknown_keys": unknown_origin,
            "per_place_working": (
                "; ".join(f"{p}: {sorted(v)}" for p, v in per_place.items())
                or "no location-bearing variable named"),
            "log": (f"decision={decision}, load={load}/{budget}. Every key passed is "
                    f"charged: an exclusion is indistinguishable from an adjustment "
                    f"here, so excluded keys escape the budget only by not being "
                    f"passed. origin_unknown is a DISTINCT state, never a default — "
                    f"any key listed there must be resolved before this gate means "
                    f"anything.")}


TOOLS: dict[str, Callable] = {
    "resolve_variable": resolve_variable,
    "search_variables": search_variables,
    "browse_variables": browse_variables,
    "get_item_group": get_item_group,
    "registry_coverage": registry_coverage,
    "get_design_convention": get_design_convention,
    "list_derivations": list_derivations,
    "get_derivation": get_derivation,
    "estimate_n": estimate_n,
    "estimate_detectability": estimate_detectability,
    "get_contrast_convention": get_contrast_convention,
    "check_access": check_access,
}
