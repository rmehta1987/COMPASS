"""benchmark/instrument_terms.py — can the built instrument supply this phrase?

ONE IMPLEMENTATION, TWO CALLERS. `tier_gate.py` and `scorability.py` ask the
same question and neither keeps a copy: a test comparing two copies pins their
shared bug rather than catching drift, so there is one function, tested against
the instrument.

WHY SHORT TOKENS ARE KEPT, MEASURED 2026-08-29. A rule that keeps only words of
at least four characters and asks whether any occurs in `build/dictionary.json`
refutes wrongly in two ways, which is the direction that matters — a false
REFUTED discards a paper from the benchmark:

  1. DROPPED SHORT TOKENS. `'serum PSA'` refutes, while the instrument carries
     `m2:Q6.3`, "How long has it been since you had a blood test for prostate
     cancer, for example PSA?". `PSA` is three characters and is discarded,
     leaving only `serum`. Dropping a token that IS present makes refutation
     MORE likely, never less, so the discard is never safe.
  2. VACUOUS ABSENCE. `any()` over an empty word list is False, so a term whose
     every word is short is declared absent on no evidence at all: `('PSA',)`
     and `('HIV',)` both come back absent, with both strings in the instrument.

THE RULE. A term is tokenised into runs of at least three characters. A long
token (>= MIN_CONTENT_WORD) matches as a substring, which is deliberately loose —
`care` matching `healthcare` keeps a term OUT of the absent set, and failing to
refute is the safe error. A short token matches only on a word boundary, so `PSA`
finds the prostate item while `WQS` and `NO2` still find nothing. A term with no
tokens at all is UNDETERMINED and never absent; `absent_and_undetermined` returns
that set separately so a caller cannot silently read it as a refutation.

WHAT THIS STILL CANNOT DO, and the reason the docstring says it twice: a word
being present is not the construct being measurable. `screening` occurs in the
instrument and says nothing about whether the CRC item exists. This module
refutes and never confirms. Confirmation needs a resolved key —
`scorability.py` requires `resolve_variable` to return `unique` — or the
ascertainment the held-out key records.
"""

from __future__ import annotations

import re

from benchmark.input_leakage import instrument_text

#: At or above this length a token matches as a substring; below it, only on a
#: word boundary. Four keeps method acronyms (`CRC`, `WQS`) from matching inside
#: longer words, and boundary-matching the short tokens keeps constructs such as
#: `PSA` and `HIV` findable, so the exclusion is not guessed from length alone.
MIN_CONTENT_WORD = 4

#: Runs of at least three characters, digits and dots allowed after the first so
#: `pm2.5` and `no2` survive tokenisation as single tokens rather than being cut
#: into fragments that match anything.
_TOKEN = re.compile(r"[a-z][a-z0-9.]{2,}")


def content_tokens(term: str) -> tuple[str, ...]:
    """The tokens of a term that carry meaning for an instrument lookup.

    Args:
        term: A phrase from a paper's design line.

    Returns:
        Lowercased tokens of at least three characters, in order of appearance.
    """
    return tuple(_TOKEN.findall(term.lower()))


def term_is_carried(term: str, instrument: str) -> bool | None:
    """Whether the instrument carries any token of `term`.

    Args:
        term: A phrase from a paper's design line.
        instrument: The normalised instrument, from `instrument_text()`.

    Returns:
        True when at least one token is found, False when none is, and None when
        the term has no tokens to look up — which is an absence of evidence and
        must not be read as evidence of absence.
    """
    tokens = content_tokens(term)
    if not tokens:
        return None
    for token in tokens:
        if len(token) >= MIN_CONTENT_WORD:
            if token in instrument:
                return True
        elif re.search(rf"\b{re.escape(token)}\b", instrument):
            return True
    return False


def absent_and_undetermined(
        terms: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split terms into those the instrument cannot supply and those unlookupable.

    Args:
        terms: Phrases from one side of a design line.

    Returns:
        `(absent, undetermined)`. `absent` holds terms with tokens, none of which
        the instrument carries — the only ones a caller may refute on.
        `undetermined` holds terms with no tokens at all.
    """
    instrument = instrument_text()
    absent, undetermined = [], []
    for term in terms:
        carried = term_is_carried(term, instrument)
        if carried is None:
            undetermined.append(term)
        elif not carried:
            absent.append(term)
    return tuple(absent), tuple(undetermined)


def terms_absent_from_instrument(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Terms the instrument carries no token of.

    One-directional, and now actually so: a term is returned only when it HAS
    tokens and the instrument carries none of them. A term with nothing to look
    up is excluded rather than silently refuted.

    Args:
        terms: Phrases from one side of a design line.

    Returns:
        The subset the instrument cannot supply.
    """
    return absent_and_undetermined(terms)[0]
