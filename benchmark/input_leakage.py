"""benchmark/input_leakage.py — does the input already contain the answer?

WHAT THIS IS. A static comparison, run before any model is called: for each pair
the funnel enumerates, does `agent/specifier.py::user_prompt` already hand the
model content that only that pair's answer key should hold? No backend, no
network, no cost. A benchmark can be broken before the model is invoked, and no
downstream control repairs it — the refusal path, the tool authority gate and the
marker scan all run on what the model produced, and every one of them passes a
model that read the answer out of its own prompt.

WHY IT LIVES HERE. It needs the key. `benchmark/` is fenced from the tool layer
by `contamination_check.check_holdout_not_reachable`, which fails if
`env/tools.py` so much as names the directory, and the scan therefore reads
`cohort_papers.py` and `prevalence_key.py` without putting either on a path the
model can reach. This is the same placement argument as
`check_no_prevalence_figure_in_surface`: paper facts are DERIVED at check time
from a file that already exists on the held-out side, never written into a
scanned one.

TWO PAPERS DO THIS AND WE DID NOT, both quoted in
`references/PRIOR_ART_CONTAMINATION.md`:

  - MOOSE-Chem has human experts verify "whether the background does not contain
    any information in inspirations or hypothesis".
  - CiteME excludes excerpts naming authors or acronyms "which simply tests LM
    memorization and retrieval".

THE THREE-FILTER RULE, and why the obvious version of this check is wrong. The
naive scan — grep the prompt for the paper's design words — fires on
`hypertension`, `asthma` and `blood pressure`, and it is WRONG to call those
leaks. The papers drew on this instrument, so instrument/paper vocabulary overlap
is the benchmark working rather than failing. So a candidate phrase survives only
if all three hold:

  1. it is not in `build/dictionary.json` — the instrument can supply it, so its
     presence in a prompt is a question the study asked;
  2. it is not in the prompt TEMPLATE, rendered against a blanked pair — the
     template's own design vocabulary (`exposure`, `outcome`, `covariate`,
     `falsifier`) is boilerplate every prompt carries, and deriving it from the
     template rather than listing it keeps this correct when Lane A edits it;
  3. it is not a bare function word.

What survives is answer-only: a method the environment does not name, an external
data source, a realised n, a PubMed id. Those, in a prompt, are the defect.

WHERE FILTER 2 HANDS OFF, and it is a hand-off rather than a hole. A paper's
method token written into the TEMPLATE itself would appear in every prompt, and
filter 2 would then read it as boilerplate — MEASURED, by seeding `E2SFCA` into
the template and watching the design-phrase half go quiet. That case belongs to
the marker scan, which reads `user_prompt` as one of its surfaces and holds
`E2SFCA` as a marker, so it fails there instead. The two checks partition the
prompt: `check_markers` owns the template, this owns what the pair injects into
it. Seeding the same token into the pair-specific half alone produces a finding
on all 384 pairs.

THE IDENTIFIER FIELDS DO NOT DEFER. A PubMed id, a venue and a realised n are
checked against the whole prompt with no template filter at all, because there
is no reading on which any of them is legitimate boilerplate.

WHAT THIS DOES NOT AND CANNOT DO. It cannot tell a paraphrase from a novel
sentence, the same limit the marker scan has. And it is bounded by the key that
exists: `cohort_papers.py` carries a one-line design per paper and no resolved
exposure/outcome keys, so the phrase half of this check is as detailed as those
one-liners and no more. C12 is what makes it sharper.

THE PARTITION, WHICH IS THE OTHER HALF AND IS REPORTED RATHER THAN ENFORCED.
`environment_supplied` names the answer-key fields the enumeration hands the
model BY CONSTRUCTION — the exposure construct key, the outcome construct key,
their stems and their member keys are all in every prompt, because the funnel
chose the pair. Those are not leaks; they are the reason a single "percent of
design recovered" figure conflates rediscovery with recall. C12 needs this
partition and this is where it is computed rather than asserted.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent

from agent.specifier import user_prompt  # noqa: E402
from benchmark.cohort_papers import (  # noqa: E402
    COHORT_PAPERS,
    KNOWN_DUPLICATES,
    CohortPaper,
)
from benchmark.prevalence_key import PREVALENCE_KEY  # noqa: E402
from generate.funnel import Candidate, Construct, load_constructs, run  # noqa: E402

#: The longest phrase compared. Four covers every distinctive construction in the
#: bibliography's design lines — "seven linked community characteristics",
#: "primary-care spatial accessibility" — without generating a combinatorial set
#: from prose that is one sentence long anyway.
MAX_PHRASE_WORDS = 4

#: Function words, so that a phrase made only of these is not a finding. Small
#: and closed on purpose: everything else that must not count is DERIVED, from
#: the instrument or from the prompt template. A growing hand-list here would be
#: the judgement this check exists to remove.
_FUNCTION_WORDS = frozenset(
    "a an and are as at be by for from in into is it of on or the to with "
    "not no per that this these those was were".split())

#: A venue field that records the absence of a venue rather than a venue.
_NO_VENUE = "not recorded here"

_WORD = re.compile(r"[a-z0-9][a-z0-9.·'-]*")


class InputLeak(NamedTuple):
    """One piece of answer-key content found inside a model input.

    Attributes:
        pair_id: The enumerated pair whose prompt carries it.
        pmid: The paper whose key it belongs to.
        field: Which part of the key — `pubmed_id`, `venue`, `analytic_n`,
            `design_phrase` or `published_prevalence`. Named so a reader can see
            whether the benchmark leaked an identifier or a design.
        token: The exact text found.
    """

    pair_id: str
    pmid: str
    field: str
    token: str


def _norm(text: str) -> str:
    """Lower-case and collapse whitespace, so phrases compare across line breaks.

    Args:
        text: Any text.

    Returns:
        The text lower-cased with runs of whitespace reduced to one space.
    """
    return re.sub(r"\s+", " ", text.lower())


def _phrases(text: str, max_words: int = MAX_PHRASE_WORDS) -> set[str]:
    """Every 1- to n-word phrase in `text`, normalised.

    Args:
        text: Source text.
        max_words: Longest phrase to emit.

    Returns:
        Phrases, lower-cased, excluding those made only of function words.
    """
    words = _WORD.findall(_norm(text))
    out: set[str] = set()
    for i in range(len(words)):
        for n in range(1, max_words + 1):
            if i + n > len(words):
                break
            part = words[i:i + n]
            if all(w in _FUNCTION_WORDS for w in part):
                continue
            out.add(" ".join(part))
    return out


@lru_cache(maxsize=1)
def instrument_text() -> str:
    """The built instrument as one normalised string.

    Read rather than parsed: the question is only ever "can the instrument
    supply this phrase", and a substring test over the whole artefact answers it
    without this module needing to know the dictionary's shape.

    Returns:
        `build/dictionary.json`, normalised.

    Raises:
        FileNotFoundError: When the dictionary has not been built. A missing
            generated input must raise, never read as empty — an empty
            instrument would make every paper phrase look answer-only and turn
            this check into noise.
    """
    p = ROOT / "build" / "dictionary.json"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing — run `python build.py` first. Without it every paper "
            f"phrase reads as answer-only and this check reports nothing but "
            f"false positives.")
    return _norm(p.read_text())


@lru_cache(maxsize=1)
def template_text() -> str:
    """`user_prompt` rendered against a blanked pair: the boilerplate, alone.

    Derived rather than listed. The template carries design vocabulary a paper's
    design line also uses — `exposure`, `outcome`, `covariate`, `unit of
    analysis` — and hand-listing those would need editing every time Lane A
    touches the prompt, which is the staleness this project keeps paying for.
    A real `Candidate` with blanked `Construct`s is used rather than a stand-in
    object so that a field ADDED to the prompt is rendered here too.

    Returns:
        The prompt with every pair-supplied field empty, normalised.
    """
    def blank() -> Construct:
        return Construct(construct_key="", module="", base_id="", stem_text="",
                         member_keys=[], is_group=False, is_free_text=False,
                         roster_instances=0)

    return _norm(user_prompt(Candidate(exposure=blank(), outcome=blank(),
                                       estimability="", requires_derivation=False)))


def _n_tokens(n_field: str) -> set[str]:
    """Sample-size tokens from a bibliography `n` field, in both written forms.

    Unlike `contamination_check._published_n_tokens` this keeps the SHORT n.
    The haystack there is the whole model-visible surface, where three-digit
    integers are generated by `registry_coverage`, `estimate_n` and the
    detectability grid; the haystack here is one prompt, whose numerals are
    construct keys and member keys of the form `m2:Q5.8`. MEASURED 2026-08-28
    over all 384 enumerated pairs: zero hits from any short n.

    Args:
        n_field: `CohortPaper.n`, which may be a note rather than a number.

    Returns:
        Bare and comma-grouped forms, empty for an approximate or absent figure.
    """
    out: set[str] = set()
    for m in re.finditer(r"(~?)(\d[\d,]*)", n_field):
        if m.group(1):
            continue
        bare = m.group(2).replace(",", "")
        if len(bare) < 3:
            continue
        out |= {bare, f"{int(bare):,}"}
    return out


@cache
def answer_only_phrases(pmid: str) -> frozenset[str]:
    """Design phrases from one paper that this instrument cannot supply.

    The three filters in the module docstring, applied in order. What remains
    names a method, an external exposure or a data source the environment has no
    route to — and therefore something whose presence in a prompt hands the model
    an answer rather than a question.

    Args:
        pmid: PubMed id of a paper in `COHORT_PAPERS`.

    Returns:
        The surviving phrases.
    """
    paper = next(p for p in COHORT_PAPERS if p.pmid == pmid)
    instrument, template = instrument_text(), template_text()
    return frozenset(
        ph for ph in _phrases(paper.design)
        if ph not in instrument and ph not in template)


def _prevalence_tokens() -> set[str]:
    """Published prevalence figures, in the forms a prompt could carry.

    The same restriction `check_no_prevalence_figure_in_surface` documents: the
    one-decimal percent and the three-decimal proportion, never the integer
    percent, which collides with unrelated sentences.

    Returns:
        Figure tokens derived from the held-out prevalence key.
    """
    out: set[str] = set()
    for row in PREVALENCE_KEY:
        if row.value is None:
            continue
        out |= {f"{row.value * 100:.1f}%", f"{row.value * 100:.1f}",
                f"{row.value:.3f}"}
    return out


def _standalone(haystack: str, needle: str) -> bool:
    """Is `needle` in `haystack` other than inside a longer token?

    Args:
        haystack: Normalised text.
        needle: Normalised literal.

    Returns:
        True on a standalone match.
    """
    return bool(re.search(rf"(?<![\w.]){re.escape(needle)}(?![\w])", haystack))


def scan_prompt(pair_id: str, prompt: str,
                papers: tuple[CohortPaper, ...] = COHORT_PAPERS) -> list[InputLeak]:
    """Every piece of answer-key content this one prompt already contains.

    Args:
        pair_id: The pair the prompt was rendered for, for the report.
        prompt: The rendered `user_prompt` text.
        papers: The bibliography to check against.

    Returns:
        One `InputLeak` per (paper, field, token) hit; empty for a clean prompt.
    """
    text = _norm(prompt)
    template = template_text()
    out: list[InputLeak] = []

    for pmid, real in KNOWN_DUPLICATES.items():
        if _standalone(text, pmid):
            out.append(InputLeak(pair_id, real, "pubmed_id", pmid))

    for paper in papers:
        if _standalone(text, paper.pmid):
            out.append(InputLeak(pair_id, paper.pmid, "pubmed_id", paper.pmid))
        venue = _norm(paper.venue)
        if venue != _NO_VENUE and venue in text:
            out.append(InputLeak(pair_id, paper.pmid, "venue", paper.venue))
        for tok in sorted(_n_tokens(paper.n)):
            if _standalone(text, tok):
                out.append(InputLeak(pair_id, paper.pmid, "analytic_n", tok))
        for ph in sorted(answer_only_phrases(paper.pmid)):
            # `not in template` again, at match time rather than only at
            # derivation time: a phrase can be answer-only against the blanked
            # template and still arrive in this prompt from the boilerplate if
            # the template ever renders differently for a real pair.
            if ph in text and ph not in template:
                out.append(InputLeak(pair_id, paper.pmid, "design_phrase", ph))

    for tok in sorted(_prevalence_tokens()):
        if _standalone(text, tok.lower()):
            out.append(InputLeak(pair_id, "", "published_prevalence", tok))
    return out


def enumerated_pairs() -> list[Candidate]:
    """Every live pair the current frame produces.

    The frame is `generate/funnel.py`'s 6x64 comprehension, duplicated here from
    `contamination_check.model_visible_surface` rather than imported because that
    function samples ONE pair for the surface hash and this check needs all of
    them. When T7 gives the frame an author and a hash, both should read it from
    there instead.

    Returns:
        The funnel's live candidates, in enumeration order.
    """
    C, _ = load_constructs()
    e = sorted([c for c in C.values() if c.module == "3"
                and c.base_id.startswith("Q16.")], key=lambda c: c.base_id)
    o = sorted([c for c in C.values() if c.module == "2"
                and c.base_id.startswith("Q5.")], key=lambda c: c.base_id)
    cands, _ = run(e, o)
    return cands


def scan_frame() -> list[InputLeak]:
    """Run the input check over every pair in the current frame.

    Every pair, not a sample. The one-pair version is what
    `model_visible_surface` does for the hash, and a leak that reaches only the
    prompts of pairs 2 through 256 is exactly the hole that argument leaves.

    Returns:
        Every hit across the frame; empty when no prompt contains an answer.
    """
    return [leak
            for cand in enumerated_pairs()
            for leak in scan_prompt(cand.pair_id, user_prompt(cand))]


def environment_supplied(pair: Candidate) -> dict[str, list[str]]:
    """Answer-key fields this prompt hands the model by construction.

    NOT leaks, and reported rather than enforced. The enumeration chose the pair,
    so both anchors and their wording are in the input by design — which means a
    "percent of design recovered" score that counts exposure and outcome
    identification is scoring the funnel, not the model. This is the
    environment-forced half of the partition C12 needs; the paper-free half is
    everything a protocol must supply that is not listed here.

    Args:
        pair: An enumerated candidate.

    Returns:
        Mapping of answer-key field name to the values the prompt supplies.
    """
    return {
        "exposure_key": [pair.exposure.construct_key],
        "exposure_wording": [pair.exposure.stem_text],
        "exposure_member_keys": list(pair.exposure.member_keys),
        "outcome_key": [pair.outcome.construct_key],
        "outcome_wording": [pair.outcome.stem_text],
        "outcome_member_keys": list(pair.outcome.member_keys),
        "estimability": [str(pair.estimability)],
        "requires_derivation": [str(pair.requires_derivation)],
    }


def check_input_does_not_contain_the_answer() -> list[str]:
    """Fail when any enumerated prompt already carries a paper's answer.

    Returns:
        One string per hit, empty when every prompt is clean.
    """
    return [f"{leak.pair_id}  ->  PMID {leak.pmid or '-'} "
            f"{leak.field}={leak.token!r}"
            for leak in scan_frame()]


def report() -> str:
    """A human-readable summary, for a session that wants the numbers.

    Returns:
        The counts and, when there are any, the hits.
    """
    pairs = enumerated_pairs()
    hits = scan_frame()
    lines = [f"pairs scanned            {len(pairs)}",
             f"papers in the key        {len(COHORT_PAPERS)}",
             f"answer-only phrases      "
             f"{sum(len(answer_only_phrases(p.pmid)) for p in COHORT_PAPERS)}",
             f"input leaks              {len(hits)}"]
    lines += [f"    {h}" for h in check_input_does_not_contain_the_answer()]
    lines.append("")
    lines.append("environment-forced fields, present in EVERY prompt by "
                 "construction and not leaks:")
    lines += [f"    {k}" for k in environment_supplied(pairs[0])]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
