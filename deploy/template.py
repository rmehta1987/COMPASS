"""COMPASS query template -- shipped WITH the retriever so it cannot be forgotten.

    from template import RetrievalRequest, VariableRole
    RetrievalRequest(construct="prescription pain medication use",
                     role=VariableRole.EXPOSURE,
                     instances=("ibuprofen", "naproxen")).to_query()
    -> "prescription pain medication use: ibuprofen, naproxen"

Template:   [population] construct [timeframe][: instance, instance, ...]

A slot is rendered only when its content words are not already in the text.
`role` is never rendered. No model call, no network, pure string concatenation.

Shipped contract (manifest["template"]): INSTANCES ONLY. Leave `population`
at its default of None. Supplying it measured net -1 row on the 17 rows it
touched (0.647 -> 0.588, +2 -3): the roster noun pulls the query toward the
roster block's OTHER question about the same cancer at margins down to 0.0001.

Provenance: `RetrievalRequest`, `to_query`, `covered`, `VariableRole` copied
verbatim from src/query_expand.py; `STOPWORDS`, `TOKEN_RE`, `light_stem`,
`content_words` copied verbatim from src/phrase_overlap.py. Nothing else was
brought across: `fields_from_target()` reads the gold target's metadata and
is the fixture's stand-in for a specifier, not production code. The smoke test
re-renders all 268 pre-registered strings through THIS file and stops on the
first difference.
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass

# --- src/phrase_overlap.py ----------------------------------------------------

# A standard English stoplist plus the handful of survey-instrument function
# words that appear in nearly every stem ("please", "describe", "following").
STOPWORDS = set("""
a about above after again against all am an and any are aren as at be because
been before being below between both but by can cannot could couldn did didn do
does doesn doing don down during each few for from further had hadn has hasn
have haven having he her here hers herself him himself his how i if in into is
isn it its itself just me more most mustn my myself no nor not now of off on
once only or other ought our ours ourselves out over own same shan she should
shouldn so some such than that the their theirs them themselves then there these
they this those through to too under until up very was wasn we were weren what
when where which while who whom why with won would wouldn you your yours
yourself yourselves s t don ve ll re d m o
please describe following ever your you have has been did do does was were are
is any other another type kind number times time many much often long
""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+")


def light_stem(w: str) -> str:
    """Deliberately conservative suffix normalisation. Not Porter."""
    if len(w) <= 3:
        return w
    for suf, repl, minlen in (
        ("ies", "y", 5), ("sses", "ss", 6), ("ization", "ize", 8),
        ("isation", "ise", 8), ("ation", "ate", 7), ("ement", "e", 7),
        ("ment", "", 6), ("ance", "", 6), ("ence", "", 6),
        ("ing", "", 6), ("edly", "", 7), ("ed", "", 5), ("ly", "", 5),
        ("es", "", 5), ("s", "", 4),
    ):
        if w.endswith(suf) and len(w) >= minlen:
            return w[: len(w) - len(suf)] + repl
    return w


def content_words(text: str, stem: bool) -> set[str]:
    ws = [w for w in TOKEN_RE.findall((text or "").lower())
          if len(w) >= 2 and w not in STOPWORDS]
    if stem:
        ws = [light_stem(w) for w in ws]
    return {w for w in ws if w and w not in STOPWORDS}


# --- src/query_expand.py ------------------------------------------------------

class VariableRole(str, enum.Enum):
    EXPOSURE = "exposure"
    OUTCOME = "outcome"
    CONFOUNDER = "confounder"


def covered(phrase: str, text: str) -> bool:
    """True when every content word of `phrase` is already in `text`.
    Empty phrases (all stopwords) count as covered: nothing to add."""
    p = content_words(phrase, True)
    return not p or p <= content_words(text, True)


@dataclass(frozen=True)
class RetrievalRequest:
    construct: str                     # "nonsteroidal anti-inflammatory medication use"
    role: VariableRole                 # exposure / outcome / confounder -- NOT rendered
    population: str | None = None      # shipped contract: leave None (see module doc)
    timeframe: str | None = None       # "past 12 months" | "lifetime" | "current"
    instances: tuple[str, ...] = ()    # ("ibuprofen", "naproxen", "aspirin")

    def to_query(self, *, with_instances: bool = True) -> str:
        """Deterministic template. No model call, no network."""
        text = self.construct.strip()
        pop = (self.population or "").strip()
        if pop and pop.lower() != "participant" and not covered(pop, text):
            text = f"{pop} {text}"
        tf = (self.timeframe or "").strip()
        if tf and not covered(tf, text):
            text = f"{text} {tf}"
        if with_instances:
            added = []
            for inst in self.instances:
                inst = inst.strip()
                if inst and not covered(inst, text + " " + " ".join(added)):
                    added.append(inst)
            if added:
                text = f"{text}: {', '.join(added)}"
        return text
