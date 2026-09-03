from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from agent import query_rewrite as QR
from env import tools

# --------------------------------------------------------------------------- #
# the rewriter is corpus-blind, and that is a property of the signature
# --------------------------------------------------------------------------- #

# Names that could carry a hit, a wording, a key or a score into the prompt. The
# rewriter may reference none of them, so no measured artefact of the corpus can
# reach the model that writes the phrasings — which is what keeps this stage from
# reproducing the fixture's KNOWN_BIAS in a second place.
CORPUS_NAMES = ("tools", "search_variables", "searchable_text", "question_text",
                "dictionary", "_BY_KEY", "hits", "gold")


def test_the_rewriter_cannot_see_the_corpus():
    """The seal is the signature, not a sentence in the docstring.

    `rewrite` takes a request, a model and a count. None of those can carry a
    retrieved wording, so the leak this stage is most exposed to — writing a
    phrasing against the item the search already found — is unrepresentable
    rather than discouraged.
    """
    params = list(inspect.signature(QR.rewrite).parameters)
    assert params == ["request", "model", "n"], (
        f"rewrite's parameters are {params}; a fourth one is how corpus text "
        f"reaches the rewriting model")

    body = next(n for n in ast.parse(Path(QR.__file__).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == "rewrite")
    named = {n.id for n in ast.walk(body) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(body) if isinstance(n, ast.Attribute)}
    leaked = named & set(CORPUS_NAMES)
    assert not leaked, f"rewrite references {sorted(leaked)}"


def test_only_the_rewriter_talks_to_the_model():
    """One call site, so the model-visible surface of this stage is one string.

    A second function taking a `ModelFn` would be a second prompt, and a scan
    over `REWRITE_PROMPT` would then be a scan over a prompt this stage does not
    only send.
    """
    takes_model = sorted(
        name for name, fn in vars(QR).items()
        if inspect.isfunction(fn) and "model" in inspect.signature(fn).parameters)
    assert takes_model == ["rewrite"], takes_model


def test_the_prompt_carries_no_instrument_wording():
    """The prompt is model-visible surface and the instrument is the answer key.

    Checked as five-word runs rather than by eye, over collapsed whitespace,
    because a codebook breaks phrases across lines — `AGENTS.md` §Testing
    Patterns. An example phrasing lifted from a question would hand the rewriter
    the wording it is supposed to reach independently.
    """
    def grams(text: str, n: int = 5) -> set[tuple[str, ...]]:
        w = " ".join(text.lower().split()).split()
        return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}

    corpus: set[tuple[str, ...]] = set()
    for e in tools._load()["entries"]:
        corpus |= grams(str(e["searchable_text"]))
    shared = grams(QR.REWRITE_PROMPT.body) & corpus
    assert not shared, f"the prompt repeats instrument wording: {sorted(shared)}"


# --------------------------------------------------------------------------- #
# parsing: a malformed reply degrades to the control arm, never to an error
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw", [
    "",
    "I cannot help with that.",
    '{"phrasings": "not a list"}',
    '{"other": ["a b", "c d"]}',
    "```json\n{\n```",
])
def test_an_unparseable_reply_falls_back_to_the_request_itself(raw):
    r = QR.rewrite("household size", lambda _p: raw)
    assert r.malformed is True
    assert r.phrasings == ("household size",)
    assert r.raw == raw, "the reply is kept verbatim so a report can show it"


@pytest.mark.parametrize("raw", [
    '{"phrasings": ["how many people live here", "who lives with you"]}',
    '```json\n{"phrasings": ["how many people live here", "who lives with you"]}\n```',
    'Here you go:\n{"phrasings": ["how many people live here", '
    '"who lives with you"]}\nHope that helps.',
])
def test_a_fenced_or_chatty_reply_still_parses(raw):
    """The CLI backend has no grammar enforcement and says so; this is the cost."""
    r = QR.rewrite("household size", lambda _p: raw)
    assert r.malformed is False
    assert r.added == ("how many people live here", "who lives with you")


def test_repeats_and_blanks_are_dropped_but_the_request_survives():
    raw = json.dumps({"phrasings": ["Household Size", "  ", "household size",
                                    "how many people live here"]})
    r = QR.rewrite("household size", lambda _p: raw)
    assert r.phrasings == ("household size", "how many people live here"), (
        "a case-variant repeat of the request is not a second phrasing")


# --------------------------------------------------------------------------- #
# fusion
# --------------------------------------------------------------------------- #

FUSIONS = (QR.min_rank_fusion, QR.rrf_fusion)


@pytest.mark.parametrize("fuse", FUSIONS)
def test_fusion_returns_every_key_any_ranking_held(fuse):
    fused = fuse([["a", "b"], ["c"], ["b", "d"]])
    assert sorted(fused) == ["a", "b", "c", "d"]
    assert len(fused) == len(set(fused)), "a key appearing twice is a double slot"


@pytest.mark.parametrize("fuse", FUSIONS)
def test_fusion_is_a_total_order_and_reproducible(fuse):
    rankings = [["a", "b", "c"], ["c", "a"], ["d", "a"]]
    assert fuse(rankings) == fuse(rankings)


def test_min_rank_keeps_a_first_place_hit_in_first_place():
    """The property the stage is built on: another phrasing may not bury a find.

    Fusing on the mean or the sum does not hold this — a key one phrasing ranks
    first and three never mention averages away, and that is exactly the shape a
    vocabulary bridge produces.
    """
    fused = QR.min_rank_fusion([["gold"], ["x", "y", "z"], ["x", "y"]])
    assert fused[0] == "gold"


def test_min_rank_breaks_a_tie_on_the_earlier_stream():
    """The request is stream 0, so its answer survives every tie.

    Agreement across phrasings is NOT the tie-break, deliberately: two invented
    phrasings agreeing with each other would otherwise outrank what the shipped
    search returned first, and this arm's safety property is that it can only
    add. `rrf_fusion` is the arm that rewards agreement.
    """
    assert QR.min_rank_fusion([["a"], ["b"], ["b"]]) == ["a", "b"]
    assert QR.rrf_fusion([["a"], ["b"], ["b"]]) == ["b", "a"]


# --------------------------------------------------------------------------- #
# the candidate-set callable
# --------------------------------------------------------------------------- #

def _recording_search(order: dict[str, list[str]]) -> tuple:
    """A stub `search_variables` returning a scripted ranking per phrase."""
    seen: list[str] = []

    def search(phrase: str, limit: int) -> dict:
        seen.append(phrase)
        keys = order.get(phrase, [])[:limit]
        return {"hits": [{"key": k} for k in keys], "outcome": "ok",
                "n_matched_items": len(keys)}
    return search, seen


def test_the_request_is_searched_first_and_always():
    """The stage may only ADD reachability.

    A row the shipped search already answers cannot be made unreachable by a
    phrasing the model invented, because the request's own ranking is always one
    of the streams — and it is the first, so it wins every tie.
    """
    search, seen = _recording_search({"req": ["gold"], "p1": ["junk"]})
    arm = QR.RewriteSearch({"req": ["p1"]}, cap=10, search=search)
    out = arm("req", 10)
    assert seen[0] == "req"
    assert out["hits"][0]["key"] == "gold"
    assert out["phrasings"] == ["req", "p1"]


def test_a_request_absent_from_the_artifact_degrades_to_the_control_arm():
    """A partial artifact is a smaller improvement, never an error."""
    search, seen = _recording_search({"req": ["gold", "other"]})
    arm = QR.RewriteSearch({}, cap=10, search=search)
    out = arm("req", 10)
    assert seen == ["req"]
    assert [h["key"] for h in out["hits"]] == ["gold", "other"]


def test_the_cap_truncates_and_the_pre_cap_size_is_reported():
    """A truncating default is a cutoff, not a preference (`AGENTS.md`)."""
    search, _ = _recording_search({"req": ["a", "b", "c", "d"]})
    arm = QR.RewriteSearch({}, cap=2, search=search)
    out = arm("req", 10)
    assert [h["key"] for h in out["hits"]] == ["a", "b"]
    assert out["pool_before_cap"] == 4
    assert arm.pool_sizes["req"] == 4


def test_the_cap_says_what_it_costs():
    """`POOL_CAP` is derived from a measured table, not chosen.

    The table is what makes the cap auditable: it names, for every candidate
    value, how many rows that value turns back into excluded ones.
    """
    assert QR.POOL_CAP in QR.POOL_CAP_COST, (
        "the shipped cap is not in the cost table, so its cost is unstated")
    assert QR.POOL_CAP_COST[QR.POOL_CAP] == 0, (
        "the shipped cap costs rows; C16's acceptance figure is gold_excluded 0")
    caps = sorted(QR.POOL_CAP_COST)
    costs = [QR.POOL_CAP_COST[c] for c in caps]
    assert costs == sorted(costs, reverse=True), (
        f"cost must not rise as the cap grows: {dict(zip(caps, costs, strict=True))}")


def test_the_arm_names_its_fusion_so_two_arms_cannot_be_reported_as_one():
    search, _ = _recording_search({})
    assert "min_rank" in QR.RewriteSearch({}, search=search).__name__
    assert "rrf" in QR.RewriteSearch(
        {}, fusion=QR.rrf_fusion, search=search).__name__


def test_the_outcome_label_is_reported_but_never_a_stopping_signal():
    """Task 0's finding, encoded.

    9 of the 34 fixture rows whose gold item is already at rank 1 come back
    `low_confidence`, so this arm records the label and branches on nothing. The
    guard is structural: no comparison against a confidence label or the score
    floor appears anywhere in this module.
    """
    source = Path(QR.__file__).read_text()
    tree = ast.parse(source)
    compared = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "SEARCH_SCORE_FLOOR" not in compared
    assert "below_threshold" not in source, (
        "reading below_threshold is one edit away from branching on it")
