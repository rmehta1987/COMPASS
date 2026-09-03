"""C16's rewrite stage: the researcher's words, restated as a questionnaire's words.

WHY THIS EXISTS. `DESIGN.md` §7 assigns the vocabulary gap — "age" against
"birthday" — to an agent-side stage OUTSIDE `env/`, because closing it is
semantics and `env/` may not load a model. This is that stage. It does not
change retrieval and it must not: it produces PHRASINGS, hands each one to
`env.tools.search_variables` unchanged, and fuses the rankings that come back.

WHAT IT OWNS, and the figure it is gated on. Measured 2026-09-02 over build
3dc8415eccfe, 18 of the committed fixture's 224 rows had their gold wording at
NO rank under the fixture's own request string. Every one of those 18 was shown
reachable under some hand-written rephrasing, so the population a corpus change
could serve is empty and the whole of the defect is vocabulary. `gold_excluded
18/224 -> 0/224` is this module's acceptance figure. Recall@k is NOT: 91 rows
sit in the pool below rank 10 under a good phrasing, and those belong to the
screening stage, which reads deeper rather than ranking better.

WHAT IT REUSES. Retrieval is `env.tools.search_variables`, untouched. The
prompt contract is `agent.specifier.PromptTemplate`, so this template's variable
list is parsed from its own body by the formatter that renders it. The model
seam is the one-argument `(prompt) -> raw text` callable
`benchmark.resolver_eval.ModelFn` already defines; it is restated here rather
than imported so that `agent/` does not depend on `benchmark/`.

THE REWRITER IS CORPUS-BLIND, BY CONSTRUCTION. `rewrite` takes a request string,
a model and a count, and nothing else. No hit, no wording, no key and no score
can reach the model, because no parameter can carry one — which is the property
`tests/test_query_rewrite.py::test_the_rewriter_cannot_see_the_corpus` reads off
the signature rather than off this sentence. That matters twice: it is what
keeps the measurement from reproducing the fixture's own KNOWN_BIAS in a second
place, and it is what makes the whole model-visible surface of this stage one
rendered string.

NO EXAMPLE PHRASINGS IN THE PROMPT. The obvious way to teach a small model what
a questionnaire sounds like is to show it one, and every candidate example this
prompt could carry is either instrument wording or close enough to it to be
indistinguishable in a leak scan. The rules below are therefore abstract, and
the cost is real: a weaker model gets less help. `AGENTS.md` §Contamination
Practice — control by selection, in code, never by an instruction naming the
thing to avoid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from agent.specifier import PromptTemplate

#: `(prompt) -> raw model text`. One argument, for the reason
#: `benchmark/resolver_eval.py::ModelFn` states: every instruction this stage
#: gives is inside the prompt, which is what makes its model-visible surface a
#: single scannable string.
ModelFn = Callable[[str], str]

#: How many alternative phrasings one request is asked for. Four is the number
#: the reachability partition of 2026-09-02 was measured with, kept so the
#: ceiling that partition reported stays the comparable figure.
N_PHRASINGS = 4

#: The most candidates a fused pool may carry. The SMALLEST measured cap that
#: costs no row its gold wording — chosen off `POOL_CAP_COST`, not picked. It
#: truncates: the median fused pool holds 1,804 candidates, so most rows lose
#: their tail, and what that tail costs is the table below.
POOL_CAP = 1100

#: cap -> rows of 224 whose gold wording falls outside the pool at that cap.
#: MEASURED 2026-09-02 over build 3dc8415eccfe, the committed 224-row fixture,
#: `claude-haiku-4-5` rewrites at prompt 90cd5cca85ad, `min_rank_fusion` — the
#: SHIPPED arm; `rrf_fusion` reaches zero at 800 and is not what this table
#: describes. Recorded because a truncating default is a cutoff, not a
#: preference (`AGENTS.md` §Testing Patterns): the cap is the one number here
#: that can turn a reachable row back into an excluded one with no retrieval
#: changing at all, and at 500 it costs 11 of them.
POOL_CAP_COST: dict[int, int] = {
    10: 101, 25: 76, 50: 49, 100: 32, 250: 20, 500: 11, 600: 8, 700: 2,
    900: 1, 1000: 1, 1100: 0, 1500: 0, 2804: 0,
}

#: Reciprocal-rank-fusion's rank offset. The conventional 60, carried as a
#: constant because it is a tuning knob and an unnamed one drifts.
RRF_K = 60

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class Phrasings(BaseModel):
    """Alternative ways of asking for the same variable.

    Attributes:
        phrasings: Each way of asking, in the words a questionnaire would print.
    """

    phrasings: list[str] = Field(
        description="Each alternative way of asking for the same thing.")


REWRITE_PROMPT = PromptTemplate(
    name="query_rewrite",
    body="""A researcher has asked for one variable, in their own words. Write \
{n} other ways of asking for the SAME variable, in the words a self-report \
questionnaire would actually print on the page.

The request:

  {request}

Rules.

- Write what the QUESTION would say, not what a variable would be called. A
  questionnaire prints a sentence addressed to the person answering it; a
  codebook prints a label. You are writing the sentence.
- Expand every abbreviation, acronym and initialism. Whatever they stand for,
  write it out in full words.
- Prefer the vocabulary of the person answering over the vocabulary of the
  person analysing: everyday words, not technical or clinical ones.
- Make the {n} phrasings differ from each other. Rewordings that share most of
  their words are one phrasing, not several. Change the vocabulary, change how
  specific it is, and change the grammatical form.
- Do not answer the request. Do not name, guess at or invent a variable, a code,
  an identifier or a questionnaire item. Do not say which phrasing you prefer.

Emit one JSON object matching this schema and nothing else. No prose, no
markdown fence, no commentary.

{schema}""")


@dataclass(frozen=True)
class Rewrite:
    """One request and the phrasings a model returned for it.

    Attributes:
        request: The researcher's words, exactly as they arrived.
        phrasings: The model's phrasings, deduplicated, with the request itself
            first. Never empty: a request that fails to parse still searches.
        malformed: True when the model's text could not be parsed into the
            schema, so `phrasings` fell back to the request alone.
        raw: The model's text, kept verbatim so a report can show what was said
            rather than what was recovered.
    """

    request: str
    phrasings: tuple[str, ...]
    malformed: bool = False
    raw: str = ""

    @property
    def added(self) -> tuple[str, ...]:
        """The phrasings the model contributed, without the original request.

        Returns:
            Every phrasing after the first.
        """
        return self.phrasings[1:]


def _dedupe(phrases: Iterable[str]) -> tuple[str, ...]:
    """Drop blanks and case-insensitive repeats, keeping first-seen order.

    Args:
        phrases: Phrasings in the order they were produced.

    Returns:
        The surviving phrasings, stripped.
    """
    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        t = " ".join(str(p).split())
        if not t or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return tuple(out)


def parse_phrasings(raw: str) -> tuple[str, ...] | None:
    """Recover the phrasings from a model's reply.

    Tolerant of a markdown fence and of surrounding prose, because the CLI
    backend has no grammar enforcement and `agent/cli_backend.py` names that as
    an accepted, unenforced degradation. Tolerant of nothing else: a reply whose
    JSON does not match the schema is a malformed reply, not a reply to repair
    by guessing.

    Args:
        raw: The model's text.

    Returns:
        The phrasings, or None when the text carries no schema-shaped object.
    """
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = Phrasings.model_validate_json(text[start:end + 1])
    except ValueError:
        return None
    return _dedupe(parsed.phrasings)


def rewrite(request: str, model: ModelFn, n: int = N_PHRASINGS) -> Rewrite:
    """Ask a model for other ways of asking for the same variable.

    One call. There is no confidence-driven re-query loop here, and that is a
    decision rather than an omission: measured 2026-09-02 over the committed
    fixture, 9 of the 34 rows whose gold item is already at rank 1 come back
    `low_confidence`, so the label cannot be a stopping signal for this
    population — and `tests/test_search_scoring.py::
    test_dropping_the_unmatched_term_does_not_turn_a_flagged_miss_into_a_find`
    records where iterating on it leads: the same item, a better label, no
    better answer.

    Args:
        request: The researcher's words. The ONLY corpus-derived thing that may
            reach the model, and it is not corpus-derived — it is the caller's.
        model: The `(prompt) -> raw text` seam.
        n: How many phrasings to ask for.

    Returns:
        The request, its phrasings and whether the reply parsed.
    """
    prompt = REWRITE_PROMPT.render(
        request=request, n=n,
        schema=json.dumps(Phrasings.model_json_schema(), indent=2))
    raw = model(prompt)
    got = parse_phrasings(raw)
    if got is None:
        return Rewrite(request=request, phrasings=(request,), malformed=True,
                       raw=raw)
    return Rewrite(request=request, phrasings=_dedupe((request, *got)), raw=raw)


def min_rank_fusion(rankings: Sequence[Sequence[str]]) -> list[str]:
    """Fuse rankings on each key's BEST rank across them.

    THE SHIPPED FUSION, and the reason is a property rather than a score.
    Measured 2026-09-02 against `rrf_fusion` over the same rewrites: RRF is
    better on every aggregate — recall@1 0.192 against 0.152, @10 0.567 against
    0.549, 110 rows improved against 81 — and it demotes 11 rows whose gold item
    the shipped search already ranked FIRST, one of them to rank 24. This one
    demotes none, by construction. C16 is not gated on recall, so the arm that
    cannot regress a row it was not asked to improve is the one that ships;
    `rrf_fusion` is reported beside it because the screening stage reads deep and
    may value the tighter depth distribution more than head fidelity. That is
    C17's call, on C17's measurement.

    Chosen over a sum or a mean because the property that matters downstream is
    "some phrasing put this near the top", and an average punishes a key that
    one phrasing ranks first and three others never mention — which is exactly
    the shape a vocabulary bridge produces.

    Ties break on the EARLIER stream, which is what makes the request's own
    ranking authoritative: the request is always stream 0, so a key the shipped
    search already ranked first stays first and this arm cannot cost a row its
    rank-1 answer. Agreement across phrasings is deliberately not a tie-break
    here — rewarding it is what `rrf_fusion` does, and the two are reported side
    by side rather than blended into one arm whose behaviour is neither.

    Args:
        rankings: One ranked key list per phrasing, best first.

    Returns:
        Every key any ranking held, fused, best first.
    """
    best: dict[str, int] = {}
    seen: dict[str, tuple[int, int]] = {}
    for stream, keys in enumerate(rankings):
        for rank, key in enumerate(keys, start=1):
            if key not in best or rank < best[key]:
                best[key] = rank
            seen.setdefault(key, (stream, rank))
    return sorted(best, key=lambda k: (best[k], seen[k], k))


def rrf_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[str]:
    """Fuse rankings by reciprocal rank, as the measured alternative.

    Pure Python over lists sqlite already ranked, so it carries none of the
    `numpy`/`sentence-transformers` reproducibility problem `AGENTS.md` records
    for the embedding and RRF arms; it is reported beside `min_rank_fusion`
    rather than argued about.

    Args:
        rankings: One ranked key list per phrasing, best first.
        k: The rank offset.

    Returns:
        Every key any ranking held, fused, best first.
    """
    score: dict[str, float] = {}
    seen: dict[str, tuple[int, int]] = {}
    for stream, keys in enumerate(rankings):
        for rank, key in enumerate(keys, start=1):
            score[key] = score.get(key, 0.0) + 1.0 / (k + rank)
            seen.setdefault(key, (stream, rank))
    return sorted(score, key=lambda key: (-score[key], seen[key], key))


FusionFn = Callable[[Sequence[Sequence[str]]], list[str]]

#: `(phrase, limit) -> search result`. `env.tools.search_variables`' shape, and
#: `benchmark.retrieval_eval.SearchFn`'s.
SearchFn = Callable[[str, int], dict]


@dataclass
class RewriteSearch:
    """A candidate-set callable that searches every phrasing and fuses the pools.

    The request is always searched FIRST and always contributes its ranking, so
    this stage can only add reachability; a row the shipped search already
    answers cannot be made unreachable by a phrasing the model invented.

    Attributes:
        rewrites: Request -> phrasings, from a prior `rewrite` pass. A request
            absent here searches unrewritten rather than raising, so a partial
            cache degrades to the control arm instead of to an error.
        fusion: How the per-phrasing rankings are combined.
        cap: The most candidates the fused pool may carry.
        search: The retrieval callable, `env.tools.search_variables` by default.
        pool_sizes: Request -> fused pool size before the cap, filled as it runs.
        searched: Request -> the phrasings actually searched, filled as it runs.
    """

    rewrites: Mapping[str, Sequence[str]]
    fusion: FusionFn = min_rank_fusion
    cap: int = POOL_CAP
    search: SearchFn | None = None
    pool_sizes: dict[str, int] = field(default_factory=dict)
    searched: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Bind the default search late, so importing this module stays cheap."""
        if self.search is None:
            from env import tools
            self.search = tools.search_variables

    @property
    def __name__(self) -> str:
        """The name `RecallReport` prints for the arm under measurement.

        Returns:
            The fusion's name, so two arms cannot be reported as one.
        """
        return f"rewrite_search[{self.fusion.__name__}]"

    def __call__(self, query: str, limit: int) -> dict:
        """Search every phrasing of `query` and return the fused pool.

        Args:
            query: The researcher's words.
            limit: The per-phrasing limit, passed through untouched.

        Returns:
            A result dict shaped like `search_variables`', carrying `hits`,
            plus the phrasings searched and the pre-cap pool size.
        """
        assert self.search is not None
        phrasings = _dedupe((query, *self.rewrites.get(query, ())))
        rankings: list[list[str]] = []
        outcomes: list[str] = []
        matched = 0
        for phrase in phrasings:
            result = self.search(phrase, limit)
            rankings.append([str(h["key"]) for h in result.get("hits", [])])
            outcomes.append(str(result.get("outcome", "unknown")))
            matched = max(matched, int(result.get("n_matched_items", 0)))
        fused = self.fusion(rankings)
        self.pool_sizes[query] = len(fused)
        self.searched[query] = phrasings
        capped = fused[:self.cap]
        return {
            "hits": [{"key": k} for k in capped],
            "n": len(capped),
            "n_matched_items": matched,
            # The arm's own label, not a per-phrasing one: `ok` when any
            # phrasing came back ok. It is REPORTED, never a stopping signal —
            # see `rewrite` on why this population cannot use it as one.
            "outcome": "ok" if "ok" in outcomes else "low_confidence",
            "phrasings": list(phrasings),
            "pool_before_cap": len(fused),
        }
